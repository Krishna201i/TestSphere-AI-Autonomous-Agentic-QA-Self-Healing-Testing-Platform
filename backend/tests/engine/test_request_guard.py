"""
tests/engine/test_request_guard.py
==================================
The outbound request guard covers everything the browser fetches: direct
navigations, redirects and subresources, not only the first URL.

Two local servers stand in for a public site and an internal service; the
guard refuses the internal one's port.  Runs in every installed browser
(Chromium always; Firefox and WebKit when `playwright install` added them).
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from engine import browser
from engine.runner import run_test
from engine.schemas import ActionType, RunOptions, Step, StepStatus, TestPlan


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


def _installed(name: str) -> bool:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        return Path(getattr(pw, name).executable_path).exists()


@pytest.fixture(params=["chromium", "firefox", "webkit"])
def engine(request) -> RunOptions:
    if request.param != "chromium" and not _installed(request.param):
        pytest.skip(f"{request.param} not installed (python -m playwright install {request.param})")
    return RunOptions(browser=request.param)


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


async def test_direct_navigation_to_a_blocked_address_fails(sites, engine):
    _, internal_url, internal_hits, _ = sites
    result = await run_test(_plan(f"{internal_url}/secret"), engine)
    assert result.steps[0].status == StepStatus.FAILED
    assert internal_hits == []


async def test_redirect_to_a_blocked_address_is_stopped(sites, engine):
    public_url, _, internal_hits, public_hits = sites
    await run_test(_plan(f"{public_url}/redirect"), engine)
    assert "/redirect" in public_hits
    assert internal_hits == []


async def test_subresources_from_a_blocked_address_are_not_fetched(sites, engine):
    public_url, _, internal_hits, public_hits = sites
    result = await run_test(_plan(f"{public_url}/embeds"), engine)
    assert result.steps[0].status == StepStatus.PASSED  # the page itself is allowed
    assert "/embeds" in public_hits
    assert internal_hits == []


async def test_allowed_sites_still_load(sites, engine):
    public_url, _, _, public_hits = sites
    result = await run_test(_plan(f"{public_url}/page"), engine)
    assert result.steps[0].status == StepStatus.PASSED
    assert "/page" in public_hits


async def test_a_name_that_resolves_to_a_blocked_address_is_refused(monkeypatch):
    """DNS rebinding: the name passes the guard, but the proxy checks the
    addresses it resolved and connects only to those, never by name again."""
    import asyncio

    from engine.egress import EgressProxy

    internal, _, internal_hits = _serve({})
    port = internal.server_address[1]

    def guard(url: str) -> None:
        if urlsplit(url).hostname == "127.0.0.1":
            raise ValueError("internal address")

    loop = asyncio.get_running_loop()
    real = loop.getaddrinfo

    async def rebinding(host, *args, **kwargs):  # the attacker's DNS: a public-looking name, an internal answer
        return await real("127.0.0.1" if host == "rebind.test" else host, *args, **kwargs)

    monkeypatch.setattr(loop, "getaddrinfo", rebinding)
    proxy = EgressProxy(guard)
    proxy_url = await proxy.start()
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", urlsplit(proxy_url).port)
        writer.write(f"GET http://rebind.test:{port}/secret HTTP/1.1\r\nHost: rebind.test\r\n\r\n".encode())
        await writer.drain()
        reply = await asyncio.wait_for(reader.read(), timeout=5)
        writer.close()
    finally:
        await proxy.close()
        internal.shutdown()
    assert b"ok" not in reply
    assert internal_hits == []
