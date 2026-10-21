"""
engine/benchmark.py
===================
Benchmark harness for the TestSphere-AI self-healing engine.

Usage
-----
    python -m engine.benchmark

What it does
------------
1. Serves tests/engine/demo_app via a background http.server thread on an
   ephemeral port -- no external network needed.
2. Runs a *baseline* plan on the unmodified app to enrich targets with
   fingerprints and ranked fallback_locators.
3. For each mutant (HTML patch applied in-memory to the served content):
   - deep-copies the enriched plan
   - runs it twice: healing_enabled=False, then healing_enabled=True
4. Records per-mutant metrics and aggregates, then writes:
   - benchmark_results.csv
   - benchmark_results.md
   and prints the aggregate block to stdout.
"""

from __future__ import annotations

import asyncio
import copy
import csv
import http.server
import io
import logging
import re
import socket
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from playwright.async_api import async_playwright

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

log = logging.getLogger("testsphere.benchmark")
logging.basicConfig(level=logging.WARNING)

# ---------------------------------------------------------------------------
# Demo-app path
# ---------------------------------------------------------------------------

DEMO_DIR = Path(__file__).resolve().parent.parent / "tests" / "engine" / "demo_app"


# ---------------------------------------------------------------------------
# Local HTTP server with patchable content
# ---------------------------------------------------------------------------

# Module-level dict holding the current patched HTML for each file.
_PATCHED: dict[str, bytes] = {}


def _load_demo() -> None:
    for p in DEMO_DIR.glob("*.html"):
        _PATCHED[p.name] = p.read_bytes()


def _patch(filename: str, transform: Callable[[str], str]) -> None:
    original = _PATCHED.get(filename, b"")
    _PATCHED[filename] = transform(original.decode()).encode()


def _reset() -> None:
    _load_demo()


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        path = self.path.lstrip("/") or "index.html"
        content = _PATCHED.get(path)
        if content is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


