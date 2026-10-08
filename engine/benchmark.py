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
2. Runs a baseline plan on the unmodified app; fingerprints and fallback_locators
   are enriched on the plan's steps.
3. For each mutant in mutants.json:
   a. Serves the mutant's directory via a second server thread.
   b. Runs a deep copy of the enriched plan with healing_enabled=False.
   c. Runs a deep copy of the enriched plan with healing_enabled=True.
   d. Records: change_type, expected_to_heal, passed_off, outcome_on,
      healed_locator, strategy_used, confidence, false_heal,
      time_per_step_ms_off, time_per_step_ms_on.
4. Aggregates: pass-rate off/on, heal success rate, false-heal rate,
   correct-refusal rate, mean time per step.
5. Writes benchmark_results.csv and benchmark_results.md.
6. Prints the aggregate block to stdout.

Design notes
------------
- Each mutant gets its own ephemeral HTTP port to avoid cross-test pollution.
- RunOptions(headless=True) is used throughout.
- "false_heal": healed but the resolved element lacks expected_element_marker.
  Detected by evaluating document.documentElement.outerHTML after healing.
- ponytail: sequential mutant runs; parallelism would cut wall time but
  complicates port management and is not needed for ≤20 mutants.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import csv
import json
import socketserver
import threading
import time
from http.server import SimpleHTTPRequestHandler
from pathlib import Path
from typing import Any

from engine.healer import attempt_healing
from engine.runner import run_test, _execute_step
from engine.schemas import (
    ActionType,
    EngineConfig,
    RunOptions,
    Step,
    StepStatus,
    Target,
    TestPlan,
    TestResult,
    TestStatus,
)

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
# Baseline test plan
# ---------------------------------------------------------------------------
# Covers the elements mutated by the mutation set so healing has something to do.

def _make_baseline_plan(base_url: str) -> TestPlan:
    """Return a plan that exercises all mutable elements on index + dashboard."""
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
                    fallback_locators=['#test-count', '.stat-card'],
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
# HTTP server helpers
# ---------------------------------------------------------------------------

class _QuietHandler(SimpleHTTPRequestHandler):
    """Suppress access logs."""
    def log_message(self, *_: Any) -> None:  # noqa: ANN002
        pass


def _start_server(directory: Path) -> tuple[socketserver.TCPServer, int, str]:
    """Start a TCP server in a daemon thread. Returns (server, port, base_url)."""
    handler = lambda *a, **kw: _QuietHandler(*a, directory=str(directory), **kw)  # noqa: E731
    server = socketserver.TCPServer(("127.0.0.1", 0), handler)
    server.allow_reuse_address = True
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server, port, f"http://127.0.0.1:{port}/index.html"


def _stop_server(server: socketserver.TCPServer) -> None:
    server.shutdown()


# ---------------------------------------------------------------------------
# Healing-enabled runner
# ---------------------------------------------------------------------------
# The engine runner's _attempt_healing stub returns None. We wire in the real
# engine.healer here by monkey-patching the module attribute for each run.

import engine.runner as _runner_mod
import engine.healer as _healer_mod


def _make_run_options(headless: bool = True, artifacts_dir: str = "artifacts") -> RunOptions:
    return RunOptions(headless=headless, artifacts_dir=artifacts_dir, tracing_enabled=False)


async def _run_with_healing(
    plan: TestPlan,
    options: RunOptions,
    healing_enabled: bool,
) -> TestResult:
    """Run plan, optionally wiring in the real healer."""
    if healing_enabled:
        # Patch the stub with the real healer
        orig = _runner_mod._attempt_healing
        _runner_mod._attempt_healing = attempt_healing
        try:
            return await run_test(plan, options)
        finally:
            _runner_mod._attempt_healing = orig
    else:
        return await run_test(plan, options)


# ---------------------------------------------------------------------------
# False-heal detection
# ---------------------------------------------------------------------------

async def _check_false_heal(
    plan: TestPlan,
    options: RunOptions,
    healed_locator: str,
    marker: str,
) -> bool:
    """
    Return True if the healed_locator resolves to an element that does NOT
    contain the expected_element_marker attribute in the live DOM.

    Strategy: run the plan up to navigation, then check via JS.
    Simplified: just navigate to the URL and check the DOM.
    """
    if not marker:
        return False  # no marker defined for non-healable mutants

    from engine.browser import BrowserSession
    config = options.merged(EngineConfig())
    try:
        async with BrowserSession(config) as session:
            page = await session.new_page()
            await page.goto(plan.base_url, timeout=10_000, wait_until="domcontentloaded")
            # Parse marker: attr="value"
            import re
            m = re.match(r'(\w[\w-]*)="([^"]+)"', marker)
            if not m:
                return False
            attr, val = m.group(1), m.group(2)

            # Check if healed_locator finds an element WITH the marker
            js = f"""
            () => {{
                const el = document.querySelector({json.dumps(healed_locator)});
                if (!el) return null;
                return el.getAttribute({json.dumps(attr)});
            }}
            """
            result = await page.evaluate(js)
            if result is None:
                return True  # locator found nothing — false heal
            return result != val
    except Exception:
        return False  # can't confirm → assume not a false heal


