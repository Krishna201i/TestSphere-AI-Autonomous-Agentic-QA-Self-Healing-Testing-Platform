"""
Sites for active testing, managed from the dashboard.

Active scans send attack payloads, so they used to need a host in the server's
SECURITY_SCAN_ALLOWED_HOSTS.  Now an account adds a site, publishes the token
TestSphere gives it at /.well-known/testsphere-verify.txt, and once that is
verified the site joins that account's active-scan scope (for 30 days).
Typing a site's name is never enough on a server that requires proof.
"""

from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

from backend.api.security import widen_active_scope
from backend.config import settings
from backend.main import app
from backend.models import SCAN_TARGETS
from backend.services import domain_verify
from security import ActiveScanner, ScopePolicy

PUBLISHED: dict[str, str] = {}


@pytest.fixture(scope="module")
def site():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            body = PUBLISHED.get(self.path)
            self.send_response(200 if body else 404)
            self.end_headers()
            self.wfile.write((body or "").encode())

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture
def client():
    return TestClient(app)


def test_add_list_and_remove_a_site(client):
    added = client.post("/api/security/targets", json={"url": "https://shop.example/path?q=1"})
    assert added.status_code == 201
    site = added.json()
    # Stored as its origin, with a token and the exact file to publish
    assert site["url"] == "https://shop.example" and site["host"] == "shop.example"
    assert site["token"].startswith("testsphere-verify=")
    assert site["file_url"] == "https://shop.example/.well-known/testsphere-verify.txt"

    # The same host twice is the same site
    assert client.post("/api/security/targets", json={"url": "https://shop.example/"}).json()["id"] == site["id"]

    listed = client.get("/api/security/targets").json()
    assert [t["host"] for t in listed["targets"]] == ["shop.example"]
    assert set(listed["active_scan"]) == {"server", "allowed", "reason", "uid", "proof_required"}

    assert client.delete(f"/api/security/targets/{site['id']}").status_code == 204
    assert client.get("/api/security/targets").json()["targets"] == []


def test_a_bad_address_is_refused(client):
    response = client.post("/api/security/targets", json={"url": "shop.example"})
    assert response.status_code == 422 and "http://" in response.json()["detail"]


def test_ownership_is_proven_by_the_published_token(client, site, fresh_store):
    target = client.post("/api/security/targets", json={"url": site}).json()

    # Not published yet: refused, nothing recorded
    refused = client.post(f"/api/security/targets/{target['id']}/verify")
    assert refused.status_code == 422 and "404" in refused.json()["detail"]
    assert fresh_store.get(SCAN_TARGETS, target["id"])["verified_at"] is None

    # Published: verified
    PUBLISHED[domain_verify.WELL_KNOWN_PATH] = f"some other line\n{target['token']}\n"
    verified = client.post(f"/api/security/targets/{target['id']}/verify")
    assert verified.status_code == 200 and "verified for 30 days" in verified.json()["message"]
    assert fresh_store.get(SCAN_TARGETS, target["id"])["verified_at"]


def test_only_fresh_verified_sites_join_the_active_scope_when_proof_is_required(fresh_store, monkeypatch):
    monkeypatch.setattr(settings, "REQUIRE_DOMAIN_VERIFICATION", "on")
    old = (datetime.now(UTC) - timedelta(days=31)).isoformat()
    for host, verified_at in [("fresh.example", datetime.now(UTC).isoformat()), ("old.example", old),
                              ("pending.example", None)]:
        fresh_store.insert(SCAN_TARGETS, owner_uid="u1", host=host, url=f"https://{host}", token="t",
                           verified_at=verified_at)
    fresh_store.insert(SCAN_TARGETS, owner_uid="someone-else", host="theirs.example", url="https://theirs.example",
                       token="t", verified_at=datetime.now(UTC).isoformat())

    assert domain_verify.active_hosts(fresh_store, "u1") == {"fresh.example"}
    assert domain_verify.refusal(fresh_store, "u1", "https://fresh.example/x") is None
    assert "not verified" in domain_verify.refusal(fresh_store, "u1", "https://old.example/")
    # Another account's verified site is not yours
    assert domain_verify.refusal(fresh_store, "u1", "https://theirs.example/")

    states = {t["host"]: domain_verify.target_view(t)["state"] for t in fresh_store.find(SCAN_TARGETS, owner_uid="u1")}
    assert states == {"fresh.example": "verified", "old.example": "expired", "pending.example": "pending"}


