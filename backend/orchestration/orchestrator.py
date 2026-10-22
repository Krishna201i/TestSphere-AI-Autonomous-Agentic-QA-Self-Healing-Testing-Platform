from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
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
from agents.memory.persistent_store import PersistentMemoryStore
from agents.orchestration.agent_orchestrator import AgentOrchestrator
from agents.orchestration.recovery_policy import (
    RecoveryAction,
    RecoveryPolicy,
    RecoveryPolicyConfig,
)
from agents.orchestration.workflow_schemas import (
    AgentState,
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
    TestAction,
    ValidationStatus,
)
from agents.schemas.member3_contract import (
    DashboardWorkflowSummary,
    build_dashboard_summary,
)
from backend.database.store import Store, StoreUnavailableError
from backend.models import APPLICATIONS, TEST_CASES, TEST_EXECUTIONS
from backend.models.test_execution import TestExecutionStatus
from backend.orchestration.converters import (
    engine_result_to_execution_result,
    test_case_to_engine_plan,
)
from engine.runner import run_test
from engine.schemas import (
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


def create_memory_store() -> MemoryStore:
    """Healing memory backend from ``AGENT_MEMORY_BACKEND`` (database by default)."""
    from backend.config import settings

    if settings.AGENT_MEMORY_BACKEND == "memory":
        return InMemoryStore()
    from backend.database.session import get_store

    try:
        return PersistentMemoryStore(get_store())
    except StoreUnavailableError as exc:
        # Never let a database outage stop the API from starting; healing
        # memory just isn't persisted until the backend restarts with a DB.
        logger.error("Healing memory falling back to in-process storage (database unavailable): %s", exc)
        return InMemoryStore()


def create_default_orchestrator(memory_store: MemoryStore | None = None) -> AgentOrchestrator:
    """Create a fully configured AgentOrchestrator.

    Uses the LLM provider from the environment (``LLM_PROVIDER``); the default
    ``mock`` provider is pre-loaded with the offline planner scenarios.
    Healing memory persists across restarts unless ``AGENT_MEMORY_BACKEND=memory``.
    """
    memory_store = memory_store or create_memory_store()
    config = LLMConfig.from_env()
    if config.provider == "mock":
        provider = MockLLMProvider(LLMConfig(provider="mock", model="mock-model", max_retries=0))
        register_planner_scenarios(provider)
        llm_session = LLMClientSession(provider=provider)
    else:
        llm_session = create_llm_client(config)
    logger.info("Platform orchestrator using LLM provider: %s", llm_session.provider_name)

    failure_analyzer = FailureAnalyzerAgent(memory_store=memory_store)
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
                        if "assert" in act_raw or act_raw in ("element_visible", "element_not_visible", "element_contains_text"):
                            as_type = AssertionType.ELEMENT_VISIBLE
                            if "text" in act_raw:
                                as_type = AssertionType.ELEMENT_CONTAINS_TEXT
                            elif "not" in act_raw:
                                as_type = AssertionType.ELEMENT_NOT_VISIBLE
                            m1_assertions.append(
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
                                try:
                                    act_enum = TestAction(act_raw)
                                except ValueError:
                                    act_enum = TestAction.CLICK if (s.get("target") or s.get("target_selector")) else TestAction.NAVIGATE

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

        # Convert to Member 2 TestPlan
        engine_plan = test_case_to_engine_plan(m1_test_case, app.base_url)

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

        # Run test via Member 2
        run_opts = options or RunOptions(headless=True)
        engine_result: EngineTestResult = await run_test(engine_plan, options=run_opts)

        exec_result = engine_result_to_execution_result(
            engine_result=engine_result,
            workflow_id=workflow_id,
            test_case_id=m1_test_case.test_id,
            engine_plan=engine_plan,
        )

        final_status = TestExecutionStatus.PASSED.value
        error_msg = None
        duration_ms = engine_result.duration_ms

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
            state = await self.ai_orchestrator.submit_execution_result(state, exec_result)
        else:
            # Failure detected -> delegate to Member 1 AI intelligence
            logger.info("Test execution failed. Submitting result to AI orchestrator for analysis.")
            state = await self.ai_orchestrator.submit_execution_result(state, exec_result)
            recommendation = state.healing_recommendation

            # Check if self-healing is recommended
            if (
                recommendation
                and recommendation.target_selector
                and recommendation.action == RecoveryAction.TRY_HEALING
            ):
                logger.info(
                    "Self-healing proposed replacement selector: %s. Validating with engine...",
                    recommendation.target_selector,
                )
                fc = exec_result.failure_context
                healed_plan = apply_healed_selector(
                    engine_plan,
                    broken_selector=recommendation.original_selector or (fc.target_selector if fc else ""),
                    failed_step=fc.failed_step if fc else 0,
                    healed_selector=recommendation.target_selector,
                )
                validation_result = await run_test(healed_plan, options=run_opts)

                validation_success = validation_result.status in (
                    TestStatus.PASSED,
                    TestStatus.HEALED,
                )

                feedback = HealingResultFeedback(
                    healing_id=recommendation.healing_id,
                    test_id=m1_test_case.test_id,
                    original_selector=recommendation.original_selector or "",
                    healed_selector=recommendation.target_selector,
                    validation_status=(
                        ValidationStatus.SUCCESS
                        if validation_success
                        else ValidationStatus.FAILED
                    ),
                    execution_time_ms=validation_result.duration_ms,
                )
                state = await self.ai_orchestrator.submit_healing_result(state, feedback)

                if validation_success:
                    final_status = TestExecutionStatus.PASSED.value
                    error_msg = f"Self-healed selector: {recommendation.target_selector}"
                else:
                    final_status = TestExecutionStatus.FAILED.value
                    failed_step = next((st for st in getattr(validation_result, "steps", []) if getattr(st, "status", None) in (StepStatus.FAILED, "failed")), None)
                    error_msg = (
                        getattr(validation_result, "error_message", None)
                        or (getattr(failed_step, "error", None) if failed_step else None)
                        or "Healing validation failed"
                    )
            else:
                final_status = TestExecutionStatus.FAILED.value
                failed_step = next((st for st in getattr(engine_result, "steps", []) if getattr(st, "status", None) in (StepStatus.FAILED, "failed")), None)
                error_msg = (
                    getattr(engine_result, "error_message", None)
                    or (getattr(failed_step, "error", None) if failed_step else None)
                    or "Test execution failed"
                )

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

        # Update database execution record
        end_time = datetime.now(UTC)
        execution = db.update(
            TEST_EXECUTIONS, execution.id,
            status=final_status, completed_at=end_time, duration_ms=duration_ms, error_message=error_msg,
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
                passed_tests=1 if final_status == TestExecutionStatus.PASSED.value else 0,
                failed_tests=1 if final_status == TestExecutionStatus.FAILED.value else 0,
            )
        )

        return {
            "execution_id": execution.id,
            "status": final_status,
            "duration_ms": duration_ms,
            "error_message": error_msg,
            "dashboard_summary": dashboard_summary.model_dump(),
            "events": [e.model_dump() for e in (state.events if state else [])],
            "engine_steps": [st.model_dump(mode="json") for st in engine_result.steps],
            "analysis": analysis_data,
        }

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
