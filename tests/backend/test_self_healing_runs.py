"""
Self-healing on real executions (backend/orchestration/orchestrator.py).

Covers the path a run takes when a locator breaks:
- the AI healer gets the failed page's elements, its replacement is
  validated by a re-run, and the heal is recorded (and never crashes the run);
- a Playwright locator timeout reaches the healer; a transient failure is retried;
- fingerprints and fallback locators the engine learns are kept on the test
  case and used by the next run;
- healing memory is recorded with its owner and erased with the account;
- the failure analyzer gets the configured LLM.

The last class drives real Chromium against a page whose button id changed.
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import AsyncMock, patch

import pytest

from agents.analyzer.analyzer import FailureAnalyzerAgent
from agents.analyzer.schemas import FailureContext
from agents.memory.in_memory_store import InMemoryStore
from agents.memory.memory_schemas import HealingRecord
from agents.memory.persistent_store import (
    COLLECTION,
    PersistentMemoryStore,
    memory_owner,
)
from agents.orchestration.workflow_schemas import AgentState, WorkflowStep
from agents.schemas.enums import FailureType
from backend.database.session import get_store
from backend.models import AGENT_MEMORY, TEST_CASES, TEST_EXECUTIONS
from backend.orchestration import orchestrator as orchestration
from backend.orchestration.converters import (
    collect_learned_targets,
    engine_result_to_execution_result,
    learned_targets_by_locator,
    page_elements_from_dom,
)
from backend.orchestration.converters import (
    test_case_to_engine_plan as to_engine_plan,
)
from backend.orchestration.orchestrator import (
    PlatformWorkflowOrchestrator,
    create_default_orchestrator,
)
from backend.services.application_service import ApplicationService
from backend.services.project_service import ProjectService
from backend.services.test_case_service import TestCaseService
from backend.services.test_execution_service import TestExecutionService
from engine.schemas import (
    ActionType,
    ElementFingerprint,
    HealingReport,
    RunOptions,
    Step,
    StepResult,
    StepStatus,
    Target,
    TestPlan,
    TestResult,
    TestStatus,
)

LOCATOR_TIMEOUT = (
    'Locator.click: Timeout 1500ms exceeded.\nCall log:\n  - waiting for locator("#login-button").first'
)

LOGIN_FINGERPRINT = ElementFingerprint(tag="button", id="login-button", classes=["btn"], text="Log in")

FAILED_PAGE = """<html><body>
<a href="/help">Help</a>
<input name="email" placeholder="Email">
<button id="sign-in" class="btn">Log in</button>
<button id="cancel" class="btn">Cancel</button>
</body></html>"""


def _steps(*steps: dict) -> str:
    return json.dumps({"steps": list(steps)})


LOGIN_STEPS = _steps(
    {"action": "navigate", "value": "https://shop.example/login"},
    {"action": "click", "target": "#login-button"},
)


def _result(status: TestStatus, *steps: StepResult) -> TestResult:
    return TestResult(test_id="t", status=status, started_at=datetime.now(UTC), duration_ms=10,
                      steps=list(steps), artifacts_dir="artifacts")


def _ok(step_id: str, url: str = "https://shop.example/login") -> StepResult:
    return StepResult(step_id=step_id, status=StepStatus.PASSED, duration_ms=1, page_url=url)


def _setup(description: str, healing_targets: list | None = None, owner: str | None = None):
    db = get_store()
    project = ProjectService.create_project(db, name="Healing")
    app = ApplicationService.create_application(db, project.id, name="Shop", base_url="https://shop.example/login")
    tc = TestCaseService.create_test_case(db, app.id, external_id=None, name="Login", description=description)
    if healing_targets is not None:
        db.update(TEST_CASES, tc.id, healing_targets=healing_targets)
    execution = TestExecutionService.create_execution(db, tc.id)
    if owner:
        db.update(TEST_EXECUTIONS, execution.id, owner_uid=owner)
    return db, tc, execution


def _service(memory=None) -> PlatformWorkflowOrchestrator:
    return PlatformWorkflowOrchestrator(create_default_orchestrator(memory or InMemoryStore()))


def _known_login_button() -> list[dict]:
    """What an earlier passing run learned about #login-button."""
    return [{"locator": "#login-button", "fallback_locators": [],
             "fingerprint": LOGIN_FINGERPRINT.model_dump(mode="json")}]


