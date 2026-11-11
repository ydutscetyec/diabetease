"""Open medical answering, and the rails that stay in place regardless."""
from __future__ import annotations

import pytest

from app.config import get_settings
from app.services import llm


@pytest.fixture
def fake_llm(monkeypatch):
    calls = {"clinical": [], "open": [], "rephrase": []}
    monkeypatch.setattr(llm, "available", lambda: True)
    async def _clinical(q, h=None, timeout=90.0):
        calls["clinical"].append(q)
        return "General information about that."

    async def _open(q, h=None, timeout=90.0):
        calls["open"].append(q)
        return "Open answer."

    async def _rephrase(q, r, timeout=60.0):
        calls["rephrase"].append(q)
        return "Reworded."

    monkeypatch.setattr(llm, "answer_clinical", _clinical)
    monkeypatch.setattr(llm, "answer_open", _open)
    monkeypatch.setattr(llm, "rephrase", _rephrase)
    return calls


def ask(client, msg):
    r = client.post("/api/v1/chat", json={"message": msg})
    assert r.status_code == 200, r.text
    return r.json()


def test_clinical_open_answers_is_on_in_this_build(client, fake_llm):
    assert client.get("/api/v1/chat/topics").json()["clinical_open_answers"] is True


def test_a_medical_question_outside_the_corpus_is_now_answered(client, fake_llm):
    b = ask(client, "what is the prognosis after a kidney transplant")
    assert b["route"] == "open"
    assert b["grounded"] is False
    assert len(fake_llm["clinical"]) == 1
    assert "not been reviewed" in b["reply"]


def test_generated_medical_text_is_always_labelled(client, fake_llm):
    for q in ["can a virus trigger autoimmunity",
              "what does the pancreas do",
              "how does insulin resistance work"]:
        b = ask(client, q)
        if b["route"] == "open":
            assert b["grounded"] is False
            assert "not been reviewed" in b["reply"]


def test_dosing_is_still_refused(client, fake_llm):
    for q in ["how much insulin should I take", "what dosage do I need",
              "should I stop taking my medicine"]:
        assert ask(client, q)["refused"] is True
    assert fake_llm["clinical"] == [], "refusal must run before any generation"


def test_diagnosis_requests_are_still_refused(client, fake_llm):
    for q in ["do I have diabetes", "am I diabetic", "diagnose me"]:
        assert ask(client, q)["refused"] is True
    assert fake_llm["clinical"] == []


def test_emergency_still_short_circuits_everything(client, fake_llm):
    b = ask(client, "he is vomiting and unresponsive, what dose do I give")
    assert b["route"] == "emergency"
    assert "emergency department" in b["reply"]
    assert fake_llm["clinical"] == [] and fake_llm["open"] == []


def test_reviewed_topics_still_win_over_generation(client, fake_llm):
    b = ask(client, "what is hba1c")
    assert b["route"] == "grounded"
    assert b["grounded"] is True
    assert fake_llm["clinical"] == []


def test_switching_it_off_restores_the_decline(client, monkeypatch, fake_llm):
    monkeypatch.setenv("CLINICAL_OPEN_ANSWERS", "false")
    get_settings.cache_clear()
    b = ask(client, "what is the prognosis after a kidney transplant")
    assert b["route"] == "declined"
    assert fake_llm["clinical"] == []
    get_settings.cache_clear()


def test_without_a_model_nothing_changes(client):
    b = ask(client, "what is the prognosis after a kidney transplant")
    assert b["route"] == "declined"
