"""
Tests for the /security and /audit API routers (scanner network stubbed,
isolated in-memory store).
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
    """Scanner network stubbed; storage is the per-test in-memory store (conftest)."""
    transport = httpx.MockTransport(lambda r: httpx.Response(200, headers=state["headers"], text=""))
    app.dependency_overrides[get_scanner] = lambda: PassiveScanner(ScopePolicy.of("app.test"), transport=transport)
    yield TestClient(app)
    app.dependency_overrides.clear()


def _scan(client, url="http://app.test/"):
    resp = client.post("/api/security/scan", json={"url": url})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _by_id(findings):
    return {f["check_id"]: f for f in findings}


# ── Scan ──────────────────────────────────────────────────────


def test_scan_returns_sorted_findings_and_summary(client) -> None:
    body = _scan(client)
    assert body["summary"] == {"medium": 2, "low": 2, "high": 1}
    assert body["findings"][0]["check_id"] == "SEC-TRANSPORT-HTTP"
    assert all(len(f["key"]) == 16 and f["status"] == "open" for f in body["findings"])


def test_out_of_scope_is_403_and_audited(client) -> None:
    resp = client.post("/api/security/scan", json={"url": "https://elsewhere.test/"})
    assert resp.status_code == 403
    assert "authorized scope" in resp.json()["detail"]
    assert client.get("/api/audit").json()[0]["level"] == "error"


def test_unreachable_target_is_502(client) -> None:
    def boom(request):
        raise httpx.ConnectError("refused", request=request)
    app.dependency_overrides[get_scanner] = lambda: PassiveScanner(
        ScopePolicy.of("app.test"), transport=httpx.MockTransport(boom))
    assert client.post("/security/scan", json={"url": "https://app.test/"}).status_code == 502


def test_scan_includes_headers_and_remediation(client, state) -> None:
    state["headers"] = {"content-type": "text/html", "Server": "nginx/1.25.3", "set-cookie": "sid=TOKEN"}
    body = _scan(client, "https://app.test/")

    assert ["Server", "nginx/1.25.3"] in body["response_headers"]
    assert ["set-cookie", "…redacted…"] in body["response_headers"]
    assert "TOKEN" not in str(body)

    findings = _by_id(body["findings"])
    csp = findings["SEC-HDR-CSP"]["remediation"]
    assert csp["kind"] == "header"
    assert {"kind": "added", "text": "Content-Security-Policy: default-src 'self'; frame-ancestors 'none'"} in csp["diff"]
    assert "add_header Content-Security-Policy" in csp["snippets"]["nginx"]
    leak = findings["SEC-DISCLOSURE"]["remediation"]
    assert {"kind": "removed", "text": "Server: nginx/1.25.3"} in leak["diff"]


# ── Persistence lifecycle ─────────────────────────────────────


def test_findings_persist_and_rescan_does_not_duplicate(client) -> None:
    _scan(client)
    _scan(client)
    stored = client.get("/api/security/findings").json()
    assert len(stored) == 5
    assert len({f["key"] for f in stored}) == 5


def test_approve_then_retest_is_stored(client, state) -> None:
    csp = _by_id(_scan(client)["findings"])["SEC-HDR-CSP"]

    approved = client.post(f"/api/security/findings/{csp['key']}/approve", json={"actor": "krishna"}).json()
    assert approved["approved_by"] == "krishna" and approved["approved_at"]

    failed = client.post(f"/api/security/findings/{csp['key']}/retest", json={}).json()
    assert (failed["retest_result"], failed["status"]) == ("fail", "open")

    state["headers"] = HARDENED
    fixed = client.post(f"/api/security/findings/{csp['key']}/retest", json={}).json()
    assert (fixed["retest_result"], fixed["status"]) == ("pass", "resolved")

    stored = _by_id(client.get("/api/security/findings").json())["SEC-HDR-CSP"]
    assert stored["status"] == "resolved" and stored["approved_by"] == "krishna"


def test_rescan_resolves_findings_that_disappeared(client, state) -> None:
    _scan(client)
    state["headers"] = HARDENED
    body = _scan(client)
    resolved_ids = {f["check_id"] for f in body["resolved"]}
    assert {"SEC-HDR-CSP", "SEC-HDR-FRAME", "SEC-HDR-XCTO", "SEC-HDR-REFERRER"} <= resolved_ids
    assert all(f["retest_result"] == "pass" for f in body["resolved"])


def test_reappearing_finding_is_reopened_as_regression(client, state) -> None:
    key = _by_id(_scan(client)["findings"])["SEC-HDR-CSP"]["key"]
    client.post(f"/api/security/findings/{key}/approve", json={})
    state["headers"] = HARDENED
    _scan(client)  # resolves it
    state["headers"] = {"content-type": "text/html"}
    again = _by_id(_scan(client)["findings"])["SEC-HDR-CSP"]
    assert again["status"] == "open"
    assert again["approved_by"] is None and again["retest_result"] is None
    assert any("Regression" in e["message"] for e in client.get("/api/audit").json())


def test_unknown_finding_is_404(client) -> None:
    assert client.post("/api/security/findings/nope/approve", json={}).status_code == 404
    assert client.post("/api/security/findings/nope/retest", json={}).status_code == 404


def test_audit_trail_records_scan_approval_retest(client) -> None:
    key = _by_id(_scan(client)["findings"])["SEC-HDR-CSP"]["key"]
    client.post(f"/api/security/findings/{key}/approve", json={"actor": "krishna"})
    client.post(f"/api/security/findings/{key}/retest", json={"actor": "krishna"})

    events = client.get("/api/audit").json()
    kinds = [e["kind"] for e in events]
    assert kinds[-1] == "scan"  # oldest last
    assert "approval" in kinds and kinds.count("retest") == 2  # started + result
    approval = next(e for e in events if e["kind"] == "approval")
    assert approval["actor"] == "krishna" and approval["ref"] == key


def test_stateless_retest_still_works(client, state) -> None:
    csp = _by_id(_scan(client)["findings"])["SEC-HDR-CSP"]
    state["headers"] = HARDENED
    body = {k: v for k, v in csp.items() if k in (
        "check_id", "source", "title", "severity", "component", "target_url", "evidence")}
    assert client.post("/api/security/retest", json=body).json()["retest_result"] == "pass"


def test_default_scanner_scope_is_config_driven(monkeypatch) -> None:
    monkeypatch.setattr(settings, "SECURITY_SCAN_ALLOWED_HOSTS", "staging.test, ")
    scope = get_scanner().scope
    assert scope.allows("https://staging.test/")
    assert scope.allows("http://127.0.0.1:8000/")
    assert not scope.allows("https://example.com/")


def test_timestamps_are_utc_aware(client) -> None:
    _scan(client)
    event = client.get("/api/audit").json()[0]
    finding = client.get("/api/security/findings").json()[0]
    assert event["at"].endswith("+00:00")
    assert finding["first_seen"].endswith("+00:00")
