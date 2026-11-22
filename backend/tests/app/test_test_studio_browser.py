"""Test Studio end to end in real Chromium: describe -> draft -> save -> run -> the site changes -> healed."""

from __future__ import annotations

import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

from app.main import app

PAGE = """<!doctype html><html><head><title>Shop</title></head><body>
<main id="app">
  <h1>Sign in</h1>
  <form id="login-form" onsubmit="event.preventDefault();
      document.getElementById('app').innerHTML = '<h1>Products</h1><p>Welcome, ' + document.getElementById('user').value + '</p>';">
    <label for="user">User name</label> <input id="user" name="user" type="text">
    <label for="pass">Password</label> <input id="pass" name="pass" type="password">
    <button id="{button_id}" type="submit">Log in</button>
  </form>
</main>
</body></html>"""


@pytest.fixture
def site(tmp_path):
    root = tmp_path / "site"
    root.mkdir()
    handler = partial(SimpleHTTPRequestHandler, directory=str(root))
    handler.log_message = lambda *_: None  # type: ignore[method-assign]
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    def publish(button_id: str) -> None:
        (root / "login.html").write_text(PAGE.replace("{button_id}", button_id), encoding="utf-8")

    publish("login")
    yield f"http://127.0.0.1:{server.server_address[1]}/login.html", publish
    server.shutdown()


def test_a_studio_test_runs_and_heals_in_a_real_browser(site):
    url, publish = site
    client = TestClient(app)
    project = client.post("/projects", json={"name": "Shop", "app_url": url}).json()

    # Reviewed steps, checked against the real page (no model needed)
    steps = [
        {"action": "FILL", "target": "#user", "value": "demo"},
        {"action": "FILL", "target": "#pass", "value": "secret"},
        {"action": "CLICK", "target": "#login"},
        {"action": "ASSERT_CONTAINS_TEXT", "target": "body", "value": "Welcome, demo"},
    ]
    checked = client.post(f"/projects/{project['id']}/studio/verify", json={"steps": steps})
    assert checked.status_code == 200, checked.text
    assert [s["status"] for s in checked.json()["steps"]] == ["found", "found", "found", "found"]

    saved = client.post(f"/projects/{project['id']}/studio/tests",
                        json={"name": "Sign in", "instruction": "log in as demo", "steps": steps}).json()
    assert saved["quarantined"] is False

    first = client.post("/workflow/plan-and-execute", json={"test_case_id": saved["id"]}).json()
    assert first["status"] == "PASSED", first.get("error_message")

    publish("sign-in-v2")  # the app renamed its button: #login is gone
    second = client.post("/workflow/plan-and-execute", json={"test_case_id": saved["id"]}).json()
    assert second["status"] == "HEALED", second.get("error_message")

    listed = client.get(f"/projects/{project['id']}/studio/tests").json()
    assert listed[0]["last_result"]["status"] == "HEALED"


def test_a_rejected_heal_fails_the_next_run_instead_of_passing(site):
    url, publish = site
    client = TestClient(app)
    project = client.post("/projects", json={"name": "Shop", "app_url": url}).json()
    steps = [
        {"action": "FILL", "target": "#user", "value": "demo"},
        {"action": "CLICK", "target": "#login"},
        {"action": "ASSERT_CONTAINS_TEXT", "target": "body", "value": "Welcome, demo"},
    ]
    saved = client.post(f"/projects/{project['id']}/studio/tests", json={"name": "Sign in", "steps": steps}).json()
    assert client.post("/workflow/plan-and-execute", json={"test_case_id": saved["id"]}).json()["status"] == "PASSED"

    publish("sign-in-v2")
    healed = client.post("/workflow/plan-and-execute", json={"test_case_id": saved["id"]}).json()
    assert healed["status"] == "HEALED", healed.get("error_message")

    [heal] = [h for h in client.get("/heals").json()["heals"] if h["test_case_id"] == saved["id"]]
    assert heal["original"] == "#login"
    res = client.post(f"/heals/{heal['execution_id']}/review", json={"original_locator": "#login", "decision": "reject"})
    assert res.status_code == 200, res.text

    again = client.post("/workflow/plan-and-execute", json={"test_case_id": saved["id"]}).json()
    assert again["status"] == "FAILED"
    assert "a reviewer rejected healing this step" in again["error_message"]
