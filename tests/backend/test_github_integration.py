"""
GitHub integration: connect with a token, open a pull request from a fix
patch, set commit statuses.  GitHub itself is an httpx mock.
"""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from backend import github, secretbox
from backend.config import settings
from backend.database.session import get_store
from backend.github import GitHubClient, GitHubError, parse_repo
from backend.main import app
from backend.models import FIX_PATCHES, INTEGRATIONS

BASE = "a" * 40
TOKEN = "github_pat_" + "x" * 40


class FakeGitHub:
    """Records calls; answers like the GitHub REST API."""

    def __init__(self, push=True, existing_branches=0, status=200):
        self.calls, self.push, self.existing, self.status = [], push, existing_branches, status

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path, body = request.url.path, json.loads(request.content or b"{}")
        self.calls.append((request.method, path, body))
        if self.status != 200:
            return httpx.Response(self.status, json={"message": "Bad credentials"})
        if path == "/user":
            return httpx.Response(200, json={"login": "octo", "name": "Octo Cat", "avatar_url": "https://x/a.png"})
        if path == "/repos/acme/shop":
            return httpx.Response(200, json={"default_branch": "main", "permissions": {"push": self.push}})
        if path == f"/repos/acme/shop/git/commits/{BASE}":
            return httpx.Response(200, json={"sha": BASE, "tree": {"sha": "basetree"}})
        if path.endswith("/git/blobs"):
            return httpx.Response(201, json={"sha": f"blob{len(self.calls)}"})
        if path.endswith("/git/trees"):
            return httpx.Response(201, json={"sha": "newtree"})
        if path.endswith("/git/commits"):
            return httpx.Response(201, json={"sha": "newcommit"})
        if path.endswith("/git/refs"):
            if self.existing:
                self.existing -= 1
                return httpx.Response(422, json={"message": "Reference already exists"})
            return httpx.Response(201, json={"ref": body["ref"]})
        if path.endswith("/pulls"):
            return httpx.Response(201, json={"html_url": "https://github.com/acme/shop/pull/7", "number": 7})
        if "/statuses/" in path:
            return httpx.Response(201, json={})
        return httpx.Response(404, json={"message": "Not Found"})


def test_parse_repo():
    assert parse_repo("https://github.com/acme/shop") == ("acme", "shop")
    assert parse_repo("https://github.com/acme/shop.git/") == ("acme", "shop")
    assert parse_repo("https://gitlab.com/acme/shop") is None
    assert parse_repo("https://github.com.evil.example/acme/shop") is None


def test_pull_request_is_one_commit_on_a_new_branch_from_the_patch_base():
    fake = FakeGitHub(existing_branches=1)
    with GitHubClient(TOKEN, transport=httpx.MockTransport(fake)) as gh:
        pr = gh.open_fix_pr("acme", "shop", BASE, [("app/main.py", "x = 1\n"), ("nginx.conf", "y\n")],
                            branch="testsphere/fix-3", title="Fix headers", body="Body")
    assert pr == {"url": "https://github.com/acme/shop/pull/7", "number": 7, "branch": "testsphere/fix-3-2", "base": "main"}
    blobs = [b for m, p, b in fake.calls if p.endswith("/git/blobs")]
    assert [b["content"] for b in blobs] == ["x = 1\n", "y\n"]
    tree = next(b for m, p, b in fake.calls if p.endswith("/git/trees"))
    assert tree["base_tree"] == "basetree" and [e["path"] for e in tree["tree"]] == ["app/main.py", "nginx.conf"]
    commit = next(b for m, p, b in fake.calls if p.endswith("/git/commits") and m == "POST")
    assert commit["parents"] == [BASE]
    pull = next(b for m, p, b in fake.calls if p.endswith("/pulls"))
    assert pull["base"] == "main" and pull["head"] == "testsphere/fix-3-2"
    assert all(request_path.startswith("/") for _, request_path, _ in fake.calls)


def test_readable_errors_for_missing_access_and_bad_tokens():
    with GitHubClient(TOKEN, transport=httpx.MockTransport(FakeGitHub(push=False))) as gh, pytest.raises(GitHubError, match="cannot push"):
        gh.open_fix_pr("acme", "shop", BASE, [("a", "b")], "b", "t", "x")
    with GitHubClient(TOKEN, transport=httpx.MockTransport(FakeGitHub(status=401))) as gh, pytest.raises(GitHubError, match="rejected the token"):
        gh.user()


