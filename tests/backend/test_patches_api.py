"""POST /api/security/patches: findings of a site -> a stored patch for its repository."""

import json
import textwrap

import pytest
from fastapi.testclient import TestClient

from backend import auth
from backend.config import settings
from backend.database.session import get_store
from backend.main import app
from backend.models import SECURITY_FINDINGS
from backend.services.project_service import ProjectService

SITE = "http://shop.test/"
APP = textwrap.dedent("""
    from fastapi import FastAPI

    app = FastAPI()
""").lstrip()


def seed_finding(db, check_id, owner="local-dev", status="open", target=SITE):
    data = {"check_id": check_id, "title": check_id, "severity": "medium", "component": target,
            "evidence": [], "recommendation": f"fix {check_id}", "target_url": target}
    return db.insert(SECURITY_FINDINGS, key=f"{owner}:{check_id}", target_url=target, check_id=check_id,
                     severity="medium", title=check_id, data=json.dumps(data), status=status, owner_uid=owner,
                     first_seen="2026-10-24T10:00:00+00:00", last_seen="2026-10-24T10:00:00+00:00")


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "INGEST_ALLOW_LOCAL_PATHS", True)
    monkeypatch.setattr(settings, "INGEST_WORKSPACE", str(tmp_path / "ws"))
    root = tmp_path / "shop"
    root.mkdir()
    (root / "main.py").write_text(APP, encoding="utf-8")
    return root


def test_patch_for_the_projects_repository_is_built_stored_and_downloadable(repo):
    db = get_store()
    ProjectService.create_project(db, name="Shop", owner_uid="local-dev", app_url=SITE, repo_url=str(repo))
    seed_finding(db, "SEC-HDR-FRAME")
    seed_finding(db, "SEC-TRANSPORT-HTTP")
    seed_finding(db, "SEC-HDR-XCTO", status="resolved")  # only open findings are patched
    client = TestClient(app)

    resp = client.post("/api/security/patches", json={"target_url": SITE})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["repo"] == str(repo) and body["frameworks"] == ["fastapi"]
    assert [f["path"] for f in body["files"]] == ["main.py"] and body["files"][0]["verified"] is True
    assert '+    response.headers["X-Frame-Options"] = "DENY"' in body["patch"]
    assert "X-Content-Type-Options" not in body["patch"]
    assert [m["check_id"] for m in body["manual"]] == ["SEC-TRANSPORT-HTTP"]
    assert (repo / "main.py").read_text() == APP  # the repository itself is never modified

    listed = client.get("/api/security/patches", params={"target_url": SITE}).json()
    assert [p["id"] for p in listed] == [body["id"]]
    dl = client.get(f"/api/security/patches/{body['id']}/download")
    assert dl.status_code == 200 and dl.text == body["patch"]
    assert "attachment" in dl.headers["content-disposition"]
    assert any(e["kind"] == "patch" for e in client.get("/api/audit").json())


def test_explains_missing_findings_or_repository(repo):
    db = get_store()
    client = TestClient(app)
    assert "scan it first" in client.post("/api/security/patches", json={"target_url": SITE}).json()["detail"]
    seed_finding(db, "SEC-HDR-FRAME")
    resp = client.post("/api/security/patches", json={"target_url": SITE})
    assert resp.status_code == 422 and "No repository is linked" in resp.json()["detail"]
    # an explicit repository works without a project
    assert client.post("/api/security/patches", json={"target_url": SITE, "repo": str(repo)}).status_code == 201


def test_local_paths_and_bad_git_urls_are_refused(repo, monkeypatch):
    seed_finding(get_store(), "SEC-HDR-FRAME")
    client = TestClient(app)
    monkeypatch.setattr(settings, "INGEST_ALLOW_LOCAL_PATHS", False)
    resp = client.post("/api/security/patches", json={"target_url": SITE, "repo": str(repo)})
    assert resp.status_code == 422 and "Local folder paths are disabled" in resp.json()["detail"]
    resp = client.post("/api/security/patches", json={"target_url": SITE, "repo": "https://evil.example/a/b"})
    assert resp.status_code == 422 and "not allowed" in resp.json()["detail"]


def test_patches_belong_to_their_owner(repo, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    tokens = {"a": {"uid": "alice", "email": "a@x.example", "firebase": {"sign_in_provider": "password"}},
              "b": {"uid": "bob", "email": "b@x.example", "firebase": {"sign_in_provider": "password"}}}
    monkeypatch.setattr(auth, "verify_token", lambda t: tokens[t])
    seed_finding(get_store(), "SEC-HDR-FRAME", owner="alice")
    client = TestClient(app)
    alice, bob = {"Authorization": "Bearer a"}, {"Authorization": "Bearer b"}

    created = client.post("/api/security/patches", json={"target_url": SITE, "repo": str(repo)}, headers=alice).json()
    assert client.get(f"/api/security/patches/{created['id']}/download", headers=bob).status_code == 404
    assert client.get("/api/security/patches", headers=bob).json() == []
    # Bob cannot patch Alice's findings either
    assert client.post("/api/security/patches", json={"target_url": SITE, "repo": str(repo)}, headers=bob).status_code == 422

    from backend.api import me
    monkeypatch.setattr(me, "_delete_sign_in_account", lambda uid: True)
    client.request("DELETE", "/api/me", json={"confirm": "DELETE MY ACCOUNT"}, headers=alice)
    assert get_store().find("fix_patches", owner_uid="alice") == []
