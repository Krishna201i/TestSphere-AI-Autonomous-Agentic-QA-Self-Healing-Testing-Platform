from __future__ import annotations

import json
import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agents.analyzer.analyzer import FailureAnalyzerAgent
from agents.healer.healing_decision import HealingDecisionEngine
from agents.healer.healing_feedback import (
    HealingResultFeedback,
    HealingResultFeedbackProcessor,
)
from agents.llm import LLMClientSession, MockLLMProvider
from agents.llm.config import LLMConfig
from agents.llm.factory import create_llm_client
from agents.memory.in_memory_store import InMemoryStore
from agents.memory.memory_interface import MemoryStore
from agents.memory.memory_schemas import FailureInfo, TestExecutionRecord
from agents.memory.persistent_store import PersistentMemoryStore, memory_owner
from agents.orchestration.agent_orchestrator import AgentOrchestrator
from agents.orchestration.recovery_policy import (
    RecoveryAction,
    RecoveryPolicy,
    RecoveryPolicyConfig,
)
from agents.orchestration.workflow_schemas import (
    AgentState,
    ExecutionResult,
    ExecutionResultStatus,
    OrchestratorConfig,
    WorkflowEvent,
    WorkflowEventType,
    WorkflowStep,
)
from agents.planner.mock_scenarios import register_planner_scenarios
from agents.planner.planner import LLMTestPlanner
from agents.planner.schemas import (
    Assertion,
)
from agents.planner.schemas import (
    TestCase as Member1TestCase,
)
from agents.planner.schemas import (
    TestStep as Member1TestStep,
)
from agents.schemas.enums import (
    AssertionType,
    ExecutionStatus,
    HealingStatus,
    TestAction,
    ValidationStatus,
)
from agents.schemas.member3_contract import (
    DashboardWorkflowSummary,
    build_dashboard_summary,
)
from backend.artifacts import load_baseline, persist_run_artifacts, record_visual
from backend.config import settings
from backend.database.store import Store, StoreUnavailableError
from backend.models import APPLICATIONS, TEST_CASES, TEST_EXECUTIONS
from backend.models.test_execution import TestExecutionStatus
from backend.orchestration.converters import (
    collect_learned_targets,
    element_record_from_fingerprint,
    engine_result_to_execution_result,
    learned_targets_by_locator,
    test_case_to_engine_plan,
)
from engine.runner import run_test
from engine.schemas import (
    EngineConfig,
    RunOptions,
    StepStatus,
    TestStatus,
)
from engine.schemas import (
    Step as EngineStep,
)
from engine.schemas import (
    TestPlan as EngineTestPlan,
)
from engine.schemas import (
    TestResult as EngineTestResult,
)

logger = logging.getLogger("testsphere.orchestration")


def apply_healed_selector(
    plan: EngineTestPlan,
    broken_selector: str,
    failed_step: int,
    healed_selector: str,
) -> EngineTestPlan:
    """Return a copy of *plan* with the healed selector on the broken step(s) only.

    Steps whose primary locator equals *broken_selector* are updated; if none
    match, only the step that failed (1-based *failed_step*) is.  Every other
    step keeps its own locator.
    """
    matches = [
        bool(broken_selector) and st.target is not None and st.target.primary_locator == broken_selector
        for st in plan.steps
    ]
    if not any(matches):
        matches = [idx == failed_step - 1 and st.target is not None for idx, st in enumerate(plan.steps)]

    steps: list[EngineStep] = []
    for step, hit in zip(plan.steps, matches, strict=True):
        step_copy = step.model_copy(deep=True)
        if hit:
            step_copy.target.primary_locator = healed_selector
        steps.append(step_copy)
    return plan.model_copy(update={"steps": steps})


_STEP_VERBS = {
    "goto": "Open", "click": "Click", "fill": "Type into", "press": "Press", "select": "Choose in",
    "assert_text": "Check the text of", "assert_visible": "Check that it shows", "wait_for": "Wait for",
    "assert_hidden": "Check that it's gone:", "assert_url": "Check the page address",
}