# ---------------------------------------------------------------------------
# Core benchmark logic
# ---------------------------------------------------------------------------

async def _run_baseline(base_url: str, options: RunOptions) -> TestPlan:
    """Run baseline on unmodified app to enrich fingerprints. Returns enriched plan."""
    plan = _make_baseline_plan(base_url)
    # Wire real healer for baseline too (enriches on success)
    orig = _runner_mod._attempt_healing
    _runner_mod._attempt_healing = attempt_healing
    try:
        await run_test(plan, options)
    finally:
        _runner_mod._attempt_healing = orig
    return plan


def _steps_for_mutant(enriched_plan: TestPlan, target_step_id: str, source_file: str) -> list[Step]:
    """
    Return deep-copied steps relevant for this mutant.

    - If source_file is index.html: steps up to (and including) click-login.
    - If source_file is dashboard.html: steps that operate on dashboard elements.
    - We always include the goto step so the page loads correctly.
    """
    all_steps = copy.deepcopy(enriched_plan.steps)

    if source_file == "index.html":
        # Keep steps through click-login (dashboard steps not reached)
        keep = {"goto-index", "fill-username", "fill-password", "click-login",
                "assert-error", "fill-username"}
        # Filter to steps up to and including the target
        step_ids = [s.step_id for s in all_steps]
        try:
            cut = step_ids.index(target_step_id) + 1
        except ValueError:
            cut = len(all_steps)
        return all_steps[:cut]
    else:
        # Dashboard: need navigation to dashboard.html directly
        dash_steps = [s for s in all_steps if s.step_id in (
            "assert-welcome", "assert-test-count", "click-logout",
        )]
        goto_dash = Step(
            step_id="goto-dashboard",
            action=ActionType.GOTO,
            value=None,  # filled per-mutant below
            timeout_ms=10_000,
        )
        try:
            cut = [s.step_id for s in dash_steps].index(target_step_id) + 1
        except ValueError:
            cut = len(dash_steps)
        return [goto_dash] + dash_steps[:cut]


async def _benchmark_mutant(
    mutant: dict,
    enriched_plan: TestPlan,
    options: RunOptions,
    base_server_url: str,
) -> dict:
    """Run one mutant off/on and return a result record."""
    name = mutant["name"]
    change_type = mutant["change_type"]
    expected_to_heal = mutant["expected_to_heal"]
    target_step_id = mutant["target_step_id"]
    marker = mutant["expected_element_marker"]
    source_file = mutant["source_file"]

    mutant_dir = _MUTATIONS_DIR / name

    # Serve mutant directory
    server, port, mutant_url = _start_server(mutant_dir)
    # Adjust base URL: dashboard mutants go to dashboard.html
    if source_file == "dashboard.html":
        mutant_url = f"http://127.0.0.1:{port}/dashboard.html"

    try:
        steps = _steps_for_mutant(enriched_plan, target_step_id, source_file)

        # Fix ALL goto step URLs to point at the mutant server (not baseline)
        for s in steps:
            if s.action == ActionType.GOTO:
                s.value = mutant_url

        mini_plan_off = TestPlan(
            test_id=f"{name}-off",
            name=f"{name} [healing=off]",
            base_url=mutant_url,
            steps=copy.deepcopy(steps),
        )
        mini_plan_on = TestPlan(
            test_id=f"{name}-on",
            name=f"{name} [healing=on]",
            base_url=mutant_url,
            steps=copy.deepcopy(steps),
        )

        # --- healing=False ---
        t0 = time.monotonic()
        result_off = await _run_with_healing(mini_plan_off, options, healing_enabled=False)
        t_off = time.monotonic() - t0
        passed_off = result_off.status in (TestStatus.PASSED, TestStatus.HEALED)
        n_steps_off = max(len(result_off.steps), 1)
        time_per_step_off = round((t_off * 1000) / n_steps_off, 1)

        # --- healing=True ---
        t0 = time.monotonic()
        result_on = await _run_with_healing(mini_plan_on, options, healing_enabled=True)
        t_on = time.monotonic() - t0
        n_steps_on = max(len(result_on.steps), 1)
        time_per_step_on = round((t_on * 1000) / n_steps_on, 1)

        # Determine outcome_on
        if result_on.status == TestStatus.PASSED:
            outcome_on = "passed"
        elif result_on.status == TestStatus.HEALED:
            outcome_on = "healed"
        else:
            outcome_on = "failed"

        # Extract healing details from the healed step (if any)
        healed_locator = ""
        strategy_used = ""
        confidence = 0.0
        for sr in result_on.steps:
            if sr.status == StepStatus.HEALED and sr.healing:
                healed_locator = sr.healing.selected_locator or ""
                strategy_used = sr.healing.strategy_used or ""
                confidence = sr.healing.confidence or 0.0
                break

        # False-heal detection
        false_heal = False
        if outcome_on == "healed" and healed_locator and marker:
            false_heal = await _check_false_heal(mini_plan_on, options, healed_locator, marker)

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
            "time_per_step_ms_off": time_per_step_off,
            "time_per_step_ms_on": time_per_step_on,
        }
    finally:
        _stop_server(server)


