"""
TestSphere-AI — The goal explorer.

An AI agent reaches a written goal in a live browser, one action at a time:
each step it reads the page (``page_view``), the model picks one action,
the guardrails check it (``guardrails``) and it runs with the element's
recorded locator.  The model ends by naming an outcome check ("the URL
contains /patient/login", "the page shows Sign in"); the explorer verifies it
itself.  Only a verified exploration becomes a recording: ordinary stored
steps, plus the fallback locators the healer needs, that later runs replay
without the model.

Model trouble never fails a pipeline run: an unreadable answer costs a step,
and a rate limit, timeout or outage ends the exploration with a reason.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin

from agents.explorer import guardrails
from agents.explorer.page_view import PageView, read_page
from agents.llm.exceptions import LLMError, LLMResponseError
from agents.llm.schemas import LLMRequest

logger = logging.getLogger("testsphere.explorer")

MAX_STEPS = 15
MAX_BAD_ANSWERS = 2
ACTION_TIMEOUT_MS = 5_000

SYSTEM = """You test a web application by reaching a goal in a real browser, one action at a time.
Each turn you see the page (URL, title, visible text, numbered elements) and the actions taken so far.
Answer with one JSON object and nothing else:
{"reason": "<one short sentence>", "action": "<click|fill|select|check|uncheck|hover|press|goto|done|give_up>",
 "element": <element number, for click/fill/select/check/uncheck/hover>,
 "value": "<text to type, option to choose, key to press, or URL path for goto>",
 "check": {"type": "<url_contains|text_visible>", "value": "<text>"}}
Rules:
- One action per turn. Use only element numbers from the current list.
- Type only the values the goal provides; never invent data. Keys: Enter, Tab, Escape, ArrowDown, ArrowUp.
- Never delete, pay, buy, transfer, sign out or change settings unless the goal says so.
- When the goal is reached, answer "done" with a "check" that proves it on the current page:
  url_contains with part of the current URL, or text_visible with a short phrase from the visible text.
