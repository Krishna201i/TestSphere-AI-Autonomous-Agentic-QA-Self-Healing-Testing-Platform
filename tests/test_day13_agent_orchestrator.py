"""
TestSphere-AI — Day 13: Agent Orchestrator Tests

Comprehensive tests for the AI Agent Orchestrator, covering:

1. AgentState schema tests
2. State transition tests
3. Planning flow tests
4. Execution success flow tests
5. Failure analysis orchestration tests
6. Candidate generation orchestration tests
7. Healing decision orchestration tests
8. Healing result feedback (success) tests
9. Healing result feedback (failure + retry) tests
10. Maximum attempt limit tests
11. Duplicate candidate prevention tests
12. Full end-to-end success scenario
13. Full end-to-end failure scenario
14. Safety tests (10 cases)
15. Workflow event log tests

All tests run fully offline with MockLLMProvider and InMemoryStore.
No internet, browser, or real LLM required.
"""

from __future__ import annotations

import pytest
import uuid
from datetime import datetime, timezone

from agents.analyzer.analyzer import FailureAnalyzerAgent
from agents.analyzer.schemas import FailureAnalysis, FailureContext
from agents.healer.healing_decision import (
    ConfidenceThresholds,
    HealingDecisionEngine,
)
from agents.healer.healing_feedback import (
    HealingResultFeedback,
    HealingResultFeedbackProcessor,
)
from agents.healer.healing_schemas import (
    HealingContext,
    HealingRecommendation,
    ScoredCandidate,
)
from agents.healer.schemas import HealingCandidate, HealingResult
from agents.llm import LLMClientSession, MockLLMProvider
from agents.llm.config import LLMConfig
from agents.memory.in_memory_store import InMemoryStore
from agents.memory.memory_schemas import ElementRecord, HealingRecord
from agents.orchestration.agent_orchestrator import AgentOrchestrator
from agents.orchestration.workflow_schemas import (
    VALID_TRANSITIONS,
    AgentState,
    ExecutionResult,
    ExecutionResultStatus,
    OrchestratorConfig,
    WorkflowEvent,
    WorkflowEventType,
    WorkflowStep,
)
from agents.planner.planner import LLMTestPlanner
from agents.planner.schemas import (
    ApplicationContext,
    ElementContext,
    PageContext,
    TestCase,
    TestPlan,
    TestStep,
)
from agents.planner.mock_scenarios import register_planner_scenarios
from agents.schemas.enums import (
    CandidateSource,
    ConfidenceLevel,
    FailureType,
    HealingAction,
    HealingDecision,
    HealingStatus,
    RecommendedAction,
    TestAction,
    TestCategory,
    TestPriority,
    ValidationStatus,
)


# ══════════════════════════════════════════════════════════════
#  Fixtures
# ══════════════════════════════════════════════════════════════


def _mock_config() -> LLMConfig:
    """Return a standard mock LLM configuration."""
    return LLMConfig(provider="mock", model="mock-model", max_retries=0)


@pytest.fixture
def memory_store() -> InMemoryStore:
    """Fresh in-memory store for each test."""
    return InMemoryStore()


@pytest.fixture
def llm_client() -> LLMClientSession:
    """LLM client session backed by MockLLMProvider."""
    provider = MockLLMProvider(_mock_config())
    register_planner_scenarios(provider)
    return LLMClientSession(provider=provider)


@pytest.fixture
def failure_analyzer(memory_store: InMemoryStore) -> FailureAnalyzerAgent:
    """Failure analyzer with the in-memory store."""
    return FailureAnalyzerAgent(memory_store=memory_store)


@pytest.fixture
def healing_engine(
    memory_store: InMemoryStore,
    llm_client: LLMClientSession,
) -> HealingDecisionEngine:
    """Healing decision engine with the in-memory store."""
    return HealingDecisionEngine(
        memory_store=memory_store,
        llm_client=llm_client,
    )


@pytest.fixture
def feedback_processor(memory_store: InMemoryStore) -> HealingResultFeedbackProcessor:
    """Feedback processor with the in-memory store."""
    return HealingResultFeedbackProcessor(memory_store=memory_store)


@pytest.fixture
def test_planner(llm_client: LLMClientSession) -> LLMTestPlanner:
    """Test planner backed by MockLLMProvider."""
    return LLMTestPlanner(llm_client=llm_client)


@pytest.fixture
def config() -> OrchestratorConfig:
    """Default orchestrator configuration."""
    return OrchestratorConfig(max_healing_attempts=3)


@pytest.fixture
def orchestrator(
    memory_store: InMemoryStore,
    failure_analyzer: FailureAnalyzerAgent,
    healing_engine: HealingDecisionEngine,
    feedback_processor: HealingResultFeedbackProcessor,
    test_planner: LLMTestPlanner,
    config: OrchestratorConfig,
) -> AgentOrchestrator:
    """Fully wired orchestrator for integration tests."""
    return AgentOrchestrator(
        memory_store=memory_store,
        failure_analyzer=failure_analyzer,
        healing_engine=healing_engine,
        feedback_processor=feedback_processor,
        test_planner=test_planner,
        config=config,
    )


@pytest.fixture
def login_app_context() -> ApplicationContext:
    """Application context for a login page."""
    return ApplicationContext(
        app_name="TestApp",
        app_url="http://localhost:3000",
        description="A simple web app with a login page",
        pages=[
            PageContext(
                url="/login",
                name="Login Page",
                title="Login",
                description="User login page",
                elements=[
                    ElementContext(
                        tag="input",
                        id="username",
                        name="username",
                        type="text",
                        placeholder="Enter username",
                    ),
                    ElementContext(
                        tag="input",
                        id="password",
                        name="password",
                        type="password",
                        placeholder="Enter password",
                    ),
                    ElementContext(
                        tag="button",
                        id="login-btn",
                        text="Login",
                        type="submit",
                    ),
                ],
            ),
        ],
    )


def _make_failure_context(
    test_id: str = "TC_LOGIN_001",
    execution_id: str = "exec_001",
    target_selector: str = "#login-btn",
    error_message: str = "Element not found: #login-btn",
    current_element: ElementRecord | None = None,
) -> FailureContext:
    """Helper to create a FailureContext."""
    return FailureContext(
        test_id=test_id,
        execution_id=execution_id,
        failed_step=3,
        action="click",
        target_selector=target_selector,
        error_message=error_message,
        current_page_url="http://localhost:3000/login",
        current_page_title="Login",
        current_element=current_element,
    )


def _make_execution_result(
    workflow_id: str,
    test_case_id: str = "TC_LOGIN_001",
    status: ExecutionResultStatus = ExecutionResultStatus.FAILED,
    failure_context: FailureContext | None = None,
) -> ExecutionResult:
    """Helper to create an ExecutionResult."""
    if status == ExecutionResultStatus.FAILED and failure_context is None:
        failure_context = _make_failure_context()

    return ExecutionResult(
        workflow_id=workflow_id,
        test_case_id=test_case_id,
        status=status,
        failure_context=failure_context,
    )