def describe_step(step: EngineStep) -> str:
    """A readable line for the run view, e.g. 'Click "Log in" button' or 'Open https://shop.example/'."""
    action = getattr(step.action, "value", str(step.action))
    verb = _STEP_VERBS.get(action, action.replace("_", " ").capitalize())
    if action == "goto":
        return f"{verb} {step.value or 'the page'}"
    if action == "assert_url":
        return f'{verb} contains "{(step.expected or "")[:80]}"'
    if step.target and step.target.description.startswith("Check: "):
        return step.target.description  # a check written for people ("Check: the cart shows a count")
    target = ""
    if step.target:
        # Generated assertions carry a placeholder description; the locator says more
        generic = not step.target.description or step.target.description.lower().startswith("assertion target")
        target = step.target.primary_locator if generic else step.target.description
    line = f"{verb} {target}".strip()
    if action == "fill" and step.value:
        line += f" ({len(step.value)} characters)"  # never echo what was typed (it may be a password)
    elif action == "assert_text" and step.expected:
        line += f' contains "{step.expected[:80]}"'
    elif action == "press" and step.value:
        line = f"Press {step.value[:20]} in {target}".strip()
    elif action == "select" and step.value:
        line += f" {step.value[:40]}"
    return line


def create_memory_store() -> MemoryStore:
    """Healing memory backend from ``AGENT_MEMORY_BACKEND`` (database by default)."""
    from backend.config import settings

    if settings.AGENT_MEMORY_BACKEND == "memory":
        return InMemoryStore()
    from backend.database.session import get_store

    try:
        return PersistentMemoryStore(get_store(), max_records=settings.AGENT_MEMORY_MAX_RECORDS)
    except StoreUnavailableError as exc:
        # Never let a database outage stop the API from starting; healing
        # memory just isn't persisted until the backend restarts with a DB.
        logger.error("Healing memory falling back to in-process storage (database unavailable): %s", exc)
        return InMemoryStore()


def create_platform_llm_client(config: LLMConfig | None = None) -> LLMClientSession:
    """The LLM client the agents use: ``LLM_PROVIDER``'s, or for the default
    ``mock`` provider one pre-loaded with the offline planner scenarios."""
    config = config or LLMConfig.from_env()
    if config.provider == "mock":
        provider = MockLLMProvider(LLMConfig(provider="mock", model="mock-model", max_retries=0))
        register_planner_scenarios(provider)
        return LLMClientSession(provider=provider)
    return create_llm_client(config)


def create_default_orchestrator(memory_store: MemoryStore | None = None) -> AgentOrchestrator:
    """Create a fully configured AgentOrchestrator.

    Uses the LLM provider from the environment (``LLM_PROVIDER``); the default
    ``mock`` provider is pre-loaded with the offline planner scenarios.
    Healing memory persists across restarts unless ``AGENT_MEMORY_BACKEND=memory``.
    """
    memory_store = memory_store or create_memory_store()
    config = LLMConfig.from_env()
    llm_session = create_platform_llm_client(config)
    logger.info("Platform orchestrator using LLM provider: %s", llm_session.provider_name)

    # The analyzer consults the model only for failures its rules cannot
    # classify; the offline mock has no diagnosis scenarios to answer with.
    failure_analyzer = FailureAnalyzerAgent(
        memory_store=memory_store,
        llm_client=llm_session if config.provider != "mock" else None,
    )
    healing_engine = HealingDecisionEngine(
        memory_store=memory_store,
        llm_client=llm_session,
    )
    feedback_processor = HealingResultFeedbackProcessor(memory_store=memory_store)
    test_planner = LLMTestPlanner(llm_client=llm_session)
    recovery_policy = RecoveryPolicy(
        config=RecoveryPolicyConfig(
            max_healing_attempts=2,
            max_retries=1,
            min_healing_confidence=0.5,
        ),
    )

    return AgentOrchestrator(
        memory_store=memory_store,
        failure_analyzer=failure_analyzer,
        healing_engine=healing_engine,
        feedback_processor=feedback_processor,
        test_planner=test_planner,
        recovery_policy=recovery_policy,
        config=OrchestratorConfig(
            max_healing_attempts=2,
            max_retries=1,
            minimum_confidence_for_healing=0.5,
        ),
    )


