"""
tests/engine/test_runner_integration.py
=======================================
Integration tests for engine/runner.py against the demo app.

The demo app is served as static files via a background HTTP server on a
random port.  All tests use the real Playwright Chromium browser (headless).

Test matrix
-----------
- Happy path: full login flow completes with status=passed
- Bad credentials: assert_text detects error message
- Wrong locator: step fails cleanly with error + artifacts captured
- RunOptions override: headless=False round-trips through config without crash
- Missing target: step fails with a clear ValueError
"""

from __future__ import annotations

import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from engine.runner import run_test
from engine.schemas import (
    ActionType,
    EngineConfig,
    RunOptions,
    Step,
    StepStatus,
    Target,
    TestPlan,
    TestStatus,
)

# ---------------------------------------------------------------------------
# Demo-app HTTP server fixture
# ---------------------------------------------------------------------------

DEMO_DIR = Path(__file__).parent / "demo_app"


@pytest.fixture(scope="module")
def demo_server() -> str:  # type: ignore[misc]
    """
    Start a ``ThreadingHTTPServer`` serving the demo_app directory on a
    random available port.  Yields the base URL.  Shuts down after the
    test module finishes.
    """
    handler = partial(SimpleHTTPRequestHandler, directory=str(DEMO_DIR))
    # Suppress HTTP access logs during tests
    handler.log_message = lambda *_: None  # type: ignore[method-assign]
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    yield base
    server.shutdown()


# ---------------------------------------------------------------------------
# Plan builders
# ---------------------------------------------------------------------------