def test_without_required_proof_an_added_site_is_in_scope(fresh_store, monkeypatch):
    # Local development (no sign-in): adding the site is the opt-in
    monkeypatch.setattr(settings, "REQUIRE_DOMAIN_VERIFICATION", "off")
    row = domain_verify.add_target(fresh_store, "local-dev", "http://staging.internal:8080/")
    assert domain_verify.active_hosts(fresh_store, "local-dev") == {"staging.internal"}
    assert domain_verify.target_view(row)["state"] == "no_proof_needed"


def test_the_active_scanner_attacks_verified_sites_and_nothing_else():
    scanner = widen_active_scope(ActiveScanner(ScopePolicy.of("listed.example")), {"verified.example"})
    assert scanner.scope.allows("https://verified.example/search")
    assert scanner.scope.allows("https://listed.example/")
    assert not scanner.scope.allows("https://unverified.example/")
    assert not scanner.scope.any_public  # the any-site mode is for passive visits only


def test_the_number_of_sites_is_limited(client, monkeypatch):
    import backend.api.security as sec_api

    monkeypatch.setattr(sec_api, "MAX_SCAN_TARGETS", 2)
    for n in range(2):
        assert client.post("/api/security/targets", json={"url": f"https://s{n}.example"}).status_code == 201
    assert client.post("/api/security/targets", json={"url": "https://s9.example"}).status_code == 422


def test_a_passive_scan_reaches_any_public_site_but_never_probes_its_secret_files():
    import httpx

    from backend.api.security import get_scanner

    requested: list[str] = []
    transport = httpx.MockTransport(lambda r: (requested.append(r.url.path), httpx.Response(200, text="<p>hi</p>"))[1])
    scanner = get_scanner()
    scanner._transport = transport
    asyncio.run(scanner.fetch("https://unlisted.example/", probe_files=True))
    assert requested == ["/"]  # no /.git/HEAD, no /.env


def test_the_first_one_click_run_already_uses_the_chosen_settings(client, fresh_store, monkeypatch):
    """Settings chosen in the run form before the first run land on the project it creates."""
    import backend.api.pipelines as pipes
    from backend.models import PROJECTS

    started = []
    monkeypatch.setattr(pipes, "start_run", lambda db, project, **kw: started.append(project) or {"id": 1})
    body = {"url": "https://shop.example/", "prompt": "log in",
            "generation_profile": {"test_types": ["smoke", "negative"], "test_data": {"email": "qa@shop.example"},
                                   "max_ai_tests": 0, "strict": True, "acceptance": True},
            "sign_in_first": True, "active_scan": True}
    assert client.post("/api/pipelines/quick", json=body).status_code == 202
    project = fresh_store.find_one(PROJECTS, app_url="https://shop.example/")
    assert project["sign_in_first"] is True and project["active_scan"] is True
    assert project["generation_profile"]["test_types"] == ["smoke", "negative"]
    assert project["generation_profile"]["strict"] is True and project["generation_profile"]["max_ai_tests"] == 0

    # A later run without settings leaves them as they are; one with a change updates it
    assert client.post("/api/pipelines/quick", json={"url": "https://shop.example/"}).status_code == 202
    assert fresh_store.get(PROJECTS, project["id"])["sign_in_first"] is True
    client.post("/api/pipelines/quick", json={"url": "https://shop.example/", "sign_in_first": False})
    assert not fresh_store.get(PROJECTS, project["id"])["sign_in_first"]  # cleared (stored as None)

    # A bad profile is refused before anything is stored
    bad = client.post("/api/pipelines/quick", json={"url": "https://x.example/", "generation_profile": {"max_ai_tests": 99}})
    assert bad.status_code == 422 and fresh_store.find_one(PROJECTS, app_url="https://x.example/") is None
