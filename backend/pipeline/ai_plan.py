"""
TestSphere-AI — The LLM Test Planner in the automated pipeline (plan stage).

The rule-based suite (``suite.py``) always runs.  When a real model is
configured (``LLM_PROVIDER`` local or api; ``PIPELINE_AI_PLANNER`` = auto, on
or off), the planner agent (``agents/planner``) is asked for extra tests from
the same page analysis and the written goal.  Its tests are kept only when
every element they touch is one the analysis found on the page: a model that
invents a selector loses that test, never the run.  Any planner failure or
timeout leaves the rule-based suite as it was and says why in the plan stage.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any
from urllib.parse import urlparse

from backend.config import settings

logger = logging.getLogger("testsphere.ai_plan")

MAX_AI_TESTS = 5
_ACTIONS = {"navigate": "NAVIGATE", "click": "CLICK", "fill": "FILL", "press": "PRESS", "select": "SELECT",
            "check": "CHECK", "uncheck": "UNCHECK", "wait": "WAIT"}
_CHECKS = {"element_visible": "ASSERT_VISIBLE", "element_not_visible": "ASSERT_HIDDEN",
           "element_contains_text": "ASSERT_CONTAINS_TEXT", "element_has_text": "ASSERT_HAS_TEXT",
           "url_contains": "ASSERT_URL", "url_equals": "ASSERT_URL_EQUALS", "value_equals": "ASSERT_VALUE"}
_PAGE_CHECKS = {"ASSERT_URL", "ASSERT_URL_EQUALS"}
_ANY_PAGE = {"body", "head > title", "title", "h1", "main"}


def enabled() -> bool:
    from agents.llm.config import LLMConfig

    mode = settings.PIPELINE_AI_PLANNER
    return mode == "on" or (mode == "auto" and LLMConfig.from_env().provider != "mock")


def page_context(analysis: dict[str, Any], prompt: str | None, frameworks: list[str] | None = None):
    """The planner's view of the analyzed page."""
    from agents.planner.schemas import ApplicationContext, ElementContext, PageContext

    inv = analysis.get("elements_inventory") or {}
    elements = [ElementContext(tag="input", id=i.get("id") or None, name=i.get("name") or None, type=i.get("type"),
                               placeholder=i.get("placeholder") or None, selector=i["selector"])
                for i in inv.get("inputs") or [] if i.get("selector")]
    elements += [ElementContext(tag="button", id=b.get("id") or None, type=b.get("type"), text=b.get("text") or None,
                                selector=b["selector"])
                 for b in inv.get("buttons") or [] if b.get("selector") and b["selector"] != "button"]
    url = analysis["url"]
    return ApplicationContext(
        app_name=analysis.get("page_title") or urlparse(url).netloc,
        app_url=url,
        description=(f"Goal: {prompt}. " if prompt else "") + (analysis.get("meta_description") or ""),
        pages=[PageContext(url=urlparse(url).path or "/", title=analysis.get("page_title") or "", elements=elements,
                           navigation_elements=list((inv.get("links") or [])[:15]))],
        technology_stack=frameworks or [],
    )


def to_suite_tests(cases: list[Any], analysis: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    """Planner test cases as pipeline tests; returns (kept, dropped).

    A test is dropped, never shortened, when a step or check touches an
    element the analysis did not find or has no engine equivalent: running
    what is left would test something else.
    """
    inv = analysis.get("elements_inventory") or {}
    known = {e["selector"] for e in [*(inv.get("inputs") or []), *(inv.get("buttons") or [])] if e.get("selector")} | _ANY_PAGE
    url = analysis["url"]
    kept, dropped = [], 0
    for tc in cases[:MAX_AI_TESTS]:
        steps: list[dict[str, Any]] = [{"step_number": 1, "action": "NAVIGATE", "value": url, "target": None,
                                        "description": f"Open {url}"}]
        ok = True
        for s in tc.steps:
            action = _ACTIONS.get(s.action.value)
            if action is None:
                ok = False
                break
            if action == "NAVIGATE":
                continue  # the test starts on the analyzed page; it never leaves the site
            if s.target and s.target not in known:
                ok = False
                break
            steps.append({"step_number": len(steps) + 1, "action": action, "target": s.target, "value": s.value,
                          "description": s.description or f"{action.lower()} {s.target or ''}".strip()})
            for a in s.assertions:
                ok = ok and _add_check(steps, a, known)
        for a in tc.assertions:
            ok = ok and _add_check(steps, a, known)
        if not ok or len(steps) < 2:
            dropped += 1
            continue
        slug = re.sub(r"[^a-z0-9]+", "-", tc.test_id.lower()).strip("-")[:40] or str(len(kept) + 1)
        kept.append({"slug": f"ai-{slug}", "name": f"AI: {tc.name}"[:120], "category": "ai", "steps": steps})
    return kept, dropped


def _add_check(steps: list[dict[str, Any]], assertion: Any, known: set[str]) -> bool:
    action = _CHECKS.get(assertion.type.value)
    if action is None:
        return False
    if action not in _PAGE_CHECKS and assertion.target not in known:
        return False
    steps.append({"step_number": len(steps) + 1, "action": action, "target": assertion.target or None,
                  "value": assertion.expected or None, "description": assertion.description or action.lower()})
    return True


async def ai_tests(analysis: dict[str, Any], prompt: str | None, frameworks: list[str] | None = None, *,
                   planner: Any = None, timeout: float | None = None) -> tuple[list[dict[str, Any]], str | None]:
    """Extra tests from the planner agent and a note for the plan stage (None when the planner is off)."""
    if planner is None and not enabled():
        return [], None
    try:
        if planner is None:
            from agents.planner.planner import LLMTestPlanner
            from backend.orchestration.orchestrator import create_platform_llm_client

            planner = LLMTestPlanner(llm_client=create_platform_llm_client())
        plan = await asyncio.wait_for(
            planner.generate_test_plan(page_context(analysis, prompt, frameworks), max_tests=MAX_AI_TESTS),
            timeout=timeout or settings.PIPELINE_AI_PLANNER_TIMEOUT)
    except Exception as exc:  # noqa: BLE001 - the rule-based suite still runs
        logger.warning("AI planner skipped: %s", exc)
        return [], f"AI planner skipped ({type(exc).__name__}: {str(exc)[:120] or 'no answer'})"
    tests, dropped = to_suite_tests(list(plan.test_cases), analysis)
    note = f"AI planner added {len(tests)} test(s), quarantined until you trust them" if tests else "AI planner added no tests"
    if dropped:
        note += f", dropped {dropped} that used elements not on the page"
    return tests, note
