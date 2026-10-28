"""
Active (DAST) scanner against a deliberately vulnerable local app.

The app reflects input, leaks a SQL error on a stray quote, and redirects to
whatever a parameter says — the three things the scanner looks for. Every
request is served from 127.0.0.1, which the scope allows; the scope tests
prove nothing else is ever contacted.
"""

import html
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from security import ActiveScanner, OutOfScopeError, ScopePolicy

pytestmark = pytest.mark.asyncio


class _Vulnerable(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        u = urlsplit(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path == "/search":
            # Reflects 'q' with no escaping -> XSS
            return self._html(f"<h1>Results for {q.get('q', '')}</h1>")
        if u.path == "/item":
            # A stray quote in 'id' leaks a database error -> SQLi
            if "'" in q.get("id", ""):
                return self._html("<pre>psycopg2.ProgrammingError: syntax error at or near \"'\"</pre>", code=500)
            return self._html("<p>Item ok</p>")
        if u.path == "/go":
            # Redirects to whatever 'next' says -> open redirect
            self.send_response(302)
            self.send_header("Location", q.get("next", "/"))
            self.end_headers()
            return None
        if u.path == "/safe":
            # Escapes input, parameterises queries: nothing to find
            return self._html(f"<h1>Hello {html.escape(q.get('q', ''))}</h1>")
        return self._html('<form action="/search" method="get"><input name="q"></form>')

    def _html(self, body, code=200):
        data = f"<!doctype html><html><body>{body}</body></html>".encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_):
        pass


@pytest.fixture(scope="module")
def site():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Vulnerable)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def _scanner(site):
    return ActiveScanner(ScopePolicy.of(urlsplit(site).netloc))


async def test_reflected_xss_is_found(site):
    findings = await _scanner(site).scan(f"{site}/search?q=hello")
    xss = [f for f in findings if f.check_id == "SEC-XSS-REFLECTED"]
    assert len(xss) == 1 and xss[0].severity.value == "high"
    assert "q" in xss[0].component


async def test_error_based_sql_injection_is_found(site):
    findings = await _scanner(site).scan(f"{site}/item?id=42")
    sqli = [f for f in findings if f.check_id == "SEC-SQLI-ERROR"]
    assert len(sqli) == 1 and sqli[0].severity.value == "critical"
    assert "PostgreSQL" in " ".join(sqli[0].evidence)


async def test_open_redirect_is_found(site):
    findings = await _scanner(site).scan(f"{site}/go?next=/home")
    redirects = [f for f in findings if f.check_id == "SEC-OPEN-REDIRECT"]
    assert len(redirects) == 1 and redirects[0].severity.value == "medium"


async def test_a_safe_endpoint_has_no_findings(site):
    assert await _scanner(site).scan(f"{site}/safe?q=hello") == []


async def test_forms_on_the_page_are_discovered_and_probed(site):
    # The index page has a GET form posting to /search; the scanner finds the XSS through it
    findings = await _scanner(site).scan(f"{site}/")
    assert any(f.check_id == "SEC-XSS-REFLECTED" for f in findings)


async def test_a_url_out_of_scope_is_refused_before_any_request():
    scanner = ActiveScanner(ScopePolicy.of("127.0.0.1"))
    with pytest.raises(OutOfScopeError):
        await scanner.scan("http://example.com/search?q=1")
    assert scanner._sent == 0


async def test_an_off_scope_form_action_is_never_submitted(site):
    scanner = ActiveScanner(ScopePolicy.of(urlsplit(site).netloc))
    # A form whose action posts to another host must never be probed
    off = _points_off_scope = scanner._points(  # noqa: SLF001
        site, httpx.Response(200, headers={"content-type": "text/html"},
                             text='<form action="https://evil.example/x" method="get"><input name="q"></form>'))
    assert list(off) == []


async def test_the_request_budget_is_never_exceeded(site):
    scanner = ActiveScanner(ScopePolicy.of(urlsplit(site).netloc), max_requests=3)
    await scanner.scan(f"{site}/search?q=a&r=b&s=c&t=d")
    assert scanner._sent <= 3
