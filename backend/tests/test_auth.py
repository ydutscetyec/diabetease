"""Accounts, role escalation and self-service deletion."""
from __future__ import annotations


def reg(client, username, password="a-long-enough-pw", **kw):
    return client.post("/api/v1/auth/register",
                       json={"username": username, "password": password, **kw})


def test_registration_returns_a_patient_token(client):
    r = reg(client, "patient_one")
    assert r.status_code == 201
    assert r.json()["role"] == "patient"


def test_self_registration_cannot_grant_a_staff_role(client):
    # role is not an accepted field; even if it were, it is never read.
    r = client.post("/api/v1/auth/register", json={
        "username": "sneaky", "password": "a-long-enough-pw", "role": "admin"})
    assert r.status_code == 422          # extra="forbid" rejects it outright
    r = reg(client, "sneaky2")
    assert r.json()["role"] == "patient"


def test_short_password_is_rejected(client):
    assert reg(client, "shorty", password="abc").status_code == 422


def test_duplicate_username_is_rejected(client):
    reg(client, "twice")
    assert reg(client, "twice").status_code == 409


def test_bad_username_characters_rejected(client):
    assert reg(client, "has spaces").status_code == 422


def test_login_and_me(client):
    reg(client, "loginuser")
    r = client.post("/api/v1/auth/login",
                    json={"username": "loginuser", "password": "a-long-enough-pw"})
    assert r.status_code == 200
    token = r.json()["token"]
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["username"] == "loginuser" and me.json()["role"] == "patient"


def test_wrong_password_rejected(client):
    reg(client, "pwtest")
    assert client.post("/api/v1/auth/login",
                       json={"username": "pwtest", "password": "wrong-password"}).status_code == 401


def test_unknown_user_and_wrong_password_give_the_same_error(client):
    a = client.post("/api/v1/auth/login", json={"username": "ghost", "password": "whatever-long"})
    reg(client, "realuser")
    b = client.post("/api/v1/auth/login", json={"username": "realuser", "password": "whatever-long"})
    assert a.status_code == b.status_code == 401
    assert a.json()["detail"] == b.json()["detail"]


def test_patient_cannot_read_evaluation_metrics(client):
    token = reg(client, "nosy_patient").json()["token"]
    r = client.get("/api/v1/admin/metrics", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


def test_patient_cannot_write_facilities(client):
    token = reg(client, "nosy_patient2").json()["token"]
    r = client.post("/api/v1/facilities", headers={"Authorization": f"Bearer {token}"},
                    json={"name": "Patient Hospital", "facility_type": "Clinic",
                          "municipality": "Surallah"})
    assert r.status_code == 403


def test_patient_cannot_grant_roles(client):
    token = reg(client, "wannabe").json()["token"]
    r = client.post("/api/v1/auth/grant", headers={"Authorization": f"Bearer {token}"},
                    json={"username": "wannabe", "role": "admin"})
    assert r.status_code == 403


def test_env_admin_can_grant_researcher(client, admin_token):
    reg(client, "future_researcher")
    r = client.post("/api/v1/auth/grant", headers={"Authorization": f"Bearer {admin_token}"},
                    json={"username": "future_researcher", "role": "researcher"})
    assert r.status_code == 200 and r.json()["role"] == "researcher"

    tok = client.post("/api/v1/auth/login",
                      json={"username": "future_researcher",
                            "password": "a-long-enough-pw"}).json()["token"]
    assert client.get("/api/v1/admin/metrics",
                      headers={"Authorization": f"Bearer {tok}"}).status_code == 200


def test_account_deletion_removes_the_account(client):
    token = reg(client, "deleteme").json()["token"]
    h = {"Authorization": f"Bearer {token}"}
    assert client.delete("/api/v1/auth/me", headers=h).json()["deleted"] is True
    assert client.post("/api/v1/auth/login",
                       json={"username": "deleteme",
                             "password": "a-long-enough-pw"}).status_code == 401


def test_me_requires_a_token(client):
    assert client.get("/api/v1/auth/me").status_code == 401
