"""Page analysis turns the written goal into real steps (found testing live sites)."""

import pytest

from backend.services.url_analyzer import URLAnalyzerService as U


@pytest.mark.parametrize(("prompt", "expected"), [
    ("log in with tomsmith / SuperSecretPassword! and reach the secure area", {"username": "tomsmith", "password": "SuperSecretPassword!"}),
    ("log in as standard_user with password secret_sauce", {"username": "standard_user", "password": "secret_sauce"}),
    ("log in with username student and password Password123", {"username": "student", "password": "Password123"}),
    ("add a todo item called Buy milk and mark it as completed", {"text": "Buy milk"}),
    ('search for "red shoes"', {"text": "red shoes"}),
    ("check the home page loads", {}),
    ("log in with an email and password", {}),  # the word "password" is not a password
    ("open https://example.com/a/b", {}),
])
def test_values_are_read_from_the_goal(prompt, expected):
    assert U.prompt_values(prompt) == expected


LOGIN = """<html><body><nav><button><svg></svg></button></nav>
<form><input id="username" name="username" type="text"/><input id="password" name="password" type="password"/>
<button id="submit" class="btn">Submit</button></form></body></html>"""


def test_login_steps_use_the_goals_credentials_and_the_submit_button():
    inputs, buttons = U._extract_inputs(LOGIN), U._extract_buttons(LOGIN)
    steps = U._synthesize_test_steps("https://x.example/", "Login", inputs, buttons,
                                     prompt="log in with username student and password Password123")
    fills = {s["target"]: s["value"] for s in steps if s["action"] == "FILL"}
    assert fills == {"#username": "student", "#password": "Password123"}
    click = next(s for s in steps if s["action"] == "CLICK")
    assert click["target"] == "#submit"  # not the bare menu "button"


def test_a_lone_input_without_a_button_submits_with_enter():
    html = '<input class="new-todo" placeholder="What needs to be done?"/>'
    steps = U._synthesize_test_steps("https://x.example/", "Todo", U._extract_inputs(html), U._extract_buttons(html),
                                     prompt="add a todo called Buy milk")
    assert [s["action"] for s in steps][1:] == ["FILL", "PRESS", "ASSERT_CONTAINS_TEXT"]
    assert steps[1]["value"] == "Buy milk" and steps[2]["value"] == "Enter"
    assert steps[3]["value"] == "Buy milk"  # the new item must show, not just the key press


# A run passed with a wrong password because nothing checked the outcome (D18)

def test_a_sign_in_must_leave_the_login_form():
    inputs, buttons = U._extract_inputs(LOGIN), U._extract_buttons(LOGIN)
    steps, cov = U._plan_scenario("https://x.example/", "Login", inputs, buttons,
                                  prompt="log in with tomsmith / WrongPassword1 and reach the secure area")
    assert [s["action"] for s in steps][-3:] == ["CLICK", "ASSERT_HIDDEN", "ASSERT_CONTAINS_TEXT"]
    assert steps[-2]["target"] == "#password" and steps[-1]["value"] == "secure area"
    assert cov == {"tested": ["log in with tomsmith / WrongPassword1", "reach the secure area"], "untested": []}


def test_later_parts_of_the_goal_become_checked_steps():
    inputs, buttons = U._extract_inputs(LOGIN), U._extract_buttons(LOGIN)
    steps, _ = U._plan_scenario("https://x.example/", "Login", inputs, buttons,
                                prompt="log in as standard_user with password secret_sauce and add the backpack to the cart")
    add, count = steps[-2], steps[-1]
    assert add["action"] == "CLICK" and 'has-text("backpack")' in add["target"] and 'has-text("add")' in add["target"]
    assert count["action"] == "ASSERT_VISIBLE" and '[class*="cart" i]' in count["target"]  # the cart shows a count

    html = '<input class="new-todo" placeholder="What needs to be done?"/>'
    steps, _ = U._plan_scenario("https://x.example/", "Todo", U._extract_inputs(html), [],
                                prompt="add a todo item called Buy milk and mark it as completed")
    tick, ticked = steps[-2], steps[-1]
    assert 'has-text("Buy milk")' in tick["target"] and tick["target"].endswith("input[type=checkbox]")
    assert ticked["action"] == "ASSERT_VISIBLE" and ticked["target"] == tick["target"] + ":checked"


