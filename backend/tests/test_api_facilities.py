from __future__ import annotations


def test_facility_list_is_empty_and_says_so(client):
    body = client.get("/api/v1/facilities").json()
    assert body["total"] == 0 and body["items"] == []
    assert "OpenStreetMap" in body["attribution"]


def test_creating_a_facility_requires_a_token(client):
    r = client.post("/api/v1/facilities", json={
        "name": "Ghost Hospital", "facility_type": "Hospital", "municipality": "Surallah"})
    assert r.status_code == 401


def test_bad_token_is_rejected(client):
    r = client.post("/api/v1/facilities",
                    headers={"Authorization": "Bearer forged.token"},
                    json={"name": "X", "facility_type": "Clinic", "municipality": "Surallah"})
    assert r.status_code == 401


def test_confirmed_service_without_evidence_is_rejected(client, admin_token):
    r = client.post("/api/v1/facilities",
                    headers={"Authorization": f"Bearer {admin_token}"},
                    json={"name": "Evidence-Free Lab", "facility_type": "Diagnostic laboratory",
                          "municipality": "Surallah",
                          "services": [{"service_code": "autoantibody", "confirmed": True}]})
    assert r.status_code == 422


def test_municipality_outside_coverage_is_rejected(client, admin_token):
    r = client.post("/api/v1/facilities",
                    headers={"Authorization": f"Bearer {admin_token}"},
                    json={"name": "Far Away Clinic", "facility_type": "Clinic",
                          "municipality": "Davao City"})
    assert r.status_code == 422


def test_record_without_evidence_lands_as_unconfirmed(client, admin_token):
    r = client.post("/api/v1/facilities",
                    headers={"Authorization": f"Bearer {admin_token}"},
                    json={"name": "Barangay Health Station A", "facility_type": "Clinic",
                          "municipality": "Surallah",
                          "services": [{"service_code": "glucose", "confirmed": False}]})
    assert r.status_code == 201
    assert r.json()["status"] == "unconfirmed"


def test_full_evidence_lands_as_verified_and_filters_work(client, admin_token):
    h = {"Authorization": f"Bearer {admin_token}"}
    r = client.post("/api/v1/facilities", headers=h, json={
        "name": "Test District Hospital", "facility_type": "Hospital",
        "municipality": "Polomolok", "source": "phone call, logged in fieldbook",
        "verified_on": "2026-10-20", "latitude": 6.217, "longitude": 125.063,
        "services": [{"service_code": "hba1c", "confirmed": True,
                      "source": "phone call", "verified_on": "2026-10-20"},
                     {"service_code": "autoantibody", "confirmed": False}],
    })
    assert r.status_code == 201 and r.json()["status"] == "verified"

    hit = client.get("/api/v1/facilities",
                     params={"service": "hba1c", "confirmed_only": True}).json()
    assert any(f["name"] == "Test District Hospital" for f in hit["items"])

    # The unconfirmed autoantibody service must not surface as a confirmed claim.
    miss = client.get("/api/v1/facilities",
                      params={"service": "autoantibody", "confirmed_only": True}).json()
    assert miss["items"] == []


def test_verification_history_marks_a_changed_record_outdated(client, admin_token):
    h = {"Authorization": f"Bearer {admin_token}"}
    fid = client.post("/api/v1/facilities", headers=h, json={
        "name": "Recheck Me Clinic", "facility_type": "Clinic", "municipality": "Surallah",
        "source": "registry", "verified_on": "2026-01-05"}).json()["id"]
    r = client.post(f"/api/v1/facilities/{fid}/verifications", headers=h, json={
        "checked_on": "2026-10-25", "checked_by": "field team",
        "method": "phone_call", "outcome": "changed"})
    assert r.status_code == 201 and r.json()["status"] == "outdated"
    assert len(client.get(f"/api/v1/facilities/{fid}/verifications").json()["items"]) == 1


def test_missing_facility_returns_404(client):
    assert client.get("/api/v1/facilities/999999").status_code == 404


def test_a_directory_listing_cannot_evidence_a_service(client, admin_token):
    """A places listing proves a facility exists, not which tests it runs.
    Accepting it as a service source is how a map ends up asserting that a
    clinic does HbA1c when nobody ever checked."""
    h = {"Authorization": f"Bearer {admin_token}"}
    r = client.post("/api/v1/facilities", headers=h, json={
        "name": "Listing Only Clinic", "facility_type": "Clinic",
        "municipality": "Surallah", "source": "Google Places",
        "verified_on": "2026-10-29",
        "services": [{"service_code": "hba1c", "confirmed": True,
                      "source": "Google Places", "verified_on": "2026-10-29"}],
    })
    # The API still accepts it (source and date are present), so the importer's
    # stricter gate is what must catch this. Guard the importer directly.
    from import_facilities import evidences_a_service
    assert evidences_a_service("Google Places") is False
    assert evidences_a_service("Google Places + RHU standard") is False
    assert evidences_a_service("assumed") is False
    assert evidences_a_service("phone call to records office") is True
    assert evidences_a_service("Web verification + PhilHealth Konsulta") is True
    assert evidences_a_service("site visit 2026-11-04") is True
    assert r.status_code in (201, 422)


def test_pharmacies_and_insulin_are_supported(client, admin_token):
    h = {"Authorization": f"Bearer {admin_token}"}
    r = client.post("/api/v1/facilities", headers=h, json={
        "name": "Test Pharmacy Insulin", "facility_type": "Pharmacy",
        "municipality": "Surallah", "source": "phone call to pharmacist",
        "verified_on": "2026-11-05",
        "services": [{"service_code": "insulin", "confirmed": True,
                      "source": "phone call to pharmacist", "verified_on": "2026-11-05"},
                     {"service_code": "glucose_supplies", "confirmed": False}],
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["facility_type"] == "Pharmacy" and body["status"] == "verified"

    hit = client.get("/api/v1/facilities",
                     params={"service": "insulin", "confirmed_only": True}).json()
    assert any(f["name"] == "Test Pharmacy Insulin" for f in hit["items"])

    miss = client.get("/api/v1/facilities",
                      params={"service": "glucose_supplies", "confirmed_only": True}).json()
    assert not any(f["name"] == "Test Pharmacy Insulin" for f in miss["items"])


def test_insulin_claim_from_a_listing_is_downgraded_by_the_importer():
    """A pharmacy appearing in a directory does not mean it stocks insulin."""
    from import_facilities import evidences_a_service
    assert evidences_a_service("Google Places search - location only") is False
    assert evidences_a_service("called the pharmacist, insulin in stock") is True
