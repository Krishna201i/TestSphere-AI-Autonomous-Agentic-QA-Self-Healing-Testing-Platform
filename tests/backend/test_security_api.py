"""
Tests for the /security API router (scanner network stubbed).
"""

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.api.security import get_scanner
from backend.config import settings
from backend.main import app
from security import PassiveScanner, ScopePolicy

HARDENED = {
    "content-type": "text/html",
    "content-security-policy": "default-src 'self'; frame-ancestors 'none'",
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
}


@pytest.fixture
def state():
    return {"headers": {"content-type": "text/html"}}


@pytest.fixture
def client(state):
    transport = httpx.MockTransport(lambda r: httpx.Response(200, headers=state["headers"], text=""))
    app.dependency_overrides[get_scanner] = lambda: PassiveScanner(ScopePolicy.of("app.test"), transport=transport)
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_scan_returns_sorted_findings_and_summary(client) -> None:
    resp = client.post("/api/security/scan", json={"url": "http://app.test/"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["summary"] == {"medium": 2, "low": 2, "high": 1}
    assert body["findings"][0]["check_id"] == "SEC-TRANSPORT-HTTP"
    assert all(len(f["key"]) == 16 for f in body["findings"])


def test_out_of_scope_is_403(client) -> None:
    resp = client.post("/api/security/scan", json={"url": "https://elsewhere.test/"})
    assert resp.status_code == 403
    assert "authorized scope" in resp.json()["detail"]


def test_unreachable_target_is_502() -> None:
    def boom(request):
        raise httpx.ConnectError("refused", request=request)
    app.dependency_overrides[get_scanner] = lambda: PassiveScanner(
        ScopePolicy.of("app.test"), transport=httpx.MockTransport(boom))
    try:
        resp = TestClient(app).post("/security/scan", json={"url": "https://app.test/"})
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 502


def test_retest_round_trip(client, state) -> None:
    finding = next(
        f for f in client.post("/api/security/scan", json={"url": "http://app.test/"}).json()["findings"]
        if f["check_id"] == "SEC-HDR-CSP"
    )
    assert client.post("/api/security/retest", json=finding).json()["retest_result"] == "fail"

    state["headers"] = HARDENED
    fixed = client.post("/api/security/retest", json=finding).json()
    assert (fixed["retest_result"], fixed["status"]) == ("pass", "resolved")
    assert fixed["key"] == finding["key"]


def test_default_scanner_scope_is_config_driven(monkeypatch) -> None:
    monkeypatch.setattr(settings, "SECURITY_SCAN_ALLOWED_HOSTS", "staging.test, ")
    scope = get_scanner().scope
    assert scope.allows("https://staging.test/")
    assert scope.allows("http://127.0.0.1:8000/")
    assert not scope.allows("https://example.com/")


def test_scan_includes_headers_and_remediation(client, state) -> None:
    state["headers"] = {"content-type": "text/html", "Server": "nginx/1.25.3", "set-cookie": "sid=TOKEN"}
    body = client.post("/api/security/scan", json={"url": "https://app.test/"}).json()

    assert ["Server", "nginx/1.25.3"] in body["response_headers"]
    assert ["set-cookie", "…redacted…"] in body["response_headers"]
    assert "TOKEN" not in str(body)

    by_id = {f["check_id"]: f for f in body["findings"]}
    csp = by_id["SEC-HDR-CSP"]["remediation"]
    assert csp["kind"] == "header"
    assert {"kind": "added", "text": "Content-Security-Policy: default-src 'self'; frame-ancestors 'none'"} in csp["diff"]
    assert "add_header Content-Security-Policy" in csp["snippets"]["nginx"]

    leak = by_id["SEC-DISCLOSURE"]["remediation"]
    assert {"kind": "removed", "text": "Server: nginx/1.25.3"} in leak["diff"]
    assert "server_tokens off;" in leak["snippets"]["nginx"]