def _find_free_port() -> int:
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _start_server() -> tuple[http.server.HTTPServer, int]:
    port = _find_free_port()
    server = http.server.HTTPServer(("127.0.0.1", port), _Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server, port


# ---------------------------------------------------------------------------
# Baseline test plan
# ---------------------------------------------------------------------------

def _make_plan(base_url: str) -> TestPlan:
    return TestPlan(
        test_id="benchmark-login",
        name="Benchmark: Login Flow",
        base_url=base_url,
        steps=[
            Step(
                step_id="goto",
                action=ActionType.GOTO,
                value=base_url,
                timeout_ms=15_000,
            ),
            Step(
                step_id="fill-username",
                action=ActionType.FILL,
                target=Target(
                    description="Username input",
                    primary_locator='[data-testid="username-input"]',
                    fallback_locators=["#username", '[name="username"]'],
                ),
                value="admin",
            ),
            Step(
                step_id="fill-password",
                action=ActionType.FILL,
                target=Target(
                    description="Password input",
                    primary_locator='[data-testid="password-input"]',
                    fallback_locators=["#password", '[name="password"]'],
                ),
                value="password",
            ),
            Step(
                step_id="click-login",
                action=ActionType.CLICK,
                target=Target(
                    description="Login button",
                    primary_locator='[data-testid="login-button"]',
                    fallback_locators=["#login-btn", 'button[type="submit"]'],
                ),
            ),
        ],
    )


# ---------------------------------------------------------------------------
# Mutant definitions
# ---------------------------------------------------------------------------

@dataclass
class Mutant:
    name: str
    change_type: str
    expected_to_heal: bool
    patch: Callable[[], None]
    # step_id -> selector for the element that step SHOULD act on in the mutated
    # DOM.  A heal on a step not listed here (target gone) is a false heal.
    truth: dict[str, str] = field(default_factory=dict)


def _mutants() -> list[Mutant]:
    return [
        # Heal-able: testid renamed; fallback #username survives
        Mutant(
            name="username-testid-rename",
            truth={"fill-username": "#username"},
            change_type="testid-rename",
            expected_to_heal=True,
            patch=lambda: _patch("index.html", lambda h: h.replace(
                'data-testid="username-input"', 'data-testid="user-field"'
            )),
        ),
        # Heal-able: password testid removed; fallback #password survives
        Mutant(
            name="password-testid-removed",
            truth={"fill-password": "#password"},
            change_type="testid-removed",
            expected_to_heal=True,
            patch=lambda: _patch("index.html", lambda h: h.replace(
                'data-testid="password-input"', ""
            )),
        ),
        # Heal-able: button testid renamed; fallback #login-btn survives
        Mutant(
            name="button-testid-rename",
            truth={"click-login": "#login-btn"},
            change_type="testid-rename",
            expected_to_heal=True,
            patch=lambda: _patch("index.html", lambda h: h.replace(
                'data-testid="login-button"', 'data-testid="submit-btn"'
            )),
        ),
        # NOT heal-able: button element entirely removed
        Mutant(
            name="login-btn-removed",
            change_type="element-removed",
            expected_to_heal=False,
            patch=lambda: _patch("index.html", lambda h: h.replace(
                '<button id="login-btn" type="submit" data-testid="login-button">',
                "<!-- button removed -->",
            ).replace("Log in", "").replace("      </button>", "")),
        ),
        # Heal-able: id, testid and name all renamed, but it is still the same
        # input (same placeholder/type/autocomplete/position) -- healing it is
        # correct, e.g. via [placeholder="admin"]
        Mutant(
            name="username-identifiers-renamed",
            change_type="identifiers-renamed",
            expected_to_heal=True,
            truth={"fill-username": "#usr-x99"},
            patch=lambda: _patch("index.html", lambda h: h.replace(
                'id="username"', 'id="usr-x99"'
            ).replace(
                'data-testid="username-input"', 'data-testid="x-dead"'
            ).replace(
                'name="username"', 'name="x-dead"'
            )),
        ),
        # NOT heal-able (by design): the input became a <textarea>.  Fallback
        # #username still resolves, so this exercises the tag-mismatch refusal --
        # a different kind of element is a change for a human to review.
        Mutant(
            name="username-tag-changed",
            change_type="tag-changed",
            expected_to_heal=False,
            patch=lambda: _patch("index.html", lambda h: re.sub(
                r'<input\s+id="username".*?/>',
                '<textarea id="username" name="username" placeholder="admin" '
                'data-testid="username-text"></textarea>',
                h,
                flags=re.S,
            )),
        ),
    ]


# ---------------------------------------------------------------------------
# Healing toggle
# ---------------------------------------------------------------------------

async def _noop_healing(*_a, **_kw):
    return None


def _set_healing(enabled: bool) -> None:
    import engine.runner as _runner
    if not enabled:
        _runner._attempt_healing = _noop_healing  # type: ignore[attr-defined]
        return
    from engine.healer import attempt_healing
    _runner._attempt_healing = attempt_healing  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Result record
# ---------------------------------------------------------------------------

@dataclass
class MutantRecord:
    name: str
    change_type: str
    expected_to_heal: bool
    passed_off: bool
    outcome_on: str
    healed_locator: str
    strategy_used: str
    confidence: float
    false_heal: bool
    time_per_step_ms_off: float
    time_per_step_ms_on: float


def _extract_healing_info(result) -> tuple[str, str, float]:
    for sr in result.steps:
        if sr.healing and sr.healing.selected_locator:
            return (sr.healing.selected_locator, sr.healing.strategy_used, sr.healing.confidence)
    return ("", "", 0.0)


async def _is_false_heal(result, mutant: Mutant, page_url: str) -> bool:
    """True if any healed step acted on an element other than the ground truth.

    Probes the (still patched) page in a fresh browser: the healed locator must
    resolve to the very element ``mutant.truth`` names for that step.
    """
    healed = [s for s in result.steps if s.status == StepStatus.HEALED]
    if not healed:
        return False
    if any(s.step_id not in mutant.truth for s in healed):
        return True  # healed a step whose real target no longer exists

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.goto(page_url, wait_until="domcontentloaded")
            for s in healed:
                same = await page.locator(s.locator_used).first.evaluate(
                    "(el, sel) => el === document.querySelector(sel)",
                    mutant.truth[s.step_id],
                )
                if not same:
                    return True
        finally:
            await browser.close()
    return False


def _ms_per_step(result) -> float:
    ms = [s.duration_ms for s in result.steps]
    return sum(ms) / len(ms) if ms else 0.0


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------

async def run_benchmark() -> list[MutantRecord]:
    _load_demo()
    server, port = _start_server()
    base_url = f"http://127.0.0.1:{port}/index.html"
    options = RunOptions(headless=True, artifacts_dir="artifacts/benchmark", default_timeout_ms=5_000)

    try:
        # Baseline: enrich fingerprints on unmodified app
        print("Running baseline (enriching fingerprints)...")
        baseline_plan = _make_plan(base_url)
        _set_healing(False)
        await run_test(baseline_plan, options)
        enriched_plan = baseline_plan  # targets mutated in-place by runner

        records: list[MutantRecord] = []

        for mutant in _mutants():
            print(f"  mutant: {mutant.name} ...", end=" ", flush=True)

            _reset()
            mutant.patch()

            # healing OFF
            plan_off = copy.deepcopy(enriched_plan)
            _set_healing(False)
            result_off = await run_test(plan_off, options)

            # healing ON
            plan_on = copy.deepcopy(enriched_plan)
            _set_healing(True)
            result_on = await run_test(plan_on, options)

            healed_loc, strategy, confidence = _extract_healing_info(result_on)

            false_heal = await _is_false_heal(result_on, mutant, base_url)

            rec = MutantRecord(
                name=mutant.name,
                change_type=mutant.change_type,
                expected_to_heal=mutant.expected_to_heal,
                passed_off=(result_off.status == TestStatus.PASSED),
                outcome_on=result_on.status.value,
                healed_locator=healed_loc,
                strategy_used=strategy,
                confidence=confidence,
                false_heal=false_heal,
                time_per_step_ms_off=_ms_per_step(result_off),
                time_per_step_ms_on=_ms_per_step(result_on),
            )
            records.append(rec)
            print(f"off={result_off.status.value}  on={result_on.status.value}")

    finally:
        _reset()
        server.shutdown()

    return records


# ---------------------------------------------------------------------------
# Aggregate
# ---------------------------------------------------------------------------

def _aggregate(records: list[MutantRecord]) -> dict:
    n = len(records)
    if not n:
        return {}

    pass_on = sum(1 for r in records if r.outcome_on in ("passed", "healed"))

    expected_heal = [r for r in records if r.expected_to_heal]
    heal_success = sum(1 for r in expected_heal if r.outcome_on in ("passed", "healed"))

    all_heals = [r for r in records if r.outcome_on == "healed"]
    false_heals = sum(1 for r in all_heals if r.false_heal)

    not_expected = [r for r in records if not r.expected_to_heal]
    correct_refusals = sum(1 for r in not_expected if r.outcome_on == "failed")

    return {
        "total_mutants": n,
        "pass_rate_off": sum(1 for r in records if r.passed_off) / n,
        "pass_rate_on": pass_on / n,
        "healing_success_rate": heal_success / len(expected_heal) if expected_heal else 0.0,
        "false_heal_rate": false_heals / len(all_heals) if all_heals else 0.0,
        "correct_refusal_rate": correct_refusals / len(not_expected) if not_expected else 0.0,
        "mean_step_ms_off": sum(r.time_per_step_ms_off for r in records) / n,
        "mean_step_ms_on": sum(r.time_per_step_ms_on for r in records) / n,
    }


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

CSV_FIELDS = [
    "name", "change_type", "expected_to_heal", "passed_off",
    "outcome_on", "healed_locator", "strategy_used", "confidence",
    "false_heal", "time_per_step_ms_off", "time_per_step_ms_on",
]


def _write_csv(records: list[MutantRecord], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        for r in records:
            w.writerow({
                "name": r.name,
                "change_type": r.change_type,
                "expected_to_heal": r.expected_to_heal,
                "passed_off": r.passed_off,
                "outcome_on": r.outcome_on,
                "healed_locator": r.healed_locator,
                "strategy_used": r.strategy_used,
                "confidence": f"{r.confidence:.3f}",
                "false_heal": r.false_heal,
                "time_per_step_ms_off": f"{r.time_per_step_ms_off:.1f}",
                "time_per_step_ms_on": f"{r.time_per_step_ms_on:.1f}",
            })


def _write_md(records: list[MutantRecord], agg: dict, path: Path) -> None:
    lines = [
        "# TestSphere-AI Benchmark Results\n",
        "## Per-Mutant Results\n",
        "| Mutant | Change Type | Expect Heal | Passed OFF | Outcome ON | "
        "Healed Locator | Strategy | Conf | False Heal | ms/step OFF | ms/step ON |",
        "|--------|-------------|-------------|------------|------------|"
        "----------------|----------|------|------------|-------------|------------|",
    ]
    for r in records:
        lines.append(
            f"| {r.name} | {r.change_type} | {r.expected_to_heal} | {r.passed_off} "
            f"| {r.outcome_on} | `{r.healed_locator or '-'}` | {r.strategy_used or '-'} "
            f"| {r.confidence:.2f} | {r.false_heal} "
            f"| {r.time_per_step_ms_off:.1f} | {r.time_per_step_ms_on:.1f} |"
        )
    lines += [
        "\n## Aggregate\n",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Total mutants | {agg['total_mutants']} |",
        f"| Pass rate (healing OFF) | {agg['pass_rate_off']:.1%} |",
        f"| Pass rate (healing ON) | {agg['pass_rate_on']:.1%} |",
        f"| Healing success rate | {agg['healing_success_rate']:.1%} |",
        f"| False-heal rate | {agg['false_heal_rate']:.1%} |",
        f"| Correct-refusal rate | {agg['correct_refusal_rate']:.1%} |",
        f"| Mean ms/step (OFF) | {agg['mean_step_ms_off']:.1f} ms |",
        f"| Mean ms/step (ON) | {agg['mean_step_ms_on']:.1f} ms |",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _print_aggregate(agg: dict) -> None:
    print("\n-- Aggregate --------------------------------------------------")
    print(f"  Total mutants          : {agg['total_mutants']}")
    print(f"  Pass rate OFF          : {agg['pass_rate_off']:.1%}")
    print(f"  Pass rate ON           : {agg['pass_rate_on']:.1%}")
    print(f"  Healing success rate   : {agg['healing_success_rate']:.1%}")
    print(f"  False-heal rate        : {agg['false_heal_rate']:.1%}")
    print(f"  Correct-refusal rate   : {agg['correct_refusal_rate']:.1%}")
    print(f"  Mean ms/step (OFF)     : {agg['mean_step_ms_off']:.1f} ms")
    print(f"  Mean ms/step (ON)      : {agg['mean_step_ms_on']:.1f} ms")
    print("---------------------------------------------------------------")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def _main() -> None:
    t0 = time.monotonic()
    records = await run_benchmark()
    agg = _aggregate(records)

    repo_root = Path(__file__).resolve().parent.parent
    _write_csv(records, repo_root / "benchmark_results.csv")
    _write_md(records, agg, repo_root / "benchmark_results.md")
    _print_aggregate(agg)

    print(f"\nDone in {time.monotonic() - t0:.1f}s  |  CSV + MD written to repo root.")


if __name__ == "__main__":
    asyncio.run(_main())