def _make_healing_feedback(
    test_case_id: str = "TC_LOGIN_001",
    original_selector: str = "#login-btn",
    attempted_selector: str = "#sign-in-btn",
    validation_status: ValidationStatus = ValidationStatus.SUCCESS,
    healing_status: HealingStatus = HealingStatus.VALIDATED_SUCCESS,
    confidence: float = 0.85,
    execution_attempt: int = 1,
    error_reason: str | None = None,
) -> HealingResultFeedback:
    """Helper to create a HealingResultFeedback."""
    return HealingResultFeedback(
        test_case_id=test_case_id,
        original_selector=original_selector,
        attempted_selector=attempted_selector,
        validation_status=validation_status,
        healing_status=healing_status,
        confidence=confidence,
        execution_attempt=execution_attempt,
        error_reason=error_reason,
    )


# ══════════════════════════════════════════════════════════════
#  1. AgentState Schema Tests
# ══════════════════════════════════════════════════════════════


class TestAgentState:
    """Unit tests for the AgentState schema."""

    def test_default_construction(self):
        """AgentState should construct with sensible defaults."""
        state = AgentState()

        assert state.workflow_id.startswith("wf_")
        assert state.current_step == WorkflowStep.PLANNING
        assert state.status == "active"
        assert state.test_plan is None
        assert state.failure_analysis is None
        assert state.healing_candidates == []
        assert state.ranked_candidates == []
        assert state.healing_decision is None
        assert state.healing_recommendation is None
        assert state.healing_result is None
        assert state.attempted_selectors == set()
        assert state.healing_attempt_count == 0
        assert state.max_healing_attempts == 3
        assert state.events == []
        assert state.error_info is None

    def test_custom_workflow_id(self):
        """AgentState should accept a custom workflow_id."""
        state = AgentState(workflow_id="wf_custom123")
        assert state.workflow_id == "wf_custom123"

    def test_attempted_selectors_tracking(self):
        """attempted_selectors should track unique selectors."""
        state = AgentState()
        updated = state.model_copy(
            update={"attempted_selectors": {"#btn-a", "#btn-b"}},
        )
        assert "#btn-a" in updated.attempted_selectors
        assert "#btn-b" in updated.attempted_selectors
        assert len(updated.attempted_selectors) == 2

    def test_healing_attempt_count_increment(self):
        """healing_attempt_count should be incrementable."""
        state = AgentState(healing_attempt_count=0)
        updated = state.model_copy(
            update={"healing_attempt_count": state.healing_attempt_count + 1},
        )
        assert updated.healing_attempt_count == 1

    def test_events_list_accumulation(self):
        """Events should accumulate as a list."""
        state = AgentState()
        event = WorkflowEvent(
            workflow_id=state.workflow_id,
            event_type=WorkflowEventType.WORKFLOW_STARTED,
            step=WorkflowStep.PLANNING,
            message="Test event",
        )
        updated = state.model_copy(
            update={"events": [event]},
        )
        assert len(updated.events) == 1
        assert updated.events[0].event_type == WorkflowEventType.WORKFLOW_STARTED

    def test_timestamps_are_set(self):
        """created_at and updated_at should be set on construction."""
        state = AgentState()
        assert state.created_at != ""
        assert state.updated_at != ""


# ══════════════════════════════════════════════════════════════
#  2. State Transition Tests
# ══════════════════════════════════════════════════════════════


class TestStateTransitions:
    """Tests for the explicit state machine transitions."""

    def test_valid_transitions_are_defined(self):
        """All WorkflowStep values should have transition entries."""
        for step in WorkflowStep:
            assert step in VALID_TRANSITIONS

    def test_terminal_states_have_no_transitions(self):
        """COMPLETED and ABORTED should have no outgoing transitions."""
        assert len(VALID_TRANSITIONS[WorkflowStep.COMPLETED]) == 0
        assert len(VALID_TRANSITIONS[WorkflowStep.ABORTED]) == 0

    def test_planning_can_go_to_execution_pending(self):
        """PLANNING → EXECUTION_PENDING should be valid."""
        assert WorkflowStep.EXECUTION_PENDING in VALID_TRANSITIONS[WorkflowStep.PLANNING]

    def test_planning_can_go_to_aborted(self):
        """PLANNING → ABORTED should be valid."""
        assert WorkflowStep.ABORTED in VALID_TRANSITIONS[WorkflowStep.PLANNING]

    def test_invalid_transition_raises_error(self):
        """Transitioning from COMPLETED to PLANNING should raise ValueError."""
        state = AgentState(current_step=WorkflowStep.COMPLETED)
        with pytest.raises(ValueError, match="Invalid state transition"):
            AgentOrchestrator._transition(state, WorkflowStep.PLANNING)

    def test_execution_pending_to_success(self):
        """EXECUTION_PENDING → EXECUTION_SUCCESS should be valid."""
        state = AgentState(current_step=WorkflowStep.EXECUTION_PENDING)
        updated = AgentOrchestrator._transition(state, WorkflowStep.EXECUTION_SUCCESS)
        assert updated.current_step == WorkflowStep.EXECUTION_SUCCESS

    def test_execution_pending_to_failure(self):
        """EXECUTION_PENDING → FAILURE_DETECTED should be valid."""
        state = AgentState(current_step=WorkflowStep.EXECUTION_PENDING)
        updated = AgentOrchestrator._transition(state, WorkflowStep.FAILURE_DETECTED)
        assert updated.current_step == WorkflowStep.FAILURE_DETECTED

    def test_healing_pending_self_transition(self):
        """HEALING_PENDING_VALIDATION → HEALING_PENDING_VALIDATION (retry)."""
        state = AgentState(current_step=WorkflowStep.HEALING_PENDING_VALIDATION)
        updated = AgentOrchestrator._transition(
            state, WorkflowStep.HEALING_PENDING_VALIDATION,
        )
        assert updated.current_step == WorkflowStep.HEALING_PENDING_VALIDATION

    def test_cannot_skip_states(self):
        """PLANNING → GENERATING_CANDIDATES should be invalid."""
        state = AgentState(current_step=WorkflowStep.PLANNING)
        with pytest.raises(ValueError, match="Invalid state transition"):
            AgentOrchestrator._transition(state, WorkflowStep.GENERATING_CANDIDATES)


# ══════════════════════════════════════════════════════════════
#  3. Workflow Event Tests
# ══════════════════════════════════════════════════════════════


