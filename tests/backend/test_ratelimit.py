"""Per-user limit on expensive actions, and the cap on concurrent browsers."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from backend import auth
from backend.config import settings
from backend.main import app

TOKENS = {"token-alice": {"uid": "alice"}, "token-bob": {"uid": "bob"}}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_RUNS_PER_MINUTE", 3)
    monkeypatch.setattr(auth, "verify_token", lambda token: TOKENS[token])
    with patch("backend.api.workflow.URLAnalyzerService.analyze_live_website",
               new=AsyncMock(return_value={"success": True})):
        yield TestClient(app)


def analyze(client, token):
    return client.post("/api/workflow/analyze", json={"url": "https://example.org"},
                       headers={"Authorization": f"Bearer {token}"})


def test_runs_over_the_budget_get_429_with_retry_after(client):
    assert [analyze(client, "token-alice").status_code for _ in range(3)] == [200, 200, 200]
    over = analyze(client, "token-alice")
    assert over.status_code == 429
    assert 1 <= int(over.headers["Retry-After"]) <= 61
    assert "at most 3 per minute" in over.json()["detail"]


def test_each_user_has_their_own_budget(client):
    for _ in range(3):
        analyze(client, "token-alice")
    assert analyze(client, "token-alice").status_code == 429
    assert analyze(client, "token-bob").status_code == 200


def test_the_budget_is_shared_across_expensive_endpoints(client):
    for _ in range(3):
        analyze(client, "token-alice")
    scan = client.post("/api/security/scan", json={"target_url": "https://example.org"},
                       headers={"Authorization": "Bearer token-alice"})
    assert scan.status_code == 429


def test_zero_disables_the_limit(client, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_RUNS_PER_MINUTE", 0)
    assert all(analyze(client, "token-alice").status_code == 200 for _ in range(5))


async def test_concurrent_browser_sessions_are_capped(monkeypatch):
    from engine import browser

    slots = asyncio.Semaphore(1)
    monkeypatch.setattr(browser, "_browser_slots", lambda: slots)
    active, peak = 0, 0

    async def open_session():
        nonlocal active, peak
        async with browser.BrowserSession(browser.EngineConfig()):
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.2)
            active -= 1

    await asyncio.gather(open_session(), open_session(), open_session())
    assert peak == 1
    assert not slots.locked()  # every slot released


async def test_a_failed_launch_releases_its_slot(monkeypatch):
    from engine import browser

    slots = asyncio.Semaphore(1)
    monkeypatch.setattr(browser, "_browser_slots", lambda: slots)

    async def boom(self):
        raise RuntimeError("launch failed")

    monkeypatch.setattr(browser.BrowserSession, "_launch", boom)
    with pytest.raises(RuntimeError, match="launch failed"):
        async with browser.BrowserSession(browser.EngineConfig()):
            pass
    assert not slots.locked()