- If the goal cannot be reached, answer "give_up" and say why."""


@dataclass
class ExplorationResult:
    reached: bool
    steps: list[dict[str, Any]] = field(default_factory=list)          # stored-step format
    healing_targets: list[dict[str, Any]] = field(default_factory=list)  # fallbacks per recorded locator
    outcome: dict[str, str] | None = None
    notes: list[str] = field(default_factory=list)                     # what happened, step by step
    reason: str | None = None                                          # why it was not reached
    model_calls: int = 0


class GoalExplorer:
    """Reaches *goal* on a live page and records the verified steps."""

    def __init__(self, llm: Any, *, max_steps: int = MAX_STEPS, step_timeout: float = 60.0) -> None:
        self.llm = llm
        self.max_steps = max_steps
        self.step_timeout = step_timeout

    async def explore(self, page: Any, start_url: str, goal: str, values: dict[str, str] | None = None) -> ExplorationResult:
        result = ExplorationResult(reached=False)
        allowed = {v for v in (values or {}).values() if v}
        await _open(page, start_url)
        result.steps.append(_stored(1, "NAVIGATE", value=start_url, description=f"Open {start_url}"))
        bad_answers = 0

        for turn in range(1, self.max_steps + 1):
            view = await read_page(page)
            try:
                decision = await self._decide(goal, allowed, view, result.notes)
                result.model_calls += 1
            except LLMResponseError as exc:
                result.model_calls += 1
                bad_answers += 1
                result.notes.append(f"{turn}. unreadable answer from the model ({exc})")
                if bad_answers > MAX_BAD_ANSWERS:
                    result.reason = "the model kept answering with something other than one JSON action"
                    return result
                continue
            except (LLMError, TimeoutError) as exc:
                result.reason = f"the model is unavailable ({type(exc).__name__}: {str(exc)[:120]})"
                return result

            action = str(decision.get("action") or "").strip().lower()
            if action not in guardrails.ACTIONS:
                result.notes.append(f"{turn}. refused: unknown action {action!r}")
                continue
            if action == "give_up":
                result.reason = f"the model gave up: {str(decision.get('reason') or 'no reason given')[:200]}"
                return result
            if action == "done":
                check = decision.get("check") if isinstance(decision.get("check"), dict) else {}
                verdict = await _verify(page, check)
                if verdict is None:
                    result.reached, result.outcome = True, {"type": check["type"], "value": str(check["value"])}
                    result.steps.append(_check_step(len(result.steps) + 1, result.outcome))
                    result.notes.append(f"{turn}. goal reached: {check['type']} {check['value']!r} verified on {page.url}")
                    return result
                result.notes.append(f"{turn}. said done, but the check did not hold: {verdict}")
                continue

            page, note = await self._act(page, start_url, goal, allowed, view, decision, action, result)
            result.notes.append(f"{turn}. {note}")

        result.reason = f"did not reach the goal within {self.max_steps} steps"
        return result

    async def _decide(self, goal: str, allowed: set[str], view: PageView, notes: list[str]) -> dict[str, Any]:
        history = "\n".join(notes[-10:]) or "(none yet)"
        values = ", ".join(repr(v) for v in sorted(allowed)) or "(none: do not type anything)"
        prompt = (f"Goal: {goal}\nValues you may type: {values}\n\nActions so far:\n{history}\n\n"
                  f"Current page:\n{view.describe()}\n\nYour next action (JSON):")
        request = LLMRequest(prompt=prompt, system_instruction=SYSTEM, temperature=0.1, max_tokens=400,
                             response_format="json")
        return await asyncio.wait_for(self.llm.generate_json(request), timeout=self.step_timeout)

    async def _act(self, page: Any, start_url: str, goal: str, allowed: set[str], view: PageView,
                   decision: dict[str, Any], action: str, result: ExplorationResult) -> tuple[Any, str]:
        """Run one checked action; returns the (possibly new) page and a note for the history."""
        value = decision.get("value")
        value = None if value is None else str(value)
        n = len(result.steps) + 1

        if action == "goto":
            if not value or not guardrails.same_site(start_url, value):
                return page, f"refused: goto {value!r} leaves the site"
            url = urljoin(page.url, value)
            await _open(page, url)
            result.steps.append(_stored(n, "NAVIGATE", value=url, description=f"Open {url}"))
            return page, f"opened {url} → now at {page.url}"

        if action == "press":
            if value not in guardrails.KEYS:
                return page, f"refused: key {value!r} is not one of {', '.join(sorted(guardrails.KEYS))}"
            page = await _following(page, page.keyboard.press(value))
            result.steps.append(_stored(n, "PRESS", value=value, description=f"Press {value}"))
            return page, f"pressed {value} → now at {page.url}"

        element = view.element(decision.get("element"))
        if element is None:
            return page, f"refused: there is no element {decision.get('element')!r} on this page"
        name = f'[{element.index}] {element.role} "{element.label}"'
        why = guardrails.risky_reason(element.label, element.href, goal)
        if why:
            return page, f"refused {action} on {name}: {why}"
        if action == "fill":
            why = guardrails.typed_value_reason(value, allowed)
            if why:
                return page, f"refused to type {value!r} into {name}: {why}"
        if action == "select" and value not in (element.options or []) and value not in allowed:
            return page, f"refused: {value!r} is not an option of {name} ({', '.join(element.options or [])})"

        locator = await _unique_locator(page, [element.primary, *element.fallbacks])
        if locator is None:
            return page, f"could not act on {name}: none of its locators matches exactly one element"
        target = page.locator(locator)
        try:
            if action == "click":
                page = await _following(page, target.click(timeout=ACTION_TIMEOUT_MS))
            elif action == "fill":
                await target.fill(value or "", timeout=ACTION_TIMEOUT_MS)
            elif action == "select":
                await target.select_option(label=value, timeout=ACTION_TIMEOUT_MS)
            elif action == "check":
                await target.check(timeout=ACTION_TIMEOUT_MS)
            elif action == "uncheck":
                await target.uncheck(timeout=ACTION_TIMEOUT_MS)
            elif action == "hover":
                await target.hover(timeout=ACTION_TIMEOUT_MS)
        except Exception as exc:  # noqa: BLE001 - reported to the model, which can try something else
            return page, f"{action} on {name} failed: {str(exc).splitlines()[0][:160]}"

        verb = {"click": "Click", "fill": "Type into", "select": "Choose in", "check": "Tick", "uncheck": "Untick",
                "hover": "Hover over"}[action]
        result.steps.append(_stored(n, action.upper(), target=locator,
                                    value=value if action in ("fill", "select") else None,
                                    description=f'{verb} "{element.label or locator}"'))
        fallbacks = [loc for loc in [element.primary, *element.fallbacks] if loc != locator]
        if fallbacks and not any(t["locator"] == locator for t in result.healing_targets):
            result.healing_targets.append({"locator": locator, "fallback_locators": fallbacks, "fingerprint": None})
        return page, f"{action} {name}" + (f" with {value!r}" if value and action != "click" else "") + f" → now at {page.url}"


def _stored(n: int, action: str, *, target: str | None = None, value: str | None = None, description: str) -> dict[str, Any]:
    return {"step_number": n, "action": action, "target": target, "value": value, "description": description}


def _check_step(n: int, outcome: dict[str, str]) -> dict[str, Any]:
    if outcome["type"] == "url_contains":
        return _stored(n, "ASSERT_URL", value=outcome["value"], description=f"URL contains '{outcome['value']}'")
    return _stored(n, "ASSERT_CONTAINS_TEXT", target="body", value=outcome["value"],
                   description=f"Page shows '{outcome['value']}'")


async def _settle(page: Any) -> None:
    for state, ms in (("domcontentloaded", 5_000), ("networkidle", 2_000)):
        with contextlib.suppress(Exception):
            await page.wait_for_load_state(state, timeout=ms)


async def _open(page: Any, url: str) -> None:
    await page.goto(url, wait_until="domcontentloaded", timeout=20_000)
    await _settle(page)


async def _following(page: Any, action: Any) -> Any:
    """Run *action*; when it opens a tab, continue there (as the replay does)."""
    before = len(page.context.pages)
    await action
    await asyncio.sleep(0.3)
    pages = page.context.pages
    if len(pages) > before:
        page = pages[-1]
    await _settle(page)
    return page


async def _unique_locator(page: Any, candidates: list[str]) -> str | None:
    for locator in candidates:
        with contextlib.suppress(Exception):
            if await page.locator(locator).count() == 1:
                return locator
    return None


async def _verify(page: Any, check: dict[str, Any]) -> str | None:
    """None when *check* holds on the current page, else why it does not."""
    from engine.runner import _text_contains

    kind, value = check.get("type"), str(check.get("value") or "").strip()
    if kind not in ("url_contains", "text_visible") or not value:
        return "a done answer needs a check: url_contains or text_visible with a value"
    if kind == "url_contains":
        return None if value in page.url else f"the URL {page.url} does not contain {value!r}"
    text = " ".join((await page.inner_text("body")).split())
    return None if _text_contains(text, value) else f"the page does not show {value!r}"