_platform_orchestrator: PlatformWorkflowOrchestrator | None = None


def get_platform_orchestrator() -> PlatformWorkflowOrchestrator:
    """The process-wide orchestrator shared by single runs and the automated pipeline
    (one healing memory, one set of workflow states)."""
    global _platform_orchestrator
    if _platform_orchestrator is None:
        _platform_orchestrator = PlatformWorkflowOrchestrator()
    return _platform_orchestrator


def forget_healing_memory() -> None:
    """Drop erased records (``DELETE /me``) from the running orchestrator's
    healing memory, which otherwise keeps them until the next restart."""
    memory = _platform_orchestrator.ai_orchestrator.memory if _platform_orchestrator else None
    if isinstance(memory, PersistentMemoryStore):
        memory.reload()


_ASSERTION_NAMES = frozenset(t.value for t in AssertionType)


def _assertion_type(name: str) -> AssertionType:
    """The planner assertion for a stored check: a planner type name
    (``value_equals``) or a pipeline action (``ASSERT_CONTAINS_TEXT``)."""
    if name in _ASSERTION_NAMES:
        return AssertionType(name)
    if "url" in name:
        return AssertionType.URL_EQUALS if "equal" in name or "exact" in name else AssertionType.URL_CONTAINS
    if "value" in name:
        return AssertionType.VALUE_EQUALS
    if "text" in name:
        return AssertionType.ELEMENT_HAS_TEXT if "has_text" in name or "exact" in name else AssertionType.ELEMENT_CONTAINS_TEXT
    if "not" in name or "hidden" in name:
        return AssertionType.ELEMENT_NOT_VISIBLE
    return AssertionType.ELEMENT_VISIBLE


# Hard cap on re-runs of a transient failure (the recovery policy sets the real limit)
MAX_RETRY_RUNS = 3


def _first_error(result: EngineTestResult, default: str) -> str:
    failed_step = next((st for st in getattr(result, "steps", []) if getattr(st, "status", None) in (StepStatus.FAILED, "failed")), None)
    return getattr(result, "error_message", None) or (getattr(failed_step, "error", None) if failed_step else None) or default