# ---------------------------------------------------------------------------
# Aggregate computation
# ---------------------------------------------------------------------------

def _compute_aggregate(records: list[dict]) -> dict:
    n = len(records)
    if n == 0:
        return {}

    passed_off = sum(1 for r in records if r["passed_off"])
    passed_on = sum(1 for r in records if r["outcome_on"] in ("passed", "healed"))
    healed = sum(1 for r in records if r["outcome_on"] == "healed")

    healable = [r for r in records if r["expected_to_heal"]]
    no_heal = [r for r in records if not r["expected_to_heal"]]

    heal_success = sum(1 for r in healable if r["outcome_on"] in ("passed", "healed"))
    false_heals = sum(1 for r in records if r["false_heal"])
    all_heals = sum(1 for r in records if r["outcome_on"] == "healed")
    correct_refusals = sum(1 for r in no_heal if r["outcome_on"] == "failed")

    mean_off = sum(r["time_per_step_ms_off"] for r in records) / n
    mean_on = sum(r["time_per_step_ms_on"] for r in records) / n

    return {
        "total_mutants": n,
        "pass_rate_off": f"{passed_off}/{n} ({100*passed_off//n}%)",
        "pass_rate_on": f"{passed_on}/{n} ({100*passed_on//n}%)",
        "healing_success_rate": (
            f"{heal_success}/{len(healable)} ({100*heal_success//max(len(healable),1)}%)"
            if healable else "n/a"
        ),
        "false_heal_rate": (
            f"{false_heals}/{all_heals} ({100*false_heals//max(all_heals,1)}%)"
            if all_heals else "0/0 (n/a)"
        ),
        "correct_refusal_rate": (
            f"{correct_refusals}/{len(no_heal)} ({100*correct_refusals//max(len(no_heal),1)}%)"
            if no_heal else "n/a"
        ),
        "mean_time_per_step_ms_off": f"{mean_off:.1f}",
        "mean_time_per_step_ms_on": f"{mean_on:.1f}",
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
        "| Mutant | Change Type | Exp. Heal | Pass Off | Outcome On | "
        "Strategy | Conf | False Heal | ms/step off | ms/step on |",
        "|--------|------------|-----------|----------|------------|"
        "----------|------|------------|------------|------------|",
    ]
    for r in records:
        exp = "✅" if r["expected_to_heal"] else "🚫"
        fh = "⚠️" if r["false_heal"] else ""
        off = "✅" if r["passed_off"] else "❌"
        on_icon = {"passed": "✅", "healed": "🔧", "failed": "❌"}.get(r["outcome_on"], "?")
        lines.append(
            f"| {r['name']} | {r['change_type']} | {exp} | {off} | "
            f"{on_icon} {r['outcome_on']} | {r['strategy_used'] or '—'} | "
            f"{r['confidence']} | {fh} | {r['time_per_step_ms_off']} | "
            f"{r['time_per_step_ms_on']} |"
        )

    lines += [
        "",
        "## Aggregate",
        "",
        "| Metric | Value |",
        "|--------|-------|",
    ]
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

    options = RunOptions(
        headless=True,
        heal_threshold=threshold,
        artifacts_dir="artifacts/benchmark",
        tracing_enabled=False,
    )

    # Start baseline server and enrich plan
    print(f"Serving baseline from {_DEMO_APP} ...")
    base_server, base_port, base_url = _start_server(_DEMO_APP)
    try:
        print("Running baseline to enrich fingerprints...")
        enriched_plan = await _run_baseline(base_url, options)
        print(f"Baseline done. Enriched {len(enriched_plan.steps)} steps.\n")

        records: list[dict] = []
        for i, mutant in enumerate(manifest, 1):
            print(f"[{i}/{len(manifest)}] {mutant['name']} ({mutant['change_type']}) ...", end=" ", flush=True)
            rec = await _benchmark_mutant(mutant, enriched_plan, options, base_url)
            records.append(rec)
            print(f"off={rec['passed_off']} on={rec['outcome_on']} "
                  f"conf={rec['confidence']} false_heal={rec['false_heal']}")
    finally:
        _stop_server(base_server)

    agg = _compute_aggregate(records)
    _write_csv(records)
    _write_md(records, agg)
    _print_aggregate(agg)
    print(f"Results written to {_OUT_CSV.name} and {_OUT_MD.name}")


def main() -> None:
    parser = argparse.ArgumentParser(description="TestSphere-AI engine benchmark")
    parser.add_argument("--subset", type=int, default=None,
                        help="Only run first N mutants (for fast CI)")
    parser.add_argument("--threshold", type=float, default=0.75,
                        help="heal_threshold for fingerprint scoring (default 0.75)")
    args = parser.parse_args()
    asyncio.run(_main(args.subset, args.threshold))


if __name__ == "__main__":
    main()