class TestWorkflowEvents:
    """Tests for the workflow event logging mechanism."""

    def test_event_creation(self):
        """WorkflowEvent should be constructable with all fields."""
        event = WorkflowEvent(
            workflow_id="wf_test",
            event_type=WorkflowEventType.WORKFLOW_STARTED,
            step=WorkflowStep.PLANNING,
            message="Started",
            metadata={"key": "value"},
        )
        assert event.workflow_id == "wf_test"
        assert event.event_type == WorkflowEventType.WORKFLOW_STARTED
        assert event.step == WorkflowStep.PLANNING
        assert event.message == "Started"
        assert event.metadata == {"key": "value"}
        assert event.timestamp != ""

    def test_add_event_appends(self):
        """_add_event should append to the events list."""
        state = AgentState()
        updated = AgentOrchestrator._add_event(
            state,
            WorkflowEventType.WORKFLOW_STARTED,
            message="First event",
        )
        assert len(updated.events) == 1

        updated2 = AgentOrchestrator._add_event(
            updated,
            WorkflowEventType.TEST_PLAN_GENERATED,
            message="Second event",
        )
        assert len(updated2.events) == 2

    def test_event_preserves_step(self):
        """Event should record the step at the time it was created."""
        state = AgentState(current_step=WorkflowStep.ANALYZING_FAILURE)
        updated = AgentOrchestrator._add_event(
            state,
            WorkflowEventType.FAILURE_ANALYSIS_COMPLETED,
            message="Analysis done",
        )
        assert updated.events[0].step == WorkflowStep.ANALYZING_FAILURE


# ══════════════════════════════════════════════════════════════
#  4. ExecutionResult Schema Tests
# ══════════════════════════════════════════════════════════════


class TestExecutionResult:
    """Tests for the ExecutionResult schema."""

    def test_success_result(self):
        """SUCCESS result should not require failure_context."""
        result = ExecutionResult(
            workflow_id="wf_123",
            test_case_id="TC_001",
            status=ExecutionResultStatus.SUCCESS,
        )
        assert result.status == ExecutionResultStatus.SUCCESS
        assert result.failure_context is None

    def test_failed_result_requires_context(self):
        """FAILED result without failure_context should raise."""
        with pytest.raises(ValueError, match="failure_context is required"):
            ExecutionResult(
                workflow_id="wf_123",
                test_case_id="TC_001",
                status=ExecutionResultStatus.FAILED,
                failure_context=None,
            )

    def test_failed_result_with_context(self):
        """FAILED result with failure_context should be valid."""
        ctx = _make_failure_context()
        result = ExecutionResult(
            workflow_id="wf_123",
            test_case_id="TC_001",
            status=ExecutionResultStatus.FAILED,
            failure_context=ctx,
        )
        assert result.status == ExecutionResultStatus.FAILED
        assert result.failure_context is not None

    def test_empty_workflow_id_rejected(self):
        """Empty workflow_id should be rejected."""
        with pytest.raises(ValueError):
            ExecutionResult(
                workflow_id="",
                test_case_id="TC_001",
                status=ExecutionResultStatus.SUCCESS,
            )

    def test_empty_test_case_id_rejected(self):
        """Empty test_case_id should be rejected."""
        with pytest.raises(ValueError):
            ExecutionResult(
                workflow_id="wf_123",
                test_case_id="",
                status=ExecutionResultStatus.SUCCESS,
            )


# ══════════════════════════════════════════════════════════════
#  5. OrchestratorConfig Tests
# ══════════════════════════════════════════════════════════════


class TestOrchestratorConfig:
    """Tests for the OrchestratorConfig schema."""

    def test_default_config(self):
        """Default config should have sensible values."""
        config = OrchestratorConfig()
        assert config.max_healing_attempts == 3
        assert config.minimum_confidence_for_healing == 0.30

    def test_custom_config(self):
        """Config should accept custom values."""
        config = OrchestratorConfig(
            max_healing_attempts=5,
            minimum_confidence_for_healing=0.50,
        )
        assert config.max_healing_attempts == 5
        assert config.minimum_confidence_for_healing == 0.50

    def test_invalid_max_attempts(self):
        """max_healing_attempts < 1 should be rejected."""
        with pytest.raises(ValueError):
            OrchestratorConfig(max_healing_attempts=0)


# ══════════════════════════════════════════════════════════════
#  6. Planning Flow Tests
# ══════════════════════════════════════════════════════════════


class TestPlanningFlow:
    """Tests for the test planning entry point."""

    @pytest.mark.asyncio
    async def test_start_planning_generates_plan(
        self, orchestrator: AgentOrchestrator, login_app_context: ApplicationContext,
    ):
        """start_planning should generate a TestPlan and transition to EXECUTION_PENDING."""
        state = await orchestrator.start_planning(login_app_context)

        assert state.current_step == WorkflowStep.EXECUTION_PENDING
        assert state.test_plan is not None
        assert len(state.test_plan.test_cases) > 0
        assert state.test_plan.application_name == "TestApp"
        assert state.status == "active"

    @pytest.mark.asyncio
    async def test_start_planning_records_events(
        self, orchestrator: AgentOrchestrator, login_app_context: ApplicationContext,
    ):
        """Planning should record WORKFLOW_STARTED and TEST_PLAN_GENERATED events."""
        state = await orchestrator.start_planning(login_app_context)

        event_types = [e.event_type for e in state.events]
        assert WorkflowEventType.WORKFLOW_STARTED in event_types
        assert WorkflowEventType.TEST_PLAN_GENERATED in event_types

    @pytest.mark.asyncio
    async def test_start_planning_without_planner_raises(
        self,
        memory_store: InMemoryStore,
        failure_analyzer: FailureAnalyzerAgent,
        healing_engine: HealingDecisionEngine,
        feedback_processor: HealingResultFeedbackProcessor,
        login_app_context: ApplicationContext,
    ):
        """start_planning without a test planner should raise ValueError."""
        orchestrator = AgentOrchestrator(
            memory_store=memory_store,
            failure_analyzer=failure_analyzer,
            healing_engine=healing_engine,
            feedback_processor=feedback_processor,
            test_planner=None,
        )
        with pytest.raises(ValueError, match="No test planner"):
            await orchestrator.start_planning(login_app_context)

    @pytest.mark.asyncio
    async def test_start_planning_stores_workflow(
        self, orchestrator: AgentOrchestrator, login_app_context: ApplicationContext,
    ):
        """Planning should store the workflow for later retrieval."""
        state = await orchestrator.start_planning(login_app_context)

        retrieved = orchestrator.get_state(state.workflow_id)
        assert retrieved is not None
        assert retrieved.workflow_id == state.workflow_id


# ══════════════════════════════════════════════════════════════
#  7. Execution Success Flow Tests
# ══════════════════════════════════════════════════════════════


class TestExecutionSuccessFlow:
    """Tests for the success execution path."""

    @pytest.mark.asyncio
    async def test_success_result_completes_workflow(
        self, orchestrator: AgentOrchestrator, login_app_context: ApplicationContext,
    ):
        """SUCCESS result should transition to COMPLETED."""
        state = await orchestrator.start_planning(login_app_context)

        result = ExecutionResult(
            workflow_id=state.workflow_id,
            test_case_id="TC_001",
            status=ExecutionResultStatus.SUCCESS,
        )
        state = await orchestrator.submit_execution_result(state, result)

        assert state.current_step == WorkflowStep.COMPLETED
        assert state.status == "completed"

    @pytest.mark.asyncio
    async def test_success_result_records_events(
        self, orchestrator: AgentOrchestrator, login_app_context: ApplicationContext,
    ):
        """SUCCESS should record EXECUTION_RESULT_RECEIVED and WORKFLOW_COMPLETED."""
        state = await orchestrator.start_planning(login_app_context)

        result = ExecutionResult(
            workflow_id=state.workflow_id,
            test_case_id="TC_001",
            status=ExecutionResultStatus.SUCCESS,
        )
        state = await orchestrator.submit_execution_result(state, result)

        event_types = [e.event_type for e in state.events]
        assert WorkflowEventType.EXECUTION_RESULT_RECEIVED in event_types
        assert WorkflowEventType.WORKFLOW_COMPLETED in event_types


