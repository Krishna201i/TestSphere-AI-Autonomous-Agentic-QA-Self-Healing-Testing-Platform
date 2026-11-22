"""
A site on free hosting sleeps when idle.

Measured on a real Render app: its first answer after a nap took 18.6 s, the
next 0.4 s.  The passive scan gave up after 10 s ("ReadTimeout") and page
analysis after 12 s.  Both now wait once for the site to wake, and say why
when it never does.
"""

import asyncio
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import pytest

from app.services import url_analyzer
from security import PassiveScanner, ScanError, ScopePolicy


def _server(first_delay: float):
    state = {"woken": False}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if not state["woken"]:
                time.sleep(first_delay)  # starting up
                state["woken"] = True
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<!doctype html><title>Awake</title><h1>Hello</h1>")

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/"


@pytest.fixture
def sleeping_site():
    server, url = _server(first_delay=1.5)
    yield url
    server.shutdown()


def test_the_passive_scan_waits_once_for_a_sleeping_site(sleeping_site):
    scanner = PassiveScanner(ScopePolicy.of(urlsplit(sleeping_site).netloc), timeout=0.5, wake_timeout=5)
    snap = asyncio.run(scanner.fetch(sleeping_site))
    assert snap.status == 200 and "Awake" in snap.html


def test_a_site_that_never_wakes_gets_a_plain_explanation(sleeping_site):
    scanner = PassiveScanner(ScopePolicy.of(urlsplit(sleeping_site).netloc), timeout=0.2, wake_timeout=0.4)
    with pytest.raises(ScanError) as caught:
        asyncio.run(scanner.fetch(sleeping_site))
    assert "did not answer within 0 seconds" not in str(caught.value)
    assert "sleep when idle" in str(caught.value)


def test_without_a_wake_wait_the_old_timeout_error_stands(sleeping_site):
    scanner = PassiveScanner(ScopePolicy.of(urlsplit(sleeping_site).netloc), timeout=0.3, wake_timeout=0)
    with pytest.raises(ScanError, match="ReadTimeout"):
        asyncio.run(scanner.fetch(sleeping_site))


def test_page_analysis_waits_for_a_sleeping_site_too(sleeping_site, monkeypatch):
    monkeypatch.setattr(url_analyzer, "WAKE_TIMEOUT", 5.0)
    response, _ = asyncio.run(url_analyzer.get_verifying_first(sleeping_site, timeout=0.5, headers={}, wake=True))
    assert response.status_code == 200
