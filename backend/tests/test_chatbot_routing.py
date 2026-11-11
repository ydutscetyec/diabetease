"""Routing and safety ordering for open-ended answering.

The property under test: a clinical question can never reach free generation,
and the emergency/refusal checks can never be bypassed by one.
"""
from __future__ import annotations

import pytest

from app.routers import chatbot
from app.services import llm


def ask(client, msg, history=None):
    payload = {"message": msg}
    if history is not None:
        payload["history"] = history
    r = client.post("/api/v1/chat", json=payload)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture
def fake_llm(monkeypatch):
    """Pretend a model is configured, and record what it was asked to do."""
    calls = {"open": [], "rephrase": []}

    async def _open(question, history=None, timeout=90.0):
        calls["open"].append((question, history))
        return "OPEN ANSWER: " + question

    async def _rephrase(question, reference, timeout=60.0):
        calls["rephrase"].append((question, reference))
        return "GROUNDED ANSWER"

    monkeypatch.setattr(llm, "available", lambda: True)
    monkeypatch.setattr(llm, "answer_open", _open)
    monkeypatch.setattr(llm, "rephrase", _rephrase)
    return calls


# ---------------------------------------------------------------- safety order
def test_emergency_never_reaches_the_model(client, fake_llm):
    b = ask(client, "my brother is vomiting and very sleepy")
    assert b["route"] == "emergency" and b["grounded"] is True
    assert fake_llm["open"] == [] and fake_llm["rephrase"] == []


def test_refusal_never_reaches_the_model(client, fake_llm):
    b = ask(client, "how much insulin should I take")
    assert b["route"] == "refused" and b["refused"] is True
    assert fake_llm["open"] == [] and fake_llm["rephrase"] == []


def test_clinical_question_without_a_corpus_hit_is_declined_not_generated(client, fake_llm):
    # Medical, but nothing in the corpus covers it. Must NOT go to open generation.
    b = ask(client, "what is the prognosis after a kidney transplant")
    assert b["route"] == "declined"
    assert b["grounded"] is True
    assert fake_llm["open"] == [], "a clinical miss must never reach free generation"


def test_clinical_hit_is_grounded_in_the_corpus(client, fake_llm):
    b = ask(client, "what is hba1c")
    assert b["route"] == "grounded" and b["grounded"] is True
    assert len(fake_llm["rephrase"]) == 1
    # the model was handed the reviewed text as its only source
    assert "6.5" in fake_llm["rephrase"][0][1]


# ------------------------------------------------------------- open answering
def test_non_clinical_question_is_answered_freely(client, fake_llm):
    b = ask(client, "can you help me write a summary for my presentation")
    assert b["route"] == "open"
    assert b["grounded"] is False
    assert b["mode"] == "language_model"
    assert len(fake_llm["open"]) == 1


def test_history_is_passed_for_follow_ups(client, fake_llm):
    hist = [{"role": "user", "content": "tell me about the project"},
            {"role": "assistant", "content": "DiabetEASE is a research prototype."}]
    ask(client, "who is it for", history=hist)
    assert fake_llm["open"][0][1] == hist


def test_history_is_length_capped(client):
    long_hist = [{"role": "user", "content": "x"} for _ in range(20)]
    r = client.post("/api/v1/chat", json={"message": "hello", "history": long_hist})
    assert r.status_code == 422


def test_history_entry_is_size_capped(client):
    r = client.post("/api/v1/chat", json={
        "message": "hello",
        "history": [{"role": "user", "content": "x" * 1001}]})
    assert r.status_code == 422


# ------------------------------------------------- behaviour with no model set
def test_without_a_model_a_near_miss_offers_related_topics(client):
    b = ask(client, "tell me something about the map records")
    assert b["route"] in ("suggestions", "grounded")
    if b["route"] == "suggestions":
        assert "Related topics" in b["reply"]


def test_without_a_model_non_clinical_misses_do_not_claim_an_answer(client):
    b = ask(client, "zzzz qqqq wwww vvvv")
    assert b["route"] == "suggestions"
    assert b["mode"] == "rule_based"


def test_a_tangential_clinical_hit_stays_grounded_rather_than_generated(client, fake_llm):
    """A weak corpus hit on an off-topic clinical question is answered from the
    corpus. The answer may be tangential, but it is reviewed text rather than an
    improvised one, which is the correct failure mode here."""
    b = ask(client, "does pancreatitis damage the beta cells permanently")
    assert b["route"] == "grounded" and b["grounded"] is True
    assert fake_llm["open"] == []


def test_clinical_classifier_catches_medical_vocabulary():
    assert chatbot._is_clinical("does pancreatitis damage beta cells")
    assert chatbot._is_clinical("what are the complications")
    assert chatbot._is_clinical("is my blood test normal")
    assert not chatbot._is_clinical("who built this website")
    assert not chatbot._is_clinical("help me write my presentation slides")


def test_topics_endpoint_reports_open_answering_state(client):
    b = client.get("/api/v1/chat/topics").json()
    assert b["open_answering"] is False
    assert b["llm_configured"] is False
