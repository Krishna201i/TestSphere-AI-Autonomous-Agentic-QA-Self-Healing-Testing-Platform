"""
Generation eval: do the tests TestSphere writes for a login or sign-up page
catch real bugs, without failing a healthy site?

    python -m scripts.generation_eval            # every scenario
    python -m scripts.generation_eval --only login-no-goal

For each scenario (a page of ``tests/fixtures/auth_app.py`` and a written
goal, or none) it does what a pipeline run does: analyzes the healthy page
(``URLAnalyzerService.analyze_live_website``), plans its tests
(``backend.pipeline.suite.page_tests``) and converts each to an engine plan
the way the orchestrator does (``parse_stored_steps``,
``test_case_to_engine_plan``).  Then it runs every test, in Chromium:

1. on the healthy site, twice without resetting it (the second run is what a
   scheduled run sees: the account the first run created now exists);
2. with each bug of that page's flow switched on, one at a time, on a fresh
   site.  A bug is **caught** when a test that passed on the healthy site fails;
3. planned and run on the page with a CAPTCHA on its form, which is not a
   bug: a test that fails there blames the site for something automation
   cannot do.

It also counts tests that check nothing about the feature (no assertion other
than "the body is visible" or the page title).

Writes docs/generation-eval.md and docs/generation-eval.csv.  Offline: no LLM
(the rule-based planner every run uses), only a local site.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

os.environ.setdefault("ALLOW_PRIVATE_TARGETS", "true")  # the site is on 127.0.0.1
os.environ.setdefault("LLM_PROVIDER", "mock")

from agents.planner.schemas import TestCase as Member1TestCase  # noqa: E402
from backend.orchestration.converters import test_case_to_engine_plan  # noqa: E402
from backend.orchestration.orchestrator import parse_stored_steps  # noqa: E402
from backend.pipeline import suite  # noqa: E402
from backend.services.url_analyzer import URLAnalyzerService  # noqa: E402
from engine.runner import run_test  # noqa: E402
from engine.schemas import RunOptions, TestStatus  # noqa: E402
from tests.fixtures.auth_app import BLOCKERS, LOGIN_GOAL, MUTANTS, AuthApp  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

# Assertions that say nothing about the login or sign-up working
_TRIVIAL_TARGETS = {"body", "html", "main", "head > title"}


@dataclass(frozen=True)
class Scenario:
    key: str
    path: str
    goal: str | None
    flow: str  # "login" | "signup": which bugs apply
    note: str
    allow_test_accounts: bool = False  # the project setting: may the sign-up create accounts


SCENARIOS = [
    Scenario("login-no-goal", "/login", None, "login", "A user gives only the URL."),
    Scenario("login-with-credentials", "/login", LOGIN_GOAL, "login", "The goal has working credentials."),
    Scenario("login-goal-no-credentials", "/login", "test the login", "login",
             "The goal asks for the login, without credentials."),
    Scenario("store-login-with-credentials", "/store/login", LOGIN_GOAL, "login",
             "Working credentials; the page also has a header search form."),
    Scenario("signup-no-goal", "/signup", None, "signup", "A user gives only the URL."),
    Scenario("signup-goal", "/signup", "sign up as a new user", "signup", "The goal asks for a sign-up."),
    Scenario("signup-no-goal-accounts-on", "/signup", None, "signup",
             "A user gives only the URL; the project allows test accounts.", allow_test_accounts=True),
    Scenario("signup-goal-accounts-on", "/signup", "sign up as a new user", "signup",
             "The goal asks for a sign-up; the project allows test accounts.", allow_test_accounts=True),
]


@dataclass
class CaseOutcome:
    slug: str
    name: str
    feature_checks: int
    runs: dict[str, tuple[bool, str]] = field(default_factory=dict)  # condition → (passed, first error line)


@dataclass
class ScenarioResult:
    scenario: Scenario
    tests: list[CaseOutcome]
    seconds: float
    blocked: dict[str, list[CaseOutcome]] = field(default_factory=dict)  # blocker → tests planned and run on it

    def blocked_failures(self, name: str) -> int:
        return sum(1 for t in self.blocked.get(name, []) if not t.runs[name][0])

    def passed(self, condition: str) -> list[bool]:
        return [t.runs[condition][0] for t in self.tests]

    def healthy_failures(self, condition: str) -> int:
        return sum(1 for ok in self.passed(condition) if not ok)

    def caught(self, mutant: str) -> bool:
        return any(t.runs["healthy-1"][0] and not t.runs[mutant][0] for t in self.tests)

    @property
    def mutants(self) -> list[str]:
        return [m for m, info in MUTANTS.items() if info["page"] == self.scenario.flow]


def feature_checks(steps: list[dict]) -> int:
    """Assertions in *steps* that check more than the page rendering."""
    return sum(1 for s in steps if "ASSERT" in str(s.get("action", "")).upper()
               and str(s.get("target") or "").strip() not in _TRIVIAL_TARGETS)


async def _run(test: dict, base_url: str, options: RunOptions) -> tuple[bool, str]:
    steps, assertions = parse_stored_steps(test["steps"], base_url)
    case = Member1TestCase(test_id=test["slug"], name=test["name"], page_url=base_url,
                           steps=steps, assertions=assertions)
    result = await run_test(test_case_to_engine_plan(case, base_url), options)
    ok = result.status in (TestStatus.PASSED, TestStatus.HEALED)
    error = next((r.error for r in result.steps if r.error), "") or ""
    return ok, error.strip().splitlines()[0][:160] if error.strip() else ""


async def run_scenario(app: AuthApp, base: str, scenario: Scenario, options: RunOptions) -> ScenarioResult:
    started = time.monotonic()
    url = f"{base}{scenario.path}"

    async def plan() -> list[dict]:
        analysis = await URLAnalyzerService.analyze_live_website(
            url=url, prompt=scenario.goal, allow_test_accounts=scenario.allow_test_accounts)
        return suite.page_tests(analysis, scenario.goal)

    app.reset()
    app.set_mutant(None)
    planned = await plan()
    tests = [CaseOutcome(t["slug"], t["name"], feature_checks(t["steps"])) for t in planned]

    async def every_test(condition: str) -> None:
        for t, outcome in zip(planned, tests, strict=True):
            outcome.runs[condition] = await _run(t, url, options)

    await every_test("healthy-1")
    await every_test("healthy-2")  # same site: what the next scheduled run sees
    for name in (m for m, info in MUTANTS.items() if info["page"] == scenario.flow):
        app.reset()
        app.set_mutant(name)
        await every_test(name)
    # A CAPTCHA is there when the page is analyzed too: plan on it, then run
    blocked: dict[str, list[CaseOutcome]] = {}
    for name in BLOCKERS:
        app.reset()
        app.set_mutant(name)
        on_page = await plan()
        blocked[name] = [CaseOutcome(t["slug"], t["name"], feature_checks(t["steps"]),
                                     {name: await _run(t, url, options)}) for t in on_page]
    app.set_mutant(None)
    return ScenarioResult(scenario, tests, time.monotonic() - started, blocked)


# ── report ────────────────────────────────────────────────────────────────

def _pct(n: int, d: int) -> str:
    return f"{100 * n / d:.0f}%" if d else "–"


def write_report(results: list[ScenarioResult], md_path: Path, csv_path: Path) -> None:
    lines = [
        "# Generation eval: login and sign-up",
        "",
        "Do the tests TestSphere writes for a login or sign-up page catch real bugs, without failing a",
        "healthy site? Produced by `python -m scripts.generation_eval` against the local site in",
        "`tests/fixtures/auth_app.py`; the rule-based planner every run uses, no LLM.",
        "",
        "* **Feature checks**: assertions other than \"the body is visible\" or the page title.",
        "* **Healthy fails**: tests failing on the working site, on the first run and on the next one",
        "  (the account the first run created now exists). Every one blames the site wrongly.",
        "* **Bugs caught**: bugs of that flow where a test that passed on the healthy site fails.",
        "* **CAPTCHA fails**: tests planned on the page with a CAPTCHA on its form, failing there. A",
        "  CAPTCHA is not a bug: the tests should leave out what it blocks and say so, not fail.",
        "",
        "## Summary",
        "",
        "| Scenario | Tests | With a feature check | Healthy fails (run 1 / run 2) | Bugs caught | CAPTCHA fails |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    total_caught = total_mutants = total_false = total_tests = total_checked = 0
    for r in results:
        caught = sum(r.caught(m) for m in r.mutants)
        checked = sum(1 for t in r.tests if t.feature_checks)
        captcha_fails = r.blocked_failures("captcha")
        h1, h2 = r.healthy_failures("healthy-1"), r.healthy_failures("healthy-2")
        total_caught += caught
        total_mutants += len(r.mutants)
        total_false += h1 + h2
        total_tests += len(r.tests)
        total_checked += checked
        lines.append(f"| `{r.scenario.key}` | {len(r.tests)} | {checked} | {h1} / {h2} | "
                     f"{caught} of {len(r.mutants)} ({_pct(caught, len(r.mutants))}) | {captcha_fails} |")
    lines += [
        f"| **All** | {total_tests} | {total_checked} | {total_false} | "
        f"{total_caught} of {total_mutants} ({_pct(total_caught, total_mutants)}) | |",
        "",
        "## Bugs, by scenario",
        "",
        "✔ caught · ✘ missed",
        "",
    ]
    for flow in ("login", "signup"):
        rs = [r for r in results if r.scenario.flow == flow]
        if not rs:
            continue
        lines += ["| Bug | " + " | ".join(f"`{r.scenario.key}`" for r in rs) + " |",
                  "| --- |" + " --- |" * len(rs)]
        for m, info in MUTANTS.items():
            if info["page"] == flow:
                lines.append(f"| `{m}` — {info['bug']} | " + " | ".join("✔" if r.caught(m) else "✘" for r in rs) + " |")
        lines.append("")
    lines += ["## Tests, by scenario", ""]
    for r in results:
        lines += [f"### `{r.scenario.key}`", "", f"{r.scenario.note} Goal: "
                  + (f"\"{r.scenario.goal}\"." if r.scenario.goal else "none."), "",
                  "| Test | Feature checks | Healthy run 1 | Healthy run 2 |", "| --- | --- | --- | --- |"]
        for t in r.tests:
            cells = []
            for cond in ("healthy-1", "healthy-2"):
                ok, err = t.runs[cond]
                cells.append("pass" if ok else f"**fail**: {err.replace('|', '/')[:90]}")
            lines.append(f"| {t.name} | {t.feature_checks} | " + " | ".join(cells) + " |")
        for name, outcomes in r.blocked.items():
            runs = "; ".join(f"{t.name}: " + ("pass" if t.runs[name][0] else f"**fail** ({t.runs[name][1][:80]})")
                             for t in outcomes)
            lines += ["", f"With a {name} on the form: {runs or 'no tests'}."]
        lines.append("")
    md_path.write_text("\n".join(lines), encoding="utf-8")

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["scenario", "test", "feature_checks", "condition", "passed", "error"])
        for r in results:
            for t in r.tests:
                for cond, (ok, err) in t.runs.items():
                    w.writerow([r.scenario.key, t.slug, t.feature_checks, cond, ok, err])
            for outcomes in r.blocked.values():
                for t in outcomes:
                    for cond, (ok, err) in t.runs.items():
                        w.writerow([r.scenario.key, t.slug, t.feature_checks, cond, ok, err])


async def main(argv: list[str] | None = None) -> list[ScenarioResult]:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--only", action="append", help="run just this scenario (repeatable)")
    parser.add_argument("--out", type=Path, default=DOCS, help="report folder (default docs/)")
    args = parser.parse_args(argv)
    scenarios = [s for s in SCENARIOS if not args.only or s.key in args.only]
    if not scenarios:
        parser.error(f"no scenario named {args.only}; choose from {[s.key for s in SCENARIOS]}")

    app = AuthApp()
    base = app.start()
    results: list[ScenarioResult] = []
    try:
        with tempfile.TemporaryDirectory() as artifacts:
            options = RunOptions(headless=True, artifacts_dir=artifacts, tracing_enabled=False)
            for s in scenarios:
                r = await run_scenario(app, base, s, options)
                results.append(r)
                caught = sum(r.caught(m) for m in r.mutants)
                print(f"{s.key:32} {len(r.tests)} tests - healthy fails {r.healthy_failures('healthy-1')}"
                      f"/{r.healthy_failures('healthy-2')} - caught {caught}/{len(r.mutants)} - {r.seconds:.0f}s",
                      flush=True)
    finally:
        app.stop()
    args.out.mkdir(parents=True, exist_ok=True)
    write_report(results, args.out / "generation-eval.md", args.out / "generation-eval.csv")
    print(f"Wrote {args.out / 'generation-eval.md'}")
    return results


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(main())
