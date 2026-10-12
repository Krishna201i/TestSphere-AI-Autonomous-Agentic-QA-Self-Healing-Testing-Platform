"""
engine/benchmark.py
===================
Mutation benchmark for the TestSphere-AI self-healing engine.

Usage
-----
    python -m engine.benchmark                  # all mutants
    python -m engine.benchmark --subset 4       # first N mutants (fast CI)
    python -m engine.benchmark --threshold 0.6  # override heal_threshold

What it does
------------
1. Serves tests/engine/demo_app/ via a local http.server thread (no network).
2. Runs a baseline plan on the unmodified app; the runner captures DOM
   fingerprints on each successful step — these enrich the plan's Targets.
3. For each mutant in mutants.json:
   a. Serves the mutant's directory via a separate server thread.
   b. Runs a deep copy of the enriched plan with healing_enabled=False.
   c. Runs a deep copy of the enriched plan with healing_enabled=True.
   d. Records: change_type, expected_to_heal, passed_off, outcome_on,
      healed_locator, strategy_used, confidence, false_heal,
      time_per_step_ms for off and on.
4. Aggregates: pass rate off vs on, healing success rate, false-heal rate,
   correct-refusal rate, mean time per step.
5. Writes benchmark_results.csv and benchmark_results.md.
6. Prints the aggregate block to stdout.

Design notes
------------
- Self-contained runner: uses Playwright directly + engine.healer.
  No dependency on engine.runner (source not available in all environments).
- Each mutant gets its own ephemeral HTTP port (no cross-test pollution).
- headless=True throughout.
- ponytail: sequential mutant runs; parallelism would cut wall time 10x but
  complicates port management — not needed for <=20 mutants.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import csv
import json
import logging
import math
import re
import socketserver
import threading
import time
from http.server import SimpleHTTPRequestHandler
from pathlib import Path
from typing import Any

from playwright.async_api import async_playwright, Page, Browser

from engine.healer import attempt_healing
from engine.schemas import (
    ActionType,
    BoundingBox,
    ElementFingerprint,
    EngineConfig,
    HealingReport,
    RunOptions,
    Step,
    StepStatus,
    Target,
    TestPlan,
    TestResult,
    TestStatus,
    StepResult,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parent.parent
_DEMO_APP = _ROOT / "tests" / "engine" / "demo_app"
_MUTATIONS_DIR = _DEMO_APP / "mutations"
_MANIFEST = _MUTATIONS_DIR / "mutants.json"

_OUT_CSV = _ROOT / "benchmark_results.csv"
_OUT_MD = _ROOT / "benchmark_results.md"

# ---------------------------------------------------------------------------
# HTTP server helpers
# ---------------------------------------------------------------------------


class _QuietHandler(SimpleHTTPRequestHandler):
    """Suppress access logs."""
    def log_message(self, *_: Any) -> None:
        pass


def _start_server(directory: Path) -> tuple[socketserver.TCPServer, int, str]:
    """Start a TCP server in a daemon thread. Returns (server, port, index_url)."""
    handler = lambda *a, **kw: _QuietHandler(*a, directory=str(directory), **kw)
    server = socketserver.TCPServer(("127.0.0.1", 0), handler)
    server.allow_reuse_address = True
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server, port, f"http://127.0.0.1:{port}/index.html"


def _stop_server(server: socketserver.TCPServer) -> None:
    server.shutdown()


# ---------------------------------------------------------------------------
# Baseline test plan
# ---------------------------------------------------------------------------


def _make_baseline_plan(base_url: str) -> TestPlan:
    """Return a plan that exercises all mutable elements on index + dashboard."""
    dash_url = base_url.replace("index.html", "dashboard.html")
    return TestPlan(
        test_id="baseline",
        name="Baseline Login Flow",
        base_url=base_url,
        steps=[
            Step(
                step_id="goto-index",
                action=ActionType.GOTO,
                value=base_url,
                timeout_ms=10_000,
            ),
            Step(
                step_id="fill-username",
                action=ActionType.FILL,
                target=Target(
                    description="Username input",
                    primary_locator='[data-testid="username-input"]',
                    fallback_locators=['#username', 'input[name="username"]'],
                ),
                value="admin",
            ),
            Step(
                step_id="fill-password",
                action=ActionType.FILL,
                target=Target(
                    description="Password input",
                    primary_locator='[data-testid="password-input"]',
                    fallback_locators=['#password', 'input[name="password"]'],
                ),
                value="password",
            ),
            Step(
                step_id="click-login",
                action=ActionType.CLICK,
                target=Target(
                    description="Login button",
                    primary_locator='[data-testid="login-button"]',
                    fallback_locators=['#login-btn', 'button[type="submit"]'],
                ),
            ),
            # Navigate directly to dashboard (avoids auth state issues in mutant runs)
            Step(
                step_id="goto-dashboard",
                action=ActionType.GOTO,
                value=dash_url,
                timeout_ms=10_000,
            ),
            Step(
                step_id="assert-welcome",
                action=ActionType.ASSERT_TEXT,
                target=Target(
                    description="Welcome message",
                    primary_locator='[data-testid="welcome-message"]',
                    fallback_locators=['#welcome-msg'],
                ),
                expected="Welcome",
            ),
            Step(
                step_id="assert-test-count",
                action=ActionType.ASSERT_VISIBLE,
                target=Target(
                    description="Test count stat card",
                    primary_locator='[data-testid="test-count"]',
                    fallback_locators=['#test-count'],
                ),
            ),
            Step(
                step_id="click-logout",
                action=ActionType.CLICK,
                target=Target(
                    description="Logout button",
                    primary_locator='[data-testid="logout-button"]',
                    fallback_locators=['#logout-btn'],
                ),
            ),
        ],
    )


# ---------------------------------------------------------------------------
# DOM fingerprint capture
# ---------------------------------------------------------------------------

_FINGERPRINT_JS = """
(selector) => {
    const el = document.querySelector(selector);
    if (!el) return null;
    const chain = [];
    let p = el.parentElement;
    while (p && p !== document.body && chain.length < 5) {
        const id  = p.id ? '#' + p.id : '';
        const cls = p.classList.length ? '.' + [...p.classList].join('.') : '';
        chain.push(p.tagName.toLowerCase() + id + cls);
        p = p.parentElement;
    }
    let sibIdx = null;
    if (el.parentElement) {
        const sibs = [...el.parentElement.children].filter(c => c.tagName === el.tagName);
        sibIdx = sibs.indexOf(el);
    }
    const attrs = {};
    const SKIP = new Set(['id','class','role','aria-label','name','placeholder']);
    for (const a of el.attributes) {
        if (!SKIP.has(a.name)) attrs[a.name] = a.value;
    }
    const r = el.getBoundingClientRect();
    return {
        tag: el.tagName.toLowerCase(),
        id: el.id || null,
        classes: [...el.classList],
        text: (el.innerText || '').trim().slice(0, 200) || null,
        role: el.getAttribute('role') || null,
        aria_label: el.getAttribute('aria-label') || null,
        name: el.getAttribute('name') || null,
        placeholder: el.getAttribute('placeholder') || null,
        attributes: attrs,
        parent_chain: chain,
        sibling_index: sibIdx,
        bounding_box: { x: r.x, y: r.y, width: r.width, height: r.height },
    };
}
"""


async def _capture_fingerprint(page: Page, locator: str) -> ElementFingerprint | None:
    try:
        data = await page.evaluate(_FINGERPRINT_JS, locator)
        if not data:
            return None
        bb = data.get("bounding_box")
        return ElementFingerprint(
            tag=data.get("tag"),
            id=data.get("id"),
            classes=data.get("classes") or [],
            text=data.get("text"),
            role=data.get("role"),
            aria_label=data.get("aria_label"),
            name=data.get("name"),
            placeholder=data.get("placeholder"),
            attributes=data.get("attributes") or {},
            parent_chain=data.get("parent_chain") or [],
            sibling_index=data.get("sibling_index"),
            bounding_box=BoundingBox(**bb) if bb and bb.get("width", 0) > 0 else None,
        )
    except Exception as e:
        log.debug("build_fingerprint failed for %r: %s", locator, e)
        return None


# ---------------------------------------------------------------------------
# Self-contained step executor
# ---------------------------------------------------------------------------


async def _execute_step(
    page: Page,
    step: Step,
    config: EngineConfig,
    healing_enabled: bool,
) -> StepResult:
    """Execute one step; return StepResult. Captures fingerprint on success."""
    t0 = time.monotonic()
    timeout = step.timeout_ms or config.default_timeout_ms

    try:
        if step.action == ActionType.GOTO:
            url = step.value or ""
            await page.goto(url, timeout=timeout, wait_until="domcontentloaded")
            return StepResult(
                step_id=step.step_id,
                status=StepStatus.PASSED,
                duration_ms=(time.monotonic() - t0) * 1000,
            )

        if step.target is None:
            raise ValueError(f"Step {step.step_id!r} requires a target")

        loc_str = step.target.primary_locator
        locator = page.locator(loc_str).first

        if step.action == ActionType.FILL:
            await locator.fill(step.value or "", timeout=timeout)
        elif step.action == ActionType.CLICK:
            await locator.click(timeout=timeout)
        elif step.action == ActionType.PRESS:
            await locator.press(step.value or "", timeout=timeout)
        elif step.action == ActionType.SELECT:
            await locator.select_option(step.value or "", timeout=timeout)
        elif step.action == ActionType.ASSERT_TEXT:
            text = await locator.inner_text(timeout=timeout)
            if step.expected and step.expected not in text:
                raise AssertionError(
                    f"Expected {step.expected!r} in text {text!r}"
                )
        elif step.action == ActionType.ASSERT_VISIBLE:
            await locator.wait_for(state="visible", timeout=timeout)
        elif step.action == ActionType.WAIT_FOR:
            await page.wait_for_timeout(int(step.value or 0))
        else:
            raise ValueError(f"Unknown action: {step.action}")

        # Capture fingerprint on success
        fp = await _capture_fingerprint(page, loc_str)
        if fp and step.target:
            # Enrich in-place (Target is not frozen)
            object.__setattr__(step.target, "fingerprint", fp) if hasattr(step.target, "__dict__") else None
            try:
                step.target.fingerprint = fp  # type: ignore[misc]
            except Exception:
                pass

        return StepResult(
            step_id=step.step_id,
            status=StepStatus.PASSED,
            duration_ms=(time.monotonic() - t0) * 1000,
        )

    except Exception as exc:
        if not healing_enabled or step.target is None:
            return StepResult(
                step_id=step.step_id,
                status=StepStatus.FAILED,
                error=str(exc)[:300],
                duration_ms=(time.monotonic() - t0) * 1000,
            )

        # Attempt healing
        report: HealingReport | None = await attempt_healing(page, step, config, exc)

        if report and report.selected_locator:
            # Validate the healed locator actually works
            healed = page.locator(report.selected_locator).first
            try:
                if step.action == ActionType.FILL:
                    await healed.fill(step.value or "", timeout=timeout)
                elif step.action == ActionType.CLICK:
                    await healed.click(timeout=timeout)
                elif step.action == ActionType.ASSERT_TEXT:
                    text = await healed.inner_text(timeout=timeout)
                    if step.expected and step.expected not in text:
                        raise AssertionError(f"Expected {step.expected!r} in {text!r}")
                elif step.action == ActionType.ASSERT_VISIBLE:
                    await healed.wait_for(state="visible", timeout=timeout)
                else:
                    await healed.wait_for(state="visible", timeout=timeout)

                return StepResult(
                    step_id=step.step_id,
                    status=StepStatus.HEALED,
                    healing=report,
                    duration_ms=(time.monotonic() - t0) * 1000,
                )
            except Exception as heal_exc:
                return StepResult(
                    step_id=step.step_id,
                    status=StepStatus.FAILED,
                    error=f"Heal failed: {heal_exc}",
                    healing=report,
                    duration_ms=(time.monotonic() - t0) * 1000,
                )

        return StepResult(
            step_id=step.step_id,
            status=StepStatus.FAILED,
            error=str(exc)[:300],
            healing=report,
            duration_ms=(time.monotonic() - t0) * 1000,
        )


async def _run_plan(
    plan: TestPlan,
    config: EngineConfig,
    healing_enabled: bool,
    browser: Browser,
) -> TestResult:
    """Run all steps; stop on first failure."""
    page = await browser.new_page()
    step_results: list[StepResult] = []
    overall = TestStatus.PASSED

    try:
        for step in plan.steps:
            sr = await _execute_step(page, step, config, healing_enabled)
            step_results.append(sr)
            if sr.status == StepStatus.HEALED:
                overall = TestStatus.HEALED
            elif sr.status == StepStatus.FAILED:
                overall = TestStatus.FAILED
                break  # stop on first failure
    finally:
        await page.close()

    return TestResult(
        test_id=plan.test_id,
        name=plan.name,
        status=overall,
        steps=step_results,
    )


# ---------------------------------------------------------------------------
# Baseline: enrich fingerprints
# ---------------------------------------------------------------------------


async def _run_baseline(base_url: str, config: EngineConfig, browser: Browser) -> TestPlan:
    """Run the baseline plan with healing=True to enrich all fingerprints."""
    plan = _make_baseline_plan(base_url)
    await _run_plan(plan, config, healing_enabled=True, browser=browser)
    return plan


# ---------------------------------------------------------------------------
# Mutant step selection
# ---------------------------------------------------------------------------


def _steps_for_mutant(enriched_plan: TestPlan, target_step_id: str, source_file: str, mutant_url: str) -> list[Step]:
    """Deep-copy and trim plan steps relevant to this mutant; fix all GOTO URLs."""
    all_steps = copy.deepcopy(enriched_plan.steps)

    if source_file == "index.html":
        # Steps up to and including target (login page only)
        step_ids = [s.step_id for s in all_steps]
        try:
            cut = step_ids.index(target_step_id) + 1
        except ValueError:
            # target may be an error-step not in baseline; take up to click-login
            cut = next((i + 1 for i, s in enumerate(all_steps) if s.step_id == "click-login"), len(all_steps))
        steps = all_steps[:cut]
    else:
        # Dashboard mutant: navigate directly; take only dashboard steps
        dash_url = mutant_url.replace("index.html", "dashboard.html")
        goto_dash = Step(
            step_id="goto-dashboard",
            action=ActionType.GOTO,
            value=dash_url,
            timeout_ms=10_000,
        )
        dashboard_ids = {"assert-welcome", "assert-test-count", "click-logout"}
        dash_steps = [s for s in all_steps if s.step_id in dashboard_ids]
        try:
            cut = [s.step_id for s in dash_steps].index(target_step_id) + 1
        except ValueError:
            cut = len(dash_steps)
        steps = [goto_dash] + dash_steps[:cut]

    # Fix ALL goto URLs to point at the mutant server
    for s in steps:
        if s.action == ActionType.GOTO:
            if source_file == "dashboard.html" and "dashboard" in (s.value or ""):
                s.value = mutant_url.replace("index.html", "dashboard.html")
            elif source_file == "index.html":
                s.value = mutant_url
            else:
                # Replace any baseline URL with mutant URL (same filename)
                if s.value:
                    fname = s.value.rsplit("/", 1)[-1]
                    base = mutant_url.rsplit("/", 1)[0]
                    s.value = f"{base}/{fname}"

    return steps


# ---------------------------------------------------------------------------
# False-heal detection
# ---------------------------------------------------------------------------


async def _check_false_heal(
    mutant_url: str,
    healed_locator: str,
    marker: str,
    config: EngineConfig,
    browser: Browser,
) -> bool:
    """
    Return True if the healed element does NOT carry expected_element_marker.
    Navigates to the mutant page and queries the DOM.
    """
    if not marker or not healed_locator:
        return False
    m = re.match(r'([\w-]+)="([^"]+)"', marker)
    if not m:
        return False
    attr, val = m.group(1), m.group(2)

    page = await browser.new_page()
    try:
        await page.goto(mutant_url, timeout=10_000, wait_until="domcontentloaded")
        js = f"""
        () => {{
            const el = document.querySelector({json.dumps(healed_locator)});
            if (!el) return '__NOT_FOUND__';
            return el.getAttribute({json.dumps(attr)}) || '__MISSING__';
        }}
        """
        result = await page.evaluate(js)
        return result not in (val, None)  # None means attr not on element but might be ok
    except Exception:
        return False
    finally:
        await page.close()


# ---------------------------------------------------------------------------
# Per-mutant benchmark run
# ---------------------------------------------------------------------------


async def _benchmark_mutant(
    mutant: dict,
    enriched_plan: TestPlan,
    config: EngineConfig,
    browser: Browser,
) -> dict:
    name = mutant["name"]
    change_type = mutant["change_type"]
    expected_to_heal: bool = mutant["expected_to_heal"]
    target_step_id: str = mutant["target_step_id"]
    marker: str = mutant["expected_element_marker"]
    source_file: str = mutant["source_file"]

    mutant_dir = _MUTATIONS_DIR / name
    server, port, mutant_url = _start_server(mutant_dir)

    try:
        steps = _steps_for_mutant(enriched_plan, target_step_id, source_file, mutant_url)

        plan_off = TestPlan(
            test_id=f"{name}-off",
            name=f"{name} [off]",
            base_url=mutant_url,
            steps=copy.deepcopy(steps),
        )
        plan_on = TestPlan(
            test_id=f"{name}-on",
            name=f"{name} [on]",
            base_url=mutant_url,
            steps=copy.deepcopy(steps),
        )

        # healing=False
        t0 = time.monotonic()
        result_off = await _run_plan(plan_off, config, healing_enabled=False, browser=browser)
        t_off = time.monotonic() - t0
        passed_off = result_off.status in (TestStatus.PASSED, TestStatus.HEALED)
        time_off = round(t_off * 1000 / max(len(result_off.steps), 1), 1)

        # healing=True
        t0 = time.monotonic()
        result_on = await _run_plan(plan_on, config, healing_enabled=True, browser=browser)
        t_on = time.monotonic() - t0
        time_on = round(t_on * 1000 / max(len(result_on.steps), 1), 1)

        outcome_on = {
            TestStatus.PASSED: "passed",
            TestStatus.HEALED: "healed",
            TestStatus.FAILED: "failed",
        }[result_on.status]

        # Extract healing info
        healed_locator = ""
        strategy_used = ""
        confidence = 0.0
        for sr in result_on.steps:
            if sr.status == StepStatus.HEALED and sr.healing and sr.healing.selected_locator:
                healed_locator = sr.healing.selected_locator
                strategy_used = sr.healing.strategy_used or ""
                confidence = sr.healing.confidence
                break

        # False-heal check
        false_heal = False
        if outcome_on == "healed" and healed_locator and marker:
            false_heal = await _check_false_heal(mutant_url, healed_locator, marker, config, browser)

        return {
            "name": name,
            "change_type": change_type,
            "expected_to_heal": expected_to_heal,
            "passed_off": passed_off,
            "outcome_on": outcome_on,
            "healed_locator": healed_locator,
            "strategy_used": strategy_used,
            "confidence": round(confidence, 3),
            "false_heal": false_heal,
            "time_per_step_ms_off": time_off,
            "time_per_step_ms_on": time_on,
        }
    finally:
        _stop_server(server)


# ---------------------------------------------------------------------------
# Aggregate
# ---------------------------------------------------------------------------


def _compute_aggregate(records: list[dict]) -> dict:
    n = len(records)
    if n == 0:
        return {}

    passed_off = sum(1 for r in records if r["passed_off"])
    passed_on = sum(1 for r in records if r["outcome_on"] in ("passed", "healed"))
    healable = [r for r in records if r["expected_to_heal"]]
    no_heal = [r for r in records if not r["expected_to_heal"]]
    heal_success = sum(1 for r in healable if r["outcome_on"] in ("passed", "healed"))
    all_heals = sum(1 for r in records if r["outcome_on"] == "healed")
    false_heals = sum(1 for r in records if r["false_heal"])
    correct_refusals = sum(1 for r in no_heal if r["outcome_on"] == "failed")

    pct = lambda a, b: f"{100 * a // max(b, 1)}%"

    return {
        "total_mutants": n,
        "pass_rate_off": f"{passed_off}/{n} ({pct(passed_off, n)})",
        "pass_rate_on": f"{passed_on}/{n} ({pct(passed_on, n)})",
        "healing_success_rate": (
            f"{heal_success}/{len(healable)} ({pct(heal_success, len(healable))})"
            if healable else "n/a"
        ),
        "false_heal_rate": (
            f"{false_heals}/{all_heals} ({pct(false_heals, all_heals)})"
            if all_heals else "0/0 (n/a)"
        ),
        "correct_refusal_rate": (
            f"{correct_refusals}/{len(no_heal)} ({pct(correct_refusals, len(no_heal))})"
            if no_heal else "n/a"
        ),
        "mean_time_per_step_ms_off": f"{sum(r['time_per_step_ms_off'] for r in records) / n:.1f}",
        "mean_time_per_step_ms_on": f"{sum(r['time_per_step_ms_on'] for r in records) / n:.1f}",
    }


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

_CSV_FIELDS = [
    "name", "change_type", "expected_to_heal",
    "passed_off", "outcome_on", "healed_locator",
    "strategy_used", "confidence", "false_heal",
    "time_per_step_ms_off", "time_per_step_ms_on",
]


def _write_csv(records: list[dict]) -> None:
    with _OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=_CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(records)


def _write_md(records: list[dict], agg: dict) -> None:
    lines = [
        "# TestSphere-AI Engine Benchmark Results\n",
        "## Per-Mutant Results\n",
        "| Mutant | Change Type | Exp.Heal | Pass Off | Outcome On | "
        "Strategy | Conf | FalseHeal | ms/step off | ms/step on |",
        "|--------|------------|---------|---------|-----------|"
        "---------|-----|----------|------------|-----------|",
    ]
    for r in records:
        exp = "yes" if r["expected_to_heal"] else "no"
        fh = "YES" if r["false_heal"] else ""
        off = "pass" if r["passed_off"] else "fail"
        lines.append(
            f"| {r['name']} | {r['change_type']} | {exp} | {off} | "
            f"{r['outcome_on']} | {r['strategy_used'] or '-'} | "
            f"{r['confidence']} | {fh} | {r['time_per_step_ms_off']} | "
            f"{r['time_per_step_ms_on']} |"
        )
    lines += ["", "## Aggregate", "", "| Metric | Value |", "|--------|-------|"]
    for k, v in agg.items():
        lines.append(f"| {k.replace('_', ' ').title()} | {v} |")
    _OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _print_aggregate(agg: dict) -> None:
    print("\n-- Benchmark Aggregate ------------------------------------------")
    for k, v in agg.items():
        print(f"  {k:<35} {v}")
    print("-----------------------------------------------------------------\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def _main(subset: int | None, threshold: float) -> None:
    if not _MANIFEST.exists():
        print("mutants.json not found - running mutation generator first...")
        import sys
        sys.path.insert(0, str(_ROOT))
        from tests.engine.mutations import generate
        generate()

    manifest: list[dict] = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    if subset is not None:
        manifest = manifest[:subset]

    config = EngineConfig(
        heal_threshold=threshold,
        headless=True,
        artifacts_dir="artifacts/benchmark",
        tracing_enabled=False,
    )

    base_server, base_port, base_url = _start_server(_DEMO_APP)
    print(f"Baseline server: {base_url}")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            print("Running baseline to enrich fingerprints...")
            enriched_plan = await _run_baseline(base_url, config, browser)
            print(f"Baseline done. {len(enriched_plan.steps)} steps enriched.\n")

            records: list[dict] = []
            for i, mutant in enumerate(manifest, 1):
                print(
                    f"[{i}/{len(manifest)}] {mutant['name']} ({mutant['change_type']}) ...",
                    end=" ", flush=True,
                )
                rec = await _benchmark_mutant(mutant, enriched_plan, config, browser)
                records.append(rec)
                print(
                    f"off={rec['passed_off']} on={rec['outcome_on']} "
                    f"conf={rec['confidence']} false_heal={rec['false_heal']}"
                )
        finally:
            await browser.close()
            _stop_server(base_server)

    agg = _compute_aggregate(records)
    _write_csv(records)
    _write_md(records, agg)
    _print_aggregate(agg)
    print(f"Results -> {_OUT_CSV.name}  {_OUT_MD.name}")


def main() -> None:
    parser = argparse.ArgumentParser(description="TestSphere-AI engine mutation benchmark")
    parser.add_argument("--subset", type=int, default=None,
                        help="Run only first N mutants (fast CI)")
    parser.add_argument("--threshold", type=float, default=0.75,
                        help="Heal threshold for fingerprint scoring (default 0.75)")
    args = parser.parse_args()
    asyncio.run(_main(args.subset, args.threshold))


if __name__ == "__main__":
    main()