def test_parts_that_cannot_be_planned_are_reported_not_claimed():
    steps, cov = U._plan_scenario("https://x.example/", "Shop", [], [], prompt="click Pricing, then fly to the moon")
    assert [s["action"] for s in steps] == ["NAVIGATE", "CLICK"]
    assert cov == {"tested": ["click Pricing"], "untested": ["fly to the moon"]}


def test_a_goal_that_starts_elsewhere_does_not_type_into_the_form():
    steps, _ = U._plan_scenario("https://x.example/", "Login", U._extract_inputs(LOGIN), U._extract_buttons(LOGIN),
                                prompt="click Forgot password")
    assert "FILL" not in [s["action"] for s in steps]


@pytest.mark.parametrize(("prompt", "parts"), [
    ("log in with username student and password Password123", ["log in with username student and password Password123"]),
    ("log in as a, add the backpack to the cart, then check out", ["log in as a", "add the backpack to the cart", "check out"]),
    ("", []),
])
def test_goals_split_into_parts(prompt, parts):
    from backend.services.goal_plan import split_goal

    assert split_goal(prompt) == parts


@pytest.mark.parametrize(("html", "client"), [
    ('<html><body><div id="root"></div><script src="/app.js"></script></body></html>', True),
    ('<html><body><form><input name="q"/></form><script></script></body></html>', False),
    ("<html><body><h1>Plain page</h1><p>" + "words " * 200 + "</p></body></html>", False),
])
def test_client_rendered_shells_are_recognised(html, client):
    assert U._looks_client_rendered(html) is client


@pytest.mark.parametrize("url", ["file:///etc/passwd", "gopher://127.0.0.1/", "ftp://example.com/"])
def test_other_schemes_are_refused_clearly(url):
    from fastapi.testclient import TestClient

    from backend.main import app

    r = TestClient(app).post("/api/workflow/analyze", json={"url": url})
    assert r.status_code == 422 and "Only http:// and https://" in r.json()["detail"]


SIGN_UP = """<!doctype html><html><head><title>Sign up</title></head><body>
<form action="/welcome" method="get">
<input id="n" name="name" required><input id="e" type="email" name="email" required>
<input id="p" type="password" name="password" required minlength="8">
<input id="age" type="number" name="age" required min="18"><input id="dob" type="date" name="dob" required>
<input id="ph" type="tel" name="phone" required><textarea id="bio" name="bio" required></textarea>
<select id="country" name="country" required><option value="" disabled selected>Choose…</option>
<option value="in">India</option></select>
<input type="radio" id="basic" name="plan" value="basic" required><input type="radio" id="pro" name="plan" value="pro">
<input id="terms" type="checkbox" name="terms" required><input id="news" type="checkbox" name="news">
<button type="submit" id="go">Create account</button></form></body></html>"""


async def test_a_sign_up_form_with_typed_and_required_fields_really_submits():
    """The browser refuses to submit unless every required field is valid."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from engine.runner import run_test
    from engine.schemas import (
        ActionType,
        RunOptions,
        Step,
        Target,
        TestPlan,
        TestStatus,
    )

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - http.server API
            body = (SIGN_UP if self.path == "/" else "<h1 id='hi'>Welcome</h1>").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        planned = U._synthesize_test_steps(f"{base}/", "Sign up", U._extract_inputs(SIGN_UP), U._extract_buttons(SIGN_UP))
        actions = {"NAVIGATE": ActionType.GOTO, "FILL": ActionType.FILL, "CHECK": ActionType.CHECK, "CLICK": ActionType.CLICK,
                   "SELECT": ActionType.SELECT}
        steps = [Step(step_id=f"s{i}", action=actions[s["action"]], value=s["value"],
                      target=Target(description=s["description"], primary_locator=s["target"]) if s["target"] else None)
                 for i, s in enumerate(planned)]
        steps.append(Step(step_id="url", action=ActionType.ASSERT_URL, expected="/welcome"))
        result = await run_test(TestPlan(test_id="signup", name="signup", base_url=base, steps=steps),
                                RunOptions(min_action_timeout_ms=3000))
        assert result.status == TestStatus.PASSED, [(s.step_id, s.error) for s in result.steps if s.error]
        assert "news" not in {s["target"].lstrip("#") for s in planned if s["target"]}  # optional box left alone
    finally:
        server.shutdown()