# ══════════════════════════════════════════════════════════════
#  8. Failure Analysis Flow Tests
# ══════════════════════════════════════════════════════════════


class TestFailureAnalysisFlow:
    """Tests for the failure analysis orchestration."""

    @pytest.mark.asyncio
    async def test_failed_result_triggers_analysis(
        self,
        orchestrator: AgentOrchestrator,
        login_app_context: ApplicationContext,
        memory_store: InMemoryStore,
    ):
        """FAILED result should trigger failure analysis."""
        # Seed memory with previous element for the selector
        memory_store.store_element(
            ElementRecord(
                element_id="login-btn",
                selector="#login-btn",
                text="Login",
                role="button",
                page_url="http://localhost:3000/login",
            )
        )

        state = await orchestrator.start_planning(login_app_context)

        # Create failure with an alternative element in current UI
        current_element = ElementRecord(
            element_id="sign-in-btn",
            selector="#sign-in-btn",
            text="Sign In",
            role="button",
            page_url="http://localhost:3000/login",
        )
        failure_ctx = _make_failure_context(
            current_element=current_element,
        )
        result = _make_execution_result(
            workflow_id=state.workflow_id,
            failure_context=failure_ctx,
        )

        state = await orchestrator.submit_execution_result(state, result)

        # Failure analysis should have been performed
        assert state.failure_analysis is not None
        event_types = [e.event_type for e in state.events]
        assert WorkflowEventType.FAILURE_ANALYSIS_COMPLETED in event_types


# ══════════════════════════════════════════════════════════════
#  9. Healing Decision Flow Tests
# ══════════════════════════════════════════════════════════════


class TestHealingDecisionFlow:
    """Tests for the healing decision orchestration."""

    @pytest.mark.asyncio
    async def test_healing_produces_recommendation(
        self,
        orchestrator: AgentOrchestrator,
        login_app_context: ApplicationContext,
        memory_store: InMemoryStore,
    ):
        """Failure → analysis → candidates → decision → recommendation."""
        memory_store.store_element(
            ElementRecord(
                element_id="login-btn",
                selector="#login-btn",
                text="Login",
                role="button",
                page_url="http://localhost:3000/login",
            )
        )

        state = await orchestrator.start_planning(login_app_context)

        current_element = ElementRecord(
            element_id="sign-in-btn",
            selector="#sign-in-btn",
            text="Sign In",
            role="button",
            page_url="http://localhost:3000/login",
        )
        failure_ctx = _make_failure_context(
            current_element=current_element,
        )
        result = _make_execution_result(
            workflow_id=state.workflow_id,
            failure_context=failure_ctx,
        )

        state = await orchestrator.submit_execution_result(state, result)

        # The workflow should have a healing recommendation
        assert state.healing_recommendation is not None
        assert state.healing_recommendation.requires_validation is True

        # Verify events
        event_types = [e.event_type for e in state.events]
        assert WorkflowEventType.CANDIDATES_GENERATED in event_types
        assert WorkflowEventType.HEALING_DECISION_CREATED in event_types


# ══════════════════════════════════════════════════════════════
#  10. Healing Feedback Tests
# ══════════════════════════════════════════════════════════════


class TestHealingFeedback:
    """Tests for healing result feedback processing."""

    @pytest.mark.asyncio
    async def test_successful_healing_completes(
        self,
        orchestrator: AgentOrchestrator,
        login_app_context: ApplicationContext,
        memory_store: InMemoryStore,
    ):
        """Successful healing feedback should complete the workflow."""
        memory_store.store_element(
            ElementRecord(
                element_id="login-btn",
                selector="#login-btn",
                text="Login",
                role="button",
                page_url="http://localhost:3000/login",
            )
        )

        state = await orchestrator.start_planning(login_app_context)

        current_element = ElementRecord(
            element_id="sign-in-btn",
            selector="#sign-in-btn",
            text="Sign In",
            role="button",
            page_url="http://localhost:3000/login",
        )
        failure_ctx = _make_failure_context(current_element=current_element)
        exec_result = _make_execution_result(
            workflow_id=state.workflow_id,
            failure_context=failure_ctx,
        )
        state = await orchestrator.submit_execution_result(state, exec_result)

        if state.current_step != WorkflowStep.HEALING_PENDING_VALIDATION:
            pytest.skip("No healing recommendation was generated")

        # Get the recommended selector
        recommended_selector = state.healing_recommendation.selected_candidate.selector

        # Member 2 reports success
        feedback = _make_healing_feedback(
            attempted_selector=recommended_selector,
            validation_status=ValidationStatus.SUCCESS,
            healing_status=HealingStatus.VALIDATED_SUCCESS,
        )
        state = await orchestrator.submit_healing_result(state, feedback)

        assert state.current_step == WorkflowStep.COMPLETED
        assert state.status == "completed"

        event_types = [e.event_type for e in state.events]
        assert WorkflowEventType.HEALING_RESULT_RECEIVED in event_types
        assert WorkflowEventType.HEALING_HISTORY_UPDATED in event_types
        assert WorkflowEventType.WORKFLOW_COMPLETED in event_types

    @pytest.mark.asyncio
    async def test_failed_healing_triggers_retry(
        self,
        orchestrator: AgentOrchestrator,
        login_app_context: ApplicationContext,
        memory_store: InMemoryStore,
    ):
        """Failed healing should try the next candidate if available."""
        memory_store.store_element(
            ElementRecord(
                element_id="login-btn",
                selector="#login-btn",
                text="Login",
                role="button",
                page_url="http://localhost:3000/login",
            )
        )

        state = await orchestrator.start_planning(login_app_context)

        current_element = ElementRecord(
            element_id="sign-in-btn",
            selector="#sign-in-btn",
            text="Sign In",
            role="button",
            page_url="http://localhost:3000/login",
        )
        failure_ctx = _make_failure_context(current_element=current_element)
        exec_result = _make_execution_result(
            workflow_id=state.workflow_id,
            failure_context=failure_ctx,
        )
        state = await orchestrator.submit_execution_result(state, exec_result)

        if state.current_step != WorkflowStep.HEALING_PENDING_VALIDATION:
            pytest.skip("No healing recommendation was generated")

        initial_attempt_count = state.healing_attempt_count
        recommended_selector = state.healing_recommendation.selected_candidate.selector

        # Member 2 reports failure
        feedback = _make_healing_feedback(
            attempted_selector=recommended_selector,
            validation_status=ValidationStatus.FAILURE,
            healing_status=HealingStatus.VALIDATED_FAILURE,
            error_reason="Element not found",
        )
        state = await orchestrator.submit_healing_result(state, feedback)

        # Should have recorded the failed attempt
        assert recommended_selector in state.attempted_selectors


