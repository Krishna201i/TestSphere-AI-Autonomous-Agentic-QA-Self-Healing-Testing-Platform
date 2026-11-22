"""Active scans need proof that the account owns the host (a published token)."""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

from backend.api.security import active_scan_refusal
from backend.config import settings
from backend.main import app
from backend.models import PROJECTS
from backend.services import domain_verify
from backend.services.project_service import ProjectService


@pytest.fixture
def site():
    served = {"body": "", "code": 200, "location": None}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if self.path != domain_verify.WELL_KNOWN_PATH:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(served["code"])
            if served["location"]:
                self.send_header("Location", served["location"])
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(served["body"].encode())

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/", served
    server.shutdown()


def test_a_published_token_verifies_the_host(fresh_store, site):
    url, served = site
    project = ProjectService.create_project(fresh_store, name="Shop", owner_uid="local-dev", app_url=url)
    client = TestClient(app)

    info = client.get(f"/api/projects/{project['id']}/domain-verification").json()
    assert info["token"].startswith("testsphere-verify=") and info["file_url"].endswith(domain_verify.WELL_KNOWN_PATH)
    assert info["verified_at"] is None

    served["body"] = "something else"
    wrong = client.post(f"/api/projects/{project['id']}/domain-verification")
    assert wrong.status_code == 422 and "does not contain" in wrong.json()["detail"]

    served["body"] = f"# TestSphere\n{info['token']}\n"
    ok = client.post(f"/api/projects/{project['id']}/domain-verification")
    assert ok.status_code == 200, ok.text
    assert ok.json()["verified_host"] == "127.0.0.1" and ok.json()["verified_at"]


def test_a_redirect_does_not_count(fresh_store, site):
    url, served = site
    project = ProjectService.create_project(fresh_store, name="Shop", owner_uid="local-dev", app_url=url)
    served.update(code=302, location="https://someone-elses.example/token.txt")
    resp = TestClient(app).post(f"/api/projects/{project['id']}/domain-verification")
    assert resp.status_code == 422 and "302" in resp.json()["detail"]


@pytest.fixture
def hosted_rules(monkeypatch):
    monkeypatch.setattr(settings, "SECURITY_ACTIVE_SCAN", True)
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    monkeypatch.setattr(settings, "SECURITY_ACTIVE_SCAN_USERS", "alice,bob")
    monkeypatch.setattr(settings, "REQUIRE_DOMAIN_VERIFICATION", "on")


def _verified(db, owner, host, days_ago=0):
    project = ProjectService.create_project(db, name=host, owner_uid=owner, app_url=f"https://{host}/")
    stamp = (datetime.now(UTC) - timedelta(days=days_ago)).isoformat()
    db.update(PROJECTS, project["id"], verified_host=host, verified_at=stamp)


def test_an_allowlisted_account_still_needs_a_verified_host(fresh_store, hosted_rules):
    url = "https://shop.example/search?q=x"
    assert "not verified" in active_scan_refusal("alice", url, fresh_store)

    _verified(fresh_store, "alice", "shop.example")
    assert active_scan_refusal("alice", url, fresh_store) is None
    assert "not verified" in active_scan_refusal("bob", url, fresh_store)  # another account's proof is not bob's
    assert "not verified" in active_scan_refusal("alice", "https://other.example/", fresh_store)


def test_a_verification_expires(fresh_store, hosted_rules):
    _verified(fresh_store, "alice", "shop.example", days_ago=domain_verify.VALID_DAYS + 1)
    assert "not verified" in active_scan_refusal("alice", "https://shop.example/", fresh_store)


def test_local_development_and_loopback_are_exempt(fresh_store, hosted_rules, monkeypatch):
    assert active_scan_refusal("alice", "http://127.0.0.1:8000/", fresh_store) is None
    monkeypatch.setattr(settings, "REQUIRE_DOMAIN_VERIFICATION", "off")
    assert active_scan_refusal("alice", "https://shop.example/", fresh_store) is None
