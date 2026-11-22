"""
A finding a person can check: its tier, the exact request, what came back, why it is rated as it is.

TestSphere's findings used to be a title, a severity and a list of strings, and
missing headers were reported alongside SQL injection.  Now every finding says
how much it proves (``proven`` / ``unconfirmed`` / ``hardening``), how to
reproduce it (a copyable curl command and numbered steps), the part of the
response that shows it, and the reason for its severity.
"""

import shlex
import subprocess
from urllib.parse import urlsplit

import httpx
import pytest

from security import ActiveScanner, PassiveScanner, ScopePolicy
from security.findings import (
    Finding,
    FindingSource,
    Severity,
    Tier,
    code_location,
    tier_of,
)
from tests.security.test_active_scanner import site  # noqa: F401 - the vulnerable app fixture

pytestmark = pytest.mark.asyncio


def _scanner(base):
    return ActiveScanner(ScopePolicy.of(urlsplit(base).netloc))


async def test_an_sql_injection_finding_reproduces_from_its_own_command(site):  # noqa: F811
    (sqli,) = [f for f in await _scanner(site).scan(f"{site}/item?id=7") if f.check_id == "SEC-SQLI-ERROR"]

    assert sqli.tier == Tier.PROVEN
    assert sqli.location == {"method": "GET", "url": f"{site}/item", "parameter": "id"}
    assert sqli.title == "A quote in parameter 'id' breaks the SQL query (PostgreSQL error)"
    assert len(sqli.steps) == 4 and "without the quote" in sqli.steps[2]
    assert "psycopg2.ProgrammingError" in sqli.response_excerpt
    assert sqli.prerequisites and "Critical" in sqli.severity_rationale

    # The command in the report is the request that shows it
    args = shlex.split(sqli.request)
    assert args[:2] == ["curl", "-s"]
    response = httpx.get(args[-1])
    assert "psycopg2.ProgrammingError" in response.text


async def test_an_open_redirect_shows_where_it_sent_the_browser(site):  # noqa: F811
    (redirect,) = [f for f in await _scanner(site).scan(f"{site}/go?next=/home")
                   if f.check_id == "SEC-OPEN-REDIRECT"]
    assert redirect.tier == Tier.PROVEN
    assert "Location: https://open-redirect.invalid" in redirect.response_excerpt
    assert redirect.request.startswith("curl -s -D - -o /dev/null")


async def test_xss_not_run_in_a_browser_is_unconfirmed(site):  # noqa: F811
    # No browser confirmer here: reflected, but not shown to run
    (xss,) = [f for f in await _scanner(site).scan(f"{site}/search?q=hi") if f.check_id == "SEC-XSS-REFLECTED"]
    assert xss.tier == Tier.UNCONFIRMED
    assert "<img/src=x>" in xss.response_excerpt


async def test_missing_headers_are_hardening_with_the_headers_shown(site):  # noqa: F811
    findings = await PassiveScanner(ScopePolicy.of(urlsplit(site).netloc)).scan(f"{site}/safe")
    csp = next(f for f in findings if f.check_id == "SEC-HDR-CSP")
    assert csp.tier == Tier.HARDENING
    assert csp.response_excerpt.startswith("HTTP 200")
    assert csp.request.startswith("curl -s -D - -o /dev/null") and "not a demonstrated attack" in csp.severity_rationale
    # Every passive finding on this page is hardening: no harm was shown
    assert {f.tier for f in findings} == {Tier.HARDENING}


def test_cookie_values_never_reach_the_excerpt():
    from security.passive_scanner import PageSnapshot, _headers_excerpt

    snap = PageSnapshot("https://x.test/", "https://x.test/", 200,
                        httpx.Headers([("set-cookie", "session=s3cr3t-value; Path=/; HttpOnly")]), "")
    excerpt = _headers_excerpt(snap)
    assert "s3cr3t" not in excerpt and "set-cookie: session=…; Path=/; HttpOnly" in excerpt


def test_tiers_for_stored_findings_and_by_check():
    assert tier_of("SEC-EXPOSED-ENV") == Tier.PROVEN
    assert tier_of("SEC-CSRF") == Tier.UNCONFIRMED
    assert tier_of("SEC-HDR-HSTS") == Tier.HARDENING
    assert tier_of("SEC-XSS-REFLECTED", 1.0) == Tier.PROVEN and tier_of("SEC-XSS-REFLECTED", 0.9) == Tier.UNCONFIRMED
    assert tier_of("QA-ANYTHING", source="qa") == Tier.PROVEN
    # The tier is part of what is stored and sent
    f = Finding(check_id="SEC-HDR-CSP", source=FindingSource.SECURITY, title="t", severity=Severity.MEDIUM, component="u")
    assert f.model_dump(mode="json")["tier"] == "hardening"


def test_a_finding_is_traced_to_the_route_that_serves_it():
    routes = [{"path": "/item/<id>", "file": "app/views.py", "line": 41}, {"path": "/api/x/{x_id}", "file": "api.py", "line": 7}]
    assert code_location("http://h/item/9", routes) == "app/views.py:41"
    assert code_location("http://h/api/x/3?q=1", routes) == "api.py:7"
    assert code_location("http://h/other", routes) == ""


def test_the_curl_command_runs_in_a_shell():
    from security.findings import curl_command

    command = curl_command("GET", "http://127.0.0.1:9/x", {"q": "it's <b>"})
    assert shlex.split(command)[-1] == "http://127.0.0.1:9/x?q=it%27s+%3Cb%3E"
    assert subprocess.run(["bash", "-n", "-c", command], capture_output=True).returncode == 0
