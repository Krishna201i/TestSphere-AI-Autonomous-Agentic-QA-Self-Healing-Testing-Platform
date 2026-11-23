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
- hover moves the pointer; upload attaches a generated file, never a server file
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
<button id="menu" onmouseenter="document.getElementById('tip').hidden = false">Menu</button>
<p id="tip" hidden>Shown on hover</p>
<input id="avatar" type="file" onchange="document.getElementById('picked').textContent = this.files[0].name + ' ' + this.files[0].type">
<p id="picked"></p>
<button id="delete" onclick="document.getElementById('deleted').textContent = confirm('Delete this item?') ? 'deleted' : 'kept'">Delete</button>
<p id="deleted"></p>
<p id="width"></p><script>document.getElementById("width").textContent = "w" + window.innerWidth;</script>
</body></html>"""


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - http.server API
        status = {"/missing": 404, "/broken": 500}.get(self.path, 200)
        body = (FORM if status == 200 else f"<h1>Error {status}</h1>").encode()
        if self.path == "/me":  # who the session cookie says you are
            signed_in = "session=alice" in (self.headers.get("Cookie") or "")
            body = f"<p id='who'>{'alice' if signed_in else 'nobody'}</p>".encode()
        self.send_response(status)
        if self.path == "/signin":
            self.send_header("Set-Cookie", "session=alice; Path=/; HttpOnly")
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


async def _run(site: str, *steps: Step, path: str = "/form", test_id: str = "actions", keep_state=None, **options) -> list:
    plan = TestPlan(test_id=test_id, name="actions", base_url=site,
                    steps=[Step(step_id="open", action=ActionType.GOTO, value=f"{site}{path}"), *steps])
    result = await run_test(plan, RunOptions(min_action_timeout_ms=1000, **options), keep_state=keep_state)
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


async def test_hover_shows_what_the_pointer_reveals(site: str) -> None:
    result = await _run(
        site,
        Step(step_id="hover", action=ActionType.HOVER, target=_target("#menu")),
        Step(step_id="tip", action=ActionType.ASSERT_VISIBLE, target=_target("#tip")),
    )
    assert result.status == TestStatus.PASSED, [s.error for s in result.steps]


async def test_upload_attaches_a_generated_file_by_name_only(site: str) -> None:
    result = await _run(
        site,
        # A path to a real server file: only its name is used, the content is generated
        Step(step_id="upload", action=ActionType.UPLOAD, target=_target("#avatar"), value="C:/Windows/../etc/photo.png"),
        Step(step_id="picked", action=ActionType.ASSERT_TEXT, target=_target("#picked"), expected="photo.png image/png",
             exact=True),
    )
    assert result.status == TestStatus.PASSED, [s.error for s in result.steps]


async def test_a_signed_in_session_carries_over_to_the_next_run(site: str) -> None:
    kept: list[dict] = []
    signin = TestPlan(test_id="signin", name="signin", base_url=site,
                      steps=[Step(step_id="open", action=ActionType.GOTO, value=f"{site}/signin")])
    assert (await run_test(signin, RunOptions(min_action_timeout_ms=1000), keep_state=kept)).status == TestStatus.PASSED
    assert any(c["name"] == "session" for c in kept[0]["cookies"])

    who = Step(step_id="who", action=ActionType.ASSERT_TEXT, target=_target("#who"), expected="alice", exact=True)
    me = TestPlan(test_id="me", name="me", base_url=site,
                  steps=[Step(step_id="open", action=ActionType.GOTO, value=f"{site}/me"), who])
    assert (await run_test(me, RunOptions(min_action_timeout_ms=1000), storage_state=kept[0])).status == TestStatus.PASSED
    # Without the session the same page is signed out
    assert (await run_test(me, RunOptions(min_action_timeout_ms=1000))).status == TestStatus.FAILED


async def test_a_failed_run_hands_no_session_on(site: str) -> None:
    kept: list[dict] = []
    await _run(site, Step(step_id="x", action=ActionType.CLICK, target=_target("#nothing-here")), keep_state=kept)
    assert kept == []


async def test_the_window_size_can_be_a_phone(site: str) -> None:
    width = Step(step_id="width", action=ActionType.ASSERT_TEXT, target=_target("#width"), expected="w390", exact=True)
    assert (await _run(site, width, viewport="390x844")).status == TestStatus.PASSED
    default = Step(step_id="width", action=ActionType.ASSERT_TEXT, target=_target("#width"), expected="w1280", exact=True)
    assert (await _run(site, default)).status == TestStatus.PASSED


async def test_a_confirm_dialog_is_answered_ok_and_recorded(site: str) -> None:
    result = await _run(
        site,
        Step(step_id="delete", action=ActionType.CLICK, target=_target("#delete")),
        Step(step_id="deleted", action=ActionType.ASSERT_TEXT, target=_target("#deleted"), expected="deleted", exact=True),
    )
    assert result.status == TestStatus.PASSED, [s.error for s in result.steps]
    click = next(s for s in result.steps if s.step_id == "delete")
    assert "[dialog confirm] Delete this item?" in click.console_logs


DRAGDROP = """<!doctype html><html><head><title>Drag</title></head><body>
<div id="src" draggable="true">handle</div>
<div id="zone">drop here</div>
<p id="dropped"></p>
<script>
const zone = document.getElementById('zone');
document.getElementById('src').addEventListener('dragstart', e => e.dataTransfer.setData('t', '1'));
zone.addEventListener('dragover', e => e.preventDefault());
zone.addEventListener('drop', e => { e.preventDefault(); document.getElementById('dropped').textContent = 'yes'; });
</script></body></html>"""

TABS = """<!doctype html><html><head><title>Opener</title></head><body>
<a id="open" href="/other" target="_blank">Open other</a>
<a id="dl" href="data:text/plain,hello" download="note.txt">Download</a>
<a id="report" href="/files/report.pdf">Report</a>
<button id="popup" onclick="window.open('/other')">Pop up</button>
<button id="plain">Plain</button>
</body></html>"""


class _MultiHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        body = {"/drag": DRAGDROP, "/tabs": TABS, "/other": "<!doctype html><title>Other</title><h1 id='h'>Other page</h1>"}.get(
            self.path, "<!doctype html><title>x</title>").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


@pytest.fixture(scope="module")
def multisite():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _MultiHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


async def test_drag_moves_an_element_onto_a_target(multisite: str) -> None:
    plan = TestPlan(test_id="drag", name="drag", base_url=multisite, steps=[
        Step(step_id="open", action=ActionType.GOTO, value=f"{multisite}/drag"),
        Step(step_id="drag", action=ActionType.DRAG, target=Target(description="handle", primary_locator="#src"), value="#zone"),
        Step(step_id="check", action=ActionType.ASSERT_TEXT, target=Target(description="result", primary_locator="#dropped"),
             expected="yes", exact=True),
    ])
    result = await run_test(plan, RunOptions(min_action_timeout_ms=2000))
    assert result.status == TestStatus.PASSED, [s.error for s in result.steps]


async def test_a_click_that_opens_a_new_tab_is_followed(multisite: str) -> None:
    plan = TestPlan(test_id="tabs", name="tabs", base_url=multisite, steps=[
        Step(step_id="open", action=ActionType.GOTO, value=f"{multisite}/tabs"),
        Step(step_id="click", action=ActionType.CLICK, target=Target(description="open", primary_locator="#open")),
        # This assertion only passes if the run switched to the newly opened tab
        Step(step_id="check", action=ActionType.ASSERT_TEXT, target=Target(description="heading", primary_locator="#h"),
             expected="Other page", exact=True),
    ])
    result = await run_test(plan, RunOptions(min_action_timeout_ms=2000))
    assert result.status == TestStatus.PASSED, [s.error for s in result.steps]
    assert any("[new tab]" in log for log in result.steps[1].console_logs)


async def test_a_download_is_captured(multisite: str) -> None:
    plan = TestPlan(test_id="dl", name="dl", base_url=multisite, steps=[
        Step(step_id="open", action=ActionType.GOTO, value=f"{multisite}/tabs"),
        Step(step_id="dl", action=ActionType.CLICK, target=Target(description="download", primary_locator="#dl")),
    ])
    result = await run_test(plan, RunOptions(min_action_timeout_ms=2000))
    # The download is recorded against the step that triggered it
    await_logs = result.steps[1].console_logs
    assert any("[download] note.txt" in log for log in await_logs), await_logs


async def test_a_tab_a_script_opens_is_followed(multisite: str) -> None:
    plan = TestPlan(test_id="popup", name="popup", base_url=multisite, steps=[
        Step(step_id="open", action=ActionType.GOTO, value=f"{multisite}/tabs"),
        Step(step_id="click", action=ActionType.CLICK, target=Target(description="pop up", primary_locator="#popup")),
        Step(step_id="check", action=ActionType.ASSERT_TEXT, target=Target(description="heading", primary_locator="#h"),
             expected="Other page", exact=True),
    ])
    result = await run_test(plan, RunOptions(min_action_timeout_ms=2000))
    assert result.status == TestStatus.PASSED, [s.error for s in result.steps]


async def test_only_links_to_a_tab_or_a_file_wait_long_for_one(multisite: str) -> None:
    from playwright.async_api import async_playwright

    from engine.runner import _OPEN_GRACE_LINKED_S, _OPEN_GRACE_OTHER_S, _open_grace

    def click(selector: str) -> Step:
        return Step(step_id="c", action=ActionType.CLICK, target=Target(description="x", primary_locator=selector))

    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page()
        await page.goto(f"{multisite}/tabs")
        for selector in ("#open", "#dl", "#report"):
            assert await _open_grace(page, click(selector)) == _OPEN_GRACE_LINKED_S, selector
        for selector in ("#plain", "#popup", "#missing"):  # a missing element is not waited for
            assert await _open_grace(page, click(selector)) == _OPEN_GRACE_OTHER_S, selector
        fill = Step(step_id="f", action=ActionType.FILL, target=Target(description="x", primary_locator="#plain"), value="v")
        assert await _open_grace(page, fill) == 0.0
        await browser.close()
