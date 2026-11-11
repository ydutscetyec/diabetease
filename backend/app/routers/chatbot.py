"""Candie: retrieval over a reviewed corpus, with an optional grounded LLM pass.

Order of checks is the safety property that matters:
    emergency  ->  refusal  ->  retrieval  ->  optional rephrase
Generation never runs before the first two, and never runs at all when retrieval
finds nothing, so the model is never asked to invent a medical answer.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..schemas import ChatRequest, ChatResponse
from ..services import llm

router = APIRouter(prefix="/api/v1", tags=["chatbot"])

_CORPUS = json.loads((Path(__file__).resolve().parent.parent / "data" / "faq.json").read_text())
_TOPICS = _CORPUS["topics"]
_SOURCES = json.loads((Path(__file__).resolve().parent.parent / "data" / "sources.json").read_text())


def _source_name(key: str) -> str:
    entry = _SOURCES["sources"].get(key)
    return entry["short"] if entry else key

DISCLAIMER = (
    "General information only. Candie cannot diagnose, interpret your personal "
    "results, or advise on medication."
)
REFUSAL = (
    "I cannot answer that. Treatment, medication and insulin dosing are a "
    "clinician's decision, and I am not permitted to diagnose anyone. Please "
    "bring this question to a doctor or your municipal health office."
)
NO_MATCH = (
    "I do not have an answer for that. I can cover symptoms, HbA1c, glucose "
    "thresholds, islet autoantibodies, family history, the testing centre map, "
    "and how the assessment works."
)
CLINICAL_DECLINE = (
    "I do not have a reviewed answer to that medical question, so I cannot answer "
    "it reliably. Please consult a doctor or your municipal health office."
)
SUGGEST_LEAD = "I do not cover that exactly. Related topics I can explain:"

# A question is CLINICAL if it touches disease, the body, tests or results.
# Clinical questions may only be answered from the reviewed corpus; if retrieval
# misses, Candie declines rather than letting a model improvise medicine.
_CLINICAL = {
    "diabetes", "diabetic", "insulin", "glucose", "sugar", "hba1c", "a1c",
    "antibody", "antibodies", "autoantibody", "autoantibodies", "pancreas",
    "symptom", "symptoms", "disease", "illness", "sick", "diagnosis", "diagnose",
    "treatment", "treat", "cure", "medicine", "medication", "drug", "dose",
    "ketoacidosis", "dka", "blood", "test", "result", "results", "lab",
    "risk", "healthy", "health", "doctor", "hospital", "clinic", "pain",
    "thirst", "thirsty", "urine", "urination", "weight", "fatigue", "vision",
    "hereditary", "genetic", "immune", "autoimmune", "prognosis", "severe",
    "complication", "complications", "screening", "stage", "stages",
    "beta", "cell", "cells", "pancreatitis", "organ", "hormone", "metabolic",
    "metabolism", "kidney", "kidneys", "eye", "eyes", "nerve", "nerves", "heart",
    "infection", "virus", "fever", "nausea", "breathing", "ketone", "ketones",
    "hypoglycemia", "hyperglycemia", "glycemic", "prediabetes", "carbohydrate",
    "diet", "nutrition", "exercise", "pregnancy", "pregnant", "injection",
    "prognosis", "chronic", "immunity", "antibody", "inflammation",
}

_STOP = {"the", "a", "an", "of", "to", "in", "on", "for", "and", "or"}
MIN_SCORE = 2.5


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9' ]+", " ", text.lower()).strip()


def _stem(word: str) -> str:
    """Crude suffix stripping, enough to tie 'tested'->'test' and
    'stages'->'stage' without adding a stemming dependency.

    Plurals are handled before other suffixes: stripping 'es' first turned
    'stages' into 'stag', which then failed to match the keyword 'stage'.
    """
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        if word.endswith("ies") and len(word) > 4:
            return word[:-3] + "y"
        if word.endswith("es") and word[:-2].endswith(("s", "x", "z", "ch", "sh")):
            return word[:-2]
        return word[:-1]
    for suf in ("ations", "ation", "ingly", "ing", "ied", "ed"):
        if word.endswith(suf) and len(word) - len(suf) >= 3:
            base = word[: -len(suf)]
            return base + "y" if suf == "ied" else base
    return word


def _tokens(text: str) -> set[str]:
    out = set()
    for t in _norm(text).split():
        if t in _STOP:
            continue
        # Short tokens are usually noise, but digits are not: dropping "1" made
        # "what is type 1 diabetes" indistinguishable from "what is diabetes".
        if len(t) <= 2 and not t.isdigit():
            continue
        out.add(_stem(t))
    return out


def _score(query: str, topic: dict) -> float:
    """A keyword matches when all of its content tokens appear in the question.

    Multi-word keywords score highest, because 'where test' matching a question
    about testing is far stronger evidence than one shared word. Partial credit
    for a multi-word keyword keeps near-misses alive without letting a single
    incidental word select a topic on its own.
    """
    q_tokens = _tokens(query)
    if not q_tokens:
        return 0.0
    score = 0.0
    partial_best = 0.0
    for kw in topic["keywords"]:
        k_tokens = _tokens(kw)
        if not k_tokens:
            continue
        hit = k_tokens & q_tokens
        if hit == k_tokens:
            # A phrase that collapses to a single content token ("who are you" ->
            # "who") is generic, so it must not select a topic by itself.
            if len(k_tokens) == 1 and len(_norm(kw).split()) > 1:
                score += 1.0
            else:
                score += 3.0 + 0.8 * len(k_tokens)
        elif len(hit) >= 2 and len(hit) * 2 >= len(k_tokens):
            # Partial credit is capped at the single best near-miss. Summing it
            # let three keywords sharing one generic word ("who") elect a topic.
            partial_best = max(partial_best, 1.2 * len(hit))
    return score + partial_best


def _rank(query: str) -> list[tuple[dict, float]]:
    scored = [(t, _score(query, t)) for t in _TOPICS]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def _retrieve(query: str) -> tuple[dict | None, float]:
    ranked = _rank(query)
    best, best_score = ranked[0]
    return (best, best_score) if best_score >= MIN_SCORE else (None, best_score)


def _is_clinical(query: str) -> bool:
    return bool(_tokens(query) & {_stem(w) for w in _CLINICAL})


TOPIC_TITLES = {
    "what_is_t1d": "what Type 1 diabetes is",
    "symptoms": "the common symptoms",
    "glucose": "blood glucose thresholds",
    "hba1c": "what HbA1c means",
    "autoantibodies": "islet autoantibody testing",
    "stages": "the three stages before symptoms",
    "family": "family history and inheritance",
    "type_difference": "how Type 1 differs from Type 2",
    "prevention": "whether it can be prevented",
    "treatment": "how it is treated",
    "testing_centers": "where to get tested",
    "verification": "what verified and unconfirmed mean on the map",
    "coverage": "which municipalities are covered",
    "how_to_use": "how to use the assessment",
    "result_meaning": "what an assessment result means",
    "no_threshold": "why a normal result is not an all-clear",
    "no_labs": "what to do with no laboratory results",
    "model_status": "whether the AI model is accurate",
    "why_no_model": "why no model has been trained",
    "forecasting": "why forecasting is not available",
    "privacy": "what happens to your data",
    "limitations": "the limitations of this system",
    "research_objectives": "the research objectives",
    "research_design": "the research methodology",
    "who_made_it": "who built this",
    "what_is_candie": "who I am",
    "cost": "what testing costs",
    "emergency": "emergency warning signs",
}


def _suggestions(query: str, n: int = 3) -> list[str]:
    """Near misses, so a miss offers a route forward instead of a dead end."""
    out = []
    for topic, score in _rank(query):
        if score <= 0:
            break
        title = TOPIC_TITLES.get(topic["id"])
        if title:
            out.append(title)
        if len(out) >= n:
            break
    return out


@router.post("/chat", response_model=ChatResponse)
async def chat(body: ChatRequest, db: Session = Depends(get_db)) -> ChatResponse:
    """Routing, in a fixed order. Each step can only narrow what follows.

        emergency -> refusal -> grounded retrieval -> open generation -> decline

    The two safety steps run before any generation path exists, and a question
    classified as clinical never reaches open generation.
    """
    text = _norm(body.message)

    # 1. Emergency, ahead of everything.
    if any(p in text for p in _CORPUS["emergency_patterns"]):
        topic = next(t for t in _TOPICS if t["id"] == "emergency")
        return ChatResponse(reply=topic["answer"], mode="rule_based",
                            matched_topic="emergency", route="emergency",
                            grounded=True, disclaimer=DISCLAIMER)

    # 2. Refusal, before any model can be reached.
    if any(_norm(p) in text for p in _CORPUS["refusal_patterns"]):
        return ChatResponse(reply=REFUSAL, mode="rule_based", matched_topic=None,
                            refused=True, route="refused", grounded=True,
                            disclaimer=DISCLAIMER)

    # 2b. Facility lookup. "Where can I get tested in Surallah" is answered from
    #     the facility table, so every name and service comes from a stored,
    #     sourced record. Runs after the two safety steps and before retrieval,
    #     which would otherwise return the generic "open the map" answer.
    from ..services import facility_lookup
    found = facility_lookup.answer(db, body.message)
    if found:
        return ChatResponse(reply=found, mode="rule_based",
                            matched_topic="facility_lookup", route="grounded",
                            grounded=True, disclaimer=DISCLAIMER)

    # 3. Grounded retrieval. A hit is answered from the reviewed corpus, with the
    #    model allowed only to rephrase it.
    topic, score = _retrieve(body.message)
    if topic is not None:
        if llm.available():
            generated = await llm.rephrase(body.message, topic["answer"])
            if generated:
                return ChatResponse(reply=generated, mode="language_model",
                                    matched_topic=topic["id"], route="grounded",
                                    grounded=True, disclaimer=DISCLAIMER)
        return ChatResponse(reply=topic["answer"], mode="rule_based",
                            matched_topic=topic["id"], route="grounded",
                            grounded=True, disclaimer=DISCLAIMER)

    # 4. No corpus hit on a clinical question. With CLINICAL_OPEN_ANSWERS on,
    #    this goes to the model under a stricter prompt; the answer is flagged
    #    ungrounded and carries a visible "not reviewed" line. With it off, it
    #    is declined. Either way steps 1 and 2 have already run.
    if _is_clinical(body.message):
        settings = get_settings()
        if settings.clinical_open_answers and llm.available():
            history = [{"role": h.role, "content": h.content} for h in body.history]
            generated = await llm.answer_clinical(body.message, history)
            if generated:
                return ChatResponse(
                    reply=generated + "\n\nThis answer was generated and has not "
                          "been reviewed by the research team. Confirm anything "
                          "important with a doctor or your municipal health office.",
                    mode="language_model", matched_topic=None, route="open",
                    grounded=False, disclaimer=DISCLAIMER)
        return ChatResponse(reply=CLINICAL_DECLINE, mode="rule_based",
                            matched_topic=None, route="declined", grounded=True,
                            disclaimer=DISCLAIMER)

    # 5. Non-clinical: answer freely if a model is configured.
    if llm.available():
        history = [{"role": t.role, "content": t.content} for t in body.history]
        generated = await llm.answer_open(body.message, history)
        if generated:
            return ChatResponse(reply=generated, mode="language_model",
                                matched_topic=None, route="open", grounded=False,
                                disclaimer=DISCLAIMER)

    # 6. No model configured: offer the nearest reviewed topics rather than a
    #    flat refusal, so the miss still points somewhere useful.
    near = _suggestions(body.message)
    if near:
        return ChatResponse(
            reply=SUGGEST_LEAD + " " + "; ".join(near) + ". Ask about any of those, "
                  "or try rephrasing your question.",
            mode="rule_based", matched_topic=None, route="suggestions",
            grounded=True, disclaimer=DISCLAIMER)

    return ChatResponse(reply=NO_MATCH, mode="rule_based", matched_topic=None,
                        route="suggestions", grounded=True, disclaimer=DISCLAIMER)


@router.post("/chat/warmup")
async def warmup() -> dict:
    """Pre-load the model. Safe to call repeatedly; cheap once warm."""
    return await llm.warm_up()


@router.get("/chat/diagnose")
async def diagnose() -> dict:
    """Actually call the model and report what happened."""
    return await llm.diagnose()


@router.get("/sources")
def sources() -> dict:
    """The reference list behind the clinical content, with how each was checked."""
    return _SOURCES


@router.get("/chat/topics")
def topics() -> dict:
    s = get_settings()
    return {
        "mode": "language_model" if llm.available() else "rule_based",
        "llm_configured": llm.available(),
        "topic_count": len(_TOPICS),
        "topics": [{"id": t["id"], "source": _source_name(t.get("source", "unspecified"))}
                   for t in _TOPICS],
        "open_answering": llm.available(),
        "clinical_open_answers": get_settings().clinical_open_answers and llm.available(),
        "assistant": llm.describe(),
        "note": ("Clinical questions are answered only from the reviewed corpus; if "
                 "retrieval misses, Candie declines. Non-clinical questions may be "
                 "answered freely when a language model is configured. Emergency and "
                 "refusal checks run before either path."),
    }
