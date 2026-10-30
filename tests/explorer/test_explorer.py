"""The goal explorer, driven by a scripted model against a local site.

The site has what scripted tests miss: the portal link only appears after a
menu opens.  The model is a script that answers from the page it is shown,
so these tests are deterministic and never call a real model.
"""

from __future__ import annotations

import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from playwright.async_api import async_playwright

from agents.explorer import GoalExplorer
from agents.llm.exceptions import LLMRateLimitError, LLMResponseError
from engine.runner import run_test
from engine.schemas import ActionType, RunOptions, Step, Target, TestPlan, TestStatus

HOME = """<!doctype html><html><head><title>CareLink</title></head><body>
<h1>The Modern Operating System<br>for National Healthcare</h1>
<button id="menu" onclick="document.getElementById('portals').hidden = false">Select Portal ↓</button>
<div id="portals" hidden><a href="/patient/login">Patient portal</a> <a href="/doctor/login">Doctor portal</a></div>
<button data-testid="danger">Delete account</button>
</body></html>"""
LOGIN = """<!doctype html><html><head><title>Sign in · Patient portal</title></head><body>
<h1>Welcome back</h1>
<form onsubmit="event.preventDefault(); location.href = '/patient/home'">
<input name="email" placeholder="Email"><input name="password" type="password" placeholder="Password">
<button type="submit">Sign in</button></form></body></html>"""
PAGES = {"/": HOME, "/patient/login": LOGIN, "/doctor/login": LOGIN,
         "/patient/home": "<!doctype html><title>Home</title><h1>Hello patient</h1>"}


class _Site(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = PAGES.get(self.path.split("?")[0])
        self.send_response(200 if body else 404)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write((body or "not found").encode())

    def log_message(self, *_):
        pass


@pytest.fixture(scope="module")
def site():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Site)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.fixture
async def page():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        yield await browser.new_page()
        await browser.close()


def num(prompt: str, label: str) -> int:
    """The number the page listing gives the element labelled *label*."""
    match = re.search(r"^\[(\d+)\] \S+ \"" + re.escape(label) + '"', prompt, re.MULTILINE)
    assert match, f"{label!r} is not listed on this page:\n{prompt}"
    return int(match.group(1))


class ScriptedModel:
    """Answers each turn with the next scripted function of the prompt."""

    def __init__(self, *turns):
        self.turns, self.prompts = list(turns), []

    async def generate_json(self, request):
        self.prompts.append(request.prompt)
        turn = self.turns.pop(0)
        if isinstance(turn, Exception):
            raise turn
        return turn(request.prompt)


def to_plan(steps: list[dict], base_url: str) -> TestPlan:
    """A recording as an engine plan (what the pipeline's replay runs)."""
    kinds = {"NAVIGATE": ActionType.GOTO, "CLICK": ActionType.CLICK, "FILL": ActionType.FILL,
             "PRESS": ActionType.PRESS, "ASSERT_URL": ActionType.ASSERT_URL, "ASSERT_CONTAINS_TEXT": ActionType.ASSERT_TEXT}
    plan = []
    for s in steps:
        kind = kinds[s["action"]]
        target = Target(description=s["description"], primary_locator=s["target"]) if s["target"] else None
        expected = s["value"] if kind in (ActionType.ASSERT_URL, ActionType.ASSERT_TEXT) else None
        plan.append(Step(step_id=f"s{s['step_number']}", action=kind, target=target,
                         value=None if expected else s["value"], expected=expected))
    return TestPlan(test_id="explored", name="explored", base_url=base_url, steps=plan)


async def test_it_opens_a_menu_to_reach_a_link_and_records_a_replayable_test(site, page):
    model = ScriptedModel(
        lambda p: {"action": "click", "element": num(p, "Select Portal ↓"), "reason": "the portals are in this menu"},
        lambda p: {"action": "click", "element": num(p, "Patient portal")},
        lambda p: {"action": "done", "check": {"type": "url_contains", "value": "/patient/login"}},
    )
    result = await GoalExplorer(model).explore(page, site + "/", "open the Patient portal and reach the sign-in page")

    assert result.reached and result.model_calls == 3
    assert [s["action"] for s in result.steps] == ["NAVIGATE", "CLICK", "CLICK", "ASSERT_URL"]
    assert result.steps[1]["target"] == "#menu"                      # most stable locator first
    assert result.steps[2]["target"] == 'a[href="/patient/login"]'
    assert result.outcome == {"type": "url_contains", "value": "/patient/login"}
    # The portal link was hidden when the first page was read: the model only saw it after the menu opened
    assert '"Patient portal"' not in model.prompts[0] and '"Patient portal"' in model.prompts[1]

    replay = await run_test(to_plan(result.steps, site), RunOptions(min_action_timeout_ms=2000))
    assert replay.status == TestStatus.PASSED, [s.error for s in replay.steps]