# ---------------------------------------------------------------------------
# AI healing on a run
# ---------------------------------------------------------------------------


class TestAIHealingOnARun:
    async def test_a_run_the_engine_healed_counts_as_healed_in_the_summary(self):
        healed = _result(TestStatus.HEALED, _ok("step-1"), StepResult(
            step_id="step-2", status=StepStatus.HEALED, duration_ms=1, locator_used="button.btn",
            healing=HealingReport(original_locator="#login-button", selected_locator="button.btn",
                                  confidence=0.9, strategy_used="fallback[0]")))
        db, _tc, execution = _setup(LOGIN_STEPS)

        with patch("backend.orchestration.orchestrator.run_test", new=AsyncMock(return_value=healed)):
            result = await _service().execute_test_run(db=db, execution_id=execution.id)

        assert result["status"] == "HEALED"
        assert result["dashboard_summary"]["healed_tests"] == 1

    async def test_broken_selector_is_healed_validated_and_recorded(self, tmp_path):
        snapshot = tmp_path / "dom.html"
        snapshot.write_text(FAILED_PAGE, encoding="utf-8")
        failed = _result(TestStatus.FAILED, _ok("step-1"), StepResult(
            step_id="step-2", status=StepStatus.FAILED, duration_ms=1500, error=LOCATOR_TIMEOUT,
            dom_snapshot_path=str(snapshot), page_url="https://shop.example/login"))
        validated = _result(TestStatus.PASSED, _ok("step-1"), _ok("step-2"))
        db, tc, execution = _setup(LOGIN_STEPS, _known_login_button())
        memory = InMemoryStore()

        with patch("backend.orchestration.orchestrator.run_test", new=AsyncMock(side_effect=[failed, validated])) as run:
            result = await _service(memory).execute_test_run(db=db, execution_id=execution.id)

        assert result["status"] == "HEALED", result["error_message"]
        assert "#login-button -> #sign-in" in result["error_message"]
        assert run.await_count == 2
        validation_plan = run.await_args_list[1].args[0]
        assert validation_plan.steps[1].target.primary_locator == "#sign-in"  # only the broken step changed
        assert db.get(TEST_EXECUTIONS, execution.id).status == "HEALED"

        # The validated heal is in healing memory, with the run itself
        heals = memory.get_healing_history("#login-button")
        assert [(h.new_selector, h.validation_result) for h in heals] == [("#sign-in", True)]
        assert memory.get_execution_history(f"tc-{tc.id}")[0].status.value == "PASSED"
        # ... and the next run of the test case tries the replacement first
        targets = learned_targets_by_locator(db.get(TEST_CASES, tc.id)["healing_targets"])
        assert targets["#login-button"]["fallback_locators"][0] == "#sign-in"

    async def test_a_replacement_that_does_not_pass_is_recorded_as_failed(self, tmp_path):
        snapshot = tmp_path / "dom.html"
        snapshot.write_text(FAILED_PAGE, encoding="utf-8")
        failed = _result(TestStatus.FAILED, _ok("step-1"), StepResult(
            step_id="step-2", status=StepStatus.FAILED, duration_ms=1500, error=LOCATOR_TIMEOUT,
            dom_snapshot_path=str(snapshot), page_url="https://shop.example/login"))
        db, _, execution = _setup(LOGIN_STEPS, _known_login_button())
        memory = InMemoryStore()

        with patch("backend.orchestration.orchestrator.run_test", new=AsyncMock(side_effect=[failed, failed, failed])):
            result = await _service(memory).execute_test_run(db=db, execution_id=execution.id)

        assert result["status"] == "FAILED"
        assert result["error_message"].startswith("Locator.click: Timeout")
        assert "none passed" in result["error_message"]
        assert all(h.validation_result is False for h in memory.get_healing_history("#login-button"))

    async def test_an_error_while_healing_ends_the_run_as_failed(self, tmp_path):
        snapshot = tmp_path / "dom.html"
        snapshot.write_text(FAILED_PAGE, encoding="utf-8")
        failed = _result(TestStatus.FAILED, _ok("step-1"), StepResult(
            step_id="step-2", status=StepStatus.FAILED, duration_ms=1500, error=LOCATOR_TIMEOUT,
            dom_snapshot_path=str(snapshot), page_url="https://shop.example/login"))
        db, _, execution = _setup(LOGIN_STEPS, _known_login_button())

        run = AsyncMock(side_effect=[failed, RuntimeError("browser vanished")])
        with patch("backend.orchestration.orchestrator.run_test", new=run):
            result = await _service().execute_test_run(db=db, execution_id=execution.id)

        assert result["status"] == "FAILED"
        assert db.get(TEST_EXECUTIONS, execution.id).status == "FAILED"

    async def test_a_crash_never_leaves_the_execution_running(self):
        db, _, execution = _setup(LOGIN_STEPS)
        service = _service()
        failed = _result(TestStatus.FAILED, StepResult(step_id="step-1", status=StepStatus.FAILED, duration_ms=1,
                                                       error="boom"))
        with patch("backend.orchestration.orchestrator.run_test", new=AsyncMock(return_value=failed)), \
                patch.object(service.ai_orchestrator, "submit_execution_result",
                             new=AsyncMock(side_effect=AttributeError("no such field"))), \
                pytest.raises(AttributeError):
            await service.execute_test_run(db=db, execution_id=execution.id)

        row = db.get(TEST_EXECUTIONS, execution.id)
        assert row.status == "FAILED"
        assert "Run failed unexpectedly (AttributeError" in row.error_message
        assert row.completed_at


