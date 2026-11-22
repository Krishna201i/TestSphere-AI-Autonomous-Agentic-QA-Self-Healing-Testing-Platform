"""
Negative form tests and the broken-page acceptance check, in real Chromium.

The negative tests (an empty required field, a malformed email) must pass on
a healthy form and fail on one that stopped validating; the acceptance check
must call a real check "verified" and a test that only sees the page render
"unverifiable".
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from agents.planner.schemas import TestCase as Member1TestCase
from backend.orchestration.converters import test_case_to_engine_plan as to_engine_plan
from backend.orchestration.orchestrator import parse_stored_steps
from backend.pipeline import acceptance, suite
from backend.services.url_analyzer import URLAnalyzerService as U
from engine.runner import run_test
from engine.schemas import RunOptions, TestStatus

CONTACT = """<!doctype html><title>Contact us</title><h1>Contact us</h1>
<form action="/sent"{novalidate}><input id="name" name="name"{required}>
<input id="email" name="email" type="{email_type}"{required}><textarea id="msg" name="message"{required}></textarea>
<button type="submit">Send</button></form>"""
PAGES = {
    "/contact": CONTACT.format(novalidate="", required=" required", email_type="email"),
    # The same form after a regression: nothing is required any more, the email field is plain text
    "/contact-broken": CONTACT.format(novalidate="", required="", email_type="text"),
    "/contact-novalidate": CONTACT.format(novalidate=" novalidate", required=" required", email_type="email"),
    "/login": """<!doctype html><title>Sign in</title><form action="/in"><input id="email" type="email" required>
<input id="pw" type="password" required><button type="submit">Sign in</button></form>""",
    "/sent": "<!doctype html><title>Sent</title><p>Thanks</p>",
}


@pytest.fixture(scope="module")
def site():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            body = PAGES.get(self.path.split("?")[0], "<p>404</p>")
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(body.encode())

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def _form_tests(url: str, html: str) -> dict[str, dict]:
    from backend.services import form_checks

    return {t["slug"]: t for t in form_checks.negative_tests(url, U._extract_inputs(html), U._extract_buttons(html), html)}


async def _run(test: dict, url: str) -> TestStatus:
    steps, assertions = parse_stored_steps(test["steps"], url)
    case = Member1TestCase(test_id=test["slug"], name=test["name"], page_url=url, steps=steps, assertions=assertions)
    return (await run_test(to_engine_plan(case, url), RunOptions(min_action_timeout_ms=1500))).status


def test_only_validated_non_login_forms_get_negative_tests(site):
    assert set(_form_tests(site + "/contact", PAGES["/contact"])) == {"form-required-empty", "form-invalid-email"}
    assert _form_tests(site + "/contact-novalidate", PAGES["/contact-novalidate"]) == {}
    assert _form_tests(site + "/login", PAGES["/login"]) == {}  # auth_plan has its own


async def test_negative_tests_pass_on_a_validating_form_and_fail_once_it_stops(site):
    tests = _form_tests(site + "/contact", PAGES["/contact"])
    for test in tests.values():
        assert await _run(test, site + "/contact") == TestStatus.PASSED, test["slug"]
        # The same steps against the regressed form
        broken = {**test, "steps": [{**s, "value": site + "/contact-broken"} if s["action"] == "NAVIGATE" else s
                                    for s in test["steps"]]}
        assert await _run(broken, site + "/contact-broken") == TestStatus.FAILED, test["slug"]


async def test_the_acceptance_check_verifies_real_checks_and_names_render_only_tests(site):
    url = site + "/contact"
    required = _form_tests(url, PAGES["/contact"])["form-required-empty"]
    verdict = await acceptance.check({"id": 1, "name": "t", "description": __import__("json").dumps(
        {"steps": required["steps"]})}, url)
    assert verdict["status"] == acceptance.VERIFIED, verdict

    render_only = {"steps": [{"action": "NAVIGATE", "value": url}, {"action": "ASSERT_VISIBLE", "target": "body"}]}
    verdict = await acceptance.check({"id": 2, "name": "t", "description": __import__("json").dumps(render_only)}, url)
    assert verdict["status"] == acceptance.UNVERIFIABLE


def test_a_test_that_passes_on_the_broken_page_asserts_nothing():
    from engine.schemas import ActionType, StepStatus

    plan = SimpleNamespace(steps=[SimpleNamespace(step_id="c", action=ActionType.ASSERT_TEXT, expected="Thanks",
                                                  target=None)])
    passed = SimpleNamespace(status=TestStatus.PASSED, steps=[])
    assert acceptance.judge(plan, passed, ["Thanks"], []) == acceptance.ASSERTS_NOTHING
    # failing somewhere other than the removed check proves nothing either way
    elsewhere = SimpleNamespace(status=TestStatus.FAILED, steps=[SimpleNamespace(step_id="x", status=StepStatus.FAILED)])
    assert acceptance.judge(plan, elsewhere, ["Thanks"], []) == acceptance.INCONCLUSIVE


def test_a_test_is_checked_once_per_version_of_its_steps():
    import json

    steps = [{"action": "NAVIGATE", "value": "u"}, {"action": "ASSERT_CONTAINS_TEXT", "target": "body", "value": "Hi"}]
    tc = {"id": 1, "description": json.dumps({"steps": steps})}
    assert acceptance.needs_check(tc)
    tc["acceptance"] = {"steps_key": acceptance.steps_key(steps), "status": "verified"}
    assert not acceptance.needs_check(tc)
    tc["description"] = json.dumps({"steps": [*steps, {"action": "ASSERT_VISIBLE", "target": "#x"}]})
    assert acceptance.needs_check(tc)


def test_the_suite_includes_the_form_tests(site):
    analysis = {"url": site + "/contact", "page_title": "Contact us", "elements_inventory": {},
                "synthesized_test_case": {"steps": []}, "form_tests": list(_form_tests(site + "/contact",
                                                                                     PAGES["/contact"]).values())}
    slugs = {t["slug"] for t in suite.page_tests(analysis)}
    assert {"form-required-empty", "form-invalid-email"} <= slugs
