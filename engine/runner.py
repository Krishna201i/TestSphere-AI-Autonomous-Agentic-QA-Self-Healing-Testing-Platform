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
- When a step's primary locator fails, ``_attempt_healing`` (engine/healer.py)
  tries stored fallbacks, then a fingerprint scan of the live DOM; an accepted
  locator is retried and the step is reported as HEALED.  Locators are
  healed, assertions never: when an assertion found its element and the
  check itself failed (``AssertionError``), that is the test's result.
- No database access; all output is returned as a ``TestResult`` value.
"""

from __future__ import annotations

import contextlib
import logging
import time
from datetime import UTC, datetime
from pathlib import Path

try:
    from playwright.async_api import Error as PlaywrightError
    from playwright.async_api import Page
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError
    PLAYWRIGHT_INSTALLED = True
except ImportError:
    class PlaywrightError(Exception):  # type: ignore
        pass
    class PlaywrightTimeoutError(Exception):  # type: ignore
        pass
    Page = object  # type: ignore
    PLAYWRIGHT_INSTALLED = False

from . import visual as visual_diff
from .artifacts import write_dom_snapshot, write_screenshot
from .browser import BrowserSession
from .detector import build_fingerprint
from .healer import attempt_healing as _attempt_healing
from .locators import generate_locators, rank_locators
from .schemas import (
    ActionType,
    ElementFingerprint,
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
    *,
    visual: bool = False,
    visual_baseline: bytes | None = None,
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
    visual / visual_baseline:
        Take a settled viewport screenshot when the run passes, and compare it
        with *visual_baseline* (PNG bytes) when given (``engine/visual.py``).

    Returns
    -------
    TestResult
        Always returned — never raises.  Individual step failures are
        captured inside ``StepResult.error``.
    """
    config = options.merged(EngineConfig()) if options else EngineConfig()
    started_at = datetime.now(UTC)
    wall_start = time.monotonic()

    step_results: list[StepResult] = []
    artifacts_dir = str(Path(config.artifacts_dir) / plan.test_id)
    visual_result: dict | None = None

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
            # A passing run still shows what the browser ended on
            last = step_results[-1] if step_results else None
            if last and last.status != StepStatus.FAILED and not last.screenshot_path:
                shot = await write_screenshot(page, plan.test_id, last.step_id, artifacts_dir)
                step_results[-1] = last.model_copy(update={"screenshot_path": shot})
            if visual and step_results and all(s.status != StepStatus.FAILED for s in step_results):
                visual_result = await _visual_check(page, artifacts_dir, visual_baseline)
    except Exception as exc:  # noqa: BLE001 - the engine reports failures in its result and never raises
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
        visual=visual_result,
    )


