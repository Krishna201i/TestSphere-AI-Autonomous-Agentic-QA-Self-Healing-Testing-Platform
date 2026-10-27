"""
tests/engine/test_runner_actions.py
===================================
Real-Chromium checks of engine actions and assertions whose loose versions
let wrong results pass:

- check / uncheck set the box's state (a click would toggle it)
- assert_value compares an input's value; exact assert_text / assert_url
- press without a target goes to the page; wait without a value settles
- goto fails on an HTTP error status unless that status is expected
- each run writes to its own directory, never outside the artifacts root
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

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

FORM = """<!doctype html><html><head><title>Form</title></head><body>
<input id="agree" type="checkbox" checked>
<input id="news" type="checkbox">
<input id="name" value="Bob">
<p id="greeting">Hello   Bob</p>
<p id="keys"></p>
<script>document.addEventListener("keydown", (e) => { document.getElementById("keys").textContent += e.key; });</script>
</body></html>"""


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - http.server API
        status = {"/missing": 404, "/broken": 500}.get(self.path, 200)
        body = (FORM if status == 200 else f"<h1>Error {status}</h1>").encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_: object) -> None:
        pass


@pytest.fixture(scope="module")
def site() -> str:  # type: ignore[misc]
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def _target(selector: str) -> Target:
    return Target(description=selector, primary_locator=selector)


async def _run(site: str, *steps: Step, path: str = "/form", test_id: str = "actions", **options) -> list:
    plan = TestPlan(test_id=test_id, name="actions", base_url=site,
                    steps=[Step(step_id="open", action=ActionType.GOTO, value=f"{site}{path}"), *steps])
    result = await run_test(plan, RunOptions(min_action_timeout_ms=1000, **options))
    return result


async def test_check_and_uncheck_set_the_state(site: str) -> None:
    result = await _run(
        site,
        Step(step_id="check", action=ActionType.CHECK, target=_target("#agree")),  # already checked: stays checked
        Step(step_id="uncheck", action=ActionType.UNCHECK, target=_target("#news")),  # already unchecked
        Step(step_id="checked", action=ActionType.ASSERT_VISIBLE, target=_target("#agree:checked")),
        Step(step_id="unchecked", action=ActionType.ASSERT_HIDDEN, target=_target("#news:checked")),
    )
    assert result.status == TestStatus.PASSED, [s.error for s in result.steps]


async def test_assert_value_compares_the_input_value(site: str) -> None:
    passed = await _run(site, Step(step_id="v", action=ActionType.ASSERT_VALUE, target=_target("#name"),
                                   expected="Bob"))
    failed = await _run(site, Step(step_id="v", action=ActionType.ASSERT_VALUE, target=_target("#name"),
                                   expected="Alice"))
    assert passed.status == TestStatus.PASSED
    assert failed.status == TestStatus.FAILED
    assert "expected 'Alice', got 'Bob'" in failed.steps[-1].error
    assert failed.steps[-1].healing is None  # a wrong value is a result, never a locator to heal


async def test_exact_text_and_url(site: str) -> None:
    def text(expected: str, exact: bool) -> Step:
        return Step(step_id="t", action=ActionType.ASSERT_TEXT, target=_target("#greeting"), expected=expected,
                    exact=exact)

    def url(expected: str, exact: bool) -> Step:
        return Step(step_id="u", action=ActionType.ASSERT_URL, expected=expected, exact=exact, timeout_ms=1000)

    assert (await _run(site, text("hello", exact=False))).status == TestStatus.PASSED
    assert (await _run(site, text("Hello Bob", exact=True))).status == TestStatus.PASSED  # whitespace collapsed
    assert (await _run(site, text("Hello", exact=True))).status == TestStatus.FAILED
    assert (await _run(site, url(f"{site}/form", exact=True))).status == TestStatus.PASSED
    assert (await _run(site, url(f"{site}/", exact=True))).status == TestStatus.FAILED
    assert (await _run(site, url(f"{site}/", exact=False))).status == TestStatus.PASSED


async def test_press_without_target_and_plain_wait(site: str) -> None:
    result = await _run(
        site,
        Step(step_id="wait", action=ActionType.WAIT_FOR),
        Step(step_id="press", action=ActionType.PRESS, value="Enter"),
        Step(step_id="seen", action=ActionType.ASSERT_TEXT, target=_target("#keys"), expected="Enter"),
    )
    assert result.status == TestStatus.PASSED, [s.error for s in result.steps]


@pytest.mark.parametrize("path, status", [("/missing", 404), ("/broken", 500)])
async def test_goto_fails_on_an_error_status(site: str, path: str, status: int) -> None:
    result = await _run(site, Step(step_id="body", action=ActionType.ASSERT_VISIBLE, target=_target("body")),
                        path=path)
    assert result.status == TestStatus.FAILED
    assert result.steps[0].status == StepStatus.FAILED
    assert f"HTTP {status}" in result.steps[0].error


async def test_goto_can_expect_an_error_page(site: str) -> None:
    plan = TestPlan(test_id="t", name="t", base_url=site, steps=[
        Step(step_id="open", action=ActionType.GOTO, value=f"{site}/missing", expected="404"),
    ])
    assert (await run_test(plan)).status == TestStatus.PASSED


async def test_each_run_has_its_own_directory_inside_the_root(site: str, tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    failing = Step(step_id="../../escape", action=ActionType.CLICK, target=_target("#nope"))
    first = await _run(site, failing, test_id="../../outside", artifacts_dir=str(root))
    second = await _run(site, failing, test_id="../../outside", artifacts_dir=str(root))

    assert first.artifacts_dir != second.artifacts_dir
    for result in (first, second):
        run_dir = Path(result.artifacts_dir).resolve()
        assert root.resolve() in run_dir.parents
        shot = Path(result.steps[-1].screenshot_path).resolve()
        assert run_dir in shot.parents
    assert not (tmp_path / "outside").exists()
