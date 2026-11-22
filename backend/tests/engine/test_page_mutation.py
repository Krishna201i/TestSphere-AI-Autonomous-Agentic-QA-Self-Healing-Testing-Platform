"""
A deliberately broken page (RunOptions.mutation), in real Chromium.

The acceptance check runs a test once more on a page where what its checks
rely on is removed; a test that still passes there checks nothing.  The
removal must be complete (split text, content scripts add later), or a good
test would be wrongly called empty.
"""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from engine.runner import run_test
from engine.schemas import (
    ActionType,
    PageMutation,
    RunOptions,
    Step,
    Target,
    TestPlan,
    TestStatus,
)

PAGE = """<!doctype html><title>Shop · Welcome back</title><body>
<h1>Welcome <b>back</b>, Ann</h1>
<span id="badge">3 items</span>
<p id="later"></p>
<script>setTimeout(() => { document.getElementById('later').textContent = 'Order confirmed'; }, 300);</script>
</body>"""


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


def _plan(url, check):
    return TestPlan(test_id="t", name="t", base_url=url, steps=[Step(step_id="s1", action=ActionType.GOTO, value=url),
                                                               check])


async def _status(url, check, mutation=None):
    options = RunOptions(min_action_timeout_ms=1500, mutation=mutation)
    return (await run_test(_plan(url, check), options)).status


@pytest.mark.parametrize(("check", "mutation"), [
    # text split across tags, matched case-insensitively
    (Step(step_id="c", action=ActionType.ASSERT_TEXT, target=Target(description="body", primary_locator="body"),
          expected="welcome back"), PageMutation(hide_texts=["Welcome back"])),
    # text a script adds after the page loaded
    (Step(step_id="c", action=ActionType.ASSERT_TEXT, target=Target(description="body", primary_locator="body"),
          expected="Order confirmed"), PageMutation(hide_texts=["Order confirmed"])),
    # an element
    (Step(step_id="c", action=ActionType.ASSERT_VISIBLE, target=Target(description="badge", primary_locator="#badge")),
     PageMutation(hide_selectors=["#badge"])),
])
async def test_a_check_passes_on_the_page_and_fails_on_the_broken_one(site, check, mutation):
    assert await _status(site, check) == TestStatus.PASSED
    assert await _status(site, check, mutation) == TestStatus.FAILED


async def test_removing_something_else_leaves_the_check_passing(site):
    check = Step(step_id="c", action=ActionType.ASSERT_VISIBLE, target=Target(description="badge", primary_locator="#badge"))
    assert await _status(site, check, PageMutation(hide_texts=["Order confirmed"])) == TestStatus.PASSED