class PlatformWorkflowOrchestrator:
    """Coordinates test execution runs with AI failure diagnosis and self-healing."""

    def __init__(self, orchestrator: AgentOrchestrator | None = None) -> None:
        self.ai_orchestrator = orchestrator or create_default_orchestrator()

    async def execute_test_run(
        self,
        db: Store,
        execution_id: int,
        options: RunOptions | None = None,
    ) -> dict[str, Any]:
        """Execute a single test execution run end-to-end.

        1. Fetches TestCase and Application from DB.
        2. Sets TestExecution status to RUNNING.
        3. Converts TestCase to Member 2 TestPlan.
        4. Runs browser test via Member 2 Playwright runner.
        5. On failure, invokes Member 1 FailureAnalyzer and HealingDecisionEngine.
        6. On healing recommendation, validates replacement selector in browser.
        7. Records feedback into memory and updates DB execution status.
        8. Returns dashboard summary and event stream.
        """
        execution = db.get(TEST_EXECUTIONS, execution_id)
        if not execution:
            raise ValueError(f"TestExecution #{execution_id} not found")

        test_case = db.get(TEST_CASES, execution.test_case_id)
        if not test_case:
            raise ValueError(f"TestCase #{execution.test_case_id} not found")

        app = db.get(APPLICATIONS, test_case.application_id)
        if not app:
            raise ValueError(f"Application #{test_case.application_id} not found")

        # Mark as RUNNING
        start_time = datetime.now(UTC)
        execution = db.update(TEST_EXECUTIONS, execution.id, status=TestExecutionStatus.RUNNING.value, started_at=start_time)

        try:
            # Healing memory written during this run belongs to the run's owner
            with memory_owner(execution.get("owner_uid")):
                return await self._execute(db, execution, test_case, app, options)
        except Exception as exc:
            # Never leave the run RUNNING: record why it ended, then report the error
            logger.exception("Execution #%s crashed", execution.id)
            try:
                db.update(TEST_EXECUTIONS, execution.id, status=TestExecutionStatus.FAILED.value,
                          completed_at=datetime.now(UTC),
                          error_message=f"Run failed unexpectedly ({type(exc).__name__}: {str(exc)[:300]})")
            except Exception:  # noqa: BLE001 - the original error is what the caller needs
                logger.exception("Could not record the crash of execution #%s", execution.id)
            raise

    async def _execute(self, db: Store, execution: Any, test_case: Any, app: Any,
                       options: RunOptions | None) -> dict[str, Any]:
        """Steps 3-8 of ``execute_test_run`` for an execution marked RUNNING."""
        # Build Member 1 TestCase model from DB record or structured description
        m1_steps: list[Member1TestStep] = []
        m1_assertions: list[Assertion] = []
        analysis_data: dict[str, Any] | None = None
        if test_case.description:
            try:
                desc_obj = json.loads(test_case.description)
            except ValueError:
                desc_obj = None  # a plain-text description: no stored steps
        else:
            desc_obj = None
        if desc_obj is not None:
            try:
                if isinstance(desc_obj, dict):
                    analysis_data = desc_obj.get("analysis")
                    raw_steps = desc_obj.get("steps", [])
                else:
                    raw_steps = desc_obj
                if isinstance(raw_steps, list):
                    for idx, s in enumerate(raw_steps, start=1):
                        act_raw = str(s.get("action", "navigate")).strip().lower()
                        if "assert" in act_raw or act_raw in _ASSERTION_NAMES:
                            as_type = _assertion_type(act_raw)
                            # A check belongs where it was written: right after the step
                            # before it (an outcome check mid-scenario), not at the end
                            (m1_steps[-1].assertions if m1_steps else m1_assertions).append(
                                Assertion(
                                    type=as_type,
                                    target=s.get("target") or s.get("target_selector") or "",
                                    expected=s.get("expected") or s.get("value") or "",
                                    description=s.get("description", f"Assert {idx}"),
                                )
                            )
                        else:
                            if act_raw in ("goto", "open"):
                                act_enum = TestAction.NAVIGATE
                            else:
                                # An unknown action fails the run as unreadable: guessing
                                # (e.g. a click for "check") would test something else
                                act_enum = TestAction(act_raw)

                            val = s.get("value")
                            if act_enum == TestAction.NAVIGATE and not val:
                                val = app.base_url

                            m1_steps.append(
                                Member1TestStep(
                                    step_number=s.get("step_number", len(m1_steps) + 1),
                                    action=act_enum,
                                    target=s.get("target") or s.get("target_selector"),
                                    value=val,
                                    description=s.get("description", f"Step {idx}"),
                                )
                            )
            except (TypeError, ValueError, AttributeError) as exc:
                # Never fall back to a trivial "open the page" run here: it
                # would pass a test whose stored steps never ran.
                logger.warning("Test case #%s: stored steps unreadable: %s", test_case.id, exc)
                return self._fail_unreadable_steps(db, execution, test_case, exc)

        if not m1_steps:
            m1_steps = [
                Member1TestStep(
                    step_number=1,
                    action=TestAction.NAVIGATE,
                    value=app.base_url,
                    description=f"Navigate to {app.base_url}",
                )
            ]

        m1_test_case = Member1TestCase(
            test_id=test_case.external_id or f"tc-{test_case.id}",
            name=test_case.name,
            page_url=app.base_url,
            steps=m1_steps,
            assertions=m1_assertions,
        )

        # Convert to Member 2 TestPlan, with the fallbacks and fingerprints
        # earlier runs learned (the engine heals a broken locator from them)
        learned = learned_targets_by_locator(test_case.get("healing_targets"))
        engine_plan = test_case_to_engine_plan(m1_test_case, app.base_url, learned)

        workflow_id = f"wf-exec-{execution.id}"

        # Initialize AgentState with initial events in AI Orchestrator
        state = self.ai_orchestrator.get_state(workflow_id)
        if not state:
            state = AgentState(
                workflow_id=workflow_id,
                current_step=WorkflowStep.EXECUTION_PENDING,
                max_healing_attempts=self.ai_orchestrator._config.max_healing_attempts,
            )
            state = self.ai_orchestrator._add_event(
                state,
                WorkflowEventType.WORKFLOW_STARTED,
                message=f"Autonomous QA workflow initiated for application '{app.name}'",
                metadata={"app_name": app.name, "app_url": app.base_url, "execution_id": execution.id},
            )
            state = self.ai_orchestrator._add_event(
                state,
                WorkflowEventType.STATE_TRANSITION,
                message=f"Executing test plan with {len(engine_plan.steps)} step(s) on browser engine",
                metadata={"test_case_id": m1_test_case.test_id, "step_count": len(engine_plan.steps)},
            )
            self.ai_orchestrator._workflows[workflow_id] = state

        # Run test via Member 2 (traced, so the dashboard can offer the trace)
        run_opts = options or RunOptions(headless=True)
        if run_opts.tracing_enabled is None and settings.ARTIFACT_TRACES:
            run_opts = run_opts.model_copy(update={"tracing_enabled": True})
        owner = execution.get("owner_uid") or "local-dev"
        baseline = load_baseline(owner, test_case.id) if settings.VISUAL_REGRESSION else None
        engine_result: EngineTestResult = await run_test(engine_plan, options=run_opts,
                                                         visual=settings.VISUAL_REGRESSION, visual_baseline=baseline)
        runs = [engine_result]  # every browser run, so their working files are removed
        shown_result, shown_plan = engine_result, engine_plan  # the run whose steps the dashboard shows

        exec_result = self._submit_ready(engine_result, workflow_id, m1_test_case.test_id, engine_plan)
        state = await self.ai_orchestrator.submit_execution_result(state, exec_result)

        # A transient failure the recovery policy chose to retry: run it again
        # (bounded by the policy's retry limit), then diagnose and heal as usual
        retries = 0
        while (
            exec_result.status != ExecutionResultStatus.SUCCESS
            and state.current_step == WorkflowStep.EXECUTION_PENDING
            and state.recovery_decision is not None
            and state.recovery_decision.decision == RecoveryAction.RETRY
            and retries < MAX_RETRY_RUNS
        ):
            retries += 1
            logger.info("Execution #%s: retrying after a transient failure (retry %d)", execution.id, retries)
            engine_result = await run_test(engine_plan, options=run_opts,
                                           visual=settings.VISUAL_REGRESSION, visual_baseline=baseline)
            runs.append(engine_result)
            shown_result = engine_result
            exec_result = self._submit_ready(engine_result, workflow_id, m1_test_case.test_id, engine_plan)
            state = await self.ai_orchestrator.submit_execution_result(state, exec_result)

        final_status = TestExecutionStatus.PASSED.value
        error_msg = None
        duration_ms = sum(run.duration_ms for run in runs)

        if exec_result.status == ExecutionResultStatus.SUCCESS:
            final_status = TestExecutionStatus.PASSED.value
            if engine_result.status == TestStatus.HEALED:
                # The engine healed one or more locators mid-run; keep that visible
                final_status = TestExecutionStatus.HEALED.value
                error_msg = "; ".join(
                    f"Self-healed {st.healing.original_locator} -> {st.healing.selected_locator} "
                    f"({st.healing.strategy_used}, confidence {st.healing.confidence:.2f})"
                    for st in engine_result.steps
                    if st.status == StepStatus.HEALED and st.healing
                )
        else:
            # Failure detected -> Member 1 analysed it; validate any heal it proposes
            healed = None
            try:
                state, healed = await self._validate_ai_heal(state, engine_plan, exec_result, run_opts, runs)
            except Exception:  # noqa: BLE001 - a healing error leaves the original failure as the result
                logger.exception("Execution #%s: AI self-healing failed", execution.id)
            if healed is not None:
                shown_plan, shown_result, candidate = healed
                final_status = TestExecutionStatus.HEALED.value
                error_msg = (f"Self-healed {exec_result.failure_context.target_selector} -> {candidate.selector} "
                             f"(AI healer, confidence {candidate.confidence:.2f})")
            else:
                final_status = TestExecutionStatus.FAILED.value
                error_msg = _first_error(engine_result, "Test execution failed")
                tried = len(runs) - 1 - retries  # validation runs
                if tried:
                    error_msg += f" (self-healing tried {tried} replacement selector(s); none passed)"

        # Learn from the run: healing memory and the targets' fallbacks/fingerprints
        try:
            self._learn_from_run(db, test_case, execution.id, m1_test_case, engine_plan, shown_plan,
                                 shown_result, final_status, error_msg, duration_ms)
        except Exception:  # noqa: BLE001 - learning is best-effort; the run's result stands
            logger.exception("Execution #%s: could not record what the run learned", execution.id)

        # The browser could not start (e.g. Chromium missing on the host): no
        # step ran, so this is a failure — never report it as passed, even if
        # the plain-HTTP page inspection worked.
        if error_msg and "Browser execution error" in error_msg:
            final_status = TestExecutionStatus.FAILED.value
            error_msg = (
                "Not executed: the browser could not start on this server, so no test steps ran. "
                "Install it with `python -m playwright install --with-deps chromium`. "
                f"Details: {error_msg}"
            )

        # Step results and artifacts (screenshots, DOM, trace) for the run view
        descriptions = {st.step_id: describe_step(st) for st in engine_plan.steps}
        evidence = persist_run_artifacts(shown_result, owner, execution.id, descriptions)
        visual = record_visual(engine_result.visual, owner, execution.id, test_case.id, baseline,
                               passed=final_status == TestExecutionStatus.PASSED.value)
        self._discard_local_artifacts(*runs)

        # Update database execution record
        end_time = datetime.now(UTC)
        execution = db.update(
            TEST_EXECUTIONS, execution.id,
            status=final_status, completed_at=end_time, duration_ms=duration_ms, error_message=error_msg,
            steps=evidence["steps"], trace=evidence["trace"], visual=visual,
        )

        # Retrieve AI state & dashboard summary
        state = self.ai_orchestrator.get_state(workflow_id)
        dashboard_summary = (
            build_dashboard_summary(state)
            if state
            else DashboardWorkflowSummary(
                workflow_id=workflow_id,
                current_step=WorkflowStep.COMPLETED,
                is_terminal=True,
                passed_tests=1 if final_status in (TestExecutionStatus.PASSED.value,
                                                   TestExecutionStatus.HEALED.value) else 0,
                failed_tests=1 if final_status == TestExecutionStatus.FAILED.value else 0,
            )
        )
        # The workflow state only knows heals the AI healer validated; a run the
        # engine healed on its own is just as healed
        if final_status == TestExecutionStatus.HEALED.value:
            dashboard_summary.healed_tests = max(dashboard_summary.healed_tests, 1)

        return {
            "execution_id": execution.id,
            "status": final_status,
            "duration_ms": duration_ms,
            "error_message": error_msg,
            "dashboard_summary": dashboard_summary.model_dump(),
            "events": [e.model_dump() for e in (state.events if state else [])],
            "engine_steps": [st.model_dump(mode="json") for st in shown_result.steps],
            "visual": visual,
            "analysis": analysis_data,
        }

    def _submit_ready(self, engine_result: EngineTestResult, workflow_id: str, test_id: str,
                      engine_plan: EngineTestPlan) -> ExecutionResult:
        """Convert an engine result for the AI orchestrator.

        On a failure, make sure healing memory knows the failed target's last
        known element (from its stored fingerprint), so the healer has the
        element to compare the current page against even on a cold start.
        """
        exec_result = engine_result_to_execution_result(
            engine_result=engine_result,
            workflow_id=workflow_id,
            test_case_id=test_id,
            engine_plan=engine_plan,
        )
        fc = exec_result.failure_context
        if fc is not None and fc.target_selector and 0 < fc.failed_step <= len(engine_plan.steps):
            target = engine_plan.steps[fc.failed_step - 1].target
            memory = self.ai_orchestrator.memory
            if target is not None and target.fingerprint is not None and memory.get_element_by_selector(fc.target_selector) is None:
                memory.store_element(element_record_from_fingerprint(
                    target.fingerprint, fc.target_selector, element_id=f"{test_id}:{fc.target_selector}",
                    page_url=fc.current_page_url,
                ))
        return exec_result

    async def _validate_ai_heal(
        self,
        state: AgentState,
        engine_plan: EngineTestPlan,
        exec_result: ExecutionResult,
        run_opts: RunOptions,
        runs: list[EngineTestResult],
    ) -> tuple[AgentState, tuple[EngineTestPlan, EngineTestResult, Any] | None]:
        """Validate the AI healer's replacement selector(s) by re-running the test.

        A heal counts only when the whole test passes with it; every outcome
        is fed back to healing memory.  When a candidate fails, the recovery
        policy may offer the next one, up to its attempt limit.  Returns the
        updated state and, for a validated heal, (plan, result, candidate).
        """
        fc = exec_result.failure_context
        for _ in range(self.ai_orchestrator._config.max_healing_attempts):
            recommendation = state.healing_recommendation
            candidate = recommendation.selected_candidate if recommendation else None
            if (
                state.current_step != WorkflowStep.HEALING_PENDING_VALIDATION
                or state.recovery_decision is None
                or state.recovery_decision.decision != RecoveryAction.TRY_HEALING
                or candidate is None
            ):
                break
            original = recommendation.original_selector or (fc.target_selector if fc else "")
            if not original:
                break
            logger.info("Self-healing proposed replacement selector: %s. Validating with engine...", candidate.selector)
            healed_plan = apply_healed_selector(
                engine_plan,
                broken_selector=original,
                failed_step=fc.failed_step if fc else 0,
                healed_selector=candidate.selector,
            )
            validation_result = await run_test(healed_plan, options=run_opts)
            runs.append(validation_result)
            passed = validation_result.status in (TestStatus.PASSED, TestStatus.HEALED)

            feedback = HealingResultFeedback(
                test_case_id=recommendation.test_id,
                execution_id=recommendation.execution_id,
                original_selector=original,
                attempted_selector=candidate.selector,
                healing_status=HealingStatus.VALIDATED_SUCCESS if passed else HealingStatus.VALIDATED_FAILURE,
                validation_status=ValidationStatus.SUCCESS if passed else ValidationStatus.FAILURE,
                failure_category=recommendation.failure_type,
                confidence=candidate.confidence,
                execution_attempt=state.healing_attempt_count or 1,
                error_reason=None if passed else _first_error(validation_result, "Healing validation failed")[:500],
                metadata={"source": "ai_healer", "candidate_source": candidate.source.value},
            )
            state = await self.ai_orchestrator.submit_healing_result(state, feedback)
            if passed:
                return state, (healed_plan, validation_result, candidate)
        return state, None

    def _learn_from_run(
        self,
        db: Store,
        test_case: Any,
        execution_id: int,
        m1_test_case: Member1TestCase,
        engine_plan: EngineTestPlan,
        shown_plan: EngineTestPlan,
        shown_result: EngineTestResult,
        final_status: str,
        error_msg: str | None,
        duration_ms: int,
    ) -> None:
        """Record the run in healing memory and keep what the engine learned.

        - an execution record (pass/fail history for diagnosis);
        - the element each passing step acted on (what a later heal compares with);
        - each heal the engine made in a run that then passed (a validated heal);
        - the targets' fingerprints and fallback locators, on the test case,
          so the next run of it can heal a broken locator in the engine.
        """
        memory = self.ai_orchestrator.memory
        test_id = m1_test_case.test_id
        passed = final_status in (TestExecutionStatus.PASSED.value, TestExecutionStatus.HEALED.value)
        failed_step = next((st for st in shown_result.steps if st.status == StepStatus.FAILED), None)
        memory.store_execution(TestExecutionRecord(
            execution_id=f"exec-{execution_id}",
            test_id=test_id,
            test_name=m1_test_case.name or test_id,
            status=ExecutionStatus.PASSED if passed else ExecutionStatus.FAILED,
            duration_ms=duration_ms,
            failure_info=None if passed else FailureInfo(
                error_message=(error_msg or "Test execution failed")[:1000],
                failed_step=next((i for i, st in enumerate(shown_result.steps, start=1) if st is failed_step), None),
                page_url=failed_step.page_url if failed_step else None,
            ),
            metadata={"execution_id": execution_id, "status": final_status},
        ))

        previous_url = shown_plan.base_url
        for original, step, step_res in zip(engine_plan.steps, shown_plan.steps, shown_result.steps, strict=False):
            if (step_res.status == StepStatus.PASSED and step.target is not None and step.target.fingerprint is not None
                    and original.target is not None and step.target.primary_locator == original.target.primary_locator):
                self._remember_element(memory, element_record_from_fingerprint(
                    step.target.fingerprint, step.target.primary_locator,
                    element_id=f"{test_id}:{step.target.primary_locator}",
                    page_url=previous_url,  # the page the step acted on
                    execution_id=f"exec-{execution_id}",
                ))
            if passed and step_res.status == StepStatus.HEALED and step_res.healing and step_res.healing.selected_locator:
                self.ai_orchestrator.record_healing_feedback(HealingResultFeedback(
                    test_case_id=test_id,
                    execution_id=f"exec-{execution_id}",
                    original_selector=step_res.healing.original_locator,
                    attempted_selector=step_res.healing.selected_locator,
                    healing_status=HealingStatus.VALIDATED_SUCCESS,
                    validation_status=ValidationStatus.SUCCESS,
                    confidence=step_res.healing.confidence,
                    metadata={"source": "engine", "strategy": step_res.healing.strategy_used},
                ))
            previous_url = step_res.page_url or previous_url

        targets = collect_learned_targets(engine_plan, shown_plan, shown_result)
        if targets != (test_case.get("healing_targets") or []):
            db.update(TEST_CASES, test_case.id, healing_targets=targets)

    @staticmethod
    def _remember_element(memory: MemoryStore, record: Any) -> None:
        """Store an element snapshot unless memory already holds the same one."""
        history = memory.get_element_history(record.element_id)
        latest = history[0] if history else None
        same = latest is not None and all(
            getattr(latest, field) == getattr(record, field) for field in ("selector", "text", "role", "page_url", "attributes")
        )
        if not same:
            memory.store_element(record)

    @staticmethod
    def _discard_local_artifacts(*results: Any) -> None:
        """Remove the engine's working copies once stored (they would fill the disk)."""
        root = Path(EngineConfig().artifacts_dir).resolve()
        for res in results:
            run_dir = Path(getattr(res, "artifacts_dir", "") or "").resolve()
            if run_dir != root and root in run_dir.parents:
                shutil.rmtree(run_dir, ignore_errors=True)

    def _fail_unreadable_steps(self, db: Store, execution: Any, test_case: Any, exc: Exception) -> dict[str, Any]:
        """Record a run that could not start because its stored steps are malformed."""
        error_msg = (f"Not executed: the stored steps of test case #{test_case.id} could not be read "
                     f"({type(exc).__name__}: {str(exc).splitlines()[0][:200] if str(exc) else ''}). "
                     "Edit or regenerate the test case.")
        db.update(TEST_EXECUTIONS, execution.id, status=TestExecutionStatus.FAILED.value,
                  completed_at=datetime.now(UTC), duration_ms=0, error_message=error_msg)
        summary = DashboardWorkflowSummary(workflow_id=f"wf-exec-{execution.id}", current_step=WorkflowStep.ABORTED,
                                           is_terminal=True, failed_tests=1)
        return {
            "execution_id": execution.id,
            "status": TestExecutionStatus.FAILED.value,
            "duration_ms": 0,
            "error_message": error_msg,
            "dashboard_summary": summary.model_dump(),
            "events": [],
            "engine_steps": [],
            "analysis": None,
        }

    def execution_events(self, execution_id: int) -> list[WorkflowEvent]:
        """Recorded events of the workflow run for *execution_id* (empty when
        none are held, e.g. after a restart)."""
        state = (self.ai_orchestrator.get_state(f"wf-exec-{execution_id}")
                 or self.ai_orchestrator.get_state(str(execution_id)))
        return list(state.events) if state else []
