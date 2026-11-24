"""
TestSphere-AI — Does a generated test catch anything?  (acceptance check)

A test that passes proves little until it is seen to fail when the thing it
checks is broken.  After a generated test passes, it runs once more on a
deliberately broken copy of its page: the text and elements its checks rely
on are removed as the page renders (``engine`` ``RunOptions.mutation``).  This
is the filter Meta's ACH applies to LLM-written tests ("catches a fault no
existing test catches"), on a page instead of code:

- **verified**        it failed on the broken page, at a check whose content
                      was removed: it really checks that content;
- **asserts_nothing** it still passed: its checks would pass on a broken page;
- **inconclusive**    it failed somewhere else (a flaky step, a sign-in it
                      depended on), so nothing is concluded either way;
- **unverifiable**    its checks are of a kind a broken page cannot show (the
                      URL, something being gone).

Healing is held back on that run (threshold 1.0), so a removed element is not
"healed" onto a look-alike that makes a good test look empty.  The verdict is
kept on the test case with the hash of the steps it judged; a test is checked
again only when its steps change, so each test costs one extra run once.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from app.database.store import Record, Store, now_iso
from app.models import TEST_CASES

logger = logging.getLogger("testsphere.acceptance")

VERIFIED, ASSERTS_NOTHING, INCONCLUSIVE, UNVERIFIABLE = "verified", "asserts_nothing", "inconclusive", "unverifiable"

_TEXT_CHECKS = ("ASSERT_CONTAINS_TEXT", "ASSERT_TEXT")
_ACTIONS = ("CLICK", "FILL", "PRESS", "SELECT", "CHECK", "UNCHECK", "HOVER", "UPLOAD", "DRAG")
_TRIVIAL = {"", "body", "html", "head > title", "title", "main"}
# Playwright-only selector syntax the browser's querySelectorAll cannot run
_NOT_CSS = (":has-text(", ":text(", ":text-is(", ":text-matches(", ">>", "text=", "role=", ":visible", "xpath=")


def steps_of(tc: Record) -> list[dict[str, Any]]:
    try:
        return list(json.loads(tc.get("description") or "{}").get("steps") or [])
    except (ValueError, AttributeError):
        return []


def steps_key(steps: list[dict[str, Any]]) -> str:
    essence = [(s.get("action"), s.get("target"), s.get("value")) for s in steps]
    return hashlib.sha256(json.dumps(essence).encode()).hexdigest()[:16]


def needs_check(tc: Record) -> bool:
    """Whether *tc*'s current steps have no verdict yet."""
    steps = steps_of(tc)
    return bool(steps) and (tc.get("acceptance") or {}).get("steps_key") != steps_key(steps)


