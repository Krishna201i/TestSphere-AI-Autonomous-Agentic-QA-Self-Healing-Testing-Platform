"""
TestSphere-AI — Test Studio: tests written in plain English.

A user describes a test ("log in as demo / secret, add the backpack to the
cart, check the cart shows 1").  This module

* asks the model (Groq or any configured provider) to turn the description
  into the platform's stored steps, given the live page's elements; with no
  real model, or when the model fails, the rule-based goal planner answers;
* checks every step against the page before anything runs, and says how each
  one will find its element (``status``):

    found       the element is on the analyzed page
    text        found by its visible text when the test runs (a later page)
    page        needs no element (open a page, check the URL, reload ...)
    unverified  a selector the analysis did not see: kept, but the test is
                saved quarantined (it reports, it cannot fail a run)
    invalid     cannot run as written (unknown action, missing value, a page
                on another site): the test cannot be saved

* exports a saved test as a Playwright ``.spec.ts`` file.

Steps are data the engine interprets, never code: a model that is fooled by
the page (the page text is fenced as untrusted) can only propose steps from a
fixed vocabulary, on the project's own site, which the user reviews.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urljoin, urlparse

MAX_STEPS = 40
MAX_INSTRUCTION = 2000
MAX_VALUE = 2000
MAX_TARGET = 500
MAX_PROMPT_ELEMENTS = 40

# Stored actions the engine runs (app/orchestration/orchestrator.py parse_stored_steps)
ACTIONS: dict[str, str] = {
    "NAVIGATE": "open a page of the site (value: path or URL on the same site)",
    "CLICK": "click an element",
    "FILL": "type value into a field",
    "PRESS": "press a key (value: e.g. Enter); target optional",
    "SELECT": "choose value in a dropdown",
    "CHECK": "tick a checkbox",
    "UNCHECK": "untick a checkbox",
    "HOVER": "move the mouse over an element",
    "WAIT": "wait (value: milliseconds, or empty to let the page settle)",
    "RELOAD": "reload the page",
    "GO_BACK": "go back in history",
    "ASSERT_VISIBLE": "the element is shown",
    "ASSERT_HIDDEN": "the element is not shown",
    "ASSERT_CONTAINS_TEXT": "the element's text contains value",
    "ASSERT_HAS_TEXT": "the element's text is exactly value",
    "ASSERT_VALUE": "the field's value is exactly value",
    "ASSERT_URL": "the page URL contains value",
    "ASSERT_URL_EQUALS": "the page URL is exactly value",
}
_NEEDS_TARGET = {"CLICK", "FILL", "SELECT", "CHECK", "UNCHECK", "HOVER", "ASSERT_VISIBLE", "ASSERT_HIDDEN",
                 "ASSERT_CONTAINS_TEXT", "ASSERT_HAS_TEXT", "ASSERT_VALUE"}
_NEEDS_VALUE = {"FILL", "PRESS", "SELECT", "ASSERT_CONTAINS_TEXT", "ASSERT_HAS_TEXT", "ASSERT_VALUE",
                "ASSERT_URL", "ASSERT_URL_EQUALS"}
_NO_TARGET = {"NAVIGATE", "WAIT", "RELOAD", "GO_BACK", "ASSERT_URL", "ASSERT_URL_EQUALS"}
# Always present on a rendered page
_ANY_PAGE = {"body", "main", "h1", "title", "head > title"}
# Playwright resolves these by visible text when the step runs
_TEXT_SELECTOR = re.compile(r":has-text\(|:text\(|:text-is\(|:text-matches\(|^text=|^role=|^internal:(?:role|text|label|attr|testid)=", re.IGNORECASE)
_ALIASES = {"GOTO": "NAVIGATE", "OPEN": "NAVIGATE", "TYPE": "FILL", "ENTER": "FILL", "TAP": "CLICK",
            "WAIT_FOR": "WAIT", "BACK": "GO_BACK", "ASSERT_TEXT": "ASSERT_CONTAINS_TEXT",
            "ASSERT_NOT_VISIBLE": "ASSERT_HIDDEN", "ELEMENT_VISIBLE": "ASSERT_VISIBLE",
            "ELEMENT_NOT_VISIBLE": "ASSERT_HIDDEN", "ELEMENT_CONTAINS_TEXT": "ASSERT_CONTAINS_TEXT",
            "ELEMENT_HAS_TEXT": "ASSERT_HAS_TEXT", "URL_CONTAINS": "ASSERT_URL", "URL_EQUALS": "ASSERT_URL_EQUALS",
            "VALUE_EQUALS": "ASSERT_VALUE"}


# ---------------------------------------------------------------------------
# Checking steps against the page
# ---------------------------------------------------------------------------


def known_selectors(analysis: dict[str, Any]) -> set[str]:
    """Selectors of the elements the analysis found on the page."""
    inv = analysis.get("elements_inventory") or {}
    return {e["selector"] for e in [*(inv.get("inputs") or []), *(inv.get("buttons") or [])]
            if isinstance(e, dict) and e.get("selector")} | _ANY_PAGE


def _same_site(url: str, base_url: str) -> bool:
    a, b = urlparse(url), urlparse(base_url)
    return a.scheme in ("http", "https") and (a.hostname or "").lower() == (b.hostname or "").lower() \
        and (a.port or None) == (b.port or None)


def _selector(value: Any) -> str | None:
    """A target as one line, or None."""
    if value is None:
        return None
    return " ".join(str(value).split())[:MAX_TARGET] or None


def check_steps(raw_steps: list[Any], analysis: dict[str, Any], base_url: str) -> list[dict[str, Any]]:
    """*raw_steps* in the stored shape, numbered, each with ``status`` and ``note``.

    Never raises for a bad step: it is returned ``invalid`` with the reason,
    so the user sees every problem at once.
    """
    known = known_selectors(analysis)
    out: list[dict[str, Any]] = []
    for raw in list(raw_steps or [])[:MAX_STEPS]:
        s = raw if isinstance(raw, dict) else {}
        action = re.sub(r"[\s-]+", "_", str(s.get("action") or "").strip().upper())
        action = _ALIASES.get(action, action)
        target = _selector(s.get("target"))
        value = s.get("value")
        value = None if value is None else str(value)[:MAX_VALUE]
        description = str(s.get("description") or "").strip()[:300]
        step = {"step_number": len(out) + 1, "action": action, "target": target, "value": value,
                "description": description, "status": "page", "note": None}
        out.append(step)

        if action not in ACTIONS:
            step.update(status="invalid", note=f"Unknown action '{action or '(none)'}'.")
            continue
        if action in _NO_TARGET:
            step["target"] = None
        if action in _NEEDS_TARGET and not target:
            step.update(status="invalid", note="This action needs an element (target).")
            continue
        if action in _NEEDS_VALUE and (value is None or (value.strip() == "" and action != "FILL")):
            step.update(status="invalid", note="This action needs a value.")
            continue
        if action == "NAVIGATE":
            url = urljoin(base_url, (value or "").strip() or base_url)
            if not _same_site(url, base_url):
                step.update(status="invalid", note="Tests stay on the project's site: open a page of it.")
                continue
            step["value"] = url
        if action == "WAIT" and value and not value.strip().isdigit():
            step.update(status="invalid", note="WAIT takes a number of milliseconds (or nothing).")
            continue
        if not step["description"]:
            step["description"] = _describe(step)

        if action in _NO_TARGET or (action == "PRESS" and not target):
            step["status"] = "page"
        elif target in known:
            step["status"] = "found"
        elif _TEXT_SELECTOR.search(target or ""):
            step.update(status="text", note="Found by its visible text when the test runs.")
        else:
            step.update(status="unverified",
                        note="Not seen on the analyzed page; the test is saved quarantined until you trust it.")
    return out


def _describe(step: dict[str, Any]) -> str:
    action, target, value = step["action"], step.get("target"), step.get("value")
    verb = action.replace("ASSERT_", "check ").replace("_", " ").lower()
    parts = [verb, target or "", f"'{value[:60]}'" if value else ""]
    return " ".join(p for p in parts if p)


def blocking(steps: list[dict[str, Any]]) -> list[str]:
    """Why these steps cannot be saved ([] when they can)."""
    problems = [f"Step {s['step_number']}: {s['note']}" for s in steps if s["status"] == "invalid"]
    if not steps:
        problems.append("A test needs at least one step.")
    elif not any(s["action"].startswith("ASSERT_") for s in steps):
        problems.append("Add at least one check (an ASSERT_ step): a test without one cannot fail.")
    return problems


def stored_steps(steps: list[dict[str, Any]], base_url: str) -> list[dict[str, Any]]:
    """Checked steps as stored (and run): the test starts by opening *base_url*."""
    plain = [{k: s[k] for k in ("action", "target", "value", "description")} for s in steps]
    if not plain or plain[0]["action"] != "NAVIGATE":
        plain.insert(0, {"action": "NAVIGATE", "target": None, "value": base_url, "description": f"Open {base_url}"})
    return [{"step_number": i, **s} for i, s in enumerate(plain, start=1)]


def needs_quarantine(steps: list[dict[str, Any]]) -> bool:
    return any(s["status"] == "unverified" for s in steps)


# ---------------------------------------------------------------------------
# Plain English -> steps
# ---------------------------------------------------------------------------

SYSTEM = (
    "You turn a tester's plain-English description into steps of an automated browser test for TestSphere. "
    "Answer with ONLY one JSON object:\n"
    '{"name": "short test name", "steps": [{"action": "...", "target": "...", "value": "...", '
    '"description": "what the step does, in plain words"}], "not_covered": ["parts you could not turn into steps"]}\n'
    "Actions (nothing else is allowed):\n"
    + "\n".join(f"- {a}: {d}" for a, d in ACTIONS.items())
    + "\nRules:\n"
    "- The test already starts on the page described below; do not open it again.\n"
    "- For an element of THIS page, copy its selector exactly from the element list. Never invent ids or classes.\n"
    "- For an element on a page reached later, use a text selector, e.g. "
    ':is(button,a,[role=button]):has-text("Add to cart") or :is(h1,h2,h3):has-text("Products").\n'
    '- To check that text appears anywhere, use ASSERT_CONTAINS_TEXT with target "body".\n'
    "- After every action that should change something (submit, add, delete, log in), add a check that proves it did.\n"
    "- Use only values the description gives. Never invent passwords or user names: if one is needed and "
    "not given, put that part in not_covered.\n"
    "- At most 25 steps. If part of the description cannot be done with these actions, put it in not_covered "
    "instead of guessing.\n"
)


def element_list(analysis: dict[str, Any]) -> str:
    """The page's elements for the prompt (text from the site: fenced as untrusted by the caller)."""
    inv = analysis.get("elements_inventory") or {}
    lines: list[str] = []
    for i in (inv.get("inputs") or [])[:MAX_PROMPT_ELEMENTS]:
        bits = [f"type={i.get('type') or 'text'}"] + [f"{k}={str(i[k])[:40]}" for k in ("name", "placeholder", "label")
                                                    if i.get(k)]
        lines.append(f"input  selector={i['selector']}  " + " ".join(bits))
    for b in (inv.get("buttons") or [])[:MAX_PROMPT_ELEMENTS]:
        if b.get("selector"):
            lines.append(f"button selector={b['selector']}  text={str(b.get('text') or '')[:50]}")
    for h in (inv.get("headings") or [])[:6]:
        lines.append(f"heading text={str(h)[:60]}")
    return "\n".join(lines) or "(no form fields or buttons found)"


