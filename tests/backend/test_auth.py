"""
Sign-in (Firebase ID tokens, verification stubbed), per-user data isolation
and the profile endpoints.
"""

import pytest
from fastapi.testclient import TestClient

from backend import auth
from backend.config import settings
from backend.main import app

TOKENS = {
    "token-alice": {"uid": "alice", "email": "alice@example.com", "name": "Alice", "firebase": {"sign_in_provider": "password"}},
    "token-bob": {"uid": "bob", "email": "bob@example.com", "firebase": {"sign_in_provider": "google.com"}},
}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)

    def verify(token):
        if token not in TOKENS:
            raise ValueError("Token expired")
        return TOKENS[token]

    monkeypatch.setattr(auth, "verify_token", verify)
    return TestClient(app)


def as_user(token):
    return {"Authorization": f"Bearer {token}"}


def test_requests_without_a_token_are_rejected(client):
    resp = client.get("/api/projects")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Sign in required."
    assert resp.headers["www-authenticate"] == "Bearer"


def test_invalid_token_is_rejected_with_a_readable_reason(client):
    resp = client.get("/api/projects", headers=as_user("forged"))
    assert resp.status_code == 401
    assert "Sign in again" in resp.json()["detail"]


def test_health_and_system_stay_public(client):
    assert client.get("/api/health").status_code == 200
    system = client.get("/api/system").json()
    assert system["auth"]["required"] is True
    assert system["auth"]["provider"] == "firebase"


def test_users_only_see_their_own_data(client):
    created = client.post("/api/projects", json={"name": "Alice's shop", "app_url": "https://shop.example"},
                          headers=as_user("token-alice"))
    assert created.status_code == 201, created.text
    pid = created.json()["id"]
    app_resp = client.post("/api/applications", json={"project_id": pid, "name": "Shop", "base_url": "https://shop.example"},
                           headers=as_user("token-alice"))
    assert app_resp.status_code == 201

    # Bob sees nothing and cannot touch Alice's records (404, not 403)
    assert client.get("/api/projects", headers=as_user("token-bob")).json() == []
    assert client.get("/api/applications", headers=as_user("token-bob")).json() == []
    assert client.get(f"/api/projects/{pid}", headers=as_user("token-bob")).status_code == 404
    assert client.delete(f"/api/projects/{pid}", headers=as_user("token-bob")).status_code == 404
    assert client.post("/api/applications", json={"project_id": pid, "name": "x", "base_url": "https://x.example"},
                       headers=as_user("token-bob")).status_code == 404
    assert client.get("/api/audit", headers=as_user("token-bob")).json() == []

    # Alice still sees hers, and the audit actor is her verified name
    assert [p["id"] for p in client.get("/api/projects", headers=as_user("token-alice")).json()] == [pid]
    audit = client.get("/api/audit", headers=as_user("token-alice")).json()
    assert audit and audit[0]["actor"] == "Alice"


def test_profile_is_created_on_first_sign_in_and_editable(client):
    me = client.get("/api/me", headers=as_user("token-bob")).json()
    assert me["uid"] == "bob"
    assert me["email"] == "bob@example.com"
    assert me["display_name"] == "bob"  # from the email when the token has no name
    assert me["provider"] == "google.com"
    assert me["stats"]["projects"] == 0

    updated = client.put("/api/me", json={"display_name": "Bob B", "organization": "QA Inc"}, headers=as_user("token-bob")).json()
    assert updated["display_name"] == "Bob B"
    assert updated["organization"] == "QA Inc"
    assert client.post("/api/me/login", headers=as_user("token-bob")).json()["last_login_at"]
    # Alice's profile is separate
    assert client.get("/api/me", headers=as_user("token-alice")).json()["display_name"] == "Alice"


def test_sign_in_off_runs_as_the_local_user():
    client = TestClient(app)  # conftest: AUTH_REQUIRED=false
    me = client.get("/api/me").json()
    assert me["local"] is True
    assert client.get("/api/system").json()["auth"] == {"required": False, "provider": "local", "firebase": None}
