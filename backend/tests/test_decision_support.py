"""Nearby facilities, the type filter, and Candie's database-backed lookup."""
from __future__ import annotations

import pytest


@pytest.fixture
def stocked(client, admin_token):
    """A few facilities with known evidence states."""
    h = {"Authorization": f"Bearer {admin_token}"}

    def add(**kw):
        r = client.post("/api/v1/facilities", headers=h, json=kw)
        assert r.status_code == 201, r.text
        return r.json()

    add(name="DS Confirmed Hospital", facility_type="Hospital", municipality="Surallah",
        latitude=6.374, longitude=124.747, contact="083-000-1111",
        source="phone call to laboratory", verified_on="2026-11-10",
        services=[{"service_code": "hba1c", "confirmed": True,
                   "source": "phone call to laboratory", "verified_on": "2026-11-10"}])
    add(name="DS Unchecked Clinic", facility_type="Clinic", municipality="Surallah",
        latitude=6.380, longitude=124.750)
    add(name="DS Far Hospital", facility_type="Hospital", municipality="Polomolok",
        latitude=6.217, longitude=125.063,
        source="phone call", verified_on="2026-11-10",
        services=[{"service_code": "glucose", "confirmed": True,
                   "source": "phone call", "verified_on": "2026-11-10"}])
    add(name="DS Unchecked Pharmacy", facility_type="Pharmacy", municipality="Surallah",
        latitude=6.373, longitude=124.748)
    return h


# ------------------------------------------------------------------ nearby
def test_nearby_puts_confirmed_facilities_first(client, stocked):
    b = client.get("/api/v1/facilities/nearby",
                   params={"municipality": "Surallah", "limit": 20}).json()
    names = [n["facility"]["name"] for n in b["items"]]
    assert names.index("DS Confirmed Hospital") < names.index("DS Unchecked Clinic")
    # a confirmed facility elsewhere still outranks an unconfirmed local one
    assert names.index("DS Far Hospital") < names.index("DS Unchecked Clinic")


def test_nearby_reports_distance_and_states_its_basis(client, stocked):
    b = client.get("/api/v1/facilities/nearby",
                   params={"municipality": "Surallah", "limit": 20}).json()
    by_name = {n["facility"]["name"]: n for n in b["items"]}
    assert by_name["DS Confirmed Hospital"]["distance_km"] < 2
    assert 30 < by_name["DS Far Hospital"]["distance_km"] < 45     # Surallah to Polomolok
    assert by_name["DS Far Hospital"]["same_municipality"] is False
    assert "not travel distance" in b["distance_basis"]


def test_nearby_separates_pharmacies_from_testing_centres(client, stocked):
    testing = client.get("/api/v1/facilities/nearby",
                         params={"municipality": "Surallah", "limit": 20}).json()
    assert all(n["facility"]["facility_type"] != "Pharmacy" for n in testing["items"])
    ph = client.get("/api/v1/facilities/nearby",
                    params={"municipality": "Surallah", "kind": "pharmacy", "limit": 20}).json()
    assert ph["items"] and all(n["facility"]["facility_type"] == "Pharmacy" for n in ph["items"])


def test_nearby_rejects_an_uncovered_municipality(client):
    assert client.get("/api/v1/facilities/nearby",
                      params={"municipality": "Davao City"}).status_code == 404


def test_nearby_is_not_swallowed_by_the_id_route(client):
    # /facilities/{id} is declared after /facilities/nearby; if the order were
    # reversed this would be a 422 complaining that "nearby" is not an integer.
    r = client.get("/api/v1/facilities/nearby", params={"municipality": "Surallah"})
    assert r.status_code == 200


# ------------------------------------------------------------- kind filter
def test_list_kind_filter_runs_on_the_server(client, stocked):
    ph = client.get("/api/v1/facilities", params={"kind": "pharmacy", "limit": 500}).json()
    assert ph["items"] and all(f["facility_type"] == "Pharmacy" for f in ph["items"])
    te = client.get("/api/v1/facilities", params={"kind": "testing", "limit": 500}).json()
    assert all(f["facility_type"] != "Pharmacy" for f in te["items"])
    assert client.get("/api/v1/facilities", params={"kind": "bogus"}).status_code == 422


# ------------------------------------------------------ Candie's lookup
def ask(client, msg):
    r = client.post("/api/v1/chat", json={"message": msg})
    assert r.status_code == 200, r.text
    return r.json()


