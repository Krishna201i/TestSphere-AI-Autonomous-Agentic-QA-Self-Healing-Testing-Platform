"""
tests/engine/test_healer_integration.py
=========================================
Integration tests for engine/healer.py — requires real Chromium.

Scenarios tested end-to-end via run_test():

A. Fallback healing
   - Target with broken primary + valid fallback → status=HEALED,
     strategy_used="fallback[0]", StepResult.healing populated.

B. Fingerprint healing
   - Capture a real fingerprint (successful run), then create a broken
     target with no fallbacks but the real fingerprint → fingerprint
     scoring should select the element automatically.

C. No-healing failure
   - Completely broken target (no fallbacks, no fingerprint) → status=FAILED,
     step.healing is a HealingReport with strategy_used="no_fingerprint".

D. HealingReport structure
   - Validate required fields, candidate structure, signal ranges.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from engine.runner import run_test
from engine.schemas import (
    ActionType,
    HealingReport,
    RunOptions,
    Step,
    StepStatus,
    Target,
    TestPlan,
    TestStatus,
)

DEMO_DIR = Path(__file__).parent / "demo_app"
LOGIN_URL = (DEMO_DIR / "index.html").as_uri()
DASHBOARD_URL = (DEMO_DIR / "dashboard.html").as_uri()


# ---------------------------------------------------------------------------
# Scenario A: fallback healing
# ---------------------------------------------------------------------------


async def test_fallback_heals_broken_click() -> None:
    """
    Primary locator is wrong; fallback is correct.
    run_test should return HEALED with the fallback locator used.
    """
    target = Target(
        description="Login button (broken primary)",
        primary_locator="#wrong-login-btn",  # does not exist
        fallback_locators=["#login-btn"],     # correct fallback
    )
    plan = TestPlan(
        test_id="fallback-heal",
        name="Fallback healing test",
        base_url=LOGIN_URL,
        steps=[
            Step(step_id="goto", action=ActionType.GOTO, value=LOGIN_URL),
            Step(
                step_id="click-healed",
                action=ActionType.ASSERT_VISIBLE,
                target=target,
                timeout_ms=3_000,
            ),
        ],
    )
    result = await run_test(plan, RunOptions(headless=True))
    assert result.status == TestStatus.HEALED

    healed_step = next(s for s in result.steps if s.step_id == "click-healed")
    assert healed_step.status == StepStatus.HEALED
    assert healed_step.healing is not None
    assert healed_step.healing.strategy_used == "fallback[0]"
    assert healed_step.healing.selected_locator == "#login-btn"
    assert healed_step.healing.confidence == pytest.approx(1.0)


async def test_fallback_tries_in_rank_order() -> None:
    """
    First fallback is wrong, second is correct → strategy_used="fallback[1]".
    """
    target = Target(
        description="Username (multi-fallback)",
        primary_locator="#no-such-element",
        fallback_locators=["#also-wrong", "#username"],
    )
    plan = TestPlan(
        test_id="multi-fallback",
        name="Multi-fallback heal",
        base_url=LOGIN_URL,
        steps=[
            Step(step_id="goto", action=ActionType.GOTO, value=LOGIN_URL),
            Step(
                step_id="assert-user",
                action=ActionType.ASSERT_VISIBLE,
                target=target,
                timeout_ms=3_000,
            ),
        ],
    )
    result = await run_test(plan, RunOptions(headless=True))
    assert result.status == TestStatus.HEALED
    healed = next(s for s in result.steps if s.step_id == "assert-user")
    assert healed.healing is not None
    assert healed.healing.strategy_used == "fallback[1]"
    assert healed.healing.selected_locator == "#username"


async def test_fallback_heal_preserves_original_locator_in_report() -> None:
    target = Target(
        description="Password field",
        primary_locator="#bad-locator",
        fallback_locators=["#password"],
    )
    plan = TestPlan(
        test_id="fallback-report",
        name="Fallback report test",
        base_url=LOGIN_URL,
        steps=[
            Step(step_id="goto", action=ActionType.GOTO, value=LOGIN_URL),
            Step(
                step_id="assert-pass",
                action=ActionType.ASSERT_VISIBLE,
                target=target,
                timeout_ms=3_000,
            ),
        ],
    )
    result = await run_test(plan, RunOptions(headless=True))
    healed = next(s for s in result.steps if s.step_id == "assert-pass")
    assert healed.healing is not None
    assert healed.healing.original_locator == "#bad-locator"


# ---------------------------------------------------------------------------
# Scenario B: fingerprint healing
# ---------------------------------------------------------------------------


async def _capture_fingerprint_for(locator: str) -> "Target":
    """Helper: run a successful fill to get target.fingerprint populated."""
    target = Target(description="fp capture", primary_locator=locator)
    plan = TestPlan(
        test_id="fp-capture",
        name="Fingerprint capture",
        base_url=LOGIN_URL,
        steps=[
            Step(step_id="goto", action=ActionType.GOTO, value=LOGIN_URL),
            Step(step_id="act", action=ActionType.ASSERT_VISIBLE, target=target, timeout_ms=3_000),
        ],
    )
    await run_test(plan, RunOptions(headless=True))
    return target


async def test_fingerprint_healing_selects_element() -> None:
    """
    Real fingerprint captured from #login-btn.
    New target uses broken locator + no fallbacks + real fingerprint.
    Fingerprint scoring should select #login-btn automatically.
    """
    # Capture real fingerprint
    good_target = await _capture_fingerprint_for("#login-btn")
    assert good_target.fingerprint is not None, "Fingerprint not captured in setup run"

    # Create broken target with only the fingerprint
    broken_target = Target(
        description="Login btn (fingerprint only)",
        primary_locator="#totally-broken",
        fallback_locators=[],
        fingerprint=good_target.fingerprint,
    )
    plan = TestPlan(
        test_id="fp-heal",
        name="Fingerprint healing test",
        base_url=LOGIN_URL,
        steps=[
            Step(step_id="goto", action=ActionType.GOTO, value=LOGIN_URL),
            Step(
                step_id="assert-btn",
                action=ActionType.ASSERT_VISIBLE,
                target=broken_target,
                timeout_ms=3_000,
            ),
        ],
    )
    # Low threshold to ensure auto-accept
    result = await run_test(plan, RunOptions(headless=True, heal_threshold=0.3))
    assert result.status == TestStatus.HEALED
    healed = next(s for s in result.steps if s.step_id == "assert-btn")
    assert healed.status == StepStatus.HEALED
    assert healed.healing is not None
    assert healed.healing.strategy_used == "fingerprint"
    assert healed.healing.selected_locator is not None


async def test_fingerprint_healing_candidates_include_target() -> None:
    """Candidates list must include the actual element (#login-btn)."""
    good = await _capture_fingerprint_for("#login-btn")
    broken = Target(
        description="Login btn fp-only",
        primary_locator="#broken",
        fallback_locators=[],
        fingerprint=good.fingerprint,
    )
    plan = TestPlan(
        test_id="fp-cands",
        name="Fingerprint candidates",
        base_url=LOGIN_URL,
        steps=[
            Step(step_id="goto", action=ActionType.GOTO, value=LOGIN_URL),
            Step(step_id="assert", action=ActionType.ASSERT_VISIBLE, target=broken, timeout_ms=3_000),
        ],
    )
    result = await run_test(plan, RunOptions(headless=True, heal_threshold=0.01))
    step = next(s for s in result.steps if s.step_id == "assert")
    assert step.healing is not None
    locators = [c.locator for c in step.healing.candidates]
    assert "#login-btn" in locators


async def test_fingerprint_candidates_sorted_best_first() -> None:
    """Candidates must be sorted by score descending."""
    good = await _capture_fingerprint_for("#login-btn")
    broken = Target(
        description="Login btn fp-only",
        primary_locator="#broken",
        fallback_locators=[],
        fingerprint=good.fingerprint,
    )
    plan = TestPlan(
        test_id="fp-sorted",
        name="Fingerprint sort test",
        base_url=LOGIN_URL,
        steps=[
            Step(step_id="goto", action=ActionType.GOTO, value=LOGIN_URL),
            Step(step_id="assert", action=ActionType.ASSERT_VISIBLE, target=broken, timeout_ms=3_000),
        ],
    )
    result = await run_test(plan, RunOptions(headless=True, heal_threshold=0.01))
    step = next(s for s in result.steps if s.step_id == "assert")
    scores = [c.score for c in step.healing.candidates]
    assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# Scenario C: no-healing failure
# ---------------------------------------------------------------------------


async def test_no_fingerprint_no_fallback_fails() -> None:
    """
    Completely broken target with no healing data → step FAILED,
    HealingReport present with strategy_used='no_fingerprint'.
    """
    target = Target(
        description="Completely broken",
        primary_locator="#i-dont-exist",
        fallback_locators=[],
        fingerprint=None,
    )
    plan = TestPlan(
        test_id="no-heal",
        name="No healing test",
        base_url=LOGIN_URL,
        steps=[
            Step(step_id="goto", action=ActionType.GOTO, value=LOGIN_URL),
            Step(
                step_id="assert-broken",
                action=ActionType.ASSERT_VISIBLE,
                target=target,
                timeout_ms=2_000,
            ),
        ],
    )
    result = await run_test(plan, RunOptions(headless=True))
    assert result.status == TestStatus.FAILED
    failed_step = next(s for s in result.steps if s.step_id == "assert-broken")
    assert failed_step.status == StepStatus.FAILED
    assert failed_step.healing is not None
    assert failed_step.healing.strategy_used == "no_fingerprint"
    assert failed_step.healing.selected_locator is None


async def test_below_threshold_returns_failed_with_candidates() -> None:
    """
    Fingerprint captured from the dashboard's #logout-btn, then searched on
    the login page at threshold=0.95.  The login page has no logout button,
    so all candidates score well below 0.95 → FAILED with candidates reported.
    """
    # Step 1: capture a real fingerprint from the dashboard page
    logout_target = Target(description="Logout", primary_locator="#logout-btn")
    setup = TestPlan(
        test_id="logout-capture",
        name="Capture logout fingerprint",
        base_url=DASHBOARD_URL,
        steps=[
            Step(step_id="goto", action=ActionType.GOTO, value=DASHBOARD_URL),
            Step(
                step_id="assert",
                action=ActionType.ASSERT_VISIBLE,
                target=logout_target,
                timeout_ms=3_000,
            ),
        ],
    )
    await run_test(setup, RunOptions(headless=True))
    assert logout_target.fingerprint is not None, "Setup: fingerprint not captured"

    # Step 2: search for the logout fingerprint on the login page
    # Best candidate is #login-btn but id/testid/text all differ → score ~0.4
    broken = Target(
        description="Logout btn (wrong page)",
        primary_locator="#logout-btn",   # doesn't exist on login page
        fallback_locators=[],
        fingerprint=logout_target.fingerprint,
    )
    plan = TestPlan(
        test_id="high-threshold",
        name="High threshold test",
        base_url=LOGIN_URL,
        steps=[
            Step(step_id="goto", action=ActionType.GOTO, value=LOGIN_URL),
            Step(
                step_id="assert-high",
                action=ActionType.ASSERT_VISIBLE,
                target=broken,
                timeout_ms=3_000,
            ),
        ],
    )
    # threshold=0.95: login-page buttons score ~0.4 against a logout fingerprint
    result = await run_test(plan, RunOptions(headless=True, heal_threshold=0.95))
    step = next(s for s in result.steps if s.step_id == "assert-high")
    assert step.status == StepStatus.FAILED
    assert step.healing is not None
    assert step.healing.selected_locator is None
    assert len(step.healing.candidates) > 0  # candidates still reported


# ---------------------------------------------------------------------------
# Scenario D: HealingReport structure validation
# ---------------------------------------------------------------------------


async def test_healing_report_is_HealingReport_instance() -> None:
    target = Target(
        description="Btn",
        primary_locator="#broken",
        fallback_locators=["#login-btn"],
    )
    plan = TestPlan(
        test_id="report-type",
        name="Report type test",
        base_url=LOGIN_URL,
        steps=[
            Step(step_id="goto", action=ActionType.GOTO, value=LOGIN_URL),
            Step(step_id="s", action=ActionType.ASSERT_VISIBLE, target=target, timeout_ms=3_000),
        ],
    )
    result = await run_test(plan, RunOptions(headless=True))
    step = next(s for s in result.steps if s.step_id == "s")
    assert isinstance(step.healing, HealingReport)


async def test_healing_candidate_signals_in_range() -> None:
    """All HealingSignal values must be in [0, 1]."""
    good = await _capture_fingerprint_for("#login-btn")
    broken = Target(
        description="Login btn fp-only",
        primary_locator="#broken",
        fallback_locators=[],
        fingerprint=good.fingerprint,
    )
    plan = TestPlan(
        test_id="signal-range",
        name="Signal range test",
        base_url=LOGIN_URL,
        steps=[
            Step(step_id="goto", action=ActionType.GOTO, value=LOGIN_URL),
            Step(step_id="s", action=ActionType.ASSERT_VISIBLE, target=broken, timeout_ms=3_000),
        ],
    )
    result = await run_test(plan, RunOptions(headless=True, heal_threshold=0.01))
    step = next(s for s in result.steps if s.step_id == "s")
    for cand in step.healing.candidates:
        sig = cand.signals
        for val in [sig.attribute, sig.text, sig.position, sig.structure]:
            assert 0.0 <= val <= 1.0, f"Signal out of range: {val}"
        assert 0.0 <= cand.score <= 1.0, f"Score out of range: {cand.score}"


async def test_healing_report_confidence_matches_best_candidate() -> None:
    """confidence must equal the top candidate's score."""
    good = await _capture_fingerprint_for("#login-btn")
    broken = Target(
        description="Login btn",
        primary_locator="#broken",
        fallback_locators=[],
        fingerprint=good.fingerprint,
    )
    plan = TestPlan(
        test_id="confidence-check",
        name="Confidence check",
        base_url=LOGIN_URL,
        steps=[
            Step(step_id="goto", action=ActionType.GOTO, value=LOGIN_URL),
            Step(step_id="s", action=ActionType.ASSERT_VISIBLE, target=broken, timeout_ms=3_000),
        ],
    )
    result = await run_test(plan, RunOptions(headless=True, heal_threshold=0.01))
    step = next(s for s in result.steps if s.step_id == "s")
    report = step.healing
    if report.candidates:
        assert report.confidence == pytest.approx(report.candidates[0].score, abs=0.001)