# ---------------------------------------------------------------------------
# Locator timeouts and retries
# ---------------------------------------------------------------------------


def _analyze(error: str) -> FailureType:
    import asyncio

    context = FailureContext(test_id="t", execution_id="e", action="click", target_selector="#login-button",
                             error_message=error)
    return asyncio.run(FailureAnalyzerAgent(InMemoryStore()).analyze(context)).failure_type


class TestLocatorTimeouts:
    def test_a_locator_that_never_matched_is_a_missing_element(self):
        assert _analyze(LOCATOR_TIMEOUT) == FailureType.ELEMENT_NOT_FOUND

    def test_a_timeout_on_an_element_that_was_found_is_still_a_timeout(self):
        error = LOCATOR_TIMEOUT + '\n  -   locator resolved to <button id="login-button">Log in</button>' \
                                  "\n  - attempting click action\n  -   waiting for element to be stable"
        assert _analyze(error) == FailureType.TIMEOUT
        assert _analyze("Page.goto: Timeout 15000ms exceeded.") == FailureType.TIMEOUT

    async def test_a_transient_failure_is_retried_by_the_backend(self):
        db, _, execution = _setup(LOGIN_STEPS)
        slow = _result(TestStatus.FAILED, StepResult(step_id="step-1", status=StepStatus.FAILED, duration_ms=15000,
                                                     error="Page.goto: Timeout 15000ms exceeded."))
        passed = _result(TestStatus.PASSED, _ok("step-1"), _ok("step-2"))

        with patch("backend.orchestration.orchestrator.run_test", new=AsyncMock(side_effect=[slow, passed])) as run:
            result = await _service().execute_test_run(db=db, execution_id=execution.id)

        assert run.await_count == 2
        assert result["status"] == "PASSED"

    async def test_retries_are_bounded(self):
        db, _, execution = _setup(LOGIN_STEPS)
        slow = _result(TestStatus.FAILED, StepResult(step_id="step-1", status=StepStatus.FAILED, duration_ms=15000,
                                                     error="Page.goto: Timeout 15000ms exceeded."))
        with patch("backend.orchestration.orchestrator.run_test", new=AsyncMock(return_value=slow)) as run:
            result = await _service().execute_test_run(db=db, execution_id=execution.id)

        assert result["status"] == "FAILED"
        assert run.await_count == 2  # the policy allows one retry


