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
