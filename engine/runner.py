"""
engine/runner.py
================
Sequential test step executor — the core of the TestSphere-AI engine.

Public API
----------
    async def run_test(plan: TestPlan, options: RunOptions | None = None) -> TestResult

Design notes
------------
- Steps execute **sequentially**; execution stops on the first FAILED step
  (a broken goto or click makes all subsequent steps meaningless).
- Console logs and network errors are collected *per step* via Playwright
  event listeners that are attached/removed around each action.
- Screenshots and DOM snapshots are written on **every failure** via
  engine/artifacts.py; they are also captured for HEALED steps so the
  healing event is fully auditable.
- Healing is **not** wired in this module; that comes in Step 4 (healer.py).
  The step executor has a hook (``_attempt_healing``) that returns ``None``
  in this version and is replaced by the real implementation later.
- No database access; all output is returned as a ``TestResult`` value.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    from playwright.async_api import Error as PlaywrightError
    from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError
    PLAYWRIGHT_INSTALLED = True
except ImportError:
    class PlaywrightError(Exception):  # type: ignore
        pass
    class PlaywrightTimeoutError(Exception):  # type: ignore
        pass
    Page = object  # type: ignore
    PLAYWRIGHT_INSTALLED = False

from .artifacts import write_dom_snapshot, write_screenshot
from .browser import BrowserSession
from .detector import build_fingerprint, extract_candidates  # noqa: F401 (extract_candidates used by healer)
from .locators import generate_locators, rank_locators
from .schemas import (
    ActionType,
    EngineConfig,
    HealingReport,
    RunOptions,
    Step,
    StepResult,
    StepStatus,
    Target,
    TestPlan,
    TestResult,
    TestStatus,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def run_test(
    plan: TestPlan,
    options: RunOptions | None = None,
) -> TestResult:
    """
    Execute *plan* sequentially and return a ``TestResult``.

    Parameters
    ----------
    plan:
        The test specification (steps, base_url, etc.).
    options:
        Optional per-run overrides for ``EngineConfig``.  Any ``None`` field
        inherits the engine default.

    Returns
    -------
    TestResult
        Always returned — never raises.  Individual step failures are
        captured inside ``StepResult.error``.
    """
    config = options.merged(EngineConfig()) if options else EngineConfig()
    started_at = datetime.now(timezone.utc)
    wall_start = time.monotonic()

    step_results: list[StepResult] = []
    artifacts_dir = str(Path(config.artifacts_dir) / plan.test_id)

    try:
        async with BrowserSession(config, trace_path=f"{artifacts_dir}/_trace.zip") as session:
            page = await session.new_page()

            for step in plan.steps:
                log.info("[%s] Executing step %s (%s)", plan.test_id, step.step_id, step.action)
                result = await _execute_step(page, step, config, plan.test_id, artifacts_dir)
                step_results.append(result)
                if result.status == StepStatus.FAILED:
                    log.warning(
                        "[%s] Step %s FAILED — stopping run: %s",
                        plan.test_id,
                        step.step_id,
                        result.error,
                    )
                    break
    except Exception as exc:
        log.error("[%s] Browser session error: %s", plan.test_id, exc)
        step_results.append(
            StepResult(
                step_id=plan.steps[0].step_id if plan.steps else "step_0",
                status=StepStatus.FAILED,
                duration_ms=0,
                error=f"Browser execution error: {exc}",
            )
        )

    duration_ms = int((time.monotonic() - wall_start) * 1000)
    overall = _aggregate_status(step_results)

    return TestResult(
        test_id=plan.test_id,
        status=overall,
        started_at=started_at,
        duration_ms=duration_ms,
        steps=step_results,
        artifacts_dir=artifacts_dir,
    )


# ---------------------------------------------------------------------------
# Step executor
# ---------------------------------------------------------------------------


async def _execute_step(
    page: Page,
    step: Step,
    config: EngineConfig,
    test_id: str,
    artifacts_dir: str,
) -> StepResult:
    """Execute one step and return its ``StepResult``."""
    console_logs: list[str] = []
    network_errors: list[str] = []

    # Attach per-step event listeners
    def _on_console(msg: object) -> None:  # type: ignore[type-arg]
        console_logs.append(f"[{msg.type}] {msg.text}")  # type: ignore[attr-defined]

    def _on_request_failed(req: object) -> None:  # type: ignore[type-arg]
        network_errors.append(  # type: ignore[attr-defined]
            f"{req.method} {req.url} — {req.failure}"  # type: ignore[attr-defined]
        )

    page.on("console", _on_console)
    page.on("requestfailed", _on_request_failed)

    step_start = time.monotonic()
    screenshot_path: str | None = None
    dom_snapshot_path: str | None = None
    healing: HealingReport | None = None

    try:
        locator_used = await _perform_action(page, step, config)
        # Step 3: enrich target with fingerprint + ranked fallback locators
        if locator_used and step.target is not None:
            await _enrich_target(page, step.target, locator_used)
        duration_ms = _elapsed_ms(step_start)
        return StepResult(
            step_id=step.step_id,
            status=StepStatus.PASSED,
            duration_ms=duration_ms,
            locator_used=locator_used,
            console_logs=console_logs,
            network_errors=network_errors,
        )

    except (PlaywrightTimeoutError, PlaywrightError, AssertionError, ValueError) as exc:
        duration_ms = _elapsed_ms(step_start)
        error_msg = str(exc)

        # Healing hook — returns None until healer.py is wired in (Step 4)
        healing = await _attempt_healing(page, step, config, exc)

        if healing and healing.selected_locator:
            # Healing succeeded — retry the action with the healed locator
            try:
                locator_used = await _perform_action_with_locator(
                    page, step, healing.selected_locator, config
                )
                duration_ms = _elapsed_ms(step_start)
                screenshot_path = await write_screenshot(
                    page, test_id, step.step_id, artifacts_dir
                )
                dom_snapshot_path = await write_dom_snapshot(
                    page, test_id, step.step_id, artifacts_dir
                )
                return StepResult(
                    step_id=step.step_id,
                    status=StepStatus.HEALED,
                    duration_ms=duration_ms,
                    locator_used=locator_used,
                    healing=healing,
                    screenshot_path=screenshot_path,
                    dom_snapshot_path=dom_snapshot_path,
                    console_logs=console_logs,
                    network_errors=network_errors,
                )
            except Exception as retry_exc:
                error_msg = f"Healing failed on retry: {retry_exc}"

        # Capture failure artifacts
        screenshot_path = await write_screenshot(page, test_id, step.step_id, artifacts_dir)
        dom_snapshot_path = await write_dom_snapshot(page, test_id, step.step_id, artifacts_dir)

        return StepResult(
            step_id=step.step_id,
            status=StepStatus.FAILED,
            error=error_msg,
            duration_ms=duration_ms,
            healing=healing,  # include even if healing failed (for Member 1 / dashboard)
            screenshot_path=screenshot_path,
            dom_snapshot_path=dom_snapshot_path,
            console_logs=console_logs,
            network_errors=network_errors,
        )

    finally:
        page.remove_listener("console", _on_console)
        page.remove_listener("requestfailed", _on_request_failed)


# ---------------------------------------------------------------------------
# Action dispatcher
# ---------------------------------------------------------------------------


async def _perform_action(page: Page, step: Step, config: EngineConfig) -> str | None:
    """
    Dispatch to the appropriate Playwright action for *step*.

    Returns the locator string used (or ``None`` for non-element actions like
    ``goto`` and ``wait_for``).

    Raises
    ------
    ValueError
        If a required ``target`` or ``value`` is missing from the step.
    PlaywrightTimeoutError / PlaywrightError
        Propagated from Playwright on element-not-found or action failures.
    AssertionError
        Raised by ``assert_text`` / ``assert_visible`` when the assertion fails.
    """
    action = step.action
    timeout = step.timeout_ms

    # ---- navigation ---------------------------------------------------
    if action == ActionType.GOTO:
        url = _require_value(step, "goto")
        await page.goto(url, timeout=timeout)
        return None

    # ---- element-less wait --------------------------------------------
    if action == ActionType.WAIT_FOR:
        value = step.value or ""
        try:
            ms = int(value)
            await page.wait_for_timeout(ms)
        except ValueError:
            # treat as a CSS/XPath selector
            await page.wait_for_selector(value, timeout=timeout)
        return None

    # ---- element actions: all need a locator --------------------------
    locator_str = _require_locator(step)
    return await _perform_action_with_locator(page, step, locator_str, config)


async def _perform_action_with_locator(
    page: Page,
    step: Step,
    locator_str: str,
    config: EngineConfig,  # noqa: ARG001 — reserved for future use
) -> str:
    """Run the step's action using *locator_str* and return it."""
    action = step.action
    timeout = step.timeout_ms
    loc = page.locator(locator_str)

    if action == ActionType.CLICK:
        await loc.click(timeout=timeout)

    elif action == ActionType.FILL:
        value = _require_value(step, "fill")
        await loc.fill(value, timeout=timeout)

    elif action == ActionType.PRESS:
        value = _require_value(step, "press")
        await loc.press(value, timeout=timeout)

    elif action == ActionType.SELECT:
        value = _require_value(step, "select")
        await loc.select_option(value, timeout=timeout)

    elif action == ActionType.ASSERT_TEXT:
        expected = step.expected or ""
        actual = (await loc.inner_text(timeout=timeout)).strip()
        assert expected in actual, (
            f"assert_text failed: expected {expected!r} in {actual!r}"
        )

    elif action == ActionType.ASSERT_VISIBLE:
        await loc.wait_for(state="visible", timeout=timeout)
        is_visible = await loc.is_visible()
        assert is_visible, f"assert_visible failed: {locator_str!r} is not visible"

    else:
        raise ValueError(f"Unhandled action {action!r} in _perform_action_with_locator")

    return locator_str


