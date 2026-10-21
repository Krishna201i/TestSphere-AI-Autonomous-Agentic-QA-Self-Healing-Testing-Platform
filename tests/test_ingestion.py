"""
Tests for ingestion/ (analyzer + source handling) and the /api/ingest router.
No network: cloning is exercised with a stubbed ``subprocess.run``.
"""

import json
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from backend.config import settings
from backend.main import app
from ingestion import SourceError, analyze_repo, clone, repo_name, validate_git_url

AWS_KEY = "AKIA" + "ABCDEFGHIJKLMNOP"  # split so this file isn't itself flagged


def _write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "shop"
    _write(root, "package.json", json.dumps({
        "main": "server.js",
        "scripts": {"start": "node server.js"},
        "dependencies": {"express": "^4.19.0", "react": "^18.3.1"},
        "devDependencies": {"jest": "^29.0.0"},
    }))
    _write(root, "server.js", "const app = require('express')();\napp.get('/api/products', h);\napp.post(\"/api/login\", h);\n// app.get('/commented-out', h);\n")
    _write(root, "requirements.txt", "fastapi>=0.100\nsqlalchemy==2.0\n# comment\n")
    _write(root, "api/main.py", 'from fastapi import APIRouter\nrouter = APIRouter(prefix="/orders")\n\n@router.get("/{id}")\ndef get(id): ...\n\nDEBUG = True\n')
    _write(root, "api/settings.py", f'AWS_ACCESS_KEY_ID = "{AWS_KEY}"\npassword = "hunter2-real-pass"\napi_key = "your-api-key-here"\n')
    _write(root, "tests/test_orders.py", 'API_KEY = "sk-fake-1234567890"\ndef test_x(): pass\n')
    _write(root, "web/cart.test.js", "test('x', () => {})\n")
    _write(root, ".env", "SECRET=abc\n")
    _write(root, ".env.example", "SECRET=\n")
    _write(root, "node_modules/lib/index.js", "app.get('/ignored', h)\n")
    return root


# ── Analyzer ──────────────────────────────────────────────────


def test_languages_frameworks_dependencies(repo: Path) -> None:
    bp = analyze_repo(repo)
    assert bp.name == "shop"
    assert {"JavaScript", "Python"} <= set(bp.languages)
    assert {"Express", "React", "FastAPI", "SQLAlchemy", "Jest"} <= set(bp.frameworks)
    assert "express" in bp.dependencies["npm"] and "fastapi" in bp.dependencies["pip"]


def test_skips_vendor_directories(repo: Path) -> None:
    bp = analyze_repo(repo)
    assert all("node_modules" not in r.file for r in bp.routes)
    assert bp.files_total == 9  # everything except node_modules/lib/index.js


def test_routes_with_prefix_and_without_comments(repo: Path) -> None:
    routes = {(r.method, r.path) for r in analyze_repo(repo).routes}
    assert {("GET", "/api/products"), ("POST", "/api/login"), ("GET", "/orders/{id}")} <= routes
    assert ("GET", "/commented-out") not in routes


def test_test_suites_and_entry_points(repo: Path) -> None:
    bp = analyze_repo(repo)
    suites = {s.framework: s.files for s in bp.test_suites}
    assert suites == {"Jest/Vitest": 1, "pytest": 1}
    assert "server.js" in bp.entry_points and "api/main.py" in bp.entry_points
    assert "npm run start: node server.js" in bp.entry_points


def test_risks_are_found_redacted_and_filtered(repo: Path) -> None:
    risks = analyze_repo(repo).risks
    kinds = {(r.kind, r.file) for r in risks}
    assert ("AWS access key", "api/settings.py") in kinds
    assert ("Hardcoded credential", "api/settings.py") in kinds   # real-looking password
    assert ("Committed .env file", ".env") in kinds
    assert ("Debug mode enabled", "api/main.py") in kinds
    assert not any(r.file == ".env.example" for r in risks)
    assert not any(r.file.startswith("tests/") for r in risks)    # fake fixture keys ignored
    assert sum(1 for r in risks if r.kind == "Hardcoded credential") == 1  # placeholder skipped
    assert all(AWS_KEY not in r.detail and "hunter2-real-pass" not in r.detail for r in risks)


def test_not_a_directory(tmp_path: Path) -> None:
    with pytest.raises(NotADirectoryError):
        analyze_repo(tmp_path / "missing")


# ── Source validation & clone ─────────────────────────────────


@pytest.mark.parametrize("url", [
    "http://github.com/a/b",            # not https
    "file:///etc",                      # local file protocol
    "ssh://git@github.com/a/b",
    "git@github.com:a/b.git",
    "https://internal.corp/a/b",        # host not allowed
    "https://user:pw@github.com/a/b",   # credentials
    "https://github.com/a",             # not owner/repo
    "https://github.com/a/b/../../x",
])
def test_rejects_unsafe_git_urls(url: str) -> None:
    with pytest.raises(SourceError):
        validate_git_url(url)


def test_accepts_public_repo_url() -> None:
    assert validate_git_url("https://github.com/owner/repo.git") == "https://github.com/owner/repo.git"
    assert repo_name("https://github.com/owner/repo.git") == "repo"