async def _visual_check(page: Page, artifacts_dir: str, baseline: bytes | None) -> dict | None:
    """Screenshot the page the test ended on and compare it with the baseline; None if it fails."""
    try:
        current = await visual_diff.screenshot(page)
        folder = Path(artifacts_dir) / "_visual"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "current.png").write_bytes(current)
        out: dict = {"current": str((folder / "current.png").resolve())}
        if baseline:
            res = await visual_diff.compare(page.context, baseline, current)
            if res["diff_png"]:
                (folder / "diff.png").write_bytes(res["diff_png"])
                out["diff"] = str((folder / "diff.png").resolve())
            out.update(ratio=res["ratio"], changed_pixels=res["changed"], size_changed=res["size_changed"])
        return out
    except Exception as exc:  # noqa: BLE001 - a visual check never fails a functional test
        log.warning("Visual check failed: %s", exc)
        return None


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
        # Fingerprint before acting: a click that navigates removes the element
        pre_action_fp = await _fingerprint_if_present(page, step)
        locator_used = await _perform_action(page, step, config)
        # Step 3: enrich target with fingerprint + ranked fallback locators
        if locator_used and step.target is not None:
            await _enrich_target(page, step.target, locator_used, pre_action_fp)
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

        # Healing hook — engine/healer.py (module-level name so it can be swapped out).
        # A failed check is a result, not a broken locator: healing it onto
        # another element would turn a real failure into a pass.
        healing = None if isinstance(exc, AssertionError) else await _attempt_healing(page, step, config, exc)

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
            except Exception as retry_exc:  # noqa: BLE001 - the engine reports failures in its result and never raises
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
        nav_timeout = max(timeout or 15000, 15000)
        try:
            await page.goto(url, timeout=nav_timeout, wait_until="domcontentloaded")
        except Exception:  # noqa: BLE001 - any failure: retry with the looser "commit" wait
            await page.goto(url, timeout=nav_timeout, wait_until="commit")
        # Act like a person: wait for the page to finish loading.  Acting while
        # its own requests are in flight loses races a user never sees (a login
        # whose session cookie a late analytics response overwrites).
        for state, wait_ms in (("load", 10_000), ("networkidle", 2_000)):
            with contextlib.suppress(PlaywrightTimeoutError, PlaywrightError):
                await page.wait_for_load_state(state, timeout=wait_ms)
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

    # ---- page URL check -----------------------------------------------
    if action == ActionType.ASSERT_URL:
        expected = step.expected or step.value or ""
        deadline = time.monotonic() + max(timeout or 5000, 1000) / 1000
        while expected.lower() not in page.url.lower():
            if time.monotonic() >= deadline:
                raise AssertionError(f"assert_url failed: expected {expected!r} in {page.url!r}")
            await page.wait_for_timeout(200)
        return None

    # ---- element actions: all need a locator --------------------------
    locator_str = _require_locator(step)
    return await _perform_action_with_locator(page, step, locator_str, config)


async def _perform_action_with_locator(
    page: Page,
    step: Step,
    locator_str: str,
    config: EngineConfig,
) -> str:
    """Run the step's action using *locator_str* and return it."""
    action = step.action
    floor = config.min_action_timeout_ms
    timeout = max(step.timeout_ms or floor, floor)
    loc = page.locator(locator_str).first

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
        assert expected.casefold() in actual.casefold(), (
            f"assert_text failed: expected {expected!r} in {actual!r}"
        )

    elif action == ActionType.ASSERT_VISIBLE:
        await loc.wait_for(state="visible", timeout=timeout)
        is_visible = await loc.is_visible()
        assert is_visible, f"assert_visible failed: {locator_str!r} is not visible"

    elif action == ActionType.ASSERT_HIDDEN:
        # Passes once no element matches or the match is hidden.  Still
        # visible at the deadline = a failed check (never a locator to heal).
        try:
            await loc.wait_for(state="hidden", timeout=timeout)
        except PlaywrightTimeoutError:
            raise AssertionError(f"assert_hidden failed: {locator_str!r} is still visible") from None

    else:
        raise ValueError(f"Unhandled action {action!r} in _perform_action_with_locator")

    return locator_str


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


async def _fingerprint_if_present(page: Page, step: Step) -> ElementFingerprint | None:
    """Fingerprint the step's primary target if it is already in the DOM (no waiting)."""
    if step.target is None or step.action in (ActionType.GOTO, ActionType.WAIT_FOR):
        return None
    try:
        if await page.locator(step.target.primary_locator).count() == 0:
            return None
    except Exception:  # noqa: BLE001 - invalid selector — let the action itself report it
        return None
    return await build_fingerprint(page, step.target.primary_locator)


async def _enrich_target(
    page: Page,
    target: Target,
    locator_str: str,
    fp: ElementFingerprint | None = None,
) -> None:
    """
    Post-success enrichment: attach a fresh ``ElementFingerprint`` and extend
    ``Target.fallback_locators`` with generated, ranked alternatives.

    *fp* is the fingerprint captured before the action, if any; otherwise one
    is captured now.  Best-effort — silently does nothing if capture fails
    (e.g. the element only appeared during the action and a navigation then
    removed it).
    """
    if fp is None:
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
