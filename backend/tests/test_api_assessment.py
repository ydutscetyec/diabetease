from __future__ import annotations


def test_health_reports_model_unavailable(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["model"] == "unavailable"


def test_assessment_returns_rule_based_result_with_no_model(client):
    r = client.post("/api/v1/assessments", json={
        "age": 13, "glucose_test_type": "fasting", "glucose_mgdl": 210,
        "symptoms": ["thirst", "weight_loss"],
    })
    assert r.status_code == 200
    body = r.json()
    assert body["tier"] == "urgent"
    assert body["source"] == "rule_based_thresholds"
    assert body["model"]["available"] is False
    assert "probability" not in body


def test_glucose_without_test_type_is_rejected(client):
    r = client.post("/api/v1/assessments", json={"age": 20, "glucose_mgdl": 150})
    assert r.status_code == 422
    assert r.json()["error"] == "validation_failed"


def test_impossible_values_are_rejected(client):
    assert client.post("/api/v1/assessments", json={"age": 0}).status_code == 422
    assert client.post("/api/v1/assessments", json={"age": 200}).status_code == 422
    assert client.post("/api/v1/assessments", json={
        "age": 20, "glucose_test_type": "fasting", "glucose_mgdl": 5000}).status_code == 422
    assert client.post("/api/v1/assessments", json={"age": 20, "hba1c_pct": 40}).status_code == 422


def test_unknown_symptom_code_is_rejected(client):
    r = client.post("/api/v1/assessments", json={"age": 20, "symptoms": ["sparkles"]})
    assert r.status_code == 422


def test_validation_error_does_not_echo_submitted_values(client):
    r = client.post("/api/v1/assessments", json={
        "age": 20, "hba1c_pct": 99.7, "municipality": "Surallah"})
    assert r.status_code == 422
    assert "99.7" not in r.text


def test_assessment_is_not_stored_by_default(client):
    r = client.post("/api/v1/assessments", json={"age": 20, "consent_to_store": True})
    assert r.json()["stored"] is False


def test_thresholds_endpoint_exposes_cutoffs_for_audit(client):
    body = client.get("/api/v1/assessments/thresholds").json()
    assert body["thresholds"]["hba1c_diagnostic_pct"] == 6.5
    assert "Standards of Care" in body["source"]