# ---------------------------------------------------------------------------
# Healing hook (stub — replaced by healer.py in Step 4)
# ---------------------------------------------------------------------------


async def _attempt_healing(
    page: Page,  # noqa: ARG001
    step: Step,  # noqa: ARG001
    config: EngineConfig,  # noqa: ARG001
    exc: Exception,  # noqa: ARG001
) -> HealingReport | None:
    """
    Healing hook.

    Returns ``None`` in this version.  Step 4 (healer.py) replaces this
    with real fallback + fingerprint healing logic.

    ponytail: stub; upgrade path = import and call healer.attempt_healing()
    """
    return None


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _require_value(step: Step, action_name: str) -> str:
    """Return ``step.value`` or raise ``ValueError`` with a clear message."""
    if not step.value:
        raise ValueError(f"Step {step.step_id!r}: action {action_name!r} requires a value")
    return step.value


def _require_locator(step: Step) -> str:
    """Return the primary locator from ``step.target`` or raise."""
    if step.target is None:
        raise ValueError(
            f"Step {step.step_id!r}: action {step.action!r} requires a target"
        )
    return step.target.primary_locator


def _elapsed_ms(start: float) -> int:
    """Wall-clock milliseconds since *start* (from ``time.monotonic()``)."""
    return int((time.monotonic() - start) * 1000)


