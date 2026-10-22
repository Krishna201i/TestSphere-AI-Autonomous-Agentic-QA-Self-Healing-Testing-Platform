"""
tests/engine/test_request_guard.py
==================================
The outbound request guard covers everything the browser fetches: direct
navigations, redirects and subresources, not only the first URL.

Two local servers stand in for a public site and an internal service; the
guard refuses the internal one's port.  Uses real headless Chromium.
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import pytest

from engine import browser
from engine.runner import run_test
from engine.schemas import ActionType, Step, StepStatus, TestPlan


def _serve(routes: dict[str, tuple[int, dict[str, str], bytes]]):
    hits: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            code, headers, body = routes.get(self.path, (200, {}, b"<html><body>ok</body></html>"))
            self.send_response(code)
            for name, value in {"Content-Type": "text/html", **headers}.items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}", hits


@pytest.fixture
def sites():
    internal, internal_url, internal_hits = _serve({})
    public, public_url, public_hits = _serve({
        "/redirect": (302, {"Location": f"{internal_url}/via-redirect"}, b""),
        "/embeds": (200, {}, f'<html><body><img src="{internal_url}/via-img"></body></html>'.encode()),
    })
    internal_port = internal.server_address[1]

    def guard(url: str) -> None:
        if urlsplit(url).port == internal_port:
            raise ValueError("internal address")

    browser.set_request_guard(guard)
    yield public_url, internal_url, internal_hits, public_hits
    browser.set_request_guard(None)
    internal.shutdown()
    public.shutdown()


def _plan(*urls: str) -> TestPlan:
    return TestPlan(
        test_id="guard", name="guard", base_url=urls[0],
        steps=[Step(step_id=f"s{i}", action=ActionType.GOTO, value=u) for i, u in enumerate(urls)],
    )


async def test_direct_navigation_to_a_blocked_address_fails(sites):
    _, internal_url, internal_hits, _ = sites
    result = await run_test(_plan(f"{internal_url}/secret"))
    assert result.steps[0].status == StepStatus.FAILED
    assert internal_hits == []


async def test_redirect_to_a_blocked_address_is_stopped(sites):
    public_url, _, internal_hits, public_hits = sites
    await run_test(_plan(f"{public_url}/redirect"))
    assert "/redirect" in public_hits
    assert internal_hits == []


async def test_subresources_from_a_blocked_address_are_not_fetched(sites):
    public_url, _, internal_hits, public_hits = sites
    result = await run_test(_plan(f"{public_url}/embeds"))
    assert result.steps[0].status == StepStatus.PASSED  # the page itself is allowed
    assert "/embeds" in public_hits
    assert internal_hits == []


async def test_allowed_sites_still_load(sites):
    public_url, _, _, public_hits = sites
    result = await run_test(_plan(f"{public_url}/page"))
    assert result.steps[0].status == StepStatus.PASSED
    assert "/page" in public_hits