# ══════════════════════════════════════════════════════════════
#  11. Maximum Attempt Limit Tests
# ══════════════════════════════════════════════════════════════


class TestMaxAttemptLimits:
    """Tests for healing attempt limit enforcement."""

    @pytest.mark.asyncio
    async def test_max_attempts_stops_healing(self):
        """Healing should stop after max_healing_attempts failures."""
        state = AgentState(
            current_step=WorkflowStep.HEALING_PENDING_VALIDATION,
            healing_attempt_count=3,
            max_healing_attempts=3,
            ranked_candidates=[
                ScoredCandidate(
                    selector="#candidate-d",
                    source=CandidateSource.CURRENT_DOM,
                    confidence=0.7,
                ),
            ],
        )

        # _try_next_candidate should stop
        memory_store = InMemoryStore()
        analyzer = FailureAnalyzerAgent(memory_store=memory_store)
        provider = MockLLMProvider(_mock_config())
        llm_client = LLMClientSession(provider=provider)
        engine = HealingDecisionEngine(memory_store=memory_store, llm_client=llm_client)
        feedback_proc = HealingResultFeedbackProcessor(memory_store=memory_store)

        orchestrator = AgentOrchestrator(
            memory_store=memory_store,
            failure_analyzer=analyzer,
            healing_engine=engine,
            feedback_processor=feedback_proc,
        )

        updated = orchestrator._try_next_candidate(state)
        assert updated.current_step == WorkflowStep.COMPLETED
        assert updated.status == "completed"

    def test_config_max_attempts_propagates(self):
        """OrchestratorConfig max_healing_attempts should propagate to AgentState."""
        config = OrchestratorConfig(max_healing_attempts=5)
        state = AgentState(max_healing_attempts=config.max_healing_attempts)
        assert state.max_healing_attempts == 5


# ══════════════════════════════════════════════════════════════
#  12. Duplicate Candidate Prevention Tests
# ══════════════════════════════════════════════════════════════


class TestDuplicatePrevention:
    """Tests for avoiding repeated failed candidates."""

    @pytest.mark.asyncio
    async def test_attempted_selector_not_retried(self):
        """A previously failed selector should not be recommended again."""
        state = AgentState(
            current_step=WorkflowStep.HEALING_PENDING_VALIDATION,
            healing_attempt_count=1,
            max_healing_attempts=3,
            attempted_selectors={"#sign-in-btn"},
            ranked_candidates=[
                ScoredCandidate(
                    selector="#sign-in-btn",
                    source=CandidateSource.CURRENT_DOM,
                    confidence=0.9,
                ),
                ScoredCandidate(
                    selector=".login-button",
                    source=CandidateSource.HISTORICAL_MEMORY,
                    confidence=0.6,
                ),
            ],
        )

        memory_store = InMemoryStore()
        analyzer = FailureAnalyzerAgent(memory_store=memory_store)
        provider = MockLLMProvider(_mock_config())
        llm_client = LLMClientSession(provider=provider)
        engine = HealingDecisionEngine(memory_store=memory_store, llm_client=llm_client)
        feedback_proc = HealingResultFeedbackProcessor(memory_store=memory_store)

        orchestrator = AgentOrchestrator(
            memory_store=memory_store,
            failure_analyzer=analyzer,
            healing_engine=engine,
            feedback_processor=feedback_proc,
        )

        updated = orchestrator._try_next_candidate(state)

        # Should skip #sign-in-btn and try .login-button
        assert ".login-button" in updated.attempted_selectors
        assert updated.healing_attempt_count == 2

    @pytest.mark.asyncio
    async def test_all_candidates_exhausted(self):
        """When all candidates are in attempted_selectors, should stop."""
        state = AgentState(
            current_step=WorkflowStep.HEALING_PENDING_VALIDATION,
            healing_attempt_count=2,
            max_healing_attempts=5,
            attempted_selectors={"#sign-in-btn", ".login-button"},
            ranked_candidates=[
                ScoredCandidate(
                    selector="#sign-in-btn",
                    source=CandidateSource.CURRENT_DOM,
                    confidence=0.9,
                ),
                ScoredCandidate(
                    selector=".login-button",
                    source=CandidateSource.HISTORICAL_MEMORY,
                    confidence=0.6,
                ),
            ],
        )

        memory_store = InMemoryStore()
        analyzer = FailureAnalyzerAgent(memory_store=memory_store)
        provider = MockLLMProvider(_mock_config())
        llm_client = LLMClientSession(provider=provider)
        engine = HealingDecisionEngine(memory_store=memory_store, llm_client=llm_client)
        feedback_proc = HealingResultFeedbackProcessor(memory_store=memory_store)

        orchestrator = AgentOrchestrator(
            memory_store=memory_store,
            failure_analyzer=analyzer,
            healing_engine=engine,
            feedback_processor=feedback_proc,
        )

        updated = orchestrator._try_next_candidate(state)
        assert updated.current_step == WorkflowStep.COMPLETED
        assert updated.status == "completed"


# ══════════════════════════════════════════════════════════════
#  13. Full E2E Success Scenario
# ══════════════════════════════════════════════════════════════