# ---------------------------------------------------------------------------
# The healer's view of the failed page
# ---------------------------------------------------------------------------


class TestCurrentPageElements:
    def test_elements_get_selectors_unique_on_the_page(self):
        html = """<html><body><script>var b = '<button id="fake">x</button>'</script>
        <input type="hidden" name="csrf" value="1">
        <button hidden id="ghost">Ghost</button>
        <button class="btn">Sign in</button><button class="btn">Sign in later</button>
        <a href="/help">Help</a><a>not a link</a>
        <div role="button" data-testid="go">Go</div>
        <input name="q" placeholder="Search"></body></html>"""
        selectors = [e.selector for e in page_elements_from_dom(html, "https://x.example/")]
        # "Sign in" also occurs in "Sign in later": no unique selector, left out
        assert selectors == ['button:has-text("Sign in later")', 'a:has-text("Help")', '[data-testid="go"]',
                             'input[name="q"]']
        assert [e.selector for e in page_elements_from_dom(html, tag="a")] == ['a:has-text("Help")']

    def test_failure_context_carries_the_page_elements(self, tmp_path):
        snapshot = tmp_path / "dom.html"
        snapshot.write_text(FAILED_PAGE, encoding="utf-8")
        plan = TestPlan(test_id="t", name="t", base_url="https://shop.example/", steps=[
            Step(step_id="click", action=ActionType.CLICK,
                 target=Target(description="Log in", primary_locator="#login-button", fingerprint=LOGIN_FINGERPRINT)),
        ])
        result = _result(TestStatus.FAILED, StepResult(step_id="click", status=StepStatus.FAILED, duration_ms=1,
                                                       error=LOCATOR_TIMEOUT, dom_snapshot_path=str(snapshot),
                                                       page_url="https://shop.example/login"))

        context = engine_result_to_execution_result(result, "wf", "t", plan).failure_context

        assert context.current_page_url == "https://shop.example/login"
        # Only buttons: the broken target was a button
        assert [e["selector"] for e in context.dom_evidence["elements"]] == ["#sign-in", "#cancel"]
        state = AgentState(workflow_id="wf", current_step=WorkflowStep.ANALYZING_FAILURE, failure_context=context)
        current = create_default_orchestrator(InMemoryStore())._get_current_elements(state)
        assert [(e.selector, e.text, e.role) for e in current] == [("#sign-in", "Log in", "button"),
                                                                    ("#cancel", "Cancel", "button")]


# ---------------------------------------------------------------------------
# What the engine learns is kept
# ---------------------------------------------------------------------------


