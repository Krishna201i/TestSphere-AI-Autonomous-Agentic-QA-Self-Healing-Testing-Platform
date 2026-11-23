"""
Reflected XSS confirmed in a real browser.

A reflected marker is evidence, not proof: inside a <textarea> it never
becomes markup.  The finding is confirmed (confidence 1.0) only when the
payload's script runs in Chromium, and marked unconfirmed (0.5) when it is
reflected but inert, so a reviewer sees which ones are real.
"""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import pytest

from app.services.xss_confirm import confirm_in_browser
from security import ActiveScanner, ScopePolicy

pytestmark = pytest.mark.asyncio


class _Site(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        u = urlsplit(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}.get("q", "")
        if u.path == "/search":
            return self._html(f"<h1>Results for {q}</h1>")             # raw in markup: runs
        if u.path == "/notes":
            return self._html(f"<textarea>{q}</textarea>")            # raw, but inert text
        return self._html('<form action="/comment" method="post"><input name="body"></form>')

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        body = {k: v[0] for k, v in parse_qs(self.rfile.read(length).decode()).items()}.get("body", "")
        return self._html(f"<p>Thanks for your comment: {body}</p>")  # raw in markup: runs

    def _html(self, body):
        data = f"<!doctype html><html><body>{body}</body></html>".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_):
        pass


@pytest.fixture(scope="module")
def site():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Site)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def _scanner(site):
    return ActiveScanner(ScopePolicy.of(urlsplit(site).netloc), xss_confirmer=confirm_in_browser)


def _xss(findings):
    (xss,) = [f for f in findings if f.check_id == "SEC-XSS-REFLECTED"]
    return xss


async def test_a_script_that_runs_confirms_the_finding(site):
    xss = _xss(await _scanner(site).scan(f"{site}/search?q=hello"))
    assert xss.confidence == 1.0
    assert any("Confirmed in a real browser" in e for e in xss.evidence)


async def test_a_reflection_that_cannot_run_is_kept_but_marked_unconfirmed(site):
    xss = _xss(await _scanner(site).scan(f"{site}/notes?q=hello"))
    assert xss.confidence == 0.5
    assert any("Not confirmed" in e for e in xss.evidence)


async def test_a_form_post_is_confirmed_by_submitting_it_in_the_browser(site):
    xss = _xss(await _scanner(site).scan(f"{site}/"))
    assert "body param 'body'" in xss.component and xss.confidence == 1.0


async def test_without_a_confirmer_findings_are_as_before(site):
    plain = ActiveScanner(ScopePolicy.of(urlsplit(site).netloc))
    assert _xss(await plain.scan(f"{site}/search?q=hello")).confidence == 0.9
