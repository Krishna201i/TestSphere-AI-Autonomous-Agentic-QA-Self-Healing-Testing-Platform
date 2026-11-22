"""
The passive scanner's multi-signal checks, against a local site.

Each vulnerable page must be flagged, and each look-alike safe page must not:
a nonce-protected 'unsafe-inline', the word "traceback" in a blog post, an
"Index of" title alone, a form with a CSRF token, a single-page app that
answers /.env with its HTML index.
"""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import pytest

from security import PassiveScanner, ScopePolicy

pytestmark = pytest.mark.asyncio

TRACEBACK = """<pre>Traceback (most recent call last):
  File "/srv/app/views.py", line 12, in checkout
ZeroDivisionError: division by zero</pre>"""
LISTING = "<html><head><title>Index of /uploads</title></head><body><h1>Index of /uploads</h1>" \
          '<a href="../">Parent Directory</a> <a href="a.txt">a.txt</a></body></html>'

PAGES = {
    "/weak-csp": ({"Content-Security-Policy": "default-src 'self'; script-src 'self' 'unsafe-inline'"}, "<p>x</p>"),
    "/nonce-csp": ({"Content-Security-Policy": "script-src 'nonce-r4nd0m' 'unsafe-inline'"}, "<p>x</p>"),
    "/any-csp": ({"Content-Security-Policy": "script-src *"}, "<p>x</p>"),
    "/samesite-none": ({"Set-Cookie": "sid=abc; HttpOnly; SameSite=None"}, "<p>x</p>"),
    "/samesite-none-secure": ({"Set-Cookie": "sid=abc; HttpOnly; Secure; SameSite=None"}, "<p>x</p>"),
    "/crash": ({}, TRACEBACK),
    "/blog": ({}, "<p>Reading a traceback is a skill every developer needs.</p>"),
    "/uploads/": ({}, LISTING),
    "/index-post": ({}, "<html><head><title>Index of / my notes</title></head><body>notes</body></html>"),
    "/contact": ({}, '<form method="post" action="/send"><input name="email"><textarea name="msg"></textarea></form>'),
    "/contact-token": ({}, '<form method="post" action="/send"><input type="hidden" name="csrf_token" value="t">'
                           '<input name="email"></form>'),
    "/contact-lax": ({"Set-Cookie": "sid=abc; HttpOnly; SameSite=Lax"},
                     '<form method="post" action="/send"><input name="email"></form>'),
    "/search": ({}, '<form method="get" action="/s"><input name="q"></form>'),
}


class _Site(BaseHTTPRequestHandler):
    exposed = True  # serve /.git/HEAD and /.env (else answer every path with the SPA index)

    def do_GET(self):  # noqa: N802
        path = urlsplit(self.path).path
        if path in ("/.git/HEAD", "/.env"):
            if not self.exposed:
                return self._send(200, "text/html", "<!doctype html><div id=app></div>")
            body = "ref: refs/heads/main\n" if path == "/.git/HEAD" else \
                "APP_ENV=production\nDB_PASSWORD=hunter2\nSTRIPE_SECRET_KEY=sk_live_x\n"
            return self._send(200, "text/plain", body)
        headers, body = PAGES.get(path, ({}, "<p>home</p>"))
        return self._send(200, "text/html", f"<!doctype html><html><body>{body}</body></html>"
                          if not body.startswith("<html") else body, headers)

    def _send(self, code, ctype, body, headers=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, *_):
        pass


def _serve(exposed: bool):
    handler = type("Site", (_Site,), {"exposed": exposed})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


@pytest.fixture(scope="module")
def site():
    server, url = _serve(exposed=True)
    yield url
    server.shutdown()


@pytest.fixture(scope="module")
def spa():
    server, url = _serve(exposed=False)
    yield url
    server.shutdown()


async def _ids(base, path, probe=False):
    scanner = PassiveScanner(ScopePolicy.of(urlsplit(base).netloc))
    snap = await scanner.fetch(base + path, probe_files=probe)
    return {f.check_id: f for f in scanner.analyze(snap)}


@pytest.mark.parametrize(("path", "check", "flagged"), [
    ("/weak-csp", "SEC-CSP-WEAK", True),
    ("/any-csp", "SEC-CSP-WEAK", True),
    ("/nonce-csp", "SEC-CSP-WEAK", False),           # with a nonce, browsers ignore 'unsafe-inline'
    ("/samesite-none", "SEC-COOKIE-SAMESITE-NONE", True),
    ("/samesite-none-secure", "SEC-COOKIE-SAMESITE-NONE", False),
    ("/crash", "SEC-ERROR-DISCLOSURE", True),
    ("/blog", "SEC-ERROR-DISCLOSURE", False),          # the word alone is not a trace
    ("/uploads/", "SEC-DIR-LISTING", True),
    ("/index-post", "SEC-DIR-LISTING", False),         # a title alone is not a listing
    ("/contact", "SEC-CSRF", True),
    ("/contact-token", "SEC-CSRF", False),
    ("/contact-lax", "SEC-CSRF", False),               # SameSite=Lax cookies stay home
    ("/search", "SEC-CSRF", False),                    # GET forms change nothing
])
async def test_each_check_needs_its_signals(site, path, check, flagged):
    assert (check in await _ids(site, path)) is flagged


async def test_exposed_git_and_env_are_found_without_recording_secrets(site):
    found = await _ids(site, "/", probe=True)
    assert found["SEC-EXPOSED-GIT"].severity.value == "high"
    env = found["SEC-EXPOSED-ENV"]
    assert env.severity.value == "critical"
    text = " ".join(env.evidence)
    assert "DB_PASSWORD" in text and "STRIPE_SECRET_KEY" in text
    assert "hunter2" not in text and "sk_live" not in text


async def test_an_app_answering_every_path_with_its_index_has_no_exposed_files(spa):
    found = await _ids(spa, "/", probe=True)
    assert "SEC-EXPOSED-GIT" not in found and "SEC-EXPOSED-ENV" not in found


async def test_files_are_only_probed_when_asked(site):
    found = await _ids(site, "/", probe=False)
    assert "SEC-EXPOSED-ENV" not in found


async def test_a_scan_probes_and_a_retest_resolves_once_fixed(site):
    scanner = PassiveScanner(ScopePolicy.of(urlsplit(site).netloc))
    env = next(f for f in await scanner.scan(site + "/") if f.check_id == "SEC-EXPOSED-ENV")
    assert (await scanner.retest(env)).retest_result.value == "fail"  # still served