class TestLearnedTargets:
    def _case(self):
        from agents.planner.schemas import TestCase, TestStep
        from agents.schemas.enums import TestAction

        return TestCase(test_id="t", name="t", steps=[
            TestStep(step_number=1, action=TestAction.NAVIGATE, value="https://shop.example/"),
            TestStep(step_number=2, action=TestAction.CLICK, target="#submit"),
        ])

    def test_fingerprints_and_fallbacks_round_trip_into_the_next_plan(self):
        plan = to_engine_plan(self._case(), "https://shop.example/")
        assert plan.steps[1].target.fallback_locators == [] and plan.steps[1].target.fingerprint is None
        # The runner enriches the target after the step passes
        plan.steps[1].target.fallback_locators = ['button:has-text("Log in")', "button.btn"]
        plan.steps[1].target.fingerprint = LOGIN_FINGERPRINT
        healed = _result(TestStatus.HEALED, _ok("step-1"), StepResult(
            step_id="step-2", status=StepStatus.HEALED, duration_ms=1, locator_used="button.btn",
            healing=HealingReport(original_locator="#submit", selected_locator="button.btn", confidence=0.9,
                                  strategy_used="fallback[1]")))

        stored = collect_learned_targets(plan, plan, healed)
        json.dumps(stored)  # storable as a document field
        nxt = to_engine_plan(self._case(), "https://shop.example/", learned_targets_by_locator(stored))

        target = nxt.steps[1].target
        assert target.primary_locator == "#submit"
        assert target.fallback_locators == ["button.btn", 'button:has-text("Log in")']  # the heal goes first
        assert target.fingerprint == LOGIN_FINGERPRINT

    def test_unreadable_stored_targets_are_ignored(self):
        stored = [{"locator": "#submit", "fallback_locators": ["#x"], "fingerprint": {"bounding_box": "nope"}}]
        target = to_engine_plan(self._case(), "https://shop.example/",
                                          learned_targets_by_locator(stored)).steps[1].target
        assert target.fingerprint is None and target.fallback_locators == []

    async def test_a_run_saves_what_the_engine_learned(self):
        db, tc, execution = _setup(LOGIN_STEPS)

        async def run(plan, **_):
            plan.steps[1].target.fingerprint = LOGIN_FINGERPRINT  # as runner._enrich_target does
            plan.steps[1].target.fallback_locators = ['button:has-text("Log in")']
            return _result(TestStatus.PASSED, _ok("step-1"), _ok("step-2"))

        memory = InMemoryStore()
        with patch("backend.orchestration.orchestrator.run_test", new=run):
            await _service(memory).execute_test_run(db=db, execution_id=execution.id)

        saved = db.get(TEST_CASES, tc.id)["healing_targets"]
        assert saved == [{"locator": "#login-button", "fallback_locators": ['button:has-text("Log in")'],
                          "fingerprint": LOGIN_FINGERPRINT.model_dump(mode="json")}]
        element = memory.get_element_by_selector("#login-button")
        assert (element.text, element.role, element.page_url) == ("Log in", "button", "https://shop.example/login")

        # The next run starts from it
        second = TestExecutionService.create_execution(db, tc.id)
        seen = []

        async def run_again(plan, **_):
            seen.append(plan.steps[1].target.model_copy(deep=True))
            return _result(TestStatus.PASSED, _ok("step-1"), _ok("step-2"))

        with patch("backend.orchestration.orchestrator.run_test", new=run_again):
            await _service(memory).execute_test_run(db=db, execution_id=second.id)
        assert seen[0].fingerprint == LOGIN_FINGERPRINT
        assert seen[0].fallback_locators == ['button:has-text("Log in")']
        assert len(memory.get_element_history(f"tc-{tc.id}:#login-button")) == 1  # unchanged: not stored twice

    async def test_an_engine_heal_is_recorded_in_healing_memory(self):
        db, tc, execution = _setup(LOGIN_STEPS)
        healed = _result(TestStatus.HEALED, _ok("step-1"), StepResult(
            step_id="step-2", status=StepStatus.HEALED, duration_ms=1, locator_used="#sign-in",
            healing=HealingReport(original_locator="#login-button", selected_locator="#sign-in", confidence=0.86,
                                  strategy_used="fingerprint")))
        memory = InMemoryStore()
        with patch("backend.orchestration.orchestrator.run_test", new=AsyncMock(return_value=healed)):
            result = await _service(memory).execute_test_run(db=db, execution_id=execution.id)

        assert result["status"] == "HEALED"
        assert [(h.new_selector, h.validation_result) for h in memory.get_healing_history("#login-button")] == [
            ("#sign-in", True)]


