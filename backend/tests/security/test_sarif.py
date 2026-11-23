"""
tests/security/test_sarif.py
============================
Tests for SARIF v2.1.0 export of TestSphere-AI security findings and its API.
"""

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.security import get_scanner
from app.main import app
from security import Finding, FindingSource, FindingStatus, PassiveScanner, ScopePolicy, Severity
from security.sarif import SARIF_SCHEMA, SARIF_VERSION, findings_to_sarif


def test_findings_to_sarif_empty():
    sarif = findings_to_sarif([])
    assert sarif["$schema"] == SARIF_SCHEMA
    assert sarif["version"] == SARIF_VERSION
    assert len(sarif["runs"]) == 1
    run = sarif["runs"][0]
    assert run["tool"]["driver"]["name"] == "TestSphere AI"
    assert run["tool"]["driver"]["rules"] == []
    assert run["results"] == []


def test_findings_to_sarif_severity_mapping_and_rules():
    f_crit = Finding(
        check_id="SEC-INJ-SQL",
        source=FindingSource.SECURITY,
        title="SQL Injection Detected",
        severity=Severity.CRITICAL,
        component="https://target.test/api/search?q=",
        target_url="https://target.test/api/search",
        root_cause="Unsanitized query parameter interpolated into SQL query",
        recommendation="Use parameterized queries",
        confidence=0.95,
    )
    f_high = Finding(
        check_id="SEC-HDR-CSP",
        source=FindingSource.SECURITY,
        title="Missing Content-Security-Policy",
        severity=Severity.HIGH,
        component="https://target.test/dashboard",
        target_url="https://target.test/dashboard",
        root_cause="No CSP header returned",
        recommendation="Add Content-Security-Policy header",
    )
    f_med = Finding(
        check_id="SEC-COOKIE-FLAGS",
        source=FindingSource.SECURITY,
        title="Missing HttpOnly flag",
        severity=Severity.MEDIUM,
        component="https://target.test/ (cookie: session)",
        target_url="https://target.test/",
        root_cause="Cookie lacks HttpOnly attribute",
        recommendation="Set HttpOnly on session cookies",
    )
    f_low = Finding(
        check_id="SEC-HDR-REFERRER",
        source=FindingSource.SECURITY,
        title="Referrer-Policy not strict",
        severity=Severity.LOW,
        component="https://target.test/",
        target_url="https://target.test/",
    )
    f_info = Finding(
        check_id="SEC-INFO-BANNER",
        source=FindingSource.SECURITY,
        title="Server banner disclosure",
        severity=Severity.INFO,
        component="https://target.test/",
        target_url="https://target.test/",
    )

    # Also add a duplicate check_id to verify rule deduplication
    f_dup_csp = Finding(
        check_id="SEC-HDR-CSP",
        source=FindingSource.SECURITY,
        title="Missing Content-Security-Policy on login",
        severity=Severity.HIGH,
        component="https://target.test/login",
        target_url="https://target.test/login",
    )

    sarif = findings_to_sarif([f_crit, f_high, f_med, f_low, f_info, f_dup_csp])
    run = sarif["runs"][0]
    rules = {r["id"]: r for r in run["tool"]["driver"]["rules"]}

    # Ensure unique rules for unique check_ids
    assert set(rules.keys()) == {"SEC-INJ-SQL", "SEC-HDR-CSP", "SEC-COOKIE-FLAGS", "SEC-HDR-REFERRER", "SEC-INFO-BANNER"}
    assert rules["SEC-INJ-SQL"]["defaultConfiguration"]["level"] == "error"
    assert rules["SEC-HDR-CSP"]["defaultConfiguration"]["level"] == "error"
    assert rules["SEC-COOKIE-FLAGS"]["defaultConfiguration"]["level"] == "warning"
    assert rules["SEC-HDR-REFERRER"]["defaultConfiguration"]["level"] == "note"
    assert rules["SEC-INFO-BANNER"]["defaultConfiguration"]["level"] == "note"

    # Verify results mapping
    results = run["results"]
    assert len(results) == 6

    # Verify critical result
    crit_res = [r for r in results if r["ruleId"] == "SEC-INJ-SQL"][0]
    assert crit_res["level"] == "error"
    assert "SQL Injection" in crit_res["message"]["text"]
    assert crit_res["locations"][0]["physicalLocation"]["artifactLocation"]["uri"] == "https://target.test/api/search"
    assert crit_res["properties"]["severity"] == "critical"
    assert crit_res["properties"]["confidence"] == 0.95


def test_findings_to_sarif_from_dict():
    dict_finding = {
        "check_id": "SEC-HDR-XCTO",
        "title": "Missing X-Content-Type-Options",
        "severity": "medium",
        "component": "https://example.com/api",
        "target_url": "https://example.com/api",
        "root_cause": "Header absent",
        "recommendation": "Add nosniff",
        "confidence": 1.0,
        "key": "xcto-1234",
    }
    sarif = findings_to_sarif([dict_finding])
    results = sarif["runs"][0]["results"]
    assert len(results) == 1
    assert results[0]["ruleId"] == "SEC-HDR-XCTO"
    assert results[0]["level"] == "warning"
    assert results[0]["properties"]["key"] == "xcto-1234"


def test_api_security_findings_sarif_endpoint():
    transport = httpx.MockTransport(lambda r: httpx.Response(200, headers={"content-type": "text/html"}, text=""))
    app.dependency_overrides[get_scanner] = lambda: PassiveScanner(ScopePolicy.of("app.test"), transport=transport)
    try:
        client = TestClient(app)
        # First scan to populate findings in DB
        scan_resp = client.post("/api/security/scan", json={"url": "http://app.test/"})
        assert scan_resp.status_code == 200

        # Now call the SARIF export endpoint
        sarif_resp = client.get("/api/security/findings/sarif")
        assert sarif_resp.status_code == 200
        sarif = sarif_resp.json()

        assert sarif["version"] == "2.1.0"
        assert len(sarif["runs"]) == 1
        run = sarif["runs"][0]
        assert len(run["results"]) > 0
        assert all("ruleId" in r and "level" in r for r in run["results"])
    finally:
        app.dependency_overrides.clear()


def test_cli_sarif_export(tmp_path, monkeypatch, capsys):
    from security.__main__ import main as cli_main

    dummy_findings = [
        Finding(
            check_id="SEC-HDR-CSP",
            source=FindingSource.SECURITY,
            title="Missing CSP",
            severity=Severity.HIGH,
            component="http://127.0.0.1:8000/",
            target_url="http://127.0.0.1:8000/",
        )
    ]

    async def fake_scan(self, url):
        return dummy_findings

    monkeypatch.setattr(PassiveScanner, "scan", fake_scan)

    # 1. Output to file
    out_file = tmp_path / "test.sarif"
    code = cli_main(["http://127.0.0.1:8000/", "--sarif", str(out_file)])
    assert code == 1  # HIGH severity finding present
    assert out_file.exists()
    import json
    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert data["version"] == "2.1.0"
    assert data["runs"][0]["results"][0]["ruleId"] == "SEC-HDR-CSP"

    # 2. Output to stdout with '-'
    code2 = cli_main(["http://127.0.0.1:8000/", "--sarif", "-"])
    assert code2 == 1
    stdout_sarif = capsys.readouterr().out
    data2 = json.loads(stdout_sarif)
    assert data2["runs"][0]["results"][0]["ruleId"] == "SEC-HDR-CSP"