def build_prompt(instruction: str, analysis: dict[str, Any]) -> str:
    from agents.llm.untrusted import fence

    page = f"URL: {analysis.get('url')}\nTitle: {analysis.get('page_title') or ''}\n\nElements:\n{element_list(analysis)}"
    return (f"Test description from the user:\n{instruction.strip()[:MAX_INSTRUCTION]}\n\n"
            f"The page the test starts on:\n{fence('page', page)}")


def parse_answer(data: Any) -> tuple[str, list[Any], list[str]]:
    """(name, raw steps, not covered) from the model's JSON; tolerant of shapes models use."""
    if not isinstance(data, dict):
        return "", [], []
    steps = data.get("steps") or data.get("test_steps") or []
    if isinstance(data.get("test"), dict):
        steps = steps or data["test"].get("steps") or []
    not_covered = data.get("not_covered") or data.get("unsupported") or []
    return (str(data.get("name") or "").strip()[:120], steps if isinstance(steps, list) else [],
            [str(x)[:200] for x in not_covered if x] if isinstance(not_covered, list) else [])


async def draft_with_model(instruction: str, analysis: dict[str, Any], llm: Any, *, timeout: float) -> dict[str, Any]:
    import asyncio

    from agents.llm.schemas import LLMRequest
    from agents.llm.untrusted import UNTRUSTED_RULE

    request = LLMRequest(prompt=build_prompt(instruction, analysis), system_instruction=f"{SYSTEM}\n{UNTRUSTED_RULE}",
                         temperature=0.1, max_tokens=1800)
    data = await asyncio.wait_for(llm.generate_json(request), timeout=timeout)
    name, steps, not_covered = parse_answer(data)
    if not steps:
        raise ValueError("the model returned no steps")
    return {"name": name, "steps": steps, "not_covered": not_covered}


