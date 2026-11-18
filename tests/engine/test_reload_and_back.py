"""
The engine's reload and go_back actions, in Chromium against the generation
eval's site (tests/fixtures/auth_app.py): what a person does to check that a
session survives a reload and that logging out really ends it.
"""

from __future__ import annotations

import pytest

from engine.runner import run_test
from engine.schemas import ActionType, RunOptions, Step, Target, TestPlan, TestStatus
from tests.fixtures.auth_app import USER_EMAIL, USER_PASSWORD, AuthApp


@pytest.fixture
def site():
    app = AuthApp()
    base = app.start()
    try:
        yield app, base
    finally:
        app.stop()


def _target(selector: str) -> Target:
    return Target(description=selector, primary_locator=selector)


def _sign_in(base: str) -> list[Step]:
    return [
        Step(step_id="open", action=ActionType.GOTO, value=f"{base}/login"),
        Step(step_id="email", action=ActionType.FILL, target=_target("#email"), value=USER_EMAIL),
        Step(step_id="password", action=ActionType.FILL, target=_target("#password"), value=USER_PASSWORD),
        Step(step_id="submit", action=ActionType.CLICK, target=_target("button:has-text('Sign in')")),
        Step(step_id="signed-in", action=ActionType.ASSERT_URL, expected="/account"),
    ]


async def _run(base: str, steps: list[Step]):
    plan = TestPlan(test_id="session", name="session", base_url=base, steps=steps)
    return await run_test(plan, RunOptions(headless=True, tracing_enabled=False, min_action_timeout_ms=2000))


async def test_reload_keeps_the_session_and_back_returns_to_the_last_page(site):
    _, base = site
    result = await _run(base, [
        *_sign_in(base),
        Step(step_id="reload", action=ActionType.RELOAD),
        Step(step_id="still-in", action=ActionType.ASSERT_URL, expected="/account"),
        Step(step_id="logout", action=ActionType.CLICK, target=_target("a:has-text('Log out')")),
        Step(step_id="at-login", action=ActionType.ASSERT_URL, expected="/login"),
        Step(step_id="back", action=ActionType.GO_BACK),
        Step(step_id="reload-again", action=ActionType.RELOAD),
        Step(step_id="signed-out", action=ActionType.ASSERT_URL, expected="/login"),  # the server sent us back
    ])
    assert result.status == TestStatus.PASSED, [(s.step_id, s.error) for s in result.steps if s.error]


async def test_a_reload_that_loses_the_session_fails_the_check_after_it(site):
    app, base = site
    app.set_mutant("session-lost-on-reload")
    result = await _run(base, [
        *_sign_in(base),
        Step(step_id="reload", action=ActionType.RELOAD),
        Step(step_id="still-in", action=ActionType.ASSERT_URL, expected="/account"),
    ])
    assert result.status == TestStatus.FAILED and result.steps[-1].step_id == "still-in"


async def test_back_with_no_earlier_page_fails_clearly(site):
    _, base = site
    result = await _run(base, [
        Step(step_id="open", action=ActionType.GOTO, value=f"{base}/login"),
        Step(step_id="back", action=ActionType.GO_BACK),
    ])
    assert result.status == TestStatus.FAILED
    assert "no earlier page" in (result.steps[-1].error or "")
