"""Private repositories: credentials go to the repository's host only, never into the URL, errors or other hosts."""

import base64
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

from ingestion import source
from ingestion.source import GitAuth, SourceError, git_env

AUTH = GitAuth("x-access-token", "ghp_secret_token_123")


def serve(handler_cls):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_the_header_reaches_the_host_and_not_a_host_it_redirects_to():
    seen = {"repo": [], "other": []}

    class Other(BaseHTTPRequestHandler):
        def do_GET(self):
            seen["other"].append(self.headers.get("Authorization"))
            self.send_response(404)
            self.end_headers()

        log_message = lambda *a: None  # noqa: E731

    other = serve(Other)

    class Repo(BaseHTTPRequestHandler):
        def do_GET(self):
            seen["repo"].append(self.headers.get("Authorization"))
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{other.server_address[1]}{self.path}")
            self.end_headers()

        log_message = lambda *a: None  # noqa: E731

    repo = serve(Repo)
    url = f"http://127.0.0.1:{repo.server_address[1]}/acme/private.git"
    subprocess.run(["git", "-c", "http.followRedirects=true", "ls-remote", url], capture_output=True, timeout=20,
                   env=git_env(url, AUTH))
    repo.shutdown()
    other.shutdown()
    expected = "Basic " + base64.b64encode(b"x-access-token:ghp_secret_token_123").decode()
    assert seen["repo"] and set(seen["repo"]) == {expected}
    assert seen["other"] and set(seen["other"]) == {None}  # the redirect target never gets the token


def test_without_credentials_no_header_and_no_prompts():
    env = git_env("https://github.com/a/b", None)
    assert "GIT_CONFIG_COUNT" not in env and env["GIT_TERMINAL_PROMPT"] == "0"
    assert "ghp_" not in repr(AUTH)


def test_clone_keeps_the_token_out_of_the_command_and_explains_failures(tmp_path, monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs["env"]))
        return subprocess.CompletedProcess(cmd, 128, "", "fatal: Authentication failed for 'https://github.com/a/b/' ghp_secret_token_123")

    monkeypatch.setattr(source.subprocess, "run", fake_run)
    with pytest.raises(SourceError) as err:
        source.clone("https://github.com/a/b", tmp_path, auth=AUTH)
    cmd, env = calls[0]
    assert "https://github.com/a/b" in cmd and not any("ghp_" in part for part in cmd)
    assert env["GIT_CONFIG_KEY_0"] == "http.https://github.com/.extraHeader"
    assert "refused the saved credentials" in str(err.value) and "ghp_" not in str(err.value)
    # Says what to do, including the fine-grained token limit for another account's repository
    assert "expired" in str(err.value) and "classic token" in str(err.value)

    with pytest.raises(SourceError, match="has no credentials for github.com. Connect GitHub"):
        source.clone("https://github.com/a/b", tmp_path)


def test_credentials_per_host_and_the_github_token(monkeypatch):
    from backend.api import integrations
    from backend.database.session import get_store
    from backend.main import app

    client = TestClient(app)
    saved = client.put("/api/integrations/git-credentials", json={"host": "gitlab.com", "token": "glpat-abcdefgh"}).json()
    assert saved == {**saved, "host": "gitlab.com", "username": "oauth2"} and "token" not in saved
    assert client.put("/api/integrations/git-credentials",
                      json={"host": "evil.example", "token": "abcdefghij"}).status_code == 422
    assert [c["host"] for c in client.get("/api/integrations/git-credentials").json()] == ["gitlab.com"]

    db = get_store()
    assert integrations.git_auth(db, "local-dev", "https://gitlab.com/a/b") == GitAuth("oauth2", "glpat-abcdefgh")
    assert integrations.git_auth(db, "someone-else", "https://gitlab.com/a/b") is None  # never another user's
    monkeypatch.setattr(integrations, "github_token", lambda db, uid: "ghp_connected")
    assert integrations.git_auth(db, "local-dev", "https://github.com/a/b") == GitAuth("x-access-token", "ghp_connected")

    assert client.delete("/api/integrations/git-credentials/gitlab.com").status_code == 204
    assert integrations.git_auth(db, "local-dev", "https://gitlab.com/a/b") is None


def test_ingest_uses_the_callers_credentials(monkeypatch):
    from backend.api import ingest
    from backend.main import app

    used = []
    monkeypatch.setattr(ingest, "git_auth", lambda db, uid, url: GitAuth("oauth2", f"token-of-{uid}"))
    monkeypatch.setattr(ingest, "clone", lambda url, ws, hosts, auth=None: used.append(auth) or (_ for _ in ()).throw(
        SourceError("stop here")))
    TestClient(app).post("/api/ingest", json={"source": "https://gitlab.com/acme/private"})
    assert used == [GitAuth("oauth2", "token-of-local-dev")]
