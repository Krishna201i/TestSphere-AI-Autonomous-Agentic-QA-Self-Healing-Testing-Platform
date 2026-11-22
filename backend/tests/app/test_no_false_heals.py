"""
No false heals through the AI healer, in a real browser.

The AI healer's candidate used to replace the broken locator outright, so the
engine's safeguards (same kind of control, shared identity, score threshold)
never looked at it: when the button a test clicked was removed and another
button happened to make the test's check pass, the run was reported HEALED.
Now the candidate is offered to the engine as a fallback and the engine
decides; a removed element is a failure, never a heal onto a look-alike.
"""

from __future__ import annotations

import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

from agents.memory.in_memory_store import InMemoryStore
from backend.database.session import get_store
from backend.services.application_service import ApplicationService
from backend.services.project_service import ProjectService
from backend.services.test_case_service import TestCaseService
from backend.services.test_execution_service import TestExecutionService
from engine.schemas import RunOptions
from tests.backend.test_self_healing_runs import _service, _steps

V1 = """<!doctype html><html><head><title>Shop</title></head><body>
<button id="submit" class="btn primary" type="button">Log in</button>
<p id="welcome" hidden>Welcome back</p>
<script>document.getElementById("submit").onclick = () => { document.getElementById("welcome").hidden = false; };</script>
</body></html>"""

# The "Log in" button is gone.  Another button of the same kind and style is
# there, and clicking it happens to show the text the test checks for.
V2_REMOVED = """<!doctype html><html><head><title>Shop</title></head><body>
<button id="delete" class="btn primary" type="button">Delete account</button>
<p id="welcome" hidden>Welcome back</p>
<script>document.getElementById("delete").onclick = () => { document.getElementById("welcome").hidden = false; };</script>
</body></html>"""


@pytest.fixture
def site(tmp_path):
    root = tmp_path / "site"
    root.mkdir()
    handler = partial(SimpleHTTPRequestHandler, directory=str(root))
    handler.log_message = lambda *_: None  # type: ignore[method-assign]
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    def publish(html: str) -> None:
        (root / "login.html").write_text(html, encoding="utf-8")

    publish(V1)
    yield f"http://127.0.0.1:{server.server_address[1]}/login.html", publish
    server.shutdown()


async def test_a_removed_button_is_not_healed_onto_a_look_alike_that_makes_the_check_pass(site, tmp_path):
    url, publish = site
    db = get_store()
    project = ProjectService.create_project(db, name="Shop")
    app = ApplicationService.create_application(db, project.id, name="Shop", base_url=url)
    tc = TestCaseService.create_test_case(db, app.id, external_id=None, name="Login", description=_steps(
        {"action": "navigate", "value": url},
        {"action": "click", "target": "#submit"},
        {"action": "assert_visible", "target": "#welcome"},
    ))
    memory = InMemoryStore()
    service = _service(memory)
    options = RunOptions(headless=True, min_action_timeout_ms=1500, artifacts_dir=str(tmp_path / "artifacts"))

    async def run() -> dict:
        execution = TestExecutionService.create_execution(db, tc.id)
        return await service.execute_test_run(db=db, execution_id=execution.id, options=options)

    first = await run()
    assert first["status"] == "PASSED", first["error_message"]

    publish(V2_REMOVED)
    second = await run()

    assert second["status"] == "FAILED", f"false heal: {second['error_message']}"
    assert not [h for h in memory.get_healing_history("#submit") if h.validation_result]
