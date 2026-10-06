"""
tests/engine/test_detector_integration.py
==========================================
Integration tests for engine/detector.py — requires real Chromium.

Tests validate:
- build_fingerprint extracts correct tag / id / text / placeholder / data-testid
- build_fingerprint captures bounding box
- build_fingerprint builds parent_chain with ancestor info
- build_fingerprint returns None for non-existent elements
- extract_candidates returns valid locator strings
- extract_candidates honours max_candidates cap
- extract_candidates includes known elements (login-btn, username, password)
- runner end-to-end: after run_test(), target.fingerprint is populated and
  target.fallback_locators is enriched
"""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.browser import BrowserSession
from engine.detector import build_fingerprint, extract_candidates
from engine.runner import run_test
from engine.schemas import (
    ActionType,
    ElementFingerprint,
    EngineConfig,
    RunOptions,
    Step,
    Target,
    TestPlan,
    TestStatus,
)

DEMO_DIR = Path(__file__).parent / "demo_app"
LOGIN_URL = (DEMO_DIR / "index.html").as_uri()
DASHBOARD_URL = (DEMO_DIR / "dashboard.html").as_uri()


# ---------------------------------------------------------------------------
# Shared browser page fixture (function-scoped for isolation)
# ---------------------------------------------------------------------------


@pytest.fixture()
async def demo_page():
    """Fresh Playwright page pointing at the demo login page."""
    config = EngineConfig(headless=True)
    async with BrowserSession(config) as session:
        page = await session.new_page()
        await page.goto(LOGIN_URL)
        yield page


# ---------------------------------------------------------------------------
# build_fingerprint — correctness
# ---------------------------------------------------------------------------


async def test_fingerprint_button_tag(demo_page) -> None:
    fp = await build_fingerprint(demo_page, "#login-btn")
    assert fp is not None
    assert fp.tag == "button"


async def test_fingerprint_button_id(demo_page) -> None:
    fp = await build_fingerprint(demo_page, "#login-btn")
    assert fp is not None
    assert fp.id == "login-btn"


async def test_fingerprint_button_text(demo_page) -> None:
    fp = await build_fingerprint(demo_page, "#login-btn")
    assert fp is not None
    assert fp.text == "Log in"


async def test_fingerprint_input_tag(demo_page) -> None:
    fp = await build_fingerprint(demo_page, "#username")
    assert fp is not None
    assert fp.tag == "input"


async def test_fingerprint_input_placeholder(demo_page) -> None:
    fp = await build_fingerprint(demo_page, "#username")
    assert fp is not None
    assert fp.placeholder == "admin"


async def test_fingerprint_input_name(demo_page) -> None:
    fp = await build_fingerprint(demo_page, "#username")
    assert fp is not None
    assert fp.name == "username"


async def test_fingerprint_data_testid_in_attributes(demo_page) -> None:
    fp = await build_fingerprint(demo_page, "#username")
    assert fp is not None
    assert fp.attributes.get("data-testid") == "username-input"


async def test_fingerprint_bounding_box_present(demo_page) -> None:
    fp = await build_fingerprint(demo_page, "#login-btn")
    assert fp is not None
    assert fp.bounding_box is not None
    assert fp.bounding_box.width > 0
    assert fp.bounding_box.height > 0


async def test_fingerprint_parent_chain_non_empty(demo_page) -> None:
    fp = await build_fingerprint(demo_page, "#login-btn")
    assert fp is not None
    assert len(fp.parent_chain) >= 1


async def test_fingerprint_parent_chain_contains_form(demo_page) -> None:
    fp = await build_fingerprint(demo_page, "#login-btn")
    assert fp is not None
    assert any("form" in ancestor for ancestor in fp.parent_chain)


async def test_fingerprint_sibling_index_is_int(demo_page) -> None:
    fp = await build_fingerprint(demo_page, "#login-btn")
    assert fp is not None
    assert isinstance(fp.sibling_index, int)
    assert fp.sibling_index >= 0


async def test_fingerprint_classes_is_list(demo_page) -> None:
    fp = await build_fingerprint(demo_page, "#login-btn")
    assert fp is not None
    assert isinstance(fp.classes, list)


async def test_fingerprint_returns_none_for_missing_element(demo_page) -> None:
    fp = await build_fingerprint(demo_page, "#totally-does-not-exist")
    assert fp is None


async def test_fingerprint_via_testid_locator(demo_page) -> None:
    """build_fingerprint works with data-testid locators, not just #id."""
    fp = await build_fingerprint(demo_page, '[data-testid="password-input"]')
    assert fp is not None
    assert fp.tag == "input"
    assert fp.id == "password"


async def test_fingerprint_is_ElementFingerprint_instance(demo_page) -> None:
    fp = await build_fingerprint(demo_page, "#login-btn")
    assert isinstance(fp, ElementFingerprint)


