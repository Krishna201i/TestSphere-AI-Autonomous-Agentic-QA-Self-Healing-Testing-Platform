"""
Tests for security/ — scope policy, Finding schema and the passive scanner.

Scanner tests stub HTTP with ``httpx.MockTransport``; one integration test
scans the real demo app on a loopback server.
"""

from __future__ import annotations

import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

from security.__main__ import main as cli_main
from security.findings import (
    Finding,
    FindingSource,
    FindingStatus,
    RetestResult,
    Severity,
    dedupe,
)
from security.passive_scanner import PROBE_ORIGIN, PassiveScanner, ScanError
from security.scope import OutOfScopeError, ScopePolicy

SAFE_HEADERS = {
    "content-type": "text/html; charset=utf-8",
    "content-security-policy": "default-src 'self'; frame-ancestors 'none'",
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "strict-transport-security": "max-age=31536000",
}


def _scanner(handler, *hosts: str) -> PassiveScanner:
    scope = ScopePolicy.of(*(hosts or ("app.test",)))
    return PassiveScanner(scope, transport=httpx.MockTransport(handler))


def _serve(headers: dict | None = None, html: str = "<p>hi</p>", status: int = 200):
    """Handler returning one fixed response; records requests on .requests."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        h = dict(SAFE_HEADERS if headers is None else headers)
        return httpx.Response(status, headers=h, text=html)

    handler.requests = requests  # type: ignore[attr-defined]
    return handler


def _ids(findings: list[Finding]) -> set[str]:
    return {f.check_id for f in findings}


# ---------------------------------------------------------------------------
# ScopePolicy
# ---------------------------------------------------------------------------


class TestScope:

    def test_default_scope_is_loopback_only(self) -> None:
        scope = ScopePolicy()
        assert scope.allows("http://127.0.0.1:8000/")
        assert scope.allows("http://localhost/")
        assert not scope.allows("https://example.com/")

    def test_bare_host_allows_any_port(self) -> None:
        scope = ScopePolicy.of("app.test")
        assert scope.allows("https://app.test/")
        assert scope.allows("http://app.test:8080/x")
        assert not scope.allows("https://evil.app.test/")

    def test_host_port_entry_pins_the_port(self) -> None:
        scope = ScopePolicy.of("app.test:8443")
        assert scope.allows("https://app.test:8443/")
        assert not scope.allows("https://app.test/")  # 443

    @pytest.mark.parametrize("url", ["ftp://app.test/", "file:///etc/passwd", "javascript:alert(1)", "http:///nohost"])
    def test_rejects_non_http_or_hostless(self, url: str) -> None:
        with pytest.raises(OutOfScopeError):
            ScopePolicy.of("app.test").check(url)


# ---------------------------------------------------------------------------
# Finding / dedupe
# ---------------------------------------------------------------------------


def _f(check_id: str, severity: Severity, component: str = "https://app.test/") -> Finding:
    return Finding(check_id=check_id, source=FindingSource.SECURITY, title=check_id,
                   severity=severity, component=component)


def test_key_depends_on_check_and_component_only() -> None:
    a = _f("SEC-X", Severity.LOW)
    b = _f("SEC-X", Severity.HIGH).model_copy(update={"evidence": ["different"]})
    assert a.key == b.key
    assert a.key != _f("SEC-X", Severity.LOW, "https://app.test/other").key


def test_dedupe_keeps_first_and_sorts_by_severity() -> None:
    out = dedupe([_f("SEC-B", Severity.LOW), _f("SEC-A", Severity.HIGH), _f("SEC-B", Severity.CRITICAL)])
    assert [(f.check_id, f.severity) for f in out] == [("SEC-A", Severity.HIGH), ("SEC-B", Severity.LOW)]


# ---------------------------------------------------------------------------
# Scanner — requests and scope enforcement
# ---------------------------------------------------------------------------


class TestScannerRequests:

    async def test_out_of_scope_target_sends_nothing(self) -> None:
        handler = _serve()
        with pytest.raises(OutOfScopeError):
            await _scanner(handler).scan("https://not-allowed.test/")
        assert handler.requests == []

    async def test_sends_probe_origin_and_user_agent(self) -> None:
        handler = _serve()
        await _scanner(handler).scan("https://app.test/")
        req = handler.requests[0]
        assert req.method == "GET"
        assert req.headers["origin"] == PROBE_ORIGIN
        assert "TestSphere" in req.headers["user-agent"]

    async def test_follows_in_scope_redirect(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/":
                return httpx.Response(302, headers={"location": "/login"})
            return httpx.Response(200, headers=SAFE_HEADERS, text="ok")

        findings = await _scanner(handler).scan("https://app.test/")
        assert findings == []

    async def test_refuses_redirect_out_of_scope(self) -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return httpx.Response(302, headers={"location": "https://elsewhere.test/"})

        with pytest.raises(OutOfScopeError):
            await _scanner(handler).scan("https://app.test/")
        assert seen == ["https://app.test/"]

    async def test_redirect_loop_raises_scan_error(self) -> None:
        handler = lambda r: httpx.Response(302, headers={"location": "/"})  # noqa: E731
        with pytest.raises(ScanError, match="Too many redirects"):
            await _scanner(handler).scan("https://app.test/")

    async def test_network_error_raises_scan_error(self) -> None:
        def handler(request):
            raise httpx.ConnectError("refused", request=request)
        with pytest.raises(ScanError):
            await _scanner(handler).scan("https://app.test/")


# ---------------------------------------------------------------------------
# Scanner — individual checks
# ---------------------------------------------------------------------------


def _without(*names: str) -> dict:
    return {k: v for k, v in SAFE_HEADERS.items() if k not in names}


class TestChecks:

    async def test_hardened_page_has_no_findings(self) -> None:
        assert await _scanner(_serve()).scan("https://app.test/") == []

    async def test_missing_headers(self) -> None:
        findings = await _scanner(_serve({"content-type": "text/html"})).scan("https://app.test/")
        assert _ids(findings) == {
            "SEC-HDR-CSP", "SEC-HDR-FRAME", "SEC-HDR-XCTO", "SEC-HDR-REFERRER", "SEC-HDR-HSTS",
        }
        assert findings[0].severity == Severity.MEDIUM  # sorted most severe first

    async def test_x_frame_options_satisfies_framing_without_csp(self) -> None:
        headers = {**_without("content-security-policy"), "x-frame-options": "DENY"}
        assert "SEC-HDR-FRAME" not in _ids(await _scanner(_serve(headers)).scan("https://app.test/"))

    async def test_report_only_csp_is_not_enough(self) -> None:
        headers = {**_without("content-security-policy"), "x-frame-options": "DENY",
                   "content-security-policy-report-only": "default-src 'self'"}
        findings = await _scanner(_serve(headers)).scan("https://app.test/")
        csp = next(f for f in findings if f.check_id == "SEC-HDR-CSP")
        assert any("Report-Only" in e for e in csp.evidence)

    async def test_hsts_only_checked_on_https(self) -> None:
        headers = _without("strict-transport-security")
        assert "SEC-HDR-HSTS" in _ids(await _scanner(_serve(headers)).scan("https://app.test/"))
        assert "SEC-HDR-HSTS" not in _ids(await _scanner(_serve(headers), "127.0.0.1").scan("http://127.0.0.1/"))

    async def test_hsts_max_age_zero_is_a_finding(self) -> None:
        headers = {**SAFE_HEADERS, "strict-transport-security": "max-age=0"}
        assert "SEC-HDR-HSTS" in _ids(await _scanner(_serve(headers)).scan("https://app.test/"))

    async def test_version_disclosure(self) -> None:
        headers = {**SAFE_HEADERS, "server": "nginx/1.18.0", "x-powered-by": "Express"}
        findings = await _scanner(_serve(headers)).scan("https://app.test/")
        leak = next(f for f in findings if f.check_id == "SEC-DISCLOSURE")
        assert leak.evidence == ["server: nginx/1.18.0"]  # versionless X-Powered-By not flagged

    async def test_cors_reflected_origin_with_credentials_is_high(self) -> None:
        headers = {**SAFE_HEADERS, "access-control-allow-origin": PROBE_ORIGIN,
                   "access-control-allow-credentials": "true"}
        cors = next(f for f in await _scanner(_serve(headers)).scan("https://app.test/") if f.check_id == "SEC-CORS")
        assert cors.severity == Severity.HIGH

    async def test_cors_wildcard_without_credentials_is_fine(self) -> None:
        headers = {**SAFE_HEADERS, "access-control-allow-origin": "*"}
        assert "SEC-CORS" not in _ids(await _scanner(_serve(headers)).scan("https://app.test/"))

    async def test_cookie_flags_per_cookie_and_value_redacted(self) -> None:
        def handler(request):
            return httpx.Response(200, headers=[
                *SAFE_HEADERS.items(),
                ("set-cookie", "session=SECRET123; Path=/"),
                ("set-cookie", "prefs=dark; Secure; HttpOnly; SameSite=Lax"),
            ], text="")

        findings = await _scanner(handler).scan("https://app.test/")
        cookies = [f for f in findings if f.check_id == "SEC-COOKIE-FLAGS"]
        assert len(cookies) == 1
        assert cookies[0].component.endswith("(cookie: session)")
        assert cookies[0].title == "Cookie 'session' missing HttpOnly, Secure, SameSite"
        assert cookies[0].severity == Severity.MEDIUM
        assert "SECRET123" not in " ".join(cookies[0].evidence)

    async def test_plain_http_flagged_except_on_loopback(self) -> None:
        html = '<form><input type="password"></form>'
        remote = await _scanner(_serve(html=html), "app.test").scan("http://app.test/")
        assert {"SEC-TRANSPORT-HTTP", "SEC-FORM-PASSWORD"} <= _ids(remote)
        local = await _scanner(_serve(html=html), "127.0.0.1").scan("http://127.0.0.1/")
        assert not {"SEC-TRANSPORT-HTTP", "SEC-FORM-PASSWORD"} & _ids(local)

    async def test_https_page_posting_password_to_http(self) -> None:
        html = '<form action="http://app.test/login"><input type="password" name="pw"></form>'
        findings = await _scanner(_serve(html=html)).scan("https://app.test/")
        form = next(f for f in findings if f.check_id == "SEC-FORM-PASSWORD")
        assert "Form posts to http://app.test/login" in form.evidence

    async def test_mixed_content(self) -> None:
        html = ('<script src="http://cdn.test/a.js"></script>'
                '<link rel="stylesheet" href="http://cdn.test/a.css">'
                '<link rel="canonical" href="http://app.test/">'
                '<img src="https://cdn.test/ok.png">')
        findings = await _scanner(_serve(html=html)).scan("https://app.test/")
        mixed = next(f for f in findings if f.check_id == "SEC-MIXED-CONTENT")
        assert mixed.evidence == ["http://cdn.test/a.css", "http://cdn.test/a.js"]

    async def test_non_html_body_skips_html_checks(self) -> None:
        headers = {**SAFE_HEADERS, "content-type": "application/json"}
        html = '<script src="http://cdn.test/a.js"></script>'
        assert await _scanner(_serve(headers, html=html)).scan("https://app.test/") == []


# ---------------------------------------------------------------------------
# Retest
# ---------------------------------------------------------------------------


class TestRetest:

    async def test_retest_pass_after_fix_and_fail_before(self) -> None:
        state = {"fixed": False}

        def handler(request):
            headers = SAFE_HEADERS if state["fixed"] else _without("referrer-policy")
            return httpx.Response(200, headers=headers, text="")

        scanner = _scanner(handler)
        [finding] = await scanner.scan("https://app.test/")
        assert finding.check_id == "SEC-HDR-REFERRER"

        still = await scanner.retest(finding)
        assert (still.retest_result, still.status) == (RetestResult.FAIL, FindingStatus.OPEN)

        state["fixed"] = True
        done = await scanner.retest(finding)
        assert (done.retest_result, done.status) == (RetestResult.PASS, FindingStatus.RESOLVED)
        assert finding.retest_result is None  # original untouched

    async def test_retest_uses_requested_url_not_redirect_target(self) -> None:
        def handler(request):
            if request.url.path == "/":
                return httpx.Response(302, headers={"location": "/home"})
            return httpx.Response(200, headers=_without("referrer-policy"), text="")

        scanner = _scanner(handler)
        [finding] = await scanner.scan("https://app.test/")
        assert finding.component == "https://app.test/home"
        assert finding.target_url == "https://app.test/"
        assert (await scanner.retest(finding)).retest_result == RetestResult.FAIL


# ---------------------------------------------------------------------------
# Integration — real demo app on loopback, plus the CLI
# ---------------------------------------------------------------------------

DEMO_DIR = Path(__file__).resolve().parent.parent / "engine" / "demo_app"


@pytest.fixture(scope="module")
def demo_url() -> str:  # type: ignore[misc]
    handler = partial(SimpleHTTPRequestHandler, directory=str(DEMO_DIR))
    handler.log_message = lambda *_: None  # type: ignore[method-assign]
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/index.html"
    server.shutdown()


async def test_demo_app_scan(demo_url: str) -> None:
    findings = await PassiveScanner().scan(demo_url)
    ids = _ids(findings)
    # Python's http.server sends no security headers and advertises its version
    assert {"SEC-HDR-CSP", "SEC-HDR-FRAME", "SEC-HDR-XCTO", "SEC-HDR-REFERRER", "SEC-DISCLOSURE"} <= ids
    # loopback HTTP is not flagged as a transport problem
    assert "SEC-TRANSPORT-HTTP" not in ids and "SEC-FORM-PASSWORD" not in ids


def test_cli_exit_codes(demo_url: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli_main([demo_url]) == 1  # medium findings present
    assert "SEC-HDR-CSP" in capsys.readouterr().out
    assert cli_main(["https://example.com/"]) == 2  # not authorized
    assert "not in the authorized scope" in capsys.readouterr().err
