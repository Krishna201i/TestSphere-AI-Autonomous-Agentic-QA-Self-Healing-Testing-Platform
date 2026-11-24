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
from typing import Any
from urllib.parse import urljoin, urlparse

from app.config import settings

logger = logging.getLogger("testsphere.ai_plan")

MAX_AI_TESTS = 5
_ACTIONS = {"navigate": "NAVIGATE", "click": "CLICK", "fill": "FILL", "press": "PRESS", "select": "SELECT",
            "check": "CHECK", "uncheck": "UNCHECK", "hover": "HOVER", "upload": "UPLOAD", "drag": "DRAG", "wait": "WAIT"}
_CHECKS = {"element_visible": "ASSERT_VISIBLE", "element_not_visible": "ASSERT_HIDDEN",
           "element_contains_text": "ASSERT_CONTAINS_TEXT", "element_has_text": "ASSERT_HAS_TEXT",
           "url_contains": "ASSERT_URL", "url_equals": "ASSERT_URL_EQUALS", "value_equals": "ASSERT_VALUE"}
_PAGE_CHECKS = {"ASSERT_URL", "ASSERT_URL_EQUALS"}
_ANY_PAGE = {"body", "head > title", "title", "h1", "main"}


def enabled() -> bool:
    from agents.llm.config import LLMConfig

    mode = settings.PIPELINE_AI_PLANNER
    return mode == "on" or (mode == "auto" and LLMConfig.from_env().provider != "mock")


def _profile_note(profile: Any) -> str:
    """What the project's profile asks of the planner; never a password."""
    if profile is None:
        return ""
    note = f" Kinds of tests wanted: {', '.join(profile.test_types)}."
    data = {k: v for k, v in profile.test_data.items() if k != "password"}
    if data:
        note += " Type these values where a field asks for them: " + ", ".join(f"{k} = {v!r}" for k, v in data.items()) + "."
    return note


def _elements(analysis: dict[str, Any]) -> list[Any]:
    from agents.planner.schemas import ElementContext

    inv = analysis.get("elements_inventory") or {}
    elements = [ElementContext(tag="input", id=i.get("id") or None, name=i.get("name") or None, type=i.get("type"),
                               placeholder=i.get("placeholder") or None, selector=i["selector"])
                for i in inv.get("inputs") or [] if i.get("selector")]
    elements += [ElementContext(tag="button", id=b.get("id") or None, type=b.get("type"), text=b.get("text") or None,
                                selector=b["selector"])
                 for b in inv.get("buttons") or [] if b.get("selector") and b["selector"] != "button"]
    return elements


def _page(url: str, analysis: dict[str, Any]) -> Any:
    from agents.planner.schemas import PageContext

    inv = analysis.get("elements_inventory") or {}
    headings = [h for h in inv.get("headings") or [] if h][:4]
    return PageContext(url=urlparse(url).path or "/", title=analysis.get("page_title") or "",
                       description=("Headings on this page: " + " | ".join(headings)) if headings else "",
                       elements=_elements(analysis), navigation_elements=list((inv.get("links") or [])[:15]))


def page_context(analysis: dict[str, Any], prompt: str | None, frameworks: list[str] | None = None,
                 profile: Any = None, pages: dict[str, dict[str, Any]] | None = None):
    """The planner's view of the app: the analyzed start page, then every other
    same-site page this run analyzed (a journey may move between them)."""
    from agents.planner.schemas import ApplicationContext

    url = analysis["url"]
    others = [_page(u, a) for u, a in (pages or {}).items() if _path(u) != _path(url)]
    return ApplicationContext(
        app_name=analysis.get("page_title") or urlparse(url).netloc,
        app_url=url,
        description=(f"Goal: {prompt}. " if prompt else "") + (analysis.get("meta_description") or "")
        + _profile_note(profile)
        + (" The test starts on the first page. To move to another listed page, use navigate with that page's url."
           if others else ""),
        pages=[_page(url, analysis), *others],
        technology_stack=frameworks or [],
    )


def _path(url: str) -> str:
    return (urlparse(url).path or "/").rstrip("/") or "/"


def _known(analysis: dict[str, Any]) -> set[str]:
    inv = analysis.get("elements_inventory") or {}
    return {e["selector"] for e in [*(inv.get("inputs") or []), *(inv.get("buttons") or [])] if e.get("selector")} | _ANY_PAGE


_INTERACTIONS = {"CLICK", "FILL", "PRESS", "SELECT", "CHECK", "UNCHECK", "HOVER", "UPLOAD", "DRAG"}
_SUBMITS = {"CLICK", "PRESS"}


