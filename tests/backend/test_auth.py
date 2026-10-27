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


def test_workflow_events_are_only_streamed_to_the_runs_owner(client, monkeypatch):
    """Regression: any signed-in user could read any run's events by guessing wf-exec-<n>."""
    from backend.api import workflow
    from backend.database.session import get_store
    from backend.models import TEST_EXECUTIONS
    from backend.orchestration.orchestrator import (
        WorkflowEvent,
        WorkflowEventType,
        WorkflowStep,
    )

    run = get_store().insert(TEST_EXECUTIONS, test_case_id=1, status="PASSED", owner_uid="alice")
    event = WorkflowEvent(workflow_id=f"wf-exec-{run['id']}", step=WorkflowStep.COMPLETED,
                          event_type=WorkflowEventType.STATE_TRANSITION, message="done")
    monkeypatch.setattr(workflow._workflow_orchestrator, "execution_events",
                        lambda eid: [event] if eid == run["id"] else [])

    own = client.get(f"/api/workflow/stream/wf-exec-{run['id']}", headers=as_user("token-alice"))
    assert own.status_code == 200 and "done" in own.text
    assert client.get(f"/api/workflow/stream/{run['id']}", headers=as_user("token-alice")).status_code == 200

    other = client.get(f"/api/workflow/stream/wf-exec-{run['id']}", headers=as_user("token-bob"))
    assert other.status_code == 404
    assert "done" not in other.text


def test_unknown_or_eventless_workflows_are_404_not_invented(client):
    from backend.database.session import get_store
    from backend.models import TEST_EXECUTIONS

    for wid in ("wf-exec-999", "999", "not-a-run"):
        assert client.get(f"/api/workflow/stream/{wid}", headers=as_user("token-alice")).status_code == 404
    idle = get_store().insert(TEST_EXECUTIONS, test_case_id=1, status="PENDING", owner_uid="alice")
    resp = client.get(f"/api/workflow/stream/wf-exec-{idle['id']}", headers=as_user("token-alice"))
    assert resp.status_code == 404
    assert "No recorded events" in resp.json()["detail"]


def test_system_info_shows_deployment_details_only_when_signed_in(client):
    anonymous = client.get("/api/system").json()
    assert set(anonymous) == {"service", "api_version", "auth", "privacy"}  # sign-in + the privacy notice
    assert anonymous["auth"]["firebase"] is not None

    expired = client.get("/api/system", headers=as_user("forged"))
    assert expired.status_code == 200 and "llm" not in expired.json()  # no 401: the login page still needs it

    full = client.get("/api/system", headers=as_user("token-alice")).json()
    for key in ("commit", "llm", "scan_scope", "browser", "ingestion", "scheduler"):
        assert key in full


def test_deleting_an_account_erases_only_that_users_data(client, monkeypatch):
    from backend.api import me
    from backend.database.session import get_store

    removed = []
    monkeypatch.setattr(me, "_delete_sign_in_account", lambda uid: removed.append(uid) or True)
    alice, bob = as_user("token-alice"), as_user("token-bob")
    for headers in (alice, bob):
        client.get("/api/me", headers=headers)  # creates the profile
        client.post("/api/projects", json={"name": "p", "app_url": "https://shop.example"}, headers=headers)
    db = get_store()
    db.insert("audit_events", actor="Alice", kind="qa", message="x", owner_uid="alice")

    assert client.request("DELETE", "/api/me", json={}, headers=alice).status_code == 422  # confirmation required
    assert client.request("DELETE", "/api/me", json={"confirm": "yes"}, headers=alice).status_code == 422

    resp = client.request("DELETE", "/api/me", json={"confirm": "DELETE MY ACCOUNT"}, headers=alice)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["deleted"]["projects"] == 1 and body["deleted"]["users"] == 1
    assert body["sign_in_account_deleted"] is True and removed == ["alice"]

    for name in me.OWNED_COLLECTIONS:
        assert db.find(name, owner_uid="alice") == []
    assert db.find("users", uid="alice") == []
    assert len(db.find("projects", owner_uid="bob")) == 1
    assert len(db.find("users", uid="bob")) == 1


def test_a_failed_sign_in_deletion_is_reported(client, monkeypatch):
    from backend.api import me

    monkeypatch.setattr(me, "_delete_sign_in_account", lambda uid: False)
    body = client.request("DELETE", "/api/me", json={"confirm": "DELETE MY ACCOUNT"},
                          headers=as_user("token-alice")).json()
    assert body["sign_in_account_deleted"] is False
    assert "could not be removed" in body["detail"]


def test_local_mode_has_no_account_to_delete():
    resp = TestClient(app).request("DELETE", "/api/me", json={"confirm": "DELETE MY ACCOUNT"})
    assert resp.status_code == 400


def test_the_profile_display_name_is_the_name_on_recorded_actions(client):
    bob = as_user("token-bob")
    pid = client.post("/api/projects", json={"name": "Bob shop", "app_url": "https://shop.example"}, headers=bob).json()["id"]

    def add_app(name):
        resp = client.post("/api/applications", json={"project_id": pid, "name": name, "base_url": "https://shop.example"},
                           headers=bob)
        assert resp.status_code == 201, resp.text
        return client.get("/api/audit", headers=bob).json()[0]["actor"]

    assert add_app("One") == "bob@example.com"  # the token has no name; the profile defaults to it
    client.put("/api/me", json={"display_name": "Krishna"}, headers=bob)
    assert add_app("Two") == "Krishna"


def test_api_tokens_let_an_agent_act_as_the_user_until_revoked(client, fresh_store):
    alice = as_user("token-alice")
    created = client.post("/api/me/tokens", json={"name": "Claude Code MCP"}, headers=alice)
    assert created.status_code == 201, created.text
    token = created.json()["token"]
    assert token.startswith("tsk_") and created.json()["prefix"] == token[:10]
    assert token not in str(fresh_store.find("api_tokens"))  # only its hash is stored

    agent = as_user(token)
    pid = client.post("/api/projects", json={"name": "From the agent", "app_url": "https://shop.example"},
                      headers=agent).json()["id"]
    assert [p["id"] for p in client.get("/api/projects", headers=alice).json()] == [pid]  # acts as Alice
    assert client.get("/api/projects", headers=as_user("token-bob")).json() == []
    listed = client.get("/api/me/tokens", headers=alice).json()
    assert [t["name"] for t in listed] == ["Claude Code MCP"] and listed[0]["last_used_at"]
    assert "token" not in listed[0]

    # Bob can neither see nor revoke it
    assert client.get("/api/me/tokens", headers=as_user("token-bob")).json() == []
    assert client.delete(f"/api/me/tokens/{listed[0]['id']}", headers=as_user("token-bob")).status_code == 404

    assert client.delete(f"/api/me/tokens/{listed[0]['id']}", headers=alice).status_code == 204
    resp = client.get("/api/projects", headers=agent)
    assert resp.status_code == 401 and "revoked" in resp.json()["detail"]
    assert client.get("/api/projects", headers=as_user("tsk_made-up")).status_code == 401