# ---------------------------------------------------------------------------
# Healing memory: owner, erasure, bounded start-up
# ---------------------------------------------------------------------------


def _heal(i: int) -> HealingRecord:
    return HealingRecord(healing_id=f"h{i}", test_id="t", old_selector="#old", new_selector=f"#new{i}",
                         confidence=0.9, timestamp=f"2026-10-2{i}T00:00:00+00:00")


class TestHealingMemoryStorage:
    async def test_a_run_stores_its_memory_under_its_owner(self, fresh_store):
        db, _, execution = _setup(LOGIN_STEPS, owner="alice")
        passed = _result(TestStatus.PASSED, _ok("step-1"), _ok("step-2"))
        with patch("backend.orchestration.orchestrator.run_test", new=AsyncMock(return_value=passed)):
            await _service(PersistentMemoryStore(fresh_store)).execute_test_run(db=db, execution_id=execution.id)

        rows = fresh_store.find(AGENT_MEMORY)
        assert [r["kind"] for r in rows] == ["execution"]
        assert rows[0]["owner_uid"] == "alice"

    def test_cold_start_reads_only_the_newest_records(self, fresh_store):
        memory = PersistentMemoryStore(fresh_store)
        for i in range(1, 6):
            memory.store_healing_record(_heal(i))
        restarted = PersistentMemoryStore(fresh_store, max_records=3)
        assert [r.new_selector for r in restarted.get_healing_history("#old")] == ["#new5", "#new4", "#new3"]

    def test_erased_records_leave_the_running_memory(self, fresh_store, monkeypatch):
        memory = PersistentMemoryStore(fresh_store)
        with memory_owner("alice"):
            memory.store_healing_record(_heal(1))
        with memory_owner("bob"):
            memory.store_healing_record(_heal(2))
        monkeypatch.setattr(orchestration, "_platform_orchestrator", _service(memory))

        fresh_store.delete_where(COLLECTION, owner_uid="alice")  # what DELETE /me does
        orchestration.forget_healing_memory()

        assert [r.new_selector for r in memory.get_healing_history("#old")] == ["#new2"]

    def test_account_erasure_covers_healing_memory(self):
        from backend.api import me

        assert AGENT_MEMORY in me.OWNED_COLLECTIONS


def test_the_analyzer_gets_the_configured_llm(monkeypatch):
    from agents.llm.config import LLMConfig

    class Session:
        provider_name = "api"

    session = Session()
    monkeypatch.setattr(LLMConfig, "from_env", classmethod(lambda cls: LLMConfig(provider="api", model="m")))
    monkeypatch.setattr(orchestration, "create_llm_client", lambda config: session)

    agent = create_default_orchestrator(InMemoryStore())

    assert agent._analyzer._llm_client is session


# ---------------------------------------------------------------------------
# Real browser: a button whose id changed
# ---------------------------------------------------------------------------