def test_candie_answers_a_location_question_from_the_database(client, stocked):
    b = ask(client, "where can I get tested in Surallah")
    assert b["matched_topic"] == "facility_lookup"
    assert b["grounded"] is True and b["mode"] == "rule_based"
    assert "DS Confirmed Hospital" in b["reply"]
    assert "HbA1c testing" in b["reply"]


def test_candie_never_presents_an_unconfirmed_service_as_confirmed(client, stocked):
    reply = ask(client, "where can I get tested in Surallah")["reply"]
    confirmed_part = reply.split("not yet confirmed")[0]
    assert "DS Unchecked Clinic" not in confirmed_part
    assert "DS Unchecked Clinic" in reply          # still mentioned, honestly labelled


def test_candie_says_insulin_is_unconfirmed_for_an_unchecked_pharmacy(client, stocked):
    reply = ask(client, "is there a pharmacy in Surallah")["reply"]
    assert "DS Unchecked Pharmacy" in reply
    assert "not yet confirmed to stock insulin" in reply
    assert "prescription" in reply


def test_candie_points_elsewhere_when_a_municipality_has_nothing(client, stocked):
    reply = ask(client, "is there a hospital in Banga")["reply"]
    assert "no testing centres on record in Banga" in reply
    assert "municipal health office" in reply


def test_a_medical_question_that_mentions_a_town_is_not_a_lookup(client, stocked):
    b = ask(client, "I live in Surallah, what is HbA1c?")
    assert b["matched_topic"] == "hba1c"


def test_emergency_and_refusal_still_run_before_the_lookup(client, stocked):
    assert ask(client, "he is vomiting, where is a hospital in Surallah")["route"] == "emergency"
    assert ask(client, "how much insulin should I take, pharmacy in Surallah")["refused"] is True


def test_municipality_aliases():
    from app.services.facility_lookup import find_municipality as fm
    assert fm("clinic in santo niño") == "Sto. Nino"
    assert fm("hospital sa tboli") == "T'boli"
    assert fm("pharmacy near Lake Sebu") == "Lake Sebu"
    assert fm("what is diabetes") is None
    # 'tupi' must not match inside another word
    assert fm("stupid question") is None


# ------------------------------------------------------- diagnostics guard
def test_only_one_model_diagnostic_runs_at_a_time(monkeypatch):
    from app.services import llm
    assert llm._diagnose_lock.acquire(blocking=False)
    try:
        import asyncio
        out = asyncio.run(llm.diagnose())
        assert out.get("busy") is True
    finally:
        llm._diagnose_lock.release()


def test_confirmed_facilities_elsewhere_do_not_hide_local_unconfirmed_ones(client, admin_token):
    """With a result cap, 20+ confirmed facilities in other towns pushed local
    unconfirmed ones out of the list, and Candie's answer dropped them silently."""
    h = {"Authorization": f"Bearer {admin_token}"}
    for i in range(25):
        r = client.post("/api/v1/facilities", headers=h, json={
            "name": f"Crowd Hospital {i}", "facility_type": "Hospital",
            "municipality": "Polomolok", "latitude": 6.217, "longitude": 125.063,
            "source": "phone call", "verified_on": "2026-11-10",
            "services": [{"service_code": "glucose", "confirmed": True,
                          "source": "phone call", "verified_on": "2026-11-10"}]})
        assert r.status_code == 201
    client.post("/api/v1/facilities", headers=h, json={
        "name": "Quiet Local Clinic", "facility_type": "Clinic", "municipality": "Banga",
        "latitude": 6.42, "longitude": 124.78})
    reply = client.post("/api/v1/chat",
                        json={"message": "is there a clinic in Banga"}).json()["reply"]
    assert "Quiet Local Clinic" in reply
    assert "not yet confirmed" in reply


def test_nearest_unconfirmed_pharmacies_are_named_when_none_are_local(client, admin_token):
    h = {"Authorization": f"Bearer {admin_token}"}
    client.post("/api/v1/facilities", headers=h, json={
        "name": "Lone Polomolok Botika", "facility_type": "Pharmacy",
        "municipality": "Polomolok", "latitude": 6.218, "longitude": 125.062})
    reply = client.post("/api/v1/chat",
                        json={"message": "is there a pharmacy in Banga"}).json()["reply"]
    assert "no pharmacies on record in Banga" in reply
    # Which follow-up sentence appears depends on whether any pharmacy anywhere
    # has confirmed insulin, and other tests share this database. Either way the
    # answer must point somewhere real instead of stopping at "none".
    assert ("nearest with a confirmed service" in reply
            or "none yet confirmed to stock insulin" in reply)
    assert " in Polomolok" in reply or " in Surallah" in reply