def _aggregate_status(results: list[StepResult]) -> TestStatus:
    """Derive the top-level TestStatus from collected step results."""
    statuses = {r.status for r in results}
    if StepStatus.FAILED in statuses:
        return TestStatus.FAILED
    if StepStatus.HEALED in statuses:
        return TestStatus.HEALED
    return TestStatus.PASSED


async def _enrich_target(page: Page, target: Target, locator_str: str) -> None:
    """
    Post-success enrichment: attach a fresh ``ElementFingerprint`` and extend
    ``Target.fallback_locators`` with generated, ranked alternatives.

    Best-effort — silently does nothing if fingerprint capture fails (e.g.
    when a click triggered page navigation before we could inspect the element).
    """
    fp = await build_fingerprint(page, locator_str)
    if fp is None:
        return

    # Generate locators from fingerprint; add only those not already stored
    existing = {target.primary_locator, *target.fallback_locators}
    new_locs = [l for l in generate_locators(fp) if l not in existing]

    target.fallback_locators = rank_locators(list(target.fallback_locators) + new_locs)
    target.fingerprint = fp
    log.debug(
        "Target %r enriched: %d fallbacks, fingerprint tag=%s id=%s",
        locator_str,
        len(target.fallback_locators),
        fp.tag,
        fp.id,
    )