async def test_it_types_only_values_from_the_goal(site, page):
    values = {"username": "pat@example.com", "password": "s3cret!"}
    model = ScriptedModel(
        lambda p: {"action": "goto", "value": "/patient/login"},
        lambda p: {"action": "fill", "element": num(p, "Email"), "value": "invented@example.com"},  # refused
        lambda p: {"action": "fill", "element": num(p, "Email"), "value": "pat@example.com"},
        lambda p: {"action": "fill", "element": num(p, "Password"), "value": "s3cret!"},
        lambda p: {"action": "click", "element": num(p, "Sign in")},
        lambda p: {"action": "done", "check": {"type": "text_visible", "value": "Hello patient"}},
    )
    result = await GoalExplorer(model).explore(page, site + "/", "sign in as pat@example.com with password s3cret!", values)

    assert result.reached
    assert "refused to type 'invented@example.com'" in result.notes[1]
    fills = [(s["target"], s["value"]) for s in result.steps if s["action"] == "FILL"]
    assert fills == [('input[name="email"]', "pat@example.com"), ('input[name="password"]', "s3cret!")]
    assert result.steps[-1] == {"step_number": 6, "action": "ASSERT_CONTAINS_TEXT", "target": "body",
                                "value": "Hello patient", "description": "Page shows 'Hello patient'"}
    replay = await run_test(to_plan(result.steps, site), RunOptions(min_action_timeout_ms=2000))
    assert replay.status == TestStatus.PASSED, [s.error for s in replay.steps]


async def test_it_refuses_destructive_elements_and_other_sites(site, page):
    model = ScriptedModel(
        lambda p: {"action": "click", "element": num(p, "Delete account")},
        lambda p: {"action": "goto", "value": "https://example.org/"},
        lambda p: {"action": "give_up", "reason": "nothing else to try"},
    )
    result = await GoalExplorer(model).explore(page, site + "/", "look around the home page")

    assert not result.reached and result.reason == "the model gave up: nothing else to try"
    assert "looks like it would delete" in result.notes[0]
    assert "leaves the site" in result.notes[1]
    assert [s["action"] for s in result.steps] == ["NAVIGATE"]  # nothing refused was recorded


async def test_a_goal_that_asks_for_it_may_use_a_risky_element(site, page):
    model = ScriptedModel(
        lambda p: {"action": "click", "element": num(p, "Delete account")},
        lambda p: {"action": "done", "check": {"type": "text_visible", "value": "Delete account"}},
    )
    result = await GoalExplorer(model).explore(page, site + "/", "delete account from the home page")
    assert result.reached and result.steps[1]["target"] == '[data-testid="danger"]'


async def test_a_done_whose_check_does_not_hold_is_not_recorded(site, page):
    model = ScriptedModel(*[lambda p: {"action": "done", "check": {"type": "text_visible", "value": "Dashboard"}}] * 3)
    result = await GoalExplorer(model, max_steps=3).explore(page, site + "/", "reach the dashboard")

    assert not result.reached and result.reason == "did not reach the goal within 3 steps"
    assert all("the check did not hold" in n for n in result.notes)
    assert not any(s["action"].startswith("ASSERT") for s in result.steps)


async def test_model_trouble_ends_the_exploration_without_raising(site, page):
    limited = await GoalExplorer(ScriptedModel(LLMRateLimitError("rate limited", provider="api"))).explore(
        page, site + "/", "open the Patient portal")
    assert not limited.reached and limited.reason.startswith("the model is unavailable (LLMRateLimitError")

    garbled = ScriptedModel(*[LLMResponseError("not JSON", provider="api")] * 3)
    result = await GoalExplorer(garbled).explore(page, site + "/", "open the Patient portal")
    assert not result.reached and "kept answering" in result.reason and result.model_calls == 3