def weak_reason(steps: list[dict[str, Any]]) -> str | None:
    """Why a planned test proves too little to keep, or None.

    A test must check something a broken page would get wrong: a check that
    only the page body or title exists passes on any page.  A test that clicks
    or presses must check what happened afterwards; filling a form and never
    looking at the result tests nothing."""
    checks = [(i, s) for i, s in enumerate(steps) if s["action"].startswith("ASSERT")]
    meaningful = [(i, s) for i, s in checks
                  if not (s["action"] in ("ASSERT_VISIBLE", "ASSERT_HIDDEN") and s.get("target") in _ANY_PAGE)]
    if not meaningful:
        return "no check beyond the page existing"
    submits = [i for i, s in enumerate(steps) if s["action"] in _SUBMITS]
    if submits and not any(i > submits[-1] for i, _ in meaningful):
        return "nothing checked after its last click or key press"
    return None


def to_suite_tests(cases: list[Any], analysis: dict[str, Any],
                   pages: dict[str, dict[str, Any]] | None = None) -> tuple[list[dict[str, Any]], int]:
    """Planner test cases as pipeline tests; returns (kept, dropped).

    A test is dropped, never shortened, when a step or check touches an
    element the analysis did not find on the page the test is on, goes to a
    page no analysis saw, has no engine equivalent, or checks nothing that a
    broken page would get wrong (``weak_reason``): running what is left would
    test something else.
    """
    url = analysis["url"]
    by_path = {_path(u): (u, _known(a)) for u, a in (pages or {}).items()}
    by_path[_path(url)] = (url, _known(analysis))
    kept, dropped = [], 0
    for tc in cases[:20]:  # the profile's max_ai_tests limits what is kept (app/pipeline/profile.py)
        steps: list[dict[str, Any]] = [{"step_number": 1, "action": "NAVIGATE", "value": url, "target": None,
                                        "description": f"Open {url}"}]
        known = by_path[_path(url)][1]
        ok = True
        for s in tc.steps:
            action = _ACTIONS.get(s.action.value)
            if action is None:
                ok = False
                break
            if action == "NAVIGATE":
                dest = urljoin(url, str(s.value or ""))
                if urlparse(dest).netloc != urlparse(url).netloc or _path(dest) not in by_path:
                    ok = False  # a page no analysis saw: its elements are guesses
                    break
                page_url, known = by_path[_path(dest)]
                if len(steps) == 1 and page_url == url:
                    continue  # the test already starts here
                steps.append({"step_number": len(steps) + 1, "action": "NAVIGATE", "target": None, "value": page_url,
                              "description": s.description or f"Open {page_url}"})
                continue
            if s.target and s.target not in known:
                ok = False
                break
            steps.append({"step_number": len(steps) + 1, "action": action, "target": s.target, "value": s.value,
                          "description": s.description or f"{action.lower()} {s.target or ''}".strip()})
            for a in s.assertions:
                ok = ok and _add_check(steps, a, known)
        for a in tc.assertions:
            ok = ok and _add_check(steps, a, known)
        if not ok or len(steps) < 2 or weak_reason(steps):
            dropped += 1
            continue
        kept.append({"slug": f"ai-{_steps_key(steps)}", "name": f"AI: {tc.name}"[:120], "category": "ai",
                     "steps": steps})
    return kept, dropped



def _steps_key(steps: list[dict[str, Any]]) -> str:
    """A test's identity: its steps, not the id the model gave it.  The model's
    ids change from run to run (a new row each time) and get reused for other
    steps (overwriting a test someone had trusted); the same steps keep one row."""
    import hashlib
    import json

    essence = [(s.get("action"), s.get("target"), s.get("value")) for s in steps]
    return hashlib.sha256(json.dumps(essence).encode()).hexdigest()[:12]

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
                   planner: Any = None, timeout: float | None = None, profile: Any = None,
                   pages: dict[str, dict[str, Any]] | None = None) -> tuple[list[dict[str, Any]], str | None]:
    """Extra tests from the planner agent and a note for the plan stage (None when the planner is off)."""
    if planner is None and not enabled():
        return [], None
    try:
        if planner is None:
            from agents.planner.planner import LLMTestPlanner
            from app.orchestration.orchestrator import create_platform_llm_client

            planner = LLMTestPlanner(llm_client=create_platform_llm_client())
        plan = await asyncio.wait_for(
            planner.generate_test_plan(page_context(analysis, prompt, frameworks, profile, pages),
                                       max_tests=profile.max_ai_tests if profile is not None else MAX_AI_TESTS),
            timeout=timeout or settings.PIPELINE_AI_PLANNER_TIMEOUT)
    except Exception as exc:  # noqa: BLE001 - the rule-based suite still runs
        logger.warning("AI planner skipped: %s", exc)
        return [], f"AI planner skipped ({type(exc).__name__}: {str(exc)[:120] or 'no answer'})"
    tests, dropped = to_suite_tests(list(plan.test_cases), analysis, pages)
    note = f"AI planner added {len(tests)} test(s), quarantined until you trust them" if tests else "AI planner added no tests"
    if dropped:
        note += f", dropped {dropped} that used elements not on their page or checked nothing a broken page would fail"
    return tests, note