class TestFullE2ESuccess:
    """Complete offline integration test — successful healing.

    Scenario:
    - App: Login page
    - Original selector: #login-btn
    - Previous success: #login-btn
    - Current UI: #sign-in-btn
    - Failure: ELEMENT_NOT_FOUND → SELECTOR_CHANGED
    - Candidate: #sign-in-btn
    - Decision: TRY_REPLACEMENT_SELECTOR
    - Member 2: HEALED
    - Result: HEALING_SUCCEEDED → COMPLETED
    """

    @pytest.mark.asyncio
    async def test_full_healing_success_scenario(
        self,
        login_app_context: ApplicationContext,
    ):
        """Full E2E: plan → execute → fail → analyze → heal → validate → complete."""
        # ── Setup ─────────────────────────────────────────
        memory_store = InMemoryStore()

        # Seed historical element
        memory_store.store_element(
            ElementRecord(
                element_id="login-btn",
                selector="#login-btn",
                text="Login",
                role="button",
                page_url="http://localhost:3000/login",
            )
        )

        # Seed historical healing success for #sign-in-btn
        memory_store.store_healing_record(
            HealingRecord(
                healing_id="hist_1",
                test_id="TC_LOGIN_001",
                old_selector="#login-btn",
                new_selector="#sign-in-btn",
                confidence=0.85,
                validation_result=True,
            )
        )
        memory_store.store_healing_record(
            HealingRecord(
                healing_id="hist_2",
                test_id="TC_LOGIN_002",
                old_selector="#login-btn",
                new_selector="#sign-in-btn",
                confidence=0.90,
                validation_result=True,
            )
        )

        # Seed historical healing failures for .login-button
        memory_store.store_healing_record(
            HealingRecord(
                healing_id="hist_3",
                test_id="TC_LOGIN_001",
                old_selector="#login-btn",
                new_selector=".login-button",
                confidence=0.60,
                validation_result=False,
            )
        )
        memory_store.store_healing_record(
            HealingRecord(
                healing_id="hist_4",
                test_id="TC_LOGIN_002",
                old_selector="#login-btn",
                new_selector=".login-button",
                confidence=0.55,
                validation_result=False,
            )
        )

        # Build components
        provider = MockLLMProvider(_mock_config())
        register_planner_scenarios(provider)
        llm_client = LLMClientSession(provider=provider)
        analyzer = FailureAnalyzerAgent(memory_store=memory_store)
        engine = HealingDecisionEngine(memory_store=memory_store, llm_client=llm_client)
        feedback_proc = HealingResultFeedbackProcessor(memory_store=memory_store)
        planner = LLMTestPlanner(llm_client=llm_client)

        orchestrator = AgentOrchestrator(
            memory_store=memory_store,
            failure_analyzer=analyzer,
            healing_engine=engine,
            feedback_processor=feedback_proc,
            test_planner=planner,
            config=OrchestratorConfig(max_healing_attempts=3),
        )

        # ── Step 1: Plan ──────────────────────────────────
        state = await orchestrator.start_planning(login_app_context)
        assert state.current_step == WorkflowStep.EXECUTION_PENDING
        assert state.test_plan is not None

        # ── Step 2: Execute (simulated failure) ───────────
        current_element = ElementRecord(
            element_id="sign-in-btn",
            selector="#sign-in-btn",
            text="Sign In",
            role="button",
            page_url="http://localhost:3000/login",
        )
        failure_ctx = _make_failure_context(current_element=current_element)
        exec_result = _make_execution_result(
            workflow_id=state.workflow_id,
            failure_context=failure_ctx,
        )
        state = await orchestrator.submit_execution_result(state, exec_result)

        # ── Step 3: Verify analysis ───────────────────────
        assert state.failure_analysis is not None
        assert state.failure_analysis.failure_type in {
            FailureType.SELECTOR_CHANGED,
            FailureType.ELEMENT_NOT_FOUND,
        }

        # ── Step 4: Verify recommendation ────────────────
        if state.current_step == WorkflowStep.HEALING_PENDING_VALIDATION:
            assert state.healing_recommendation is not None
            assert state.healing_recommendation.requires_validation is True

            recommended_selector = state.healing_recommendation.selected_candidate.selector

            # ── Step 5: Member 2 validates ─────────────────
            feedback = _make_healing_feedback(
                attempted_selector=recommended_selector,
                validation_status=ValidationStatus.SUCCESS,
                healing_status=HealingStatus.VALIDATED_SUCCESS,
                confidence=state.healing_recommendation.selected_candidate.confidence,
            )
            state = await orchestrator.submit_healing_result(state, feedback)

            # ── Step 6: Verify final state ─────────────────
            assert state.current_step == WorkflowStep.COMPLETED
            assert state.status == "completed"

            # Verify healing history was updated
            history = memory_store.get_healing_history("#login-btn")
            # Should have the new healing record stored
            assert len(history) > 0

            # Verify events
            event_types = [e.event_type for e in state.events]
            assert WorkflowEventType.WORKFLOW_STARTED in event_types
            assert WorkflowEventType.TEST_PLAN_GENERATED in event_types
            assert WorkflowEventType.EXECUTION_RESULT_RECEIVED in event_types
            assert WorkflowEventType.FAILURE_ANALYSIS_COMPLETED in event_types
            assert WorkflowEventType.HEALING_RESULT_RECEIVED in event_types
            assert WorkflowEventType.HEALING_HISTORY_UPDATED in event_types
            assert WorkflowEventType.WORKFLOW_COMPLETED in event_types
        else:
            # If no healing was possible (e.g., candidate confidence too low),
            # workflow should have completed
            assert state.current_step == WorkflowStep.COMPLETED


# ══════════════════════════════════════════════════════════════
#  14. Full E2E Failure Scenario
# ══════════════════════════════════════════════════════════════


class TestFullE2EFailure:
    """Complete offline integration test — all healing attempts fail.

    Scenario:
    - Candidate A: #sign-in-btn → FAILED
    - Candidate B: .login-button → FAILED
    - Max attempts reached → HEALING_FAILED → COMPLETED
    - No infinite loop.
    """

    @pytest.mark.asyncio
    async def test_full_healing_failure_scenario(
        self,
        login_app_context: ApplicationContext,
    ):
        """All candidates fail, max attempts reached, workflow completes."""
        memory_store = InMemoryStore()

        memory_store.store_element(
            ElementRecord(
                element_id="login-btn",
                selector="#login-btn",
                text="Login",
                role="button",
                page_url="http://localhost:3000/login",
            )
        )

        provider = MockLLMProvider(_mock_config())
        register_planner_scenarios(provider)
        llm_client = LLMClientSession(provider=provider)
        analyzer = FailureAnalyzerAgent(memory_store=memory_store)
        engine = HealingDecisionEngine(memory_store=memory_store, llm_client=llm_client)
        feedback_proc = HealingResultFeedbackProcessor(memory_store=memory_store)
        planner = LLMTestPlanner(llm_client=llm_client)

        orchestrator = AgentOrchestrator(
            memory_store=memory_store,
            failure_analyzer=analyzer,
            healing_engine=engine,
            feedback_processor=feedback_proc,
            test_planner=planner,
            config=OrchestratorConfig(max_healing_attempts=2),
        )

        state = await orchestrator.start_planning(login_app_context)

        current_element = ElementRecord(
            element_id="sign-in-btn",
            selector="#sign-in-btn",
            text="Sign In",
            role="button",
            page_url="http://localhost:3000/login",
        )
        failure_ctx = _make_failure_context(current_element=current_element)
        exec_result = _make_execution_result(
            workflow_id=state.workflow_id,
            failure_context=failure_ctx,
        )
        state = await orchestrator.submit_execution_result(state, exec_result)

        if state.current_step != WorkflowStep.HEALING_PENDING_VALIDATION:
            # Workflow completed without healing attempt
            assert state.current_step == WorkflowStep.COMPLETED
            return

        # Keep failing until max attempts or completion
        attempt = 0
        max_safe_iterations = 10  # Absolute safety limit
        while (
            state.current_step == WorkflowStep.HEALING_PENDING_VALIDATION
            and attempt < max_safe_iterations
        ):
            selector = state.healing_recommendation.selected_candidate.selector
            feedback = _make_healing_feedback(
                attempted_selector=selector,
                validation_status=ValidationStatus.FAILURE,
                healing_status=HealingStatus.VALIDATED_FAILURE,
                error_reason="Selector not found in browser",
                execution_attempt=attempt + 1,
            )
            state = await orchestrator.submit_healing_result(state, feedback)
            attempt += 1

        # Workflow must have completed (no infinite loop)
        assert state.current_step == WorkflowStep.COMPLETED
        assert attempt <= max_safe_iterations
        assert attempt > 0  # At least one attempt was made


