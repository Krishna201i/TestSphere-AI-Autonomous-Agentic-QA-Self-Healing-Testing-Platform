"""Dependency CVE scanning: pinned versions from lockfiles, checked against OSV.dev (mocked)."""

import json

import httpx

from ingestion.vulns import as_findings, check_dependencies, pinned_packages

ADVISORY = {
    "id": "GHSA-aaaa", "aliases": ["CVE-2026-0001"], "summary": "Prototype pollution",
    "database_specific": {"severity": "HIGH"},
    "affected": [{"package": {"name": "axios", "ecosystem": "npm"},
                  "ranges": [{"type": "SEMVER", "events": [{"introduced": "0"}, {"fixed": "0.30.3"}]},
                             {"type": "SEMVER", "events": [{"introduced": "1.0.0"}, {"fixed": "1.8.2"}]}]}],
}


def osv(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/v1/querybatch":
        queries = json.loads(request.content)["queries"]
        return httpx.Response(200, json={"results": [
            {"vulns": [{"id": "GHSA-aaaa"}]} if q["package"]["name"] == "axios" else {} for q in queries]})
    if request.url.path == "/v1/vulns/GHSA-aaaa":
        return httpx.Response(200, json=ADVISORY)
    return httpx.Response(404)


def test_versions_come_from_lockfiles_and_exact_pins(tmp_path):
    (tmp_path / "package-lock.json").write_text(json.dumps({"packages": {
        "": {"name": "app"}, "node_modules/axios": {"version": "1.6.2"}, "node_modules/a/node_modules/b": {"version": "2.0.0"}}}))
    (tmp_path / "requirements.txt").write_text("Flask==2.2.2\nrequests>=2\n# comment\ngunicorn[gevent]==21.2.0\n")
    (tmp_path / "go.mod").write_text("module x\nrequire (\n\tgithub.com/gin-gonic/gin v1.9.0\n)\n")
    nm = tmp_path / "node_modules" / "x"
    nm.mkdir(parents=True)
    (nm / "requirements.txt").write_text("evil==1.0\n")  # never read from dependency folders
    got = {(p["ecosystem"], p["name"], p["version"]) for p in pinned_packages(tmp_path)}
    assert got == {("npm", "axios", "1.6.2"), ("npm", "b", "2.0.0"), ("PyPI", "flask", "2.2.2"),
                   ("PyPI", "gunicorn", "21.2.0"), ("Go", "github.com/gin-gonic/gin", "v1.9.0")}


def test_advisories_name_the_cve_severity_and_the_fix_for_the_installed_line():
    packages = [{"ecosystem": "npm", "name": "axios", "version": "1.6.2", "file": "package-lock.json"},
                {"ecosystem": "npm", "name": "left-pad", "version": "1.3.0", "file": "package-lock.json"}]
    scan = check_dependencies(packages, transport=httpx.MockTransport(osv))
    assert scan["checked"] == 2 and scan["vulnerable"] == 1 and scan["error"] is None
    (a,) = scan["advisories"]
    assert (a["package"], a["cves"], a["severity"], a["fixed_in"]) == ("axios", ["CVE-2026-0001"], "high", "1.8.2")

    (finding,) = as_findings(scan, "https://github.com/acme/shop")
    assert finding["check_id"] == "SEC-DEP-GHSA-aaaa" and finding["severity"] == "high"
    assert finding["target_url"] == "https://github.com/acme/shop"
    assert "Upgrade axios to 1.8.2" in finding["recommendation"]


def test_an_unreachable_osv_is_reported_not_raised():
    def down(request):
        raise httpx.ConnectError("no network")

    scan = check_dependencies([{"ecosystem": "npm", "name": "axios", "version": "1.6.2", "file": "x"}],
                              transport=httpx.MockTransport(down))
    assert scan["error"].startswith("Could not check dependencies") and scan["advisories"] == []


def test_ingesting_records_vulnerable_dependencies_as_findings(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from backend.api import ingest
    from backend.config import settings
    from backend.main import app

    (tmp_path / "package-lock.json").write_text(json.dumps({"packages": {"node_modules/axios": {"version": "1.6.2"}}}))
    monkeypatch.setattr(settings, "INGEST_ALLOW_LOCAL_PATHS", True)
    monkeypatch.setattr(settings, "DEPENDENCY_SCAN", True)
    monkeypatch.setattr(ingest, "check_dependencies", lambda pk: check_dependencies(pk, transport=httpx.MockTransport(osv)))
    client = TestClient(app)
    body = client.post("/api/ingest", json={"source": str(tmp_path)}).json()
    assert body["dependency_scan"]["vulnerable"] == 1
    findings = client.get("/api/security/findings").json()
    dep = [f for f in findings if f["check_id"] == "SEC-DEP-GHSA-aaaa"]
    assert dep and dep[0]["status"] == "open"
    resp = client.post(f"/api/security/findings/{dep[0]['key']}/retest", json={})
    assert resp.status_code == 422 and "ingesting the repository again" in resp.json()["detail"]
