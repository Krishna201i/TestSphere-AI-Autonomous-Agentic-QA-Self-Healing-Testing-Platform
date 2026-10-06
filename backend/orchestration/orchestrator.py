from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, List, Optional
from sqlalchemy.orm import Session

from agents.analyzer.analyzer import FailureAnalyzerAgent
from agents.healer.healing_decision import HealingDecisionEngine
from agents.healer.healing_feedback import HealingResultFeedbackProcessor
from agents.llm import LLMClientSession, MockLLMProvider
from agents.llm.config import LLMConfig
from agents.memory.in_memory_store import InMemoryStore
from agents.orchestration.agent_orchestrator import AgentOrchestrator
from agents.orchestration.recovery_policy import (
    RecoveryPolicy,
    RecoveryPolicyConfig,
)
from agents.orchestration.workflow_schemas import (
    AgentState,
    ExecutionResultStatus,
    OrchestratorConfig,
    WorkflowEvent,
    WorkflowStep,
)
from agents.planner.mock_scenarios import register_planner_scenarios
from agents.planner.planner import LLMTestPlanner
from agents.planner.schemas import (
    ApplicationContext,
    TestCase as Member1TestCase,
    TestStep as Member1TestStep,
)
from agents.schemas.enums import (
    TestAction,
    ValidationStatus,
)
from agents.schemas.member3_contract import (
    DashboardWorkflowSummary,
    build_dashboard_summary,
    format_sse_event,
)

from backend.models.application import Application
from backend.models.test_case import TestCase
from backend.models.test_execution import TestExecution, TestExecutionStatus
from backend.orchestration.converters import (
    engine_result_to_execution_result,
    test_case_to_engine_plan,
)
from engine.runner import run_test
from engine.schemas import (
    RunOptions,
    Step as EngineStep,
    TestPlan as EngineTestPlan,
    TestResult as EngineTestResult,
    TestStatus,
)

logger = logging.getLogger("testsphere.orchestration")


def create_default_orchestrator() -> AgentOrchestrator:
    """Create a fully configured AgentOrchestrator with offline mock intelligence."""
    memory_store = InMemoryStore()
    config = LLMConfig(provider="mock", model="mock-model", max_retries=0)
    provider = MockLLMProvider(config)
    register_planner_scenarios(provider)
    llm_session = LLMClientSession(provider=provider)

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


class PlatformWorkflowOrchestrator:
    """Coordinates test execution runs with AI failure diagnosis and self-healing."""

    def __init__(self, orchestrator: Optional[AgentOrchestrator] = None) -> None:
        self.ai_orchestrator = orchestrator or create_default_orchestrator()

    async def execute_test_run(
        self,
        db: Session,
        execution_id: int,
        options: Optional[RunOptions] = None,
    ) -> Dict[str, Any]:
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
        execution = db.query(TestExecution).filter(TestExecution.id == execution_id).first()
        if not execution:
            raise ValueError(f"TestExecution #{execution_id} not found")

        test_case = db.query(TestCase).filter(TestCase.id == execution.test_case_id).first()
        if not test_case:
            raise ValueError(f"TestCase #{execution.test_case_id} not found")

        app = db.query(Application).filter(Application.id == test_case.application_id).first()
        if not app:
            raise ValueError(f"Application #{test_case.application_id} not found")

        # Mark as RUNNING
        start_time = datetime.now(timezone.utc)
        execution.status = TestExecutionStatus.RUNNING.value
        execution.started_at = start_time
        db.commit()

        # Build application context
        app_context = ApplicationContext(
            app_name=app.name,
            app_url=app.base_url,
        )

        # Build Member 1 TestCase model from DB record
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
        )

        # Convert to Member 2 TestPlan
        engine_plan = test_case_to_engine_plan(m1_test_case, app.base_url)

        # Run test via Member 2
        run_opts = options or RunOptions(headless=True)
        engine_result: EngineTestResult = await run_test(engine_plan, options=run_opts)

        workflow_id = f"wf-exec-{execution.id}"
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
        else:
            # Failure detected -> delegate to Member 1 AI intelligence
            logger.info("Test execution failed. Submitting result to AI orchestrator for analysis.")
            analysis, recommendation = self.ai_orchestrator.submit_execution_result(
                result=exec_result,
                app_context=app_context,
            )

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
                # Build healed plan with replacement selector
                healed_steps: List[EngineStep] = []
                for s in engine_plan.steps:
                    step_copy = s.model_copy(deep=True)
                    if step_copy.target:
                        step_copy.target.primary_locator = recommendation.target_selector
                    healed_steps.append(step_copy)

                healed_plan = engine_plan.model_copy(update={"steps": healed_steps})
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
                self.ai_orchestrator.submit_healing_result(feedback, app_context)

                if validation_success:
                    final_status = TestExecutionStatus.PASSED.value
                    error_msg = f"Self-healed selector: {recommendation.target_selector}"
                else:
                    final_status = TestExecutionStatus.FAILED.value
                    error_msg = validation_result.error_message or "Healing validation failed"
            else:
                final_status = TestExecutionStatus.FAILED.value
                error_msg = engine_result.error_message or "Test execution failed"

        # Update database execution record
        end_time = datetime.now(timezone.utc)
        execution.status = final_status
        execution.completed_at = end_time
        execution.duration_ms = duration_ms
        execution.error_message = error_msg
        db.commit()
        db.refresh(execution)

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
        }

    async def stream_execution_events(
        self,
        workflow_id: str,
    ) -> AsyncGenerator[str, None]:
        """Stream SSE chunks for active workflow events."""
        state = self.ai_orchestrator.get_state(workflow_id)
        if state:
            for event in state.events:
                yield format_sse_event(event)
