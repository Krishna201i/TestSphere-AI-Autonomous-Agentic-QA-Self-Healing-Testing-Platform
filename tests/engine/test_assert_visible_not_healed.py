"""A visibility check on an element that is there but hidden is a failed check.

The timeout it raised went to healing, which could move the check onto some
visible look-alike (a stored fallback) and turn a real failure into a pass.
Only an element that is not on the page at all is a locator worth healing.
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from engine.runner import run_test
from engine.schemas import (
    ActionType,
    RunOptions,
    Step,
    StepStatus,
    Target,
    TestPlan,
    TestStatus,
)

PAGE = """<!doctype html><title>t</title>
<div id="banner" style="display:none">Saved!</div>
<div id="other-banner">Saved!</div>"""


@pytest.fixture(scope="module")
def site():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(PAGE.encode())

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/"
    server.shutdown()


def _plan(url: str, locator: str) -> TestPlan:
    target = Target(description="the saved banner", primary_locator=locator, fallback_locators=["#other-banner"])
    return TestPlan(test_id="t", name="t", base_url=url, steps=[
        Step(step_id="s1", action=ActionType.GOTO, value=url),
        Step(step_id="s2", action=ActionType.ASSERT_VISIBLE, target=target),
    ])


async def test_a_hidden_element_fails_the_check_and_is_not_healed(site):
    result = await run_test(_plan(site, "#banner"), RunOptions(min_action_timeout_ms=1500))
    step = result.steps[1]
    assert result.status == TestStatus.FAILED and step.status == StepStatus.FAILED
    assert "on the page but not visible" in (step.error or "")
    assert step.healing is None


async def test_a_locator_that_matches_nothing_may_still_be_healed(site):
    result = await run_test(_plan(site, "#renamed-banner"), RunOptions(min_action_timeout_ms=1500))
    assert result.steps[1].status == StepStatus.HEALED