def test_tokens_are_encrypted_and_a_hosted_server_needs_the_key(monkeypatch, tmp_path):
    from cryptography.fernet import Fernet

    monkeypatch.setattr(settings, "TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    sealed = secretbox.encrypt(TOKEN)
    assert TOKEN not in sealed and secretbox.decrypt(sealed) == TOKEN
    monkeypatch.setattr(settings, "TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    with pytest.raises(secretbox.SecretBoxError, match="key changed"):
        secretbox.decrypt(sealed)
    monkeypatch.setattr(settings, "TOKEN_ENCRYPTION_KEY", "")
    monkeypatch.setattr(secretbox, "_hosted", lambda: True)
    with pytest.raises(secretbox.SecretBoxError, match="TOKEN_ENCRYPTION_KEY"):
        secretbox.encrypt(TOKEN)


@pytest.fixture
def gh(monkeypatch):
    """Route every GitHubClient the app creates to one fake."""
    from cryptography.fernet import Fernet

    monkeypatch.setattr(settings, "TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    fake = FakeGitHub()
    real_init = GitHubClient.__init__
    monkeypatch.setattr(github.GitHubClient, "__init__",
                        lambda self, token, transport=None: real_init(self, token, transport=httpx.MockTransport(fake)))
    return fake


def test_connect_list_and_disconnect_never_return_the_token(gh):
    client = TestClient(app)
    assert client.get("/api/integrations").json() == [{"provider": "github", "connected": False}]
    resp = client.put("/api/integrations/github", json={"token": TOKEN})
    assert resp.status_code == 200 and resp.json()["login"] == "octo"
    assert TOKEN not in resp.text and TOKEN not in client.get("/api/integrations").text
    stored = get_store().find(INTEGRATIONS)[0]
    assert stored["token"] != TOKEN
    assert client.delete("/api/integrations/github").status_code == 204
    assert get_store().find(INTEGRATIONS) == []


def test_a_rejected_token_is_not_stored(gh):
    gh.status = 401
    resp = TestClient(app).put("/api/integrations/github", json={"token": TOKEN})
    assert resp.status_code == 422 and "rejected the token" in resp.json()["detail"]
    assert get_store().find(INTEGRATIONS) == []


def _patch_row(repo="https://github.com/acme/shop"):
    return get_store().insert(
        FIX_PATCHES, owner_uid="local-dev", target_url="https://shop.example/", repo=repo, commit=BASE,
        frameworks=["fastapi"], files=[{"path": "app/main.py", "diff": "...", "verified": True, "check_note": None}],
        contents={"app/main.py": "fixed\n"},
        applied=[{"check_id": "SEC-HDR-FRAME", "file": "app/main.py", "how": "HTTP middleware sets X-Frame-Options"}],
        manual=[{"check_id": "SEC-TRANSPORT-HTTP", "reason": "Serve over HTTPS."}], patch="...", finding_keys=[])


def test_pull_request_from_a_patch(gh):
    client = TestClient(app)
    row = _patch_row()
    assert "Connect GitHub" in client.post(f"/api/security/patches/{row['id']}/pull-request").json()["detail"]
    client.put("/api/integrations/github", json={"token": TOKEN})

    listed = client.get("/api/security/patches").json()[0]
    assert listed["github"] is True and "contents" not in listed
    resp = client.post(f"/api/security/patches/{row['id']}/pull-request")
    assert resp.status_code == 201 and resp.json()["number"] == 7
    pull = next(b for m, p, b in gh.calls if p.endswith("/pulls"))
    assert "SEC-HDR-FRAME" in pull["title"] and "Serve over HTTPS." in pull["body"] and "still parses" in pull["body"]
    # opening it again returns the same pull request
    calls = len(gh.calls)
    assert client.post(f"/api/security/patches/{row['id']}/pull-request").json()["number"] == 7
    assert len(gh.calls) == calls
    assert client.get("/api/security/patches").json()[0]["pull_request"]["url"].endswith("/pull/7")


def test_pull_requests_need_a_supported_git_host(gh):
    client = TestClient(app)
    client.put("/api/integrations/github", json={"token": TOKEN})
    row = _patch_row(repo="https://git.example.com/acme/shop")
    resp = client.post(f"/api/security/patches/{row['id']}/pull-request")
    assert resp.status_code == 422 and "gitlab.com" in resp.json()["detail"]


def test_commit_status_on_a_pushed_run(gh):
    from backend.pipeline.runner import report_commit_status

    client = TestClient(app)
    client.put("/api/integrations/github", json={"token": TOKEN})
    project = {"owner_uid": "local-dev", "repo_url": "https://github.com/acme/shop"}
    run = {"id": 9, "status": "failed", "commit_sha": BASE, "summary": {"passed": 3, "total": 4}}
    assert report_commit_status(get_store(), project, run) is True
    status_call = next(b for m, p, b in gh.calls if f"/statuses/{BASE}" in p)
    assert status_call == {"state": "failure", "description": "Run #9: 3/4 tests passed", "context": "TestSphere"}
    assert report_commit_status(get_store(), project, {**run, "commit_sha": None}) is False
