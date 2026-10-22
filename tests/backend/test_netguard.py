"""SSRF guard: user-supplied URLs may not reach internal addresses on hosted servers."""

import asyncio

import httpx
import pytest

from backend.config import settings
from backend.netguard import BlockedTargetError, check_target, guard_request
from backend.services.url_analyzer import URLAnalyzerService


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
    import backend.main  # noqa: F401 - installs the guard
    from engine import browser

    assert browser._request_guard is check_target


async def test_a_browser_step_cannot_reach_an_internal_address(hosted):
    """Regression: a goto step used to bypass the guard (only httpx was covered)."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    import backend.main  # noqa: F401 - installs the guard
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
