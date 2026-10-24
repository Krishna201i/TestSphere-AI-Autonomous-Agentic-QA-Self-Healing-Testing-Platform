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
    assert [s["action"] for s in steps][-2:] == ["FILL", "PRESS"]
    assert steps[-2]["value"] == "Buy milk" and steps[-1]["value"] == "Enter"


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