def mutation_for(steps: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """(texts, selectors) to remove so that the test's checks have nothing to find."""
    acted_on = {s.get("target") for s in steps if str(s.get("action", "")).upper() in _ACTIONS}
    texts: list[str] = []
    selectors: list[str] = []
    for s in steps:
        action = str(s.get("action", "")).upper()
        target = str(s.get("target") or "").strip()
        if action in _TEXT_CHECKS:
            value = str(s.get("value") or s.get("expected") or "").strip()
            if len(value) >= 3:
                texts.append(value)
        elif action == "ASSERT_VISIBLE" and target.lower() not in _TRIVIAL and target not in acted_on \
                and not any(token in target for token in _NOT_CSS):
            selectors.append(target)
    return list(dict.fromkeys(texts)), list(dict.fromkeys(selectors))


def judge(plan: Any, result: Any, texts: list[str], selectors: list[str]) -> str:
    """The verdict for a run on the broken page."""
    from engine.schemas import ActionType, StepStatus, TestStatus

    if result.status in (TestStatus.PASSED, TestStatus.HEALED):
        return ASSERTS_NOTHING
    failed = next((r for r in result.steps if r.status == StepStatus.FAILED), None)
    step = next((s for s in plan.steps if failed is not None and s.step_id == failed.step_id), None)
    if step is None:
        return INCONCLUSIVE
    lowered = [t.casefold() for t in texts]
    if step.action == ActionType.ASSERT_TEXT and (step.expected or "").casefold() in lowered:
        return VERIFIED
    if step.action == ActionType.ASSERT_VISIBLE and step.target is not None and step.target.primary_locator in selectors:
        return VERIFIED
    return INCONCLUSIVE


async def check(tc: Record, base_url: str, *, runner: Any = None) -> dict[str, Any]:
    """Run *tc* on a broken copy of its page and return its verdict record."""
    from agents.planner.schemas import TestCase as Member1TestCase
    from app.orchestration.converters import test_case_to_engine_plan
    from app.orchestration.orchestrator import parse_stored_steps
    from engine.runner import run_test
    from engine.schemas import PageMutation, RunOptions

    steps = steps_of(tc)
    record = {"steps_key": steps_key(steps), "checked_at": now_iso()}
    texts, selectors = mutation_for(steps)
    if not (texts or selectors):
        return {**record, "status": UNVERIFIABLE,
                "detail": "Its checks (the URL, something being gone) cannot be shown on a broken page."}
    m1_steps, assertions = parse_stored_steps(steps, base_url)
    case = Member1TestCase(test_id=f"accept-{tc['id']}", name=tc.get("name") or "test", page_url=base_url,
                           steps=m1_steps, assertions=assertions)
    plan = test_case_to_engine_plan(case, base_url)
    options = RunOptions(headless=True, heal_threshold=1.0, quick_heal_ms=0,
                         mutation=PageMutation(hide_texts=texts, hide_selectors=selectors))
    result = await (runner or run_test)(plan, options)
    verdict = judge(plan, result, texts, selectors)
    detail = {
        VERIFIED: "It failed when what it checks was removed from the page.",
        ASSERTS_NOTHING: "It still passed with what it checks removed from the page: its checks prove nothing.",
        INCONCLUSIVE: "On the broken page it failed before reaching its checks; nothing concluded.",
    }[verdict]
    return {**record, "status": verdict, "detail": detail, "removed": {"texts": texts, "selectors": selectors}}


async def check_new_tests(db: Store, test_cases: list[Record], results: list[dict[str, Any]], base_url: str,
                          *, limit: int, runner: Any = None) -> dict[str, int]:
    """Check up to *limit* tests that passed this run and have no verdict for their
    current steps; store each verdict.  Returns how many got each verdict."""
    passed = {r["test_case_id"] for r in results if r.get("status") in ("PASSED", "HEALED")}
    due = [tc for tc in test_cases if tc["id"] in passed and needs_check(tc)][:limit]
    counts: dict[str, int] = {}
    for tc in due:
        try:
            verdict = await check(tc, base_url, runner=runner)
        except Exception as exc:  # noqa: BLE001 - a check that crashed decides nothing
            logger.warning("Acceptance check of test case %s failed: %s", tc["id"], exc)
            continue
        db.update(TEST_CASES, tc["id"], acceptance=verdict)
        counts[verdict["status"]] = counts.get(verdict["status"], 0) + 1
    return counts


# Consecutive passing runs (on the same steps) a quarantined test needs, on top
# of a "verified" verdict, before it may fail a run
TRUST_PASSES = 2


def graduate(db: Store, test_cases: list[Record], results: list[dict[str, Any]],
             *, passes_needed: int = TRUST_PASSES) -> list[Record]:
    """Count each test's consecutive passes on its current steps and lift the
    quarantine of the tests that earned trust: their current steps are
    ``verified`` (they fail when what they check is removed from the page) and
    they passed the last *passes_needed* runs.  A quarantine a person set
    (``quarantine_pinned``) is theirs to lift.  Returns the graduated tests."""
    outcome = {r["test_case_id"]: r.get("status") for r in results}
    graduated: list[Record] = []
    for tc in test_cases:
        status = outcome.get(tc["id"])
        if status is None:
            continue
        steps = steps_of(tc)
        key = steps_key(steps) if steps else None
        trust = tc.get("trust") or {}
        passes = int(trust.get("passes") or 0) if trust.get("steps_key") == key else 0
        passes = passes + 1 if status in ("PASSED", "HEALED") else 0
        changes: dict[str, Any] = {"trust": {"steps_key": key, "passes": passes}}
        verified = (tc.get("acceptance") or {}).get("status") == VERIFIED             and (tc.get("acceptance") or {}).get("steps_key") == key
        if tc.get("quarantined") and not tc.get("quarantine_pinned") and verified and passes >= passes_needed:
            changes["quarantined"] = False
            changes["trust"]["graduated_at"] = now_iso()
        row = db.update(TEST_CASES, tc["id"], **changes)
        if changes.get("quarantined") is False:
            graduated.append(row or tc)
    return graduated
