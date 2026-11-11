from __future__ import annotations


def test_chat_answers_from_the_corpus(client):
    body = client.post("/api/v1/chat", json={"message": "what is hba1c?"}).json()
    assert body["matched_topic"] == "hba1c"
    assert body["mode"] == "rule_based"


def test_chat_refuses_dosing_and_diagnosis(client):
    for q in ["how much insulin should I take", "do I have diabetes", "what dosage"]:
        body = client.post("/api/v1/chat", json={"message": q}).json()
        assert body["refused"] is True


def test_chat_routes_emergency_words_before_anything_else(client):
    body = client.post("/api/v1/chat",
                       json={"message": "my brother is vomiting and very sleepy"}).json()
    assert body["matched_topic"] == "emergency"
    assert "emergency department" in body["reply"]


def test_chat_admits_when_it_has_no_answer(client):
    body = client.post("/api/v1/chat", json={"message": "who won the 2026 palarong pambansa"}).json()
    assert body["matched_topic"] is None
    assert body["route"] in ("suggestions", "declined")


def test_chat_rejects_empty_and_oversized_messages(client):
    assert client.post("/api/v1/chat", json={"message": ""}).status_code == 422
    assert client.post("/api/v1/chat", json={"message": "a" * 501}).status_code == 422


def test_admin_metrics_requires_auth(client):
    assert client.get("/api/v1/admin/metrics").status_code == 401


def test_wrong_password_is_rejected(client):
    r = client.post("/api/v1/admin/login", json={"username": "tester", "password": "wrong"})
    assert r.status_code == 401


def test_admin_metrics_reports_no_active_model_and_no_denominator(client, admin_token):
    body = client.get("/api/v1/admin/metrics",
                      headers={"Authorization": f"Bearer {admin_token}"}).json()
    assert body["model"]["status"] == "no active model"
    assert body["model"]["metrics"] == {}
    assert "unknown" in body["facilities"]["coverage_denominator"]
    assert body["usability_evaluation"]["respondents"] == 0
