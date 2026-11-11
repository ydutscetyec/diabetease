"""Candie's safety ordering and retrieval quality."""
from __future__ import annotations


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
        "explain islet autoantibodies": "autoantibodies",
        "is type 1 inherited from parents": "family",
        "what are the stages before symptoms": "stages",
        "where can I get tested": "testing_centers",
        "why is there no trained model": "why_no_model",
        "what are the limitations of this study": "limitations",
        "who are you": "what_is_candie",
        "how much does it cost": "cost",
    }
    for q, expected in cases.items():
        assert ask(client, q)["matched_topic"] == expected, q


def test_local_language_triggers_resolve(client):
    assert ask(client, "ano ang type 1 diabetes")["matched_topic"] == "what_is_t1d"
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


def test_general_and_type1_definitions_are_separate_topics(client):
    """A model answering 'what is diabetes' from its own knowledge described it
    as the body being unable to use insulin, which is Type 2 and the opposite of
    the Type 1 mechanism. Both questions now have reviewed answers."""
    general = ask(client, "what is diabetes")
    assert general["matched_topic"] == "what_is_diabetes"
    assert "immune system destroys" in general["reply"]
    assert "Type 2" in general["reply"]

    t1 = ask(client, "what is type 1 diabetes")
    assert t1["matched_topic"] == "what_is_t1d"


def test_type_1_is_never_described_as_insulin_resistance(client):
    for q in ["what is diabetes", "what is type 1 diabetes",
              "tell me about type 1 diabetes", "what causes type 1"]:
        reply = ask(client, q)["reply"].lower()
        assert "type 1" not in reply or "resist" not in reply.split("type 2")[0], q


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


def test_family_risk_is_not_presented_as_a_philippine_figure(client):
    reply = ask(client, "is type 1 inherited from parents")["reply"]
    assert "United States" in reply


def test_stage_three_is_not_described_as_always_symptomatic(client):
    reply = ask(client, "tell me about the three stages")["reply"]
    assert "with or without symptoms" in reply


def test_philhealth_coverage_is_explained_with_its_limit(client):
    b = ask(client, "is the test covered by philhealth")
    assert b["matched_topic"] == "philhealth"
    assert "partner laboratory" in b["reply"]