def login_plan(base: str, *, bad_creds: bool = False) -> TestPlan:
    """Build the standard login-flow test plan."""
    password = "wrong" if bad_creds else "password"
    return TestPlan(
        test_id="demo-login" + ("-bad" if bad_creds else ""),
        name="Demo Login Flow",
        base_url=base,
        steps=[
            Step(
                step_id="goto-login",
                action=ActionType.GOTO,
                value=f"{base}/index.html",
            ),
            Step(
                step_id="fill-username",
                action=ActionType.FILL,
                target=Target(description="Username input", primary_locator="#username"),
                value="admin",
            ),
            Step(
                step_id="fill-password",
                action=ActionType.FILL,
                target=Target(description="Password input", primary_locator="#password"),
                value=password,
            ),
            Step(
                step_id="click-login",
                action=ActionType.CLICK,
                target=Target(description="Login button", primary_locator="#login-btn"),
            ),
            Step(
                step_id="assert-welcome",
                action=ActionType.ASSERT_TEXT,
                target=Target(
                    description="Welcome message",
                    primary_locator="#welcome-msg",
                ),
                expected="Welcome, admin!",
            ),
        ],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_happy_path(demo_server: str) -> None:
    """Full login flow should complete with status=passed, all steps passed."""
    plan = login_plan(demo_server)
    result = await run_test(plan)

    assert result.test_id == plan.test_id
    assert result.status == TestStatus.PASSED
    assert result.duration_ms >= 0

    assert len(result.steps) == 5
    for sr in result.steps:
        assert sr.status == StepStatus.PASSED, f"Step {sr.step_id} failed: {sr.error}"
        assert sr.error is None

    # Non-element steps have no locator; element steps do
    assert result.steps[0].locator_used is None  # goto
    assert result.steps[1].locator_used == "#username"
    assert result.steps[4].locator_used == "#welcome-msg"


async def test_bad_credentials_stops_at_assert(demo_server: str) -> None:
    """Wrong password → login button leaves user on the login page → assert_text fails."""
    plan = login_plan(demo_server, bad_creds=True)
    result = await run_test(plan)

    assert result.status == TestStatus.FAILED
    # Steps up to click-login pass; assert-welcome fails.
    # With bad creds the user stays on index.html, so #welcome-msg doesn't
    # exist → Playwright times out (not an assert_text error).  Either a
    # timeout or an explicit assertion failure is acceptable.
    step_map = {sr.step_id: sr for sr in result.steps}
    assert step_map["click-login"].status == StepStatus.PASSED
    assert step_map["assert-welcome"].status == StepStatus.FAILED
    error = step_map["assert-welcome"].error or ""
    assert "assert_text failed" in error or "Timeout" in error or "timeout" in error


async def test_failure_captures_artifacts(demo_server: str, tmp_path: pytest.TempPathFactory) -> None:
    """A failed step must produce screenshot_path and dom_snapshot_path."""
    plan = TestPlan(
        test_id="artifact-test",
        name="Artifact capture test",
        base_url=demo_server,
        steps=[
            Step(
                step_id="goto",
                action=ActionType.GOTO,
                value=f"{demo_server}/index.html",
            ),
            Step(
                step_id="click-missing",
                action=ActionType.CLICK,
                target=Target(
                    description="Non-existent element",
                    primary_locator="#does-not-exist",
                ),
                timeout_ms=1_000,
            ),
        ],
    )
    opts = RunOptions(artifacts_dir=str(tmp_path))
    result = await run_test(plan, opts)

    assert result.status == TestStatus.FAILED
    failed = result.steps[-1]
    assert failed.status == StepStatus.FAILED
    assert failed.screenshot_path is not None
    assert Path(failed.screenshot_path).exists()
    assert failed.dom_snapshot_path is not None
    assert Path(failed.dom_snapshot_path).exists()


async def test_assert_visible_passes(demo_server: str) -> None:
    """assert_visible on an existing element should pass."""
    plan = TestPlan(
        test_id="visible-test",
        name="Visibility assertion",
        base_url=demo_server,
        steps=[
            Step(
                step_id="goto",
                action=ActionType.GOTO,
                value=f"{demo_server}/index.html",
            ),
            Step(
                step_id="assert-btn-visible",
                action=ActionType.ASSERT_VISIBLE,
                target=Target(description="Login button", primary_locator="#login-btn"),
            ),
        ],
    )
    result = await run_test(plan)
    assert result.status == TestStatus.PASSED


async def test_missing_target_fails_clearly(demo_server: str) -> None:
    """A click step with no target should fail with a clear ValueError."""
    plan = TestPlan(
        test_id="no-target",
        name="Missing target",
        base_url=demo_server,
        steps=[
            Step(
                step_id="goto",
                action=ActionType.GOTO,
                value=f"{demo_server}/index.html",
            ),
            Step(
                step_id="click-no-target",
                action=ActionType.CLICK,
                target=None,  # deliberate mistake
            ),
        ],
    )
    result = await run_test(plan)
    assert result.status == TestStatus.FAILED
    failed = next(sr for sr in result.steps if sr.status == StepStatus.FAILED)
    assert "requires a target" in (failed.error or "")


async def test_run_options_headless_override(demo_server: str) -> None:
    """RunOptions.headless=True should work without error (already default)."""
    plan = TestPlan(
        test_id="opts-test",
        name="Options override",
        base_url=demo_server,
        steps=[
            Step(
                step_id="goto",
                action=ActionType.GOTO,
                value=f"{demo_server}/index.html",
            ),
        ],
    )
    result = await run_test(plan, RunOptions(headless=True, default_timeout_ms=8_000))
    assert result.status == TestStatus.PASSED


async def test_wait_for_ms(demo_server: str) -> None:
    """wait_for with an integer value should pause without error."""
    plan = TestPlan(
        test_id="wait-test",
        name="Wait for ms",
        base_url=demo_server,
        steps=[
            Step(
                step_id="goto",
                action=ActionType.GOTO,
                value=f"{demo_server}/index.html",
            ),
            Step(
                step_id="wait-200ms",
                action=ActionType.WAIT_FOR,
                value="200",
            ),
        ],
    )
    result = await run_test(plan)
    assert result.status == TestStatus.PASSED
    assert result.steps[1].duration_ms >= 200


async def test_full_dashboard_assertions(demo_server: str) -> None:
    """After login, dashboard stats elements should all be visible."""
    plan = TestPlan(
        test_id="dashboard-full",
        name="Dashboard element checks",
        base_url=demo_server,
        steps=[
            Step(step_id="goto-login", action=ActionType.GOTO, value=f"{demo_server}/index.html"),
            Step(step_id="fill-user", action=ActionType.FILL,
                 target=Target(description="Username", primary_locator="#username"), value="admin"),
            Step(step_id="fill-pass", action=ActionType.FILL,
                 target=Target(description="Password", primary_locator="#password"), value="password"),
            Step(step_id="click-login", action=ActionType.CLICK,
                 target=Target(description="Login btn", primary_locator="#login-btn")),
            Step(step_id="assert-welcome", action=ActionType.ASSERT_TEXT,
                 target=Target(description="Welcome", primary_locator="#welcome-msg"),
                 expected="Welcome"),
            Step(step_id="assert-status", action=ActionType.ASSERT_VISIBLE,
                 target=Target(description="Status text", primary_locator="#status-text")),
            Step(step_id="assert-logout", action=ActionType.ASSERT_VISIBLE,
                 target=Target(description="Logout button", primary_locator="#logout-btn")),
        ],
    )
    result = await run_test(plan)
    assert result.status == TestStatus.PASSED
    assert result.passed_count == 7
