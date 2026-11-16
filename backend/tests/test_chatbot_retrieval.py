"""Candie's safety ordering and retrieval quality."""
from __future__ import annotations

import re


def ask(client, msg):
    r = client.post("/api/v1/chat", json={"message": msg})
    assert r.status_code == 200, r.text
    return r.json()


def test_emergency_beats_everything_including_refusal(client):
    # Contains a refusal trigger AND an emergency word: emergency must win.
    b = ask(client, "he is vomiting, what dose of insulin should I give")
    assert b["matched_topic"] == "emergency"
    assert "emergency department" in b["reply"]


def test_refusal_runs_before_retrieval(client):
    for q in ["how much insulin should I take", "do I have diabetes",
              "what dosage is right", "anong gamot para dito"]:
        assert ask(client, q)["refused"] is True


def test_retrieval_matches_expected_topics(client):
    cases = {
        "what is hba1c": "hba1c",
        "what is prediabetes": "prediabetes",
        "is type 2 inherited from parents": "family",
        "should i get tested": "screening_criteria",
        "where can I get tested": "testing_centers",
        "why is there no trained model": "why_no_model",
        "what are the limitations of this study": "limitations",
        "who are you": "what_is_candie",
        "how much does it cost": "cost",
    }
    for q, expected in cases.items():
        assert ask(client, q)["matched_topic"] == expected, q


def test_local_language_triggers_resolve(client):
    assert ask(client, "ano ang type 2 diabetes")["matched_topic"] == "what_is_t2d"
    assert ask(client, "asa ko magpa test")["matched_topic"] == "testing_centers"


def test_unrelated_question_is_refused_not_guessed(client):
    b = ask(client, "who won the basketball game last night")
    assert b["matched_topic"] is None
    # behaviour, not wording: no topic is claimed and nothing is invented
    assert b["route"] in ("suggestions", "declined")
    assert b["grounded"] is True


def test_incidental_word_does_not_force_a_match(client):
    # "family" appears but the question is not about family history.
    b = ask(client, "zzzz qqqq wwww")
    assert b["matched_topic"] is None


def test_answers_never_promise_a_trained_model(client):
    b = ask(client, "how accurate is the ai model")
    assert b["matched_topic"] == "model_status"
    assert "no accuracy figure" in b["reply"].lower()


def test_topics_endpoint_reports_llm_state_and_sources(client):
    b = client.get("/api/v1/chat/topics").json()
    assert b["llm_configured"] is False
    assert b["mode"] == "rule_based"
    assert b["topic_count"] >= 25
    assert all("source" in t for t in b["topics"])


def test_llm_is_not_used_when_unconfigured(client):
    assert ask(client, "what is type 1 diabetes")["mode"] == "rule_based"


def test_general_and_type2_definitions_are_separate_topics(client):
    """'What is diabetes' and 'what is type 2' are different questions, and the
    general answer has to name both mechanisms without implying they are the
    same one. Both have reviewed answers."""
    general = ask(client, "what is diabetes")
    assert general["matched_topic"] == "what_is_diabetes"
    assert "responds to it poorly" in general["reply"]
    assert "Type 1" in general["reply"]

    t2 = ask(client, "what is type 2 diabetes")
    assert t2["matched_topic"] == "what_is_t2d"


def test_type_2_is_never_described_as_autoimmune(client):
    """The mirror of the old hazard. A model asked about type 2 will sometimes
    reach for the autoimmune explanation, which belongs to type 1."""
    for q in ["what is diabetes", "what is type 2 diabetes",
              "tell me about type 2 diabetes", "what causes type 2"]:
        reply = ask(client, q)["reply"].lower()
        before_t1 = reply.split("type 1")[0]
        # Denying it is fine and in fact wanted; asserting it is the bug.
        for hit in re.finditer(r"autoimmune", before_t1):
            window = before_t1[max(0, hit.start() - 24):hit.start()]
            assert "not" in window, f"{q}: unqualified 'autoimmune' in {window!r}"
        assert "immune system destroys" not in before_t1, q


def test_digits_survive_tokenisation(client):
    """'1' was dropped as too short, so 'what is type 1 diabetes' scored the same
    as 'what is diabetes'."""
    from app.routers.chatbot import _tokens
    assert "1" in _tokens("what is type 1 diabetes")
    assert "2" in _tokens("type 2")


def test_clinical_answers_name_a_registered_source(client):
    """Each clinical topic must point at an entry in the source registry, so a
    reader can trace a sentence to a document rather than to 'ADA' in general."""
    import json
    from pathlib import Path
    data = Path(__file__).resolve().parents[1] / "app" / "data"
    registry = json.loads((data / "sources.json").read_text())["sources"]
    topics = json.loads((data / "faq.json").read_text())["topics"]
    for t in topics:
        src = t.get("source")
        assert src, f"{t['id']} has no source"
        assert src == "DiabetEASE" or src in registry, f"{t['id']} cites unregistered source {src}"


def test_sources_endpoint_states_how_each_was_checked(client):
    b = client.get("/api/v1/sources").json()
    assert b["checked_on"]
    for key, s in b["sources"].items():
        assert s["checked"] in ("publisher", "index", "secondary"), key
        assert s["url"].startswith("https://"), key


def test_family_risk_quotes_no_unsourced_number(client):
    """The type 1 answer quoted US figures and said so. There is no comparable
    Philippine figure for type 2 here, so the answer must quote none at all
    rather than borrow one."""
    reply = ask(client, "is type 2 inherited from parents")["reply"]
    assert "no figure specific to the philippines" in reply.lower()
    assert not re.search(r"\b1 in \d+|\d+ in 100|\d+(\.\d+)?\s*%", reply), reply


def test_prediabetes_answer_gives_all_three_cutoffs(client):
    """Prediabetes replaced type 1 staging. It is only useful if it names the
    bands, because a reader is usually holding a lab slip."""
    reply = ask(client, "what is prediabetes")["reply"]
    for band in ("100 to 125", "140 to 199", "5.7 to 6.4"):
        assert band in reply, band


def test_screening_answer_carries_the_asian_ancestry_cutoff(client):
    """The single most consequential number for this study's population: 23
    rather than 25. If this answer loses it, most of the cohort is told the
    wrong thing."""
    reply = ask(client, "should i get tested")["reply"]
    assert "23" in reply and "35" in reply
    assert "three years" in reply or "3 years" in reply


def test_philhealth_coverage_is_explained_with_its_limit(client):
    b = ask(client, "is the test covered by philhealth")
    assert b["matched_topic"] == "philhealth"
    assert "partner laboratory" in b["reply"]
