"""
Test Studio eval: do tests written in plain English catch the bugs they describe?

    python -m scripts.studio_eval                  # the configured planner (rules without an AI model)
    python -m scripts.studio_eval --gate 0.6       # exit 1 below 60% of bugs caught, or on any false alarm

Each case is an instruction a tester would type in Test Studio, on a page of
``tests/fixtures/auth_app.py``, with the bugs of that site it describes.  For
every case this does what Test Studio does: analyzes the page with the
instruction as its goal, drafts the steps (the AI model when one is
configured, else the rule-based planner), checks them against the page and
stores them; then runs the test in Chromium:

1. on the healthy site: it must pass (a failure is a **false alarm**);
2. with each bug it describes switched on, on a fresh site: a failure
   **catches** the bug.

A draft that cannot be saved (an invalid step, no check) counts as missing
every bug it should catch.  Writes docs/studio-eval.md and docs/studio-eval.csv.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

os.environ.setdefault("ALLOW_PRIVATE_TARGETS", "true")  # the site is on 127.0.0.1

from app.services import test_studio as studio  # noqa: E402
from app.services.url_analyzer import URLAnalyzerService  # noqa: E402
from engine.schemas import RunOptions  # noqa: E402
from scripts.generation_eval import _run  # noqa: E402
from tests.fixtures.auth_app import MUTANTS, USER_EMAIL, USER_PASSWORD, AuthApp  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "docs"


@dataclass
class Case:
    id: str
    path: str
    instruction: str
    catches: list[str]
    held_out: bool = False  # written after the planner was tuned on the others, never tuned on


CASES = [
    Case("sign-in", "/login", f"Log in with {USER_EMAIL} and password {USER_PASSWORD} and check the page shows "
         f"Signed in as {USER_EMAIL}", ["login-rejects-valid"]),
    Case("wrong-password", "/login", f"Log in with {USER_EMAIL} and password Wrong-Pass-123 and check an error "
         "message is shown", ["login-accepts-wrong-password", "login-no-error-message"]),
    Case("empty-submit", "/login", "Click Sign in without filling anything and check the page still shows "
         "Sign in to your account", ["login-empty-submit"]),
    Case("log-out", "/login", f"Log in with {USER_EMAIL} and password {USER_PASSWORD}, click Log out, open /account "
         "and check the page does not show Signed in as", ["logout-broken"]),
    Case("reload", "/login", f"Log in with {USER_EMAIL} and password {USER_PASSWORD}, reload the page and check it "
         f"still shows Signed in as {USER_EMAIL}", ["session-lost-on-reload"]),
    Case("password-hidden", "/login", "Check the password field hides what is typed", ["password-visible"]),
    Case("sign-up", "/signup", "Sign up with name Ann Lee, email ann.lee@testsphere.test, password Strong-Pass-42, "
         "confirm Strong-Pass-42, accept the terms and check the page shows Account created",
         ["signup-broken", "signup-no-confirmation"]),
    Case("password-mismatch", "/signup", "Sign up with name Ann Lee, email ann.lee@testsphere.test, password "
         "Strong-Pass-42 and confirm Other-Pass-99, accept the terms and check the page does not show Account created",
         ["signup-mismatch-accepted"]),
    Case("duplicate-email", "/signup", f"Sign up with name Demo, email {USER_EMAIL}, password Strong-Pass-42, confirm "
         "Strong-Pass-42, accept the terms and check the page shows already exists", ["signup-duplicate-crash"]),
    Case("invalid-email", "/signup", "Sign up with name Ann Lee, email not-an-email, password Strong-Pass-42, confirm "
         "Strong-Pass-42, accept the terms and check the page does not show Account created",
         ["signup-invalid-email-accepted"]),
    # Held out: phrased differently, added after the rule-based planner was improved on the cases above
    Case("store-sign-in", "/store/login", f"Sign in using {USER_EMAIL} with password {USER_PASSWORD} then verify "
         "that the page says Your account", ["login-rejects-valid"], held_out=True),
    Case("bad-login", "/store/login", f"Try to sign in with {USER_EMAIL} and password nope-nope-1 and make sure an error "
         "is displayed", ["login-accepts-wrong-password", "login-no-error-message"], held_out=True),
    Case("signup-welcome", "/signup", "Create an account with name Bo Chen, email bo.chen@testsphere.test, password "
         "Lime-Tree-88, confirm Lime-Tree-88, agree to the terms and ensure the page shows Welcome aboard",
         ["signup-broken", "signup-no-confirmation"], held_out=True),
    Case("signup-dup", "/signup", f"Register with name Demo, email {USER_EMAIL}, password Lime-Tree-88, confirm "
         "Lime-Tree-88, accept the terms and check that an error message is shown", ["signup-duplicate-crash"], held_out=True),
    Case("account-after-reload", "/login", f"Log in with {USER_EMAIL} and password {USER_PASSWORD}, refresh and "
         "confirm the page still shows Your account", ["session-lost-on-reload"], held_out=True),
]
assert all(m in MUTANTS for c in CASES for m in c.catches)


@dataclass
class CaseResult:
    case: Case
    source: str = ""
    saveable: bool = False
    problems: list[str] = field(default_factory=list)
    steps: int = 0
    healthy: tuple[bool, str] = (False, "")
    caught: dict[str, bool] = field(default_factory=dict)
    seconds: float = 0.0


async def draft(case: Case, url: str, use_model: bool) -> tuple[str, dict, list[dict]]:
    analysis = await URLAnalyzerService.analyze_live_website(url=url, prompt=case.instruction)
    if use_model:
        from app.config import settings
        from app.orchestration.orchestrator import create_platform_llm_client

        try:
            d = await studio.draft_with_model(case.instruction, analysis, create_platform_llm_client(),
                                              timeout=settings.PIPELINE_AI_PLANNER_TIMEOUT)
            return "ai", d, studio.check_steps(d["steps"], analysis, url)
        except Exception as exc:  # noqa: BLE001 - reported as a rules draft, as Test Studio does
            print(f"  model failed ({type(exc).__name__}); rules instead", file=sys.stderr)
    d = studio.draft_with_rules(case.instruction, analysis)
    return "rules", d, studio.check_steps(d["steps"], analysis, url)


async def run_case(app: AuthApp, base: str, case: Case, use_model: bool, options: RunOptions) -> CaseResult:
    started = time.monotonic()
    url = f"{base}{case.path}"
    result = CaseResult(case)
    app.reset()
    app.set_mutant(None)
    result.source, _, checked = await draft(case, url, use_model)
    result.steps = len(checked)
    result.problems = studio.blocking(checked)
    result.saveable = not result.problems
    if result.saveable:
        test = {"slug": case.id, "name": case.instruction[:80], "steps": studio.stored_steps(checked, url)}
        app.reset()
        result.healthy = await _run(test, url, options)
        for bug in case.catches:
            app.reset()
            app.set_mutant(bug)
            ok, _ = await _run(test, url, options)
            result.caught[bug] = not ok
        app.set_mutant(None)
    else:
        result.caught = {bug: False for bug in case.catches}
    result.seconds = time.monotonic() - started
    return result


def summary(results: list[CaseResult]) -> dict[str, float | int]:
    """Totals over *results* (call with the tuned or held-out cases alone for their own numbers)."""
    saveable = [r for r in results if r.saveable]
    healthy = [r for r in saveable if r.healthy[0]]
    bugs = [c for r in results for c in r.caught.values()]
    # A bug caught by a test that also fails the healthy site proves nothing
    real = [ok and r.healthy[0] for r in results for ok in r.caught.values()]
    return {"cases": len(results), "saveable": len(saveable), "healthy_pass": len(healthy),
            "false_alarms": len(saveable) - len(healthy), "bugs": len(bugs), "caught": sum(real),
            "catch_rate": sum(real) / len(bugs) if bugs else 0.0}


def write_report(results: list[CaseResult], source: str, md: Path, csv_path: Path) -> dict:
    s = summary(results)
    tuned = summary([r for r in results if not r.case.held_out])
    held = summary([r for r in results if r.case.held_out])
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["case", "held_out", "page", "planner", "saveable", "steps", "healthy_pass", "bug", "caught", "instruction"])
        for r in results:
            for bug, ok in (r.caught or {"": False}).items():
                w.writerow([r.case.id, r.case.held_out, r.case.path, r.source, r.saveable, r.steps, r.healthy[0], bug,
                            ok and r.healthy[0], r.case.instruction])
    lines = [
        "# Test Studio eval: plain-English tests against real bugs", "",
        f"{s['cases']} instructions a tester would type, on a local login and sign-up site, each with the bugs it "
        f"describes ({s['bugs']} bugs). Planner: **{source}**. Generated by `python -m scripts.studio_eval`.", "",
        "A bug is **caught** when the test passes on the healthy site and fails with that bug switched on. A test "
        "that fails the healthy site is a **false alarm**, and catches nothing.", "",
        "| Result | Value |", "| :--- | ---: |",
        f"| Instructions turned into a saveable test | {s['saveable']} of {s['cases']} |",
        f"| Saveable tests that pass on the healthy site | {s['healthy_pass']} of {s['saveable']} |",
        f"| False alarms | {s['false_alarms']} |",
        f"| **Bugs caught** | **{s['caught']} of {s['bugs']} ({s['catch_rate'] * 100:.0f}%)** |",
        f"| Bugs caught, cases the planner was improved on ({tuned['cases']}) | {tuned['caught']} of {tuned['bugs']} |",
        f"| **Bugs caught, held-out cases ({held['cases']}, never tuned on)** | **{held['caught']} of {held['bugs']}** |", "",
        "The rule-based planner was improved while looking at the first cases; the held-out cases were written "
        "afterwards, in different words, as a fairer measure of instructions it has not seen, and the planner was not "
        "changed for them. The held-out miss is in the instruction itself: the text it checks, \"Your account\", is "
        "also on the sign-in page the bug sends you to (\"Sign in to your account\"; text checks ignore case), so no "
        "test written from it can tell the two pages apart. Checking \"Signed in as\" would.", "",
        "| Case | Planner | Steps | Healthy site | Bugs caught | Why not |", "| :--- | :--- | ---: | :--- | :--- | :--- |",
    ]
    for r in results:
        caught = ", ".join(f"{b} {'✓' if ok and r.healthy[0] else '✗'}" for b, ok in r.caught.items())
        why = "; ".join(r.problems)[:140] if not r.saveable else ("" if r.healthy[0] else f"fails healthy: {r.healthy[1]}"[:140])
        lines.append(f"| {r.case.id}{' (held out)' if r.case.held_out else ''} | {r.source} | {r.steps} | {'passes' if r.healthy[0] else ('—' if not r.saveable else 'FAILS')} "
                     f"| {caught} | {why.replace('|', '/')} |")
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return s


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="run one case")
    parser.add_argument("--rules", action="store_true", help="the rule-based planner even when a model is configured")
    parser.add_argument("--gate", type=float, default=None, help="exit 1 below this share of bugs caught or on any false alarm")
    parser.add_argument("--no-report", action="store_true")
    args = parser.parse_args(argv)

    from agents.llm.config import LLMConfig

    use_model = not args.rules and LLMConfig.from_env().provider != "mock"
    cases = [c for c in CASES if not args.only or c.id == args.only]
    app = AuthApp()
    base = app.start()
    options = RunOptions(headless=True, min_action_timeout_ms=2000)
    results = []
    try:
        for case in cases:
            r = await run_case(app, base, case, use_model, options)
            results.append(r)
            print(f"{case.id:18} {r.source:5} saveable={r.saveable} healthy={r.healthy[0]} "
                  f"caught={sum(v for v in r.caught.values())}/{len(r.caught)} ({r.seconds:.1f}s)")
    finally:
        app.stop()
    source = "AI model" if use_model else "rule-based (no AI model)"
    s = (summary(results) if args.no_report or args.only else
         write_report(results, source, DOCS / "studio-eval.md", DOCS / "studio-eval.csv"))
    print(f"caught {s['caught']}/{s['bugs']} ({s['catch_rate'] * 100:.0f}%), false alarms {s['false_alarms']}")
    if args.gate is not None and (s["catch_rate"] < args.gate or s["false_alarms"]):
        print(f"GATE FAILED: need >= {args.gate * 100:.0f}% of bugs caught and no false alarm", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