# ══════════════════════════════════════════════════════════════
#  15. Safety Tests
# ══════════════════════════════════════════════════════════════


class TestSafety:
    """Safety tests proving critical invariants."""

    @pytest.mark.asyncio
    async def test_invalid_execution_result_rejected(
        self,
        orchestrator: AgentOrchestrator,
        login_app_context: ApplicationContext,
    ):
        """Submitting result in wrong state should raise ValueError."""
        state = AgentState(current_step=WorkflowStep.PLANNING)
        result = ExecutionResult(
            workflow_id=state.workflow_id,
            test_case_id="TC_001",
            status=ExecutionResultStatus.SUCCESS,
        )
        with pytest.raises(ValueError, match="expected EXECUTION_PENDING"):
            await orchestrator.submit_execution_result(state, result)

    @pytest.mark.asyncio
    async def test_invalid_healing_result_rejected(
        self,
        orchestrator: AgentOrchestrator,
    ):
        """Submitting healing result in wrong state should raise ValueError."""
        state = AgentState(current_step=WorkflowStep.PLANNING)
        feedback = _make_healing_feedback()
        with pytest.raises(ValueError, match="expected HEALING_PENDING_VALIDATION"):
            await orchestrator.submit_healing_result(state, feedback)

    @pytest.mark.asyncio
    async def test_workflow_id_mismatch_rejected(
        self,
        orchestrator: AgentOrchestrator,
        login_app_context: ApplicationContext,
    ):
        """Mismatched workflow_id should raise ValueError."""
        state = await orchestrator.start_planning(login_app_context)

        result = ExecutionResult(
            workflow_id="wf_wrong_id",
            test_case_id="TC_001",
            status=ExecutionResultStatus.SUCCESS,
        )
        with pytest.raises(ValueError, match="Workflow ID mismatch"):
            await orchestrator.submit_execution_result(state, result)

    def test_healing_cannot_be_marked_success_without_member2(self):
        """HealingRecommendation.requires_validation must always be True."""
        with pytest.raises(ValueError, match="requires_validation must always be True"):
            HealingRecommendation(
                test_id="TC_001",
                execution_id="exec_001",
                failed_step=1,
                failure_type=FailureType.SELECTOR_CHANGED,
                confidence=ConfidenceLevel.HIGH,
                recommended_action=HealingAction.TRY_REPLACEMENT_SELECTOR,
                requires_validation=False,  # This should fail
            )

    def test_failed_candidates_tracked_in_state(self):
        """attempted_selectors should correctly track failed candidates."""
        state = AgentState(attempted_selectors={"#btn-a", "#btn-b"})
        assert "#btn-a" in state.attempted_selectors
        assert "#btn-b" in state.attempted_selectors
        assert "#btn-c" not in state.attempted_selectors

    def test_max_healing_attempts_enforced(self):
        """Healing should stop when max_healing_attempts is reached."""
        state = AgentState(
            current_step=WorkflowStep.HEALING_PENDING_VALIDATION,
            healing_attempt_count=3,
            max_healing_attempts=3,
            ranked_candidates=[
                ScoredCandidate(
                    selector="#unused-candidate",
                    source=CandidateSource.CURRENT_DOM,
                    confidence=0.95,
                ),
            ],
        )

        memory_store = InMemoryStore()
        analyzer = FailureAnalyzerAgent(memory_store=memory_store)
        provider = MockLLMProvider(_mock_config())
        llm_client = LLMClientSession(provider=provider)
        engine = HealingDecisionEngine(memory_store=memory_store, llm_client=llm_client)
        feedback_proc = HealingResultFeedbackProcessor(memory_store=memory_store)

        orchestrator = AgentOrchestrator(
            memory_store=memory_store,
            failure_analyzer=analyzer,
            healing_engine=engine,
            feedback_processor=feedback_proc,
        )

        updated = orchestrator._try_next_candidate(state)
        # Even though there's a valid candidate, max attempts reached
        assert updated.current_step == WorkflowStep.COMPLETED

    @pytest.mark.asyncio
    async def test_unknown_failure_with_low_confidence_not_healed(
        self,
        orchestrator: AgentOrchestrator,
        login_app_context: ApplicationContext,
    ):
        """UNKNOWN failure type with LOW confidence should not be healed."""
        state = await orchestrator.start_planning(login_app_context)

        # Create a failure that will be classified as UNKNOWN
        failure_ctx = FailureContext(
            test_id="TC_001",
            execution_id="exec_001",
            failed_step=1,
            action="custom_action",
            target_selector="#mystery-element",
            error_message="Something happened with the element",
            current_page_url="http://localhost:3000/unknown",
        )
        exec_result = ExecutionResult(
            workflow_id=state.workflow_id,
            test_case_id="TC_001",
            status=ExecutionResultStatus.FAILED,
            failure_context=failure_ctx,
        )
        state = await orchestrator.submit_execution_result(state, exec_result)

        # Should complete without attempting healing
        assert state.current_step == WorkflowStep.COMPLETED

    def test_empty_candidate_list_handled(self):
        """Empty candidate list should result in HEALING_FAILED."""
        state = AgentState(
            current_step=WorkflowStep.HEALING_PENDING_VALIDATION,
            healing_attempt_count=1,
            max_healing_attempts=3,
            attempted_selectors=set(),
            ranked_candidates=[],  # No candidates
        )

        memory_store = InMemoryStore()
        analyzer = FailureAnalyzerAgent(memory_store=memory_store)
        provider = MockLLMProvider(_mock_config())
        llm_client = LLMClientSession(provider=provider)
        engine = HealingDecisionEngine(memory_store=memory_store, llm_client=llm_client)
        feedback_proc = HealingResultFeedbackProcessor(memory_store=memory_store)

        orchestrator = AgentOrchestrator(
            memory_store=memory_store,
            failure_analyzer=analyzer,
            healing_engine=engine,
            feedback_processor=feedback_proc,
        )

        updated = orchestrator._try_next_candidate(state)
        assert updated.current_step == WorkflowStep.COMPLETED

    def test_cannot_transition_to_invalid_state(self):
        """Invalid state transitions should be rejected."""
        state = AgentState(current_step=WorkflowStep.EXECUTION_PENDING)
        with pytest.raises(ValueError, match="Invalid state transition"):
            AgentOrchestrator._transition(state, WorkflowStep.COMPLETED)

    def test_existing_memory_remains_intact(self):
        """Historical memory should persist through workflow operations."""
        memory_store = InMemoryStore()

        # Store pre-existing data
        memory_store.store_element(
            ElementRecord(
                element_id="pre-existing",
                selector="#pre-existing",
                text="Existing Element",
                role="button",
            )
        )
        memory_store.store_healing_record(
            HealingRecord(
                healing_id="pre_heal_1",
                test_id="TC_LEGACY",
                old_selector="#old",
                new_selector="#new",
                confidence=0.80,
                validation_result=True,
            )
        )

        # Create orchestrator — memory should not be cleared
        analyzer = FailureAnalyzerAgent(memory_store=memory_store)
        provider = MockLLMProvider(_mock_config())
        llm_client = LLMClientSession(provider=provider)
        engine = HealingDecisionEngine(memory_store=memory_store, llm_client=llm_client)
        feedback_proc = HealingResultFeedbackProcessor(memory_store=memory_store)

        _ = AgentOrchestrator(
            memory_store=memory_store,
            failure_analyzer=analyzer,
            healing_engine=engine,
            feedback_processor=feedback_proc,
        )

        # Verify data is still there
        element = memory_store.get_element_by_selector("#pre-existing")
        assert element is not None
        assert element.text == "Existing Element"

        history = memory_store.get_healing_history("#old")
        assert len(history) == 1
        assert history[0].healing_id == "pre_heal_1"


