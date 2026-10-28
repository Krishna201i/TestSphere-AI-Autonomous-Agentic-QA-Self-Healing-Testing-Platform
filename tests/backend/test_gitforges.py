"""
Fix patches as GitLab merge requests and Bitbucket pull requests, with the
Git credentials saved under Integrations.  Both hosts are httpx mocks.
"""

import json
from urllib.parse import parse_qs

import httpx
import pytest
from fastapi.testclient import TestClient

from backend import gitforges
from backend.config import settings
from backend.database.session import get_store
from backend.gitforges import BitbucketClient, GitLabClient, parse_forge_repo
from backend.main import app
from backend.models import FIX_PATCHES

BASE = "b" * 40


def test_parse_forge_repo():
    assert parse_forge_repo("https://gitlab.com/acme/web/shop.git") == ("gitlab", "acme/web/shop")
    assert parse_forge_repo("https://bitbucket.org/acme/shop") == ("bitbucket", "acme/shop")
    assert parse_forge_repo("https://github.com/acme/shop") is None
    assert parse_forge_repo("https://gitlab.com.evil.example/acme/shop") is None


class FakeGitLab:
    def __init__(self, existing_branches=0):
        self.calls, self.existing = [], existing_branches

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path, body = request.url.raw_path.decode(), json.loads(request.content or b"{}")
        self.calls.append((request.method, path, body, request.headers.get("PRIVATE-TOKEN")))
        if path == "/api/v4/projects/acme%2Fweb%2Fshop":
            return httpx.Response(200, json={"default_branch": "main"})
        if path.endswith("/repository/branches"):
            if self.existing:
                self.existing -= 1
                return httpx.Response(400, json={"message": "Branch already exists"})
            return httpx.Response(201, json={"name": body["branch"]})
        if path.endswith("/repository/commits"):
            return httpx.Response(201, json={"id": "c" * 40})
        if path.endswith("/merge_requests"):
            return httpx.Response(201, json={"iid": 12, "web_url": "https://gitlab.com/acme/web/shop/-/merge_requests/12"})
        return httpx.Response(404, json={"message": "404 Not Found"})


class FakeBitbucket:
    def __init__(self):
        self.calls = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append((request.method, path, request.content.decode(), request.headers.get("Authorization")))
        if path == "/2.0/repositories/acme/shop":
            return httpx.Response(200, json={"mainbranch": {"name": "master"}})
        if path.endswith("/refs/branches"):
            return httpx.Response(200, json={"values": []})
        if path.endswith("/src"):
            return httpx.Response(201)
        if path.endswith("/pullrequests"):
            return httpx.Response(201, json={"id": 4, "links": {"html": {"href": "https://bitbucket.org/acme/shop/pull-requests/4"}}})
        return httpx.Response(404, json={"error": {"message": "not found"}})


def test_gitlab_merge_request_is_one_commit_on_a_new_branch_from_the_patch_base():
    fake = FakeGitLab(existing_branches=1)
    with GitLabClient("glpat-secret", transport=httpx.MockTransport(fake)) as gl:
        mr = gl.open_fix_pr("acme/web/shop", BASE, [("app.py", "fixed\n")], "testsphere/fix-1", "Fix", "Body")
    assert mr == {"url": "https://gitlab.com/acme/web/shop/-/merge_requests/12", "number": 12,
                  "branch": "testsphere/fix-1-2", "base": "main"}
    branch = [b for m, p, b, _ in fake.calls if p.endswith("/repository/branches")][-1]
    assert branch == {"branch": "testsphere/fix-1-2", "ref": BASE}
    commit = next(b for m, p, b, _ in fake.calls if p.endswith("/repository/commits"))
    assert commit["actions"] == [{"action": "update", "file_path": "app.py", "content": "fixed\n"}]
    assert all(token == "glpat-secret" for *_, token in fake.calls)


def test_bitbucket_pull_request_commits_on_top_of_the_patch_base():
    fake = FakeBitbucket()
    with BitbucketClient("x-token-auth", "bb-token", transport=httpx.MockTransport(fake)) as bb:
        pr = bb.open_fix_pr("acme/shop", BASE, [("message", "a file named like a field\n")],
                            "testsphere/fix-2", "Fix", "Body")
    assert pr["number"] == 4 and pr["base"] == "master"
    form = parse_qs(next(b for m, p, b, _ in fake.calls if p.endswith("/src")))
    assert form["parents"] == [BASE] and form["branch"] == ["testsphere/fix-2"] and form["message"] == ["Fix"]
    assert form["/message"] == ["a file named like a field\n"]  # never mistaken for the commit message
    assert all(auth == "Bearer bb-token" for *_, auth in fake.calls)


def test_bitbucket_app_password_uses_basic_auth():
    fake = FakeBitbucket()
    with BitbucketClient("alice", "app-pass", transport=httpx.MockTransport(fake)) as bb:
        bb.open_fix_pr("acme/shop", BASE, [("a.py", "x")], "b", "t", "d")
    assert all(auth.startswith("Basic ") for *_, auth in fake.calls)


@pytest.fixture
def forges(monkeypatch):
    from cryptography.fernet import Fernet

    monkeypatch.setattr(settings, "TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    gl, bb = FakeGitLab(), FakeBitbucket()
    gl_init, bb_init = GitLabClient.__init__, BitbucketClient.__init__
    monkeypatch.setattr(gitforges.GitLabClient, "__init__",
                        lambda self, token, transport=None: gl_init(self, token, transport=httpx.MockTransport(gl)))
    monkeypatch.setattr(gitforges.BitbucketClient, "__init__",
                        lambda self, user, token, transport=None: bb_init(self, user, token,
                                                                          transport=httpx.MockTransport(bb)))
    return gl, bb


def _patch_row(repo):
    return get_store().insert(
        FIX_PATCHES, owner_uid="local-dev", target_url="https://shop.example/", repo=repo, commit=BASE,
        frameworks=["nextjs"], files=[{"path": "next.config.mjs", "diff": "...", "verified": True, "check_note": None}],
        contents={"next.config.mjs": "fixed\n"},
        applied=[{"check_id": "SEC-HDR-FRAME", "file": "next.config.mjs", "how": "next.config headers()"}],
        manual=[], patch="...", finding_keys=[])


@pytest.mark.parametrize(("repo", "host", "token", "number"), [
    ("https://gitlab.com/acme/web/shop", "gitlab.com", "glpat-secret-123", 12),
    ("https://bitbucket.org/acme/shop", "bitbucket.org", "bb-token-12345", 4),
])
def test_merge_and_pull_requests_use_the_saved_git_credential(forges, repo, host, token, number):
    client = TestClient(app)
    row = _patch_row(repo)
    assert client.get("/api/security/patches").json()[0]["forge"] == host.split(".")[0]
    missing = client.post(f"/api/security/patches/{row['id']}/pull-request")
    assert missing.status_code == 422 and f"Save a {host} credential" in missing.json()["detail"]

    assert client.put("/api/integrations/git-credentials", json={"host": host, "token": token}).status_code == 200
    resp = client.post(f"/api/security/patches/{row['id']}/pull-request")
    assert resp.status_code == 201 and resp.json()["number"] == number
    assert token not in resp.text
