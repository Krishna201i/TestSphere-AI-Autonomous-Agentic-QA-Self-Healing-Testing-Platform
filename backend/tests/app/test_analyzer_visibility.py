"""
Tests are planned only on what a visitor can see.

A single-page app keeps its sign-in dialog, confirm dialogs and other views
in the HTML, hidden.  Planning on those gave tests that could never pass (a
sign-up test on a closed dialog's fields, a content test on the heading of a
hidden "Are you sure?").  The analyzer renders the page, marks what is
hidden, plans on the rest and says how much it left out.
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from backend.config import settings
from backend.pipeline import suite
from backend.services.url_analyzer import HIDDEN_MARK
from backend.services.url_analyzer import URLAnalyzerService as U

PAGE = """<!doctype html><title>Cloud Cost &amp; Performance</title>
<style>.hidden{display:none}</style>
<h1>Cloud Cost &amp; Performance Optimizer</h1>
<form action="/subscribe"><input id="news" type="email" name="email" placeholder="Your email" required>
<button type="submit">Subscribe</button></form>
<a href="/pricing">Pricing</a>
<div id="auth-modal" class="hidden"><h2>Sign in to Cloud</h2>
  <form action="/signup"><input id="auth-email" type="email" required>
  <input id="auth-password" type="password" required minlength="6">
  <input id="auth-password2" type="password" required><button type="submit">Create account</button></form>
  <a href="/terms">Terms</a></div>
<div id="confirm" style="visibility:hidden"><h3>Are you sure?</h3><button id="yes">Proceed</button></div>
<dialog><h2>Never opened</h2><button id="dlg">OK</button></dialog>"""


@pytest.fixture(scope="module")
def site():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(PAGE.encode())

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/"
    server.shutdown()


async def test_only_visible_controls_headings_and_links_are_planned_on(site, monkeypatch):
    monkeypatch.setattr(settings, "ANALYZE_VISIBILITY", True)
    result = await U.analyze_live_website(site)
    inventory = result["elements_inventory"]

    assert [i["selector"] for i in inventory["inputs"]] == ["#news"]
    assert [b["text"] for b in inventory["buttons"]] == ["Subscribe"]
    assert inventory["headings"] == ["Cloud Cost & Performance Optimizer"]
    assert inventory["links"] == ["/pricing"]
    # Three dialog fields, their submit, "Proceed" and the dialog's OK
    assert inventory["hidden_controls"] == 6
    # Entities decoded: the title as a visitor reads it
    assert result["page_title"] == "Cloud Cost & Performance"

    # No sign-up tests on the closed dialog, no content test on a hidden heading
    tests = suite.page_tests(result)
    names = " | ".join(t["name"] for t in tests)
    assert "Sign-up" not in names and "Are you sure" not in names and "Never opened" not in names
    assert "Content: heading 'Cloud Cost & Performance Optimizer'" in names


def test_marked_elements_are_skipped_by_every_extractor():
    html = (f'<input id="a" {HIDDEN_MARK}=""><input id="b"><button {HIDDEN_MARK}="">X</button><button>Y</button>'
            f'<h2 {HIDDEN_MARK}="">Gone</h2><h2>Here</h2><a {HIDDEN_MARK}="" href="/x">x</a><a href="/y">y</a>')
    assert [i["selector"] for i in U._extract_inputs(html)] == ["#b"]
    assert [b["text"] for b in U._extract_buttons(html)] == ["Y"]
    assert U._extract_headings(html) == ["Here"]
    assert U._extract_links(html, "example.com") == ["/y"]


def test_without_the_check_the_raw_html_is_used():
    # ANALYZE_VISIBILITY=false (and these tests' default): nothing is marked, nothing skipped
    assert len(U._extract_inputs(PAGE)) == 4