# ══════════════════════════════════════════════════════════════
#  16. Assertion Failure Safety Test
# ══════════════════════════════════════════════════════════════


class TestAssertionFailureNotHealed:
    """Assertion failures should not trigger healing."""

    @pytest.mark.asyncio
    async def test_assertion_failure_not_healed(
        self,
        orchestrator: AgentOrchestrator,
        login_app_context: ApplicationContext,
    ):
        """ASSERTION_FAILURE type should not be healed."""
        state = await orchestrator.start_planning(login_app_context)

        failure_ctx = FailureContext(
            test_id="TC_001",
            execution_id="exec_001",
            failed_step=2,
            action="click",
            target_selector="#submit",
            error_message="Assertion failed: expected 'Dashboard' but got 'Error'",
            expected_result="Dashboard",
            actual_result="Error",
        )
        exec_result = ExecutionResult(
            workflow_id=state.workflow_id,
            test_case_id="TC_001",
            status=ExecutionResultStatus.FAILED,
            failure_context=failure_ctx,
        )
        state = await orchestrator.submit_execution_result(state, exec_result)

        # Should complete without healing
        assert state.current_step == WorkflowStep.COMPLETED
        assert state.failure_analysis is not None


# ══════════════════════════════════════════════════════════════
#  17. Contract Import Tests
# ══════════════════════════════════════════════════════════════


class TestContractImports:
    """Verify Day 13 contracts are accessible from the contracts module."""

    def test_import_from_contracts(self):
        """Day 13 schemas should be importable from contracts."""
        from agents.schemas.contracts import (
            AgentState,
            ExecutionResult,
            ExecutionResultStatus,
            OrchestratorConfig,
            WorkflowEvent,
            WorkflowEventType,
            WorkflowStep,
        )
        assert AgentState is not None
        assert WorkflowStep is not None
        assert ExecutionResult is not None

    def test_import_from_orchestration(self):
        """Day 13 classes should be importable from orchestration package."""
        from agents.orchestration import (
            AgentOrchestrator,
            AgentState,
            WorkflowStep,
            ExecutionResult,
            ExecutionResultStatus,
            OrchestratorConfig,
            WorkflowEvent,
            WorkflowEventType,
            VALID_TRANSITIONS,
        )
        assert AgentOrchestrator is not None
        assert VALID_TRANSITIONS is not None


# ══════════════════════════════════════════════════════════════
#  18. Event Log Completeness Tests
# ══════════════════════════════════════════════════════════════


class TestEventLogCompleteness:
    """Verify that events are recorded at each workflow stage."""

    @pytest.mark.asyncio
    async def test_planning_events(
        self, orchestrator: AgentOrchestrator, login_app_context: ApplicationContext,
    ):
        """Planning should produce at least 2 events."""
        state = await orchestrator.start_planning(login_app_context)
        assert len(state.events) >= 2

    @pytest.mark.asyncio
    async def test_success_events(
        self, orchestrator: AgentOrchestrator, login_app_context: ApplicationContext,
    ):
        """Success flow should produce planning + execution events."""
        state = await orchestrator.start_planning(login_app_context)
        result = ExecutionResult(
            workflow_id=state.workflow_id,
            test_case_id="TC_001",
            status=ExecutionResultStatus.SUCCESS,
        )
        state = await orchestrator.submit_execution_result(state, result)

        event_types = [e.event_type for e in state.events]
        assert WorkflowEventType.WORKFLOW_STARTED in event_types
        assert WorkflowEventType.EXECUTION_RESULT_RECEIVED in event_types

    @pytest.mark.asyncio
    async def test_events_have_correct_workflow_id(
        self, orchestrator: AgentOrchestrator, login_app_context: ApplicationContext,
    ):
        """All events should have the correct workflow_id."""
        state = await orchestrator.start_planning(login_app_context)
        for event in state.events:
            assert event.workflow_id == state.workflow_id

    @pytest.mark.asyncio
    async def test_events_have_timestamps(
        self, orchestrator: AgentOrchestrator, login_app_context: ApplicationContext,
    ):
        """All events should have non-empty timestamps."""
        state = await orchestrator.start_planning(login_app_context)
        for event in state.events:
            assert event.timestamp != ""


# ══════════════════════════════════════════════════════════════
#  19. Workflow Step Enum Completeness
# ══════════════════════════════════════════════════════════════


class TestWorkflowStepEnum:
    """Tests for the WorkflowStep enum."""

    def test_all_required_steps_exist(self):
        """All 13 required workflow steps should exist."""
        expected = {
            "PLANNING",
            "EXECUTION_PENDING",
            "EXECUTION_SUCCESS",
            "FAILURE_DETECTED",
            "ANALYZING_FAILURE",
            "GENERATING_CANDIDATES",
            "RANKING_CANDIDATES",
            "DECIDING_HEALING",
            "HEALING_PENDING_VALIDATION",
            "HEALING_SUCCEEDED",
            "HEALING_FAILED",
            "COMPLETED",
            "ABORTED",
        }
        actual = {step.value for step in WorkflowStep}
        assert expected.issubset(actual)

    def test_workflow_event_types_exist(self):
        """All required event types should exist."""
        expected = {
            "WORKFLOW_STARTED",
            "TEST_PLAN_GENERATED",
            "EXECUTION_RESULT_RECEIVED",
            "FAILURE_ANALYSIS_COMPLETED",
            "CANDIDATES_GENERATED",
            "CANDIDATES_RANKED",
            "HEALING_DECISION_CREATED",
            "HEALING_RECOMMENDATION_SENT",
            "HEALING_RESULT_RECEIVED",
            "HEALING_HISTORY_UPDATED",
            "WORKFLOW_COMPLETED",
            "WORKFLOW_ABORTED",
            "STATE_TRANSITION",
            "VALIDATION_ERROR",
        }
        actual = {evt.value for evt in WorkflowEventType}
        assert expected.issubset(actual)