def test_clone_runs_shallow_hardened_git(monkeypatch, tmp_path: Path) -> None:
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        Path(cmd[-1]).mkdir(parents=True)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    target = clone("https://github.com/owner/repo", tmp_path)
    cmd, kwargs = calls[0]
    assert target.parent == tmp_path and target.name.startswith("repo-")
    assert ["--depth", "1"] == cmd[cmd.index("--depth"):cmd.index("--depth") + 2]
    assert "protocol.allow=never" in cmd and "core.hooksPath=/dev/null" in cmd
    assert kwargs["env"]["GIT_TERMINAL_PROMPT"] == "0" and kwargs["timeout"] > 0


def test_clone_failure_and_timeout(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 128, "", "fatal: repository not found"))
    with pytest.raises(SourceError, match="repository not found"):
        clone("https://github.com/owner/missing", tmp_path)

    def slow(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 1)
    monkeypatch.setattr(subprocess, "run", slow)
    with pytest.raises(SourceError, match="timed out"):
        clone("https://github.com/owner/slow", tmp_path)


# ── API ───────────────────────────────────────────────────────


@pytest.fixture
def client():
    """Storage is the per-test in-memory store (conftest)."""
    return TestClient(app)


def test_ingest_local_path_stores_and_audits(client, repo: Path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "INGEST_ALLOW_LOCAL_PATHS", True)
    resp = client.post("/api/ingest", json={"source": str(repo)})
    assert resp.status_code == 201, resp.text
    bp = resp.json()
    assert bp["name"] == "shop" and bp["id"] >= 1

    listed = client.get("/api/ingest").json()
    assert listed[0]["primary_language"] in ("JavaScript", "Python")
    assert listed[0]["routes"] >= 3 and listed[0]["risks"] >= 4
    assert client.get(f"/api/ingest/{bp['id']}").json()["frameworks"] == bp["frameworks"]

    event = client.get("/api/audit").json()[0]
    assert event["kind"] == "ingest" and "Ingested shop" in event["message"]


def test_local_paths_can_be_disabled(client, repo: Path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "INGEST_ALLOW_LOCAL_PATHS", False)
    resp = client.post("/api/ingest", json={"source": str(repo)})
    assert resp.status_code == 400 and "disabled" in resp.json()["detail"]


def test_unsafe_url_is_400_and_audited(client) -> None:
    resp = client.post("/api/ingest", json={"source": "file:///etc"})
    assert resp.status_code == 400
    assert client.get("/api/audit").json()[0]["level"] == "error"


def test_unknown_blueprint_is_404(client) -> None:
    assert client.get("/api/ingest/999").status_code == 404


def test_system_info_reports_config_without_secrets(client, monkeypatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "sk-super-secret")
    info = client.get("/api/system").json()
    assert info["api_version"] >= 2
    assert "127.0.0.1" in info["scan_scope"]
    assert "sk-super-secret" not in json.dumps(info)


def test_reingest_replaces_read_only_checkout(monkeypatch, tmp_path: Path) -> None:
    """Git object files are read-only; a re-clone must still replace the old checkout."""
    import os
    import stat as stat_mod

    def fake_run(cmd, **kwargs):
        target = Path(cmd[-1])
        assert not target.exists(), "old checkout should have been removed"
        (target / ".git" / "objects").mkdir(parents=True)
        obj = target / ".git" / "objects" / "pack"
        obj.write_text("x")
        os.chmod(obj, stat_mod.S_IREAD)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    first = clone("https://github.com/owner/repo", tmp_path)
    second = clone("https://github.com/owner/repo", tmp_path)
    assert first == second and second.exists()


def test_git_checkout_respects_gitignore(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    _write(root, "app.py", '@app.get("/real")\ndef r(): ...\n')
    _write(root, ".gitignore", "generated/\n")
    _write(root, "generated/junk.py", '@app.get("/ignored")\ndef j(): ...\n')
    _write(root, "tests/test_app.py", '@app.get("/fixture")\ndef f(): ...\n')
    subprocess.run(["git", "init", "-q", str(root)], check=True)

    bp = analyze_repo(root)
    files = {r.file for r in bp.routes}
    assert files == {"app.py"}  # ignored dir and test fixtures excluded
    assert bp.files_total == 3  # app.py, .gitignore, tests/test_app.py


@pytest.mark.parametrize(("env", "expected"), [
    ({}, True),                                            # local development
    ({"APP_ENV": "production"}, False),
    ({"RENDER": "true"}, False),                           # public host, APP_ENV unset
    ({"RENDER": "true", "INGEST_ALLOW_LOCAL_PATHS": "true"}, True),  # explicit opt-in
    ({"INGEST_ALLOW_LOCAL_PATHS": "false"}, False),
])
def test_local_path_default_is_safe_on_cloud_hosts(monkeypatch, env, expected) -> None:
    from backend.config import _CLOUD_MARKERS, _default_allow_local_paths
    for var in ("APP_ENV", "INGEST_ALLOW_LOCAL_PATHS", *_CLOUD_MARKERS):
        monkeypatch.delenv(var, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    assert _default_allow_local_paths() is expected