PAGE = """<!doctype html><html><head><title>Shop</title></head><body>
<a href="#help">Help</a>
<button id="{id}" class="btn primary" type="button">Log in</button>
<p id="welcome" hidden>Welcome back</p>
<script>
document.getElementById("{id}").addEventListener("click", () => {{
  document.getElementById("welcome").hidden = false;
}});
</script>
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
        (root / "login.html").write_text(PAGE.format(id=button_id), encoding="utf-8")

    publish("submit")
    yield f"http://127.0.0.1:{server.server_address[1]}/login.html", publish
    server.shutdown()


class TestRealBrowserHealing:
    def _setup(self, url: str):
        db = get_store()
        project = ProjectService.create_project(db, name="Real")
        app = ApplicationService.create_application(db, project.id, name="Shop", base_url=url)
        tc = TestCaseService.create_test_case(db, app.id, external_id=None, name="Login", description=_steps(
            {"action": "navigate", "value": url},
            {"action": "click", "target": "#submit"},
            {"action": "assert_visible", "target": "#welcome"},
        ))
        return db, tc

    async def _run(self, db, tc, service, tmp_path) -> dict:
        execution = TestExecutionService.create_execution(db, tc.id)
        options = RunOptions(headless=True, min_action_timeout_ms=1500, artifacts_dir=str(tmp_path / "artifacts"))
        return await service.execute_test_run(db=db, execution_id=execution.id, options=options)

    async def test_the_engine_heals_from_what_the_last_run_learned(self, site, tmp_path):
        url, publish = site
        db, tc = self._setup(url)
        memory = InMemoryStore()
        service = _service(memory)

        first = await self._run(db, tc, service, tmp_path)
        assert first["status"] == "PASSED", first["error_message"]
        learned = learned_targets_by_locator(db.get(TEST_CASES, tc.id)["healing_targets"])
        assert learned["#submit"]["fingerprint"]["text"] == "Log in"

        publish("login-v2")  # the app renamed the button's id
        second = await self._run(db, tc, service, tmp_path)

        assert second["status"] == "HEALED", second["error_message"]
        assert second["error_message"].startswith("Self-healed #submit -> ")
        heals = memory.get_healing_history("#submit")
        assert len(heals) == 1 and heals[0].validation_result is True

    async def test_the_ai_healer_heals_when_the_engine_has_nothing_stored(self, site, tmp_path):
        url, publish = site
        db, tc = self._setup(url)
        memory = InMemoryStore()
        service = _service(memory)

        first = await self._run(db, tc, service, tmp_path)
        assert first["status"] == "PASSED", first["error_message"]
        db.update(TEST_CASES, tc.id, healing_targets=[])  # e.g. a test case saved before targets were kept

        publish("login-v2")
        second = await self._run(db, tc, service, tmp_path)

        assert second["status"] == "HEALED", second["error_message"]
        assert "AI healer" in second["error_message"]
        heals = memory.get_healing_history("#submit")
        assert [h.validation_result for h in heals] == [True]
        assert heals[0].new_selector in ("#login-v2", 'button:has-text("Log in")')
        # The validated replacement is now the engine's first fallback for #submit
        learned = learned_targets_by_locator(db.get(TEST_CASES, tc.id)["healing_targets"])
        assert learned["#submit"]["fallback_locators"][0] == heals[0].new_selector



# ---------------------------------------------------------------------------
# Stored steps reach the engine as written
# ---------------------------------------------------------------------------


async def test_checkbox_steps_and_exact_checks_reach_the_engine():
    db, _, execution = _setup(_steps(
        {"action": "NAVIGATE", "value": "https://shop.example/signup"},
        {"action": "CHECK", "target": "#terms"},
        {"action": "ASSERT_VALUE", "target": "#email", "value": "ann@example.com"},
        {"action": "ASSERT_HAS_TEXT", "target": "h1", "value": "Welcome"},
        {"action": "ASSERT_URL_EQUALS", "value": "https://shop.example/done"},
    ))
    seen = []

    async def run(plan, **_):
        seen.append(plan)
        return _result(TestStatus.PASSED, *[_ok(s.step_id) for s in plan.steps])

    with patch("backend.orchestration.orchestrator.run_test", new=run):
        await _service().execute_test_run(db=db, execution_id=execution.id)

    steps = [(s.action.value, s.expected, s.exact) for s in seen[0].steps]
    assert steps == [("goto", None, False), ("check", None, False), ("assert_value", "ann@example.com", False),
                     ("assert_text", "Welcome", True), ("assert_url", "https://shop.example/done", True)]


async def test_an_unknown_stored_action_is_not_run_as_a_click():
    db, _, execution = _setup(_steps({"action": "teleport", "target": "#menu"}))
    run = AsyncMock()
    with patch("backend.orchestration.orchestrator.run_test", new=run):
        result = await _service().execute_test_run(db=db, execution_id=execution.id)
    assert run.await_count == 0
    assert result["status"] == "FAILED" and "could not be read" in result["error_message"]
