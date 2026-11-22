"""SSRF guard: user-supplied URLs may not reach internal addresses on hosted servers."""

import asyncio

import httpx
import pytest

from app.config import settings
from app.netguard import BlockedTargetError, check_target, guard_request
from app.services.url_analyzer import URLAnalyzerService


@pytest.fixture
def hosted(monkeypatch):
    monkeypatch.setattr(settings, "ALLOW_PRIVATE_TARGETS", False)


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:8000/", "http://localhost/admin", "http://169.254.169.254/latest/meta-data/",
    "http://10.0.0.5/", "http://192.168.1.1/", "http://[::1]/", "http://0.0.0.0/",
])
def test_internal_addresses_are_refused_on_hosted_servers(hosted, url):
    with pytest.raises(BlockedTargetError, match="private or internal|does not resolve"):
        check_target(url)


def test_non_http_schemes_are_refused_everywhere():
    for url in ("file:///etc/passwd", "ftp://example.com/", "gopher://x"):
        with pytest.raises(BlockedTargetError, match="Only http"):
            check_target(url)


def test_local_development_may_test_localhost(monkeypatch):
    monkeypatch.setattr(settings, "ALLOW_PRIVATE_TARGETS", True)
    check_target("http://127.0.0.1:3000/")  # no error


def test_redirect_hops_are_checked(hosted):
    request = httpx.Request("GET", "http://169.254.169.254/latest/")
    with pytest.raises(BlockedTargetError):
        asyncio.run(guard_request(request))


def test_analyzer_reports_a_blocked_target_instead_of_fetching_it(hosted):
    result = asyncio.run(URLAnalyzerService.analyze_live_website("http://127.0.0.1:9/"))
    assert result["success"] is False
    assert "private or internal" in result["error"]


def test_the_server_holds_browser_runs_to_the_same_policy():
    import app.main  # noqa: F401 - installs the guard
    from engine import browser

    assert browser._request_guard is check_target


async def test_a_browser_step_cannot_reach_an_internal_address(hosted):
    """Regression: a goto step used to bypass the guard (only httpx was covered)."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    import app.main  # noqa: F401 - installs the guard
    from engine.runner import run_test
    from engine.schemas import ActionType, Step, StepStatus, TestPlan

    hits = []

    class Internal(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            hits.append(self.path)
            self.send_response(200)
            self.end_headers()

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Internal)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/admin-secret"
    try:
        result = await run_test(TestPlan(test_id="ssrf", name="ssrf", base_url=url,
                                         steps=[Step(step_id="s0", action=ActionType.GOTO, value=url)]))
    finally:
        server.shutdown()
    assert result.steps[0].status == StepStatus.FAILED
    assert hits == []


@pytest.mark.parametrize(("address", "blocked"), [
    ("64:ff9b::a675:5e4e", False),   # NAT64 form of a public site (seen on IPv6-only networks)
    ("64:ff9b::7f00:1", True),       # NAT64 form of 127.0.0.1
    ("64:ff9b::a9fe:a9fe", True),    # NAT64 form of 169.254.169.254
    ("::ffff:127.0.0.1", True),      # IPv4-mapped loopback
    ("::ffff:8.8.8.8", False),
    ("2606:4700::1111", False),      # plain public IPv6
    ("fd00::1", True),               # unique local
])
def test_ipv6_forms_are_judged_by_the_address_they_reach(address, blocked):
    import ipaddress

    from app.netguard import _blocked

    assert _blocked(ipaddress.ip_address(address)) is blocked


# ── PinnedTransport: DNS rebinding ─────────────────────────────


@pytest.fixture
def fake_dns(monkeypatch):
    """Resolve names from a table; each name's answers are used in order (rebinding)."""
    import socket

    answers: dict[str, list[list[str]]] = {}
    calls: list[str] = []

    def getaddrinfo(host, port, *args, **kwargs):
        calls.append(host)
        queue = answers[host]
        ips = queue.pop(0) if len(queue) > 1 else queue[0]
        return [(socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))
                for ip in ips]

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    return answers, calls


def _pinned_with_recorder(responses=None):
    """A PinnedTransport whose real connection is replaced by a recorder."""
    from app.netguard import PinnedTransport

    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return (responses or {}).get(request.extensions["sni_hostname"], httpx.Response(200, text="ok"))

    transport = PinnedTransport()
    transport._inner = httpx.MockTransport(handler)
    return transport, sent


async def test_pinned_transport_connects_to_the_address_it_checked(hosted, fake_dns):
    answers, calls = fake_dns
    # First answer is public, every later one internal: a rebinding attack
    answers["rebind.test"] = [["93.184.215.14"], ["169.254.169.254"]]
    transport, sent = _pinned_with_recorder()
    async with httpx.AsyncClient(transport=transport) as client:
        response = await client.get("https://rebind.test/page?x=1")
    assert response.status_code == 200
    assert calls == ["rebind.test"]  # resolved once, never again to connect
    assert sent[0].url.host == "93.184.215.14" and sent[0].url.path == "/page"
    assert sent[0].headers["host"] == "rebind.test"  # the site still sees its own name
    assert sent[0].extensions["sni_hostname"] == "rebind.test"  # and TLS verifies it


async def test_pinned_transport_refuses_a_name_with_any_internal_address(hosted, fake_dns):
    answers, _ = fake_dns
    answers["mixed.test"] = [["93.184.215.14", "10.0.0.7"]]
    transport, sent = _pinned_with_recorder()
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(BlockedTargetError, match="10.0.0.7"):
            await client.get("http://mixed.test/")
    assert sent == []


async def test_pinned_transport_checks_every_redirect_hop(hosted, fake_dns):
    answers, _ = fake_dns
    answers["public.test"] = [["93.184.215.14"]]
    answers["metadata.test"] = [["169.254.169.254"]]
    redirect = httpx.Response(302, headers={"Location": "http://metadata.test/latest/meta-data/"})
    transport, sent = _pinned_with_recorder({"public.test": redirect})
    async with httpx.AsyncClient(transport=transport, follow_redirects=True) as client:
        with pytest.raises(BlockedTargetError, match="169.254.169.254"):
            await client.get("http://public.test/")
    assert [r.extensions["sni_hostname"] for r in sent] == ["public.test"]


async def test_pinned_transport_refuses_internal_ip_literals(hosted):
    transport, sent = _pinned_with_recorder()
    async with httpx.AsyncClient(transport=transport) as client:
        for url in ("http://169.254.169.254/latest/", "http://[::1]:8000/", "http://10.1.2.3/"):
            with pytest.raises(BlockedTargetError):
                await client.get(url)
    assert sent == []


async def test_pinned_transport_tries_the_next_checked_address_when_one_is_unreachable(hosted, fake_dns):
    answers, _ = fake_dns
    answers["dual.test"] = [["93.184.215.14", "2606:4700::1111"]]  # dead IPv4 route, working IPv6
    from app.netguard import PinnedTransport

    tried: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        tried.append(request.url.host)
        if request.url.host == "93.184.215.14":
            raise httpx.ConnectTimeout("no route", request=request)
        return httpx.Response(200)

    transport = PinnedTransport()
    transport._inner = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        assert (await client.get("https://dual.test/")).status_code == 200
    assert tried == ["93.184.215.14", "2606:4700::1111"]