# ---------------------------------------------------------------------------
# extract_candidates — correctness
# ---------------------------------------------------------------------------


async def test_extract_candidates_returns_list(demo_page) -> None:
    fp = ElementFingerprint(tag="button")
    candidates = await extract_candidates(demo_page, fp, max_candidates=10)
    assert isinstance(candidates, list)
    assert len(candidates) > 0


async def test_extract_candidates_are_strings(demo_page) -> None:
    fp = ElementFingerprint(tag="input")
    candidates = await extract_candidates(demo_page, fp, max_candidates=10)
    assert all(isinstance(c, str) and c for c in candidates)


async def test_extract_candidates_includes_login_btn(demo_page) -> None:
    fp = ElementFingerprint(tag="button")
    candidates = await extract_candidates(demo_page, fp, max_candidates=20)
    assert "#login-btn" in candidates


async def test_extract_candidates_includes_username_input(demo_page) -> None:
    fp = ElementFingerprint(tag="input")
    candidates = await extract_candidates(demo_page, fp, max_candidates=20)
    assert "#username" in candidates


async def test_extract_candidates_includes_password_input(demo_page) -> None:
    fp = ElementFingerprint(tag="input")
    candidates = await extract_candidates(demo_page, fp, max_candidates=20)
    assert "#password" in candidates


async def test_extract_candidates_max_respected(demo_page) -> None:
    fp = ElementFingerprint(tag="input")
    candidates = await extract_candidates(demo_page, fp, max_candidates=2)
    assert len(candidates) <= 2


async def test_extract_candidates_deduplicated(demo_page) -> None:
    fp = ElementFingerprint(tag="button")
    candidates = await extract_candidates(demo_page, fp, max_candidates=20)
    assert len(candidates) == len(set(candidates))


async def test_extract_candidates_on_dashboard(demo_page) -> None:
    """Candidates on the dashboard should include #logout-btn."""
    await demo_page.goto(DASHBOARD_URL)
    fp = ElementFingerprint(tag="button")
    candidates = await extract_candidates(demo_page, fp, max_candidates=20)
    assert "#logout-btn" in candidates


# ---------------------------------------------------------------------------
# runner integration: target enrichment after run_test()
# ---------------------------------------------------------------------------


async def test_run_test_enriches_fingerprint() -> None:
    """After a successful run, Target.fingerprint should be populated."""
    username_target = Target(
        description="Username input",
        primary_locator="#username",
    )
    plan = TestPlan(
        test_id="enrich-test",
        name="Enrichment test",
        base_url=LOGIN_URL,
        steps=[
            Step(step_id="goto", action=ActionType.GOTO, value=LOGIN_URL),
            Step(
                step_id="fill-user",
                action=ActionType.FILL,
                target=username_target,
                value="admin",
            ),
        ],
    )
    result = await run_test(plan, RunOptions(headless=True))
    assert result.status == TestStatus.PASSED
    # The Target object was enriched in place
    assert username_target.fingerprint is not None
    assert username_target.fingerprint.tag == "input"
    assert username_target.fingerprint.id == "username"


async def test_run_test_enriches_fallback_locators() -> None:
    """After a successful fill, Target.fallback_locators should be non-empty."""
    password_target = Target(
        description="Password input",
        primary_locator="#password",
    )
    plan = TestPlan(
        test_id="fallback-test",
        name="Fallback enrichment test",
        base_url=LOGIN_URL,
        steps=[
            Step(step_id="goto", action=ActionType.GOTO, value=LOGIN_URL),
            Step(
                step_id="fill-pass",
                action=ActionType.FILL,
                target=password_target,
                value="password",
            ),
        ],
    )
    result = await run_test(plan, RunOptions(headless=True))
    assert result.status == TestStatus.PASSED
    assert len(password_target.fallback_locators) > 0
    # Locators should be ranked: any data-testid locator should come first
    if any("data-testid" in l for l in password_target.fallback_locators):
        assert "data-testid" in password_target.fallback_locators[0]


async def test_run_test_fingerprint_attributes_include_testid() -> None:
    """Fingerprint attributes dict must include data-testid when present in HTML."""
    target = Target(description="Username", primary_locator="#username")
    plan = TestPlan(
        test_id="testid-attr-test",
        name="Testid attribute test",
        base_url=LOGIN_URL,
        steps=[
            Step(step_id="goto", action=ActionType.GOTO, value=LOGIN_URL),
            Step(step_id="fill", action=ActionType.FILL, target=target, value="admin"),
        ],
    )
    await run_test(plan, RunOptions(headless=True))
    assert target.fingerprint is not None
    assert target.fingerprint.attributes.get("data-testid") == "username-input"
