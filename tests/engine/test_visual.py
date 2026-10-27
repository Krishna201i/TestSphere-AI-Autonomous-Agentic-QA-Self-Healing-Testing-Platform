"""Visual regression in the engine: a settled screenshot of a passing run, compared in the browser."""

from __future__ import annotations

import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from engine.runner import run_test
from engine.schemas import ActionType, Step, Target, TestPlan, TestStatus

DEMO_DIR = Path(__file__).parent / "demo_app"


@pytest.fixture(scope="module")
def demo_server():
    handler = partial(SimpleHTTPRequestHandler, directory=str(DEMO_DIR))
    handler.log_message = lambda *_: None  # type: ignore[method-assign]
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def open_page(base: str, page: str, check: str = "body") -> TestPlan:
    return TestPlan(test_id=f"visual-{page}", name="visual", base_url=base, steps=[
        Step(step_id="open", action=ActionType.GOTO, value=f"{base}/{page}"),
        Step(step_id="check", action=ActionType.ASSERT_VISIBLE, target=Target(description="page", primary_locator=check)),
    ])


async def test_same_screen_has_no_change_and_another_screen_does(demo_server):
    first = await run_test(open_page(demo_server, "index.html"), visual=True)
    assert first.status == TestStatus.PASSED and set(first.visual) == {"current"}
    baseline = Path(first.visual["current"]).read_bytes()
    assert baseline[:8] == b"\x89PNG\r\n\x1a\n"

    same = await run_test(open_page(demo_server, "index.html"), visual=True, visual_baseline=baseline)
    assert same.visual["ratio"] == 0 and "diff" not in same.visual

    other = await run_test(open_page(demo_server, "dashboard.html"), visual=True, visual_baseline=baseline)
    assert other.visual["ratio"] > 0.02 and not other.visual["size_changed"]
    assert Path(other.visual["diff"]).read_bytes()[:4] == b"\x89PNG"


async def test_failed_runs_and_runs_without_visual_take_no_screenshot(demo_server):
    failed = await run_test(open_page(demo_server, "index.html", check="#nope"), visual=True)
    assert failed.status == TestStatus.FAILED and failed.visual is None
    plain = await run_test(open_page(demo_server, "index.html"))
    assert plain.visual is None