def draft_with_rules(instruction: str, analysis: dict[str, Any]) -> dict[str, Any]:
    """The rule-based planner's steps for the same description (analysis made with it as the goal)."""
    case = analysis.get("synthesized_test_case") or {}
    steps = list(case.get("steps") or [])
    if steps and str(steps[0].get("action", "")).upper() == "NAVIGATE":
        steps = steps[1:]  # the opening of the analyzed page: stored_steps adds it back
    goal = case.get("goal") or {}
    return {"name": "", "steps": steps, "not_covered": list(goal.get("untested") or [])}


def default_name(instruction: str) -> str:
    words = re.sub(r"\s+", " ", instruction).strip()
    return (words[:1].upper() + words[1:80]).rstrip(" .,") or "Studio test"


# ---------------------------------------------------------------------------
# Export as a Playwright test
# ---------------------------------------------------------------------------


def _js(text: str | None) -> str:
    return json.dumps(text or "")


def to_playwright(name: str, steps: list[dict[str, Any]]) -> str:
    """A saved test as a standalone Playwright Test file (TypeScript)."""
    lines = ["import { test, expect } from '@playwright/test';", "",
             "// Exported from TestSphere AI. Self-healing applies when it runs in TestSphere, not here.",
             f"test({_js(name)}, async ({{ page }}) => {{"]
    for s in steps:
        a, t, v = s.get("action"), s.get("target"), s.get("value")
        loc = f"page.locator({_js(t)})" + (".first()" if t and _TEXT_SELECTOR.search(t) else "")
        code = {
            "NAVIGATE": f"await page.goto({_js(v)});",
            "CLICK": f"await {loc}.click();",
            "FILL": f"await {loc}.fill({_js(v)});",
            "PRESS": f"await {loc}.press({_js(v)});" if t else f"await page.keyboard.press({_js(v)});",
            "SELECT": f"await {loc}.selectOption({_js(v)});",
            "CHECK": f"await {loc}.check();",
            "UNCHECK": f"await {loc}.uncheck();",
            "HOVER": f"await {loc}.hover();",
            "WAIT": f"await page.waitForTimeout({int(v)});" if (v or "").strip().isdigit()
                    else "await page.waitForLoadState('networkidle');",
            "RELOAD": "await page.reload();",
            "GO_BACK": "await page.goBack();",
            "ASSERT_VISIBLE": f"await expect({loc}).toBeVisible();",
            "ASSERT_HIDDEN": f"await expect({loc}).toBeHidden();",
            "ASSERT_CONTAINS_TEXT": f"await expect({loc}).toContainText({_js(v)});",
            "ASSERT_HAS_TEXT": f"await expect({loc}).toHaveText({_js(v)});",
            "ASSERT_VALUE": f"await expect({loc}).toHaveValue({_js(v)});",
            "ASSERT_URL": f"await expect(page).toHaveURL(new RegExp({_js(re.escape(v or ''))}));",
            "ASSERT_URL_EQUALS": f"await expect(page).toHaveURL({_js(v)});",
        }.get(str(a))
        if code is None:
            code = f"// Not exported: {a}"
        comment = str(s.get("description") or "").replace("\n", " ")[:120]
        lines.append(f"  // {comment}" if comment else "")
        lines.append(f"  {code}")
    lines.append("});")
    return "\n".join(line for line in lines if line != "") + "\n"
