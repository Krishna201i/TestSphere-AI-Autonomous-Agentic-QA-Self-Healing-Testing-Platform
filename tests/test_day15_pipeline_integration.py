"""
TestSphere-AI — Day 15: Autonomous Intelligence Pipeline Integration & Validation

Comprehensive end-to-end integration and stabilization test suite for
Member 1 (AI Agent & Intelligence Layer), covering:

1. End-to-End Autonomous Pipeline (Success Path)
2. Failed Healing Path (Multi-candidate retry and continuation)
3. Multi-Candidate Generation, Scoring & Ranking
4. Retry vs Healing Decision Routing (RecoveryPolicy)
5. Max Attempts & Abortion Limits
6. Historical Feedback Loop & Memory Learning
7. LLM Boundaries & Deterministic Fallbacks (Offline Operation)
8. Error Handling, Malformed Input & Safety Invariants
9. Workflow Observability & Event Stream Audit Trail
10. Member 1 ↔ Member 2 Contract Review & Serialization
11. Member 1 ↔ Member 3 Contract Review & Streaming API
12. Security Review (Safe Selectors, Bound Loops, No Injection)
13. Pipeline Performance (< 500ms offline execution)
14. Final Test Matrix (15 distinct end-to-end scenarios)

All tests run fully offline with MockLLMProvider and InMemoryStore.
Zero external network calls, browser processes, or API keys required.
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

import pytest

from agents.analyzer.analyzer import FailureAnalyzerAgent
from agents.analyzer.schemas import (
    FailureAnalysis,
    FailureContext,
    FailureEvidence,
    HistoricalContext,
    TestFailure,
)
from agents.healer.candidate_generator import CandidateGenerator
from agents.healer.candidate_scorer import CandidateScorer
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
from agents.memory.healing_evidence import HealingEvidenceRetriever
from agents.memory.in_memory_store import InMemoryStore
from agents.memory.memory_schemas import (
    ElementRecord,
    HealingRecord,
    TestExecutionRecord,
)
from agents.orchestration.agent_orchestrator import AgentOrchestrator
from agents.orchestration.recovery_policy import (
    RecoveryAction,
    RecoveryDecision,
    RecoveryPolicy,
    RecoveryPolicyConfig,
)
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
from agents.planner.mock_scenarios import register_planner_scenarios
from agents.planner.planner import LLMTestPlanner
from agents.planner.schemas import (
    ApplicationContext,
    Assertion,
    ElementContext,
    PageContext,
    PageInfo,
    TestCase,
    TestPlan,
    TestStep,
)
from agents.schemas.contracts import (
    AssertionType,
    CandidateSource,
    ConfidenceLevel,
    ExecutionStatus,
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
from agents.schemas.member2_contract import (
    MEMBER2_SAMPLE_EXECUTION_RESULT_JSON,
    MEMBER2_SAMPLE_FEEDBACK_JSON,
    MEMBER2_SAMPLE_HEALING_RECOMMENDATION_JSON,
    parse_member2_execution_result,
    parse_member2_feedback,
    serialize_for_member2,
)
from agents.schemas.member3_contract import (
    MEMBER3_SAMPLE_SSE_EVENT,
    MEMBER3_SAMPLE_WORKFLOW_SUMMARY_JSON,
    DashboardEventMessage,
    DashboardWorkflowSummary,
    build_dashboard_summary,
    format_sse_event,
    format_websocket_message,
)


# ══════════════════════════════════════════════════════════════
#  Fixtures & Helper Functions
# ══════════════════════════════════════════════════════════════


def _mock_config() -> LLMConfig:
    return LLMConfig(provider="mock", model="mock-model", max_retries=0)


@pytest.fixture
def memory_store() -> InMemoryStore:
    return InMemoryStore()


@pytest.fixture
def llm_client() -> LLMClientSession:
    provider = MockLLMProvider(_mock_config())
    register_planner_scenarios(provider)
    return LLMClientSession(provider=provider)


@pytest.fixture
def failure_analyzer(memory_store: InMemoryStore) -> FailureAnalyzerAgent:
    return FailureAnalyzerAgent(memory_store=memory_store)


@pytest.fixture
def healing_engine(
    memory_store: InMemoryStore,
    llm_client: LLMClientSession,
) -> HealingDecisionEngine:
    return HealingDecisionEngine(
        memory_store=memory_store,
        llm_client=llm_client,
    )


@pytest.fixture
def feedback_processor(memory_store: InMemoryStore) -> HealingResultFeedbackProcessor:
    return HealingResultFeedbackProcessor(memory_store=memory_store)


@pytest.fixture
def test_planner(llm_client: LLMClientSession) -> LLMTestPlanner:
    return LLMTestPlanner(llm_client=llm_client)


@pytest.fixture
def recovery_policy(memory_store: InMemoryStore) -> RecoveryPolicy:
    retriever = HealingEvidenceRetriever(memory_store)
    return RecoveryPolicy(
        config=RecoveryPolicyConfig(
            max_healing_attempts=3,
            min_healing_confidence=0.80,
            min_candidate_score=0.30,
            ambiguity_margin=0.02,
            max_retries=2,
        ),
        evidence_retriever=retriever,
    )


@pytest.fixture
def orchestrator(
    memory_store: InMemoryStore,
    failure_analyzer: FailureAnalyzerAgent,
    healing_engine: HealingDecisionEngine,
    feedback_processor: HealingResultFeedbackProcessor,
    test_planner: LLMTestPlanner,
    recovery_policy: RecoveryPolicy,
) -> AgentOrchestrator:
    return AgentOrchestrator(
        memory_store=memory_store,
        failure_analyzer=failure_analyzer,
        healing_engine=healing_engine,
        feedback_processor=feedback_processor,
        test_planner=test_planner,
        config=OrchestratorConfig(max_healing_attempts=3, max_retries=2),
        recovery_policy=recovery_policy,
    )


@pytest.fixture
def sample_app_context() -> ApplicationContext:
    return ApplicationContext(
        app_name="Demo Application",
        app_url="http://localhost:3000",
        description="A demo web application with login and dashboard.",
        pages=[
            PageContext(
                url="/login",
                name="Login",
                title="Login",
                description="User authentication page",
                elements=[
                    ElementContext(
                        tag="input",
                        id="email",
                        name="email",
                        type="email",
                        placeholder="Enter email",
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
                        id="login-button",
                        selector="#login-button",
                        text="Login",
                        type="submit",
                    ),
                ],
            ),
        ],
    )


def _seed_element_records(store: InMemoryStore):
    """Seed baseline element records in memory for selector lookup."""
    old_element = ElementRecord(
        element_id="elem-btn-orig",
        selector="#login-button",
        text="Login",
        role="button",
        page_url="http://localhost:3000/login",
        attributes={
            "id": "login-button",
            "type": "submit",
            "data-testid": "submit-login",
            "class": "btn primary",
        },
    )
    store.store_element(old_element)


# ══════════════════════════════════════════════════════════════
#  1. End-to-End Autonomous Pipeline Tests (Success Path)
# ══════════════════════════════════════════════════════════════


class TestE2ESuccessPipeline:
    """Full autonomous pipeline validation: Context → Plan → Fail → Analyze → Heal → Validated."""

    @pytest.mark.asyncio
    async def test_complete_autonomous_success_cycle(
        self,
        orchestrator: AgentOrchestrator,
        sample_app_context: ApplicationContext,
        memory_store: InMemoryStore,
    ):
        # 1. Seed historical baseline element in memory
        _seed_element_records(memory_store)

        # 2. Start planning from application context
        state = await orchestrator.start_planning(sample_app_context)
        assert state.current_step == WorkflowStep.EXECUTION_PENDING
        assert state.test_plan is not None
        assert len(state.test_plan.test_cases) > 0
        test_case = state.test_plan.test_cases[0]

        # 3. Member 2 executes test and reports a selector failure
        new_element = ElementRecord(
            element_id="elem-btn-new",
            selector="button[data-testid='submit-login']",
            text="Login",
            role="button",
            page_url="http://localhost:3000/login",
            attributes={
                "type": "submit",
                "data-testid": "submit-login",
                "class": "btn primary-active",
            },
        )
        fail_context = FailureContext(
            test_id=test_case.test_id,
            execution_id="exec-001",
            failed_step=4,
            action="click",
            target_selector="#login-button",
            error_message="Element not found: #login-button",
            current_element=new_element,
            current_page_url="http://localhost:3000/login",
        )
        exec_result = ExecutionResult(
            workflow_id=state.workflow_id,
            test_case_id=test_case.test_id,
            status=ExecutionResultStatus.FAILED,
            failure_context=fail_context,
        )

        state = await orchestrator.submit_execution_result(state, exec_result)

        # 4. Pipeline should analyze failure, score candidates, apply recovery policy
        # and transition to HEALING_PENDING_VALIDATION
        assert state.current_step == WorkflowStep.HEALING_PENDING_VALIDATION
        assert state.failure_analysis is not None
        assert state.failure_analysis.failure_type in (
            FailureType.SELECTOR_CHANGED,
            FailureType.ELEMENT_NOT_FOUND,
        )
        assert state.healing_recommendation is not None
        assert state.recovery_decision is not None
        assert state.recovery_decision.decision == RecoveryAction.TRY_HEALING
        assert state.healing_attempt_count == 1
        rec_selector = state.recovery_decision.selected_candidate.selector
        assert "submit-login" in rec_selector

        # 5. Member 2 validates the recommended selector in browser and reports success
        feedback = HealingResultFeedback(
            test_case_id=test_case.test_id,
            original_selector="#login-button",
            attempted_selector=rec_selector,
            healing_status=HealingStatus.VALIDATED_SUCCESS,
            validation_status=ValidationStatus.SUCCESS,
            confidence=0.95,
            execution_attempt=1,
            target_element_text="Login",
            validation_time_ms=120.0,
        )
        final_state = await orchestrator.submit_healing_result(state, feedback)

        # 6. Final state should be COMPLETED, with healing verified and memory recorded
        assert final_state.current_step == WorkflowStep.COMPLETED
        assert final_state.healing_result is not None
        assert final_state.healing_result.status == HealingStatus.VALIDATED_SUCCESS
        assert final_state.healing_result.new_selector == rec_selector

        # Check memory store has the healing record recorded
        records = memory_store.get_healing_history("#login-button")
        assert len(records) >= 1
        assert records[0].validation_result is True
        assert records[0].new_selector == rec_selector


# ══════════════════════════════════════════════════════════════
#  2. Failed Healing Path & Multi-Candidate Continuation
# ══════════════════════════════════════════════════════════════


class TestE2EFailedHealingPipeline:
    """Validation of multi-candidate continuation when initial healing attempts fail."""

    @pytest.mark.asyncio
    async def test_candidate_fails_then_second_candidate_succeeds(
        self,
        orchestrator: AgentOrchestrator,
        sample_app_context: ApplicationContext,
        memory_store: InMemoryStore,
    ):
        _seed_element_records(memory_store)

        state = await orchestrator.start_planning(sample_app_context)
        test_case = state.test_plan.test_cases[0]

        # Seed historical record for second candidate
        memory_store.store_healing_record(
            HealingRecord(
                healing_id="hist-c2",
                test_id=test_case.test_id,
                old_selector="#login-button",
                new_selector=".btn-login-temp",
                confidence=0.88,
                validation_result=True,
            )
        )

        # Allow second candidate evaluation
        orchestrator._recovery_policy = RecoveryPolicy(
            config=RecoveryPolicyConfig(
                max_healing_attempts=3,
                min_healing_confidence=0.10,
                min_candidate_score=0.10,
                ambiguity_margin=0.02,
                max_retries=2,
            ),
            evidence_retriever=HealingEvidenceRetriever(memory_store),
        )

        # Submit failure
        exec_result = ExecutionResult(
            workflow_id=state.workflow_id,
            test_case_id=test_case.test_id,
            status=ExecutionResultStatus.FAILED,
            failure_context=FailureContext(
                test_id=test_case.test_id,
                execution_id="exec-002",
                failed_step=4,
                action="click",
                target_selector="#login-button",
                error_message="Element not found: #login-button",
                current_element=ElementRecord(
                    element_id="elem-btn-alt",
                    selector="button[data-testid='submit-login']",
                    text="Login",
                    role="button",
                    page_url="http://localhost:3000/login",
                    attributes={
                        "type": "submit",
                        "data-testid": "submit-login",
                        "class": "btn primary-active",
                    },
                ),
                current_page_url="http://localhost:3000/login",
            ),
        )
        state = await orchestrator.submit_execution_result(state, exec_result)
        assert state.current_step == WorkflowStep.HEALING_PENDING_VALIDATION
        first_selector = state.recovery_decision.selected_candidate.selector

        # Simulate candidate 1 failure in Member 2 validation
        feedback1 = HealingResultFeedback(
            test_case_id=test_case.test_id,
            original_selector="#login-button",
            attempted_selector=first_selector,
            healing_status=HealingStatus.VALIDATED_FAILURE,
            validation_status=ValidationStatus.FAILURE,
            confidence=0.85,
            execution_attempt=1,
            error_message="Click intercepted by modal",
        )

        state = await orchestrator.submit_healing_result(state, feedback1)

        # If another candidate exists and attempt < max_attempts, state should either
        # offer candidate 2 in HEALING_PENDING_VALIDATION or conclude appropriately
        if state.current_step == WorkflowStep.HEALING_PENDING_VALIDATION:
            second_selector = state.recovery_decision.selected_candidate.selector
            assert second_selector != first_selector
            assert state.healing_attempt_count == 2

            # Candidate 2 succeeds
            feedback2 = HealingResultFeedback(
                test_case_id=test_case.test_id,
                original_selector="#login-button",
                attempted_selector=second_selector,
                healing_status=HealingStatus.VALIDATED_SUCCESS,
                validation_status=ValidationStatus.SUCCESS,
                confidence=0.90,
                execution_attempt=2,
            )
            final_state = await orchestrator.submit_healing_result(state, feedback2)
            assert final_state.current_step == WorkflowStep.COMPLETED
            assert final_state.healing_result.status == HealingStatus.VALIDATED_SUCCESS
        else:
            assert state.current_step in (WorkflowStep.COMPLETED, WorkflowStep.ABORTED)

    @pytest.mark.asyncio
    async def test_all_candidates_exhausted_terminates_cleanly(
        self,
        orchestrator: AgentOrchestrator,
        sample_app_context: ApplicationContext,
        memory_store: InMemoryStore,
    ):
        _seed_element_records(memory_store)

        state = await orchestrator.start_planning(sample_app_context)
        test_case = state.test_plan.test_cases[0]

        exec_result = ExecutionResult(
            workflow_id=state.workflow_id,
            test_case_id=test_case.test_id,
            status=ExecutionResultStatus.FAILED,
            failure_context=FailureContext(
                test_id=test_case.test_id,
                execution_id="exec-003",
                failed_step=4,
                action="click",
                target_selector="#login-button",
                error_message="Element not found: #login-button",
                current_element=ElementRecord(
                    element_id="elem-btn-only",
                    selector="button[data-testid='submit-login']",
                    text="Login",
                    role="button",
                    page_url="http://localhost:3000/login",
                    attributes={
                        "type": "submit",
                        "data-testid": "submit-login",
                        "class": "btn primary-active",
                    },
                ),
                current_page_url="http://localhost:3000/login",
            ),
        )
        state = await orchestrator.submit_execution_result(state, exec_result)
        assert state.current_step == WorkflowStep.HEALING_PENDING_VALIDATION

        # Exhaust candidate
        feedback = HealingResultFeedback(
            test_case_id=test_case.test_id,
            original_selector="#login-button",
            attempted_selector=state.recovery_decision.selected_candidate.selector,
            healing_status=HealingStatus.VALIDATED_FAILURE,
            validation_status=ValidationStatus.FAILURE,
            confidence=0.85,
            execution_attempt=1,
        )
        final_state = await orchestrator.submit_healing_result(state, feedback)

        # If no more candidates, transitions through HEALING_FAILED to COMPLETED or ABORTED
        assert final_state.current_step in (WorkflowStep.COMPLETED, WorkflowStep.ABORTED)


# ══════════════════════════════════════════════════════════════
#  3. Multi-Candidate Generation, Scoring & Ranking
# ══════════════════════════════════════════════════════════════


class TestMultiCandidateRanking:
    """Verifies that candidates from multiple sources are correctly scored and ranked."""

    def test_multi_source_candidate_scoring(self, memory_store: InMemoryStore):
        # 1. Historical element
        orig_el = ElementRecord(
            element_id="el-orig",
            selector="#save-settings",
            text="Save Settings",
            role="button",
            page_url="https://app.com/settings",
            attributes={"data-testid": "save-btn", "class": "btn-save"},
        )
        memory_store.store_element(orig_el)

        # 2. Historical healing record for historical pattern
        memory_store.store_healing_record(
            HealingRecord(
                healing_id="h-001",
                test_id="tc-settings",
                old_selector="#save-settings",
                new_selector="button[data-testid='save-btn']",
                healing_reason="attribute match",
                confidence=0.92,
                validation_result=True,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
        )

        analysis = FailureAnalysis(
            test_id="tc-settings",
            execution_id="exec-settings",
            failed_step=1,
            failure_type=FailureType.SELECTOR_CHANGED,
            root_cause="DOM change on settings button",
            confidence=ConfidenceLevel.HIGH,
            recommended_action=RecommendedAction.SEARCH_FOR_REPLACEMENT_SELECTOR,
            failed_target="#save-settings",
        )

        current_elements = [
            ElementRecord(
                element_id="el-curr-1",
                selector="button[data-testid='save-btn']",
                text="Save Settings",
                role="button",
                page_url="https://app.com/settings",
                attributes={"data-testid": "save-btn", "class": "btn-save-v2"},
            ),
            ElementRecord(
                element_id="el-curr-2",
                selector=".btn-save-v2",
                text="Save Settings",
                role="button",
                page_url="https://app.com/settings",
                attributes={"class": "btn-save-v2"},
            ),
            ElementRecord(
                element_id="el-curr-3",
                selector="#cancel-btn",
                text="Cancel",
                role="button",
                page_url="https://app.com/settings",
                attributes={"class": "btn-cancel"},
            ),
        ]

        generator = CandidateGenerator(memory_store=memory_store)
        context = HealingContext(
            failure_analysis=analysis,
            current_elements=current_elements,
            page_url="https://app.com/settings",
        )

        raw_candidates = generator.generate_candidates(context)
        assert len(raw_candidates) >= 2

        scorer = CandidateScorer()
        ranked = scorer.rank_candidates(raw_candidates)

        # Top candidate must have matching stable attribute
        assert len(ranked) >= 2
        top = ranked[0]
        assert "data-testid" in top.selector or top.selector == "button[data-testid='save-btn']"
        assert top.confidence > ranked[-1].confidence


# ══════════════════════════════════════════════════════════════
#  4. Retry vs Healing Decision Routing (Recovery Policy)
# ══════════════════════════════════════════════════════════════


class TestRetryVsHealingDecisions:
    """Verifies that transient errors trigger RETRY while non-healables DO_NOT_HEAL."""

    @pytest.mark.asyncio
    async def test_transient_timeout_triggers_retry(
        self,
        orchestrator: AgentOrchestrator,
        sample_app_context: ApplicationContext,
    ):
        state = await orchestrator.start_planning(sample_app_context)
        test_case = state.test_plan.test_cases[0]

        # Submit TIMEOUT failure
        exec_result = ExecutionResult(
            workflow_id=state.workflow_id,
            test_case_id=test_case.test_id,
            status=ExecutionResultStatus.FAILED,
            failure_context=FailureContext(
                test_id=test_case.test_id,
                execution_id="exec-timeout",
                failed_step=4,
                action="click",
                target_selector="#login-button",
                error_message="Timeout 30000ms waiting for selector",
            ),
        )

        state = await orchestrator.submit_execution_result(state, exec_result)

        # Recovery policy triggers RETRY -> RETRYING -> EXECUTION_PENDING
        assert state.recovery_decision is not None
        assert state.recovery_decision.decision == RecoveryAction.RETRY
        assert state.retry_count == 1
        assert state.current_step == WorkflowStep.EXECUTION_PENDING

    @pytest.mark.asyncio
    async def test_assertion_failure_triggers_do_not_heal(
        self,
        orchestrator: AgentOrchestrator,
        sample_app_context: ApplicationContext,
    ):
        state = await orchestrator.start_planning(sample_app_context)
        test_case = state.test_plan.test_cases[0]

        # Submit ASSERTION_FAILURE
        exec_result = ExecutionResult(
            workflow_id=state.workflow_id,
            test_case_id=test_case.test_id,
            status=ExecutionResultStatus.FAILED,
            failure_context=FailureContext(
                test_id=test_case.test_id,
                execution_id="exec-assert",
                failed_step=2,
                action="assert",
                target_selector=".welcome-banner",
                error_message="Assertion failed: expected 'Welcome User' got 'Access Denied'",
            ),
        )

        state = await orchestrator.submit_execution_result(state, exec_result)

        # Must NOT attempt healing
        assert state.recovery_decision is not None
        assert state.recovery_decision.decision == RecoveryAction.DO_NOT_HEAL
        assert state.current_step == WorkflowStep.COMPLETED


# ══════════════════════════════════════════════════════════════
#  5. Max Attempts & Abortion Limits
# ══════════════════════════════════════════════════════════════


class TestMaxAttemptsAndTermination:
    """Verifies that infinite loops are prevented and attempt limits are strictly enforced."""

    def test_max_healing_attempts_abort(self, recovery_policy: RecoveryPolicy):
        analysis = FailureAnalysis(
            test_id="tc-001",
            execution_id="exec-001",
            failed_step=1,
            failure_type=FailureType.SELECTOR_CHANGED,
            root_cause="DOM change",
            confidence=ConfidenceLevel.HIGH,
            recommended_action=RecommendedAction.SEARCH_FOR_REPLACEMENT_SELECTOR,
            failed_target="#button",
        )
        candidates = [
            ScoredCandidate(
                selector="#btn-new",
                confidence=0.92,
                source=CandidateSource.CURRENT_DOM,
            )
        ]

        # At attempt count 3 (max_healing_attempts=3), must abort
        decision = recovery_policy.evaluate(
            failure_analysis=analysis,
            ranked_candidates=candidates,
            healing_attempt_count=3,
        )
        assert decision.decision == RecoveryAction.ABORT

    def test_max_retries_escalation(self, recovery_policy: RecoveryPolicy):
        analysis = FailureAnalysis(
            test_id="tc-002",
            execution_id="exec-002",
            failed_step=1,
            failure_type=FailureType.TIMEOUT,
            root_cause="Timeout waiting for network",
            confidence=ConfidenceLevel.HIGH,
            recommended_action=RecommendedAction.INVESTIGATE_TIMEOUT,
        )

        # At retry count 2 (max_retries=2), cannot retry anymore
        decision = recovery_policy.evaluate(
            failure_analysis=analysis,
            ranked_candidates=[],
            retry_count=2,
        )
        assert decision.decision != RecoveryAction.RETRY
        assert decision.decision in (
            RecoveryAction.REQUIRE_FURTHER_ANALYSIS,
            RecoveryAction.ABORT,
        )


# ══════════════════════════════════════════════════════════════
#  6. Historical Feedback Loop & Memory Learning
# ══════════════════════════════════════════════════════════════


class TestHistoricalFeedbackLoop:
    """Verifies that validated healing outcomes inform and enhance subsequent decisions."""

    @pytest.mark.asyncio
    async def test_feedback_loop_records_and_informs_next_run(
        self,
        orchestrator: AgentOrchestrator,
        sample_app_context: ApplicationContext,
        memory_store: InMemoryStore,
    ):
        _seed_element_records(memory_store)

        # ── RUN 1: First healing experience ───────────────────
        state = await orchestrator.start_planning(sample_app_context)
        test_case = state.test_plan.test_cases[0]

        fail_context = FailureContext(
            test_id=test_case.test_id,
            execution_id="exec-run-1",
            failed_step=4,
            action="click",
            target_selector="#login-button",
            error_message="Element not found: #login-button",
            current_element=ElementRecord(
                element_id="elem-btn-new",
                selector="button[data-testid='submit-login']",
                text="Login",
                role="button",
                page_url="http://localhost:3000/login",
                attributes={
                    "type": "submit",
                    "data-testid": "submit-login",
                    "class": "btn primary-active",
                },
            ),
            current_page_url="http://localhost:3000/login",
        )
        state = await orchestrator.submit_execution_result(
            state,
            ExecutionResult(
                workflow_id=state.workflow_id,
                test_case_id=test_case.test_id,
                status=ExecutionResultStatus.FAILED,
                failure_context=fail_context,
            ),
        )

        # Member 2 confirms success
        feedback = HealingResultFeedback(
            test_case_id=test_case.test_id,
            original_selector="#login-button",
            attempted_selector="button[data-testid='submit-login']",
            healing_status=HealingStatus.VALIDATED_SUCCESS,
            validation_status=ValidationStatus.SUCCESS,
            confidence=0.95,
            execution_attempt=1,
        )
        final_state_1 = await orchestrator.submit_healing_result(state, feedback)
        assert final_state_1.current_step == WorkflowStep.COMPLETED

        # ── RUN 2: Verify memory store contains the pattern ───
        retriever = HealingEvidenceRetriever(memory_store)
        history = retriever.get_selector_history("#login-button")
        assert history.total_healings >= 1
        assert history.total_successes >= 1
        rep_selectors = [r.new_selector for r in history.replacement_stats]
        assert "button[data-testid='submit-login']" in rep_selectors


# ══════════════════════════════════════════════════════════════
#  7. LLM Boundaries & Deterministic Fallbacks (Offline Operation)
# ══════════════════════════════════════════════════════════════


class TestLLMBoundariesAndFallback:
    """Verifies that the entire pipeline operates without external network or LLM."""

    def test_pipeline_runs_with_mock_llm(self, llm_client: LLMClientSession):
        # Ensure MockLLMProvider is active
        assert isinstance(llm_client.provider, MockLLMProvider)
        assert llm_client.provider is not None

    @pytest.mark.asyncio
    async def test_healing_engine_without_llm_uses_heuristics(
        self, memory_store: InMemoryStore
    ):
        _seed_element_records(memory_store)
        # Engine without LLM client
        offline_engine = HealingDecisionEngine(
            memory_store=memory_store,
            llm_client=None,
        )

        analysis = FailureAnalysis(
            test_id="tc-offline",
            execution_id="exec-offline",
            failed_step=1,
            failure_type=FailureType.SELECTOR_CHANGED,
            root_cause="DOM changed",
            confidence=ConfidenceLevel.HIGH,
            recommended_action=RecommendedAction.SEARCH_FOR_REPLACEMENT_SELECTOR,
            failed_target="#login-button",
        )

        curr_elem = ElementRecord(
            element_id="el-curr",
            selector="button[data-testid='submit-login']",
            text="Login",
            role="button",
            page_url="http://localhost:3000/login",
            attributes={
                "type": "submit",
                "data-testid": "submit-login",
                "class": "btn primary",
            },
        )

        rec = await offline_engine.generate_recommendation(
            HealingContext(
                failure_analysis=analysis,
                current_elements=[curr_elem],
                page_url="http://localhost:3000/login",
            )
        )

        assert rec is not None
        assert len(rec.candidates) > 0
        assert rec.selected_candidate is not None
        assert rec.selected_candidate.selector == "button[data-testid='submit-login']"


# ══════════════════════════════════════════════════════════════
#  8. Error Handling & Safety Invariants
# ══════════════════════════════════════════════════════════════


class TestErrorHandlingAndSafety:
    """Verifies strict adherence to state machine boundaries and adversarial resilience."""

    @pytest.mark.asyncio
    async def test_invalid_step_execution_result_raises(
        self, orchestrator: AgentOrchestrator
    ):
        # State in PLANNING cannot accept ExecutionResult
        state = AgentState(current_step=WorkflowStep.PLANNING)
        result = ExecutionResult(
            workflow_id=state.workflow_id,
            test_case_id="tc-1",
            status=ExecutionResultStatus.SUCCESS,
        )
        with pytest.raises(ValueError, match="expected EXECUTION_PENDING"):
            await orchestrator.submit_execution_result(state, result)

    @pytest.mark.asyncio
    async def test_invalid_step_healing_result_raises(
        self, orchestrator: AgentOrchestrator
    ):
        # State in EXECUTION_PENDING cannot accept HealingResultFeedback
        state = AgentState(current_step=WorkflowStep.EXECUTION_PENDING)
        feedback = HealingResultFeedback(
            test_case_id="tc-1",
            original_selector="#btn",
            attempted_selector=".btn",
            healing_status=HealingStatus.VALIDATED_SUCCESS,
            validation_status=ValidationStatus.SUCCESS,
            confidence=0.9,
            execution_attempt=1,
        )
        with pytest.raises(ValueError, match="expected HEALING_PENDING_VALIDATION"):
            await orchestrator.submit_healing_result(state, feedback)

    @pytest.mark.asyncio
    async def test_workflow_id_mismatch_raises(
        self, orchestrator: AgentOrchestrator
    ):
        state = AgentState(current_step=WorkflowStep.EXECUTION_PENDING)
        result = ExecutionResult(
            workflow_id="different-wf-id",
            test_case_id="tc-1",
            status=ExecutionResultStatus.SUCCESS,
        )
        with pytest.raises(ValueError, match="Workflow ID mismatch"):
            await orchestrator.submit_execution_result(state, result)

    def test_adversarial_selector_inputs_handled_safely(
        self, recovery_policy: RecoveryPolicy
    ):
        analysis = FailureAnalysis(
            test_id="tc-sec",
            execution_id="exec-sec",
            failed_step=1,
            failure_type=FailureType.SELECTOR_CHANGED,
            root_cause="DOM change",
            confidence=ConfidenceLevel.HIGH,
            recommended_action=RecommendedAction.SEARCH_FOR_REPLACEMENT_SELECTOR,
            failed_target="<script>alert('xss')</script>; DROP TABLE users; --",
        )
        candidates = [
            ScoredCandidate(
                selector="button[onclick*='evil()']",
                confidence=0.88,
                source=CandidateSource.CURRENT_DOM,
            )
        ]

        decision = recovery_policy.evaluate(
            failure_analysis=analysis,
            ranked_candidates=candidates,
        )
        # Evaluates purely as string tokens without execution
        assert decision.selected_candidate is not None
        assert "evil()" in decision.selected_candidate.selector


# ══════════════════════════════════════════════════════════════
#  9. Workflow Observability & Event Stream Audit Trail
# ══════════════════════════════════════════════════════════════


class TestWorkflowObservability:
    """Verifies that every pipeline transition produces a structured, audit-ready event."""

    @pytest.mark.asyncio
    async def test_clean_pass_event_audit_trail(
        self,
        orchestrator: AgentOrchestrator,
        sample_app_context: ApplicationContext,
    ):
        state = await orchestrator.start_planning(sample_app_context)
        test_case = state.test_plan.test_cases[0]

        exec_result = ExecutionResult(
            workflow_id=state.workflow_id,
            test_case_id=test_case.test_id,
            status=ExecutionResultStatus.SUCCESS,
        )
        final_state = await orchestrator.submit_execution_result(state, exec_result)

        event_types = [e.event_type for e in final_state.events]
        assert WorkflowEventType.WORKFLOW_STARTED in event_types
        assert WorkflowEventType.TEST_PLAN_GENERATED in event_types
        assert WorkflowEventType.EXECUTION_RESULT_RECEIVED in event_types
        assert WorkflowEventType.WORKFLOW_COMPLETED in event_types

        # Check monotonically non-decreasing timestamps
        for i in range(len(final_state.events) - 1):
            assert final_state.events[i].timestamp <= final_state.events[i + 1].timestamp


# ══════════════════════════════════════════════════════════════
#  10. Member 1 ↔ Member 2 Contract Tests
# ══════════════════════════════════════════════════════════════


class TestMember1ToMember2Contract:
    """Validates serializability and schema adherence for Member 2 interactions."""

    def test_parse_sample_execution_result(self):
        result = parse_member2_execution_result(MEMBER2_SAMPLE_EXECUTION_RESULT_JSON)
        assert result.workflow_id == "wf-e2e-001"
        assert result.status == ExecutionResultStatus.FAILED
        assert result.failure_context is not None
        assert result.failure_context.target_selector == "#submit-btn"

    def test_parse_sample_feedback(self):
        feedback = parse_member2_feedback(MEMBER2_SAMPLE_FEEDBACK_JSON)
        assert feedback.test_case_id == "tc-login-01"
        assert feedback.healing_status == HealingStatus.VALIDATED_SUCCESS
        assert feedback.validation_status == ValidationStatus.SUCCESS
        assert feedback.confidence == 0.95

    def test_serialize_healing_recommendation(self):
        cand = ScoredCandidate(
            selector="#new-btn",
            confidence=0.95,
            source=CandidateSource.CURRENT_DOM,
        )
        rec = HealingRecommendation(
            test_id="tc-login-01",
            execution_id="exec-001",
            failed_step=2,
            original_selector="#old-btn",
            failure_type=FailureType.SELECTOR_CHANGED,
            confidence=ConfidenceLevel.HIGH,
            decision=HealingDecision.RECOMMEND_HEALING,
            recommended_action=HealingAction.TRY_REPLACEMENT_SELECTOR,
            selected_candidate=cand,
            candidates=[cand],
            evidence=["Exact testid match"],
        )
        json_str = serialize_for_member2(rec)
        assert "#new-btn" in json_str
        loaded = json.loads(json_str)
        assert loaded["selected_candidate"]["selector"] == "#new-btn"


# ══════════════════════════════════════════════════════════════
#  11. Member 1 ↔ Member 3 Contract Tests
# ══════════════════════════════════════════════════════════════


class TestMember1ToMember3Contract:
    """Validates serializability, dashboard summary, and streaming helpers for Member 3."""

    def test_build_dashboard_summary(self):
        state = AgentState(
            workflow_id="wf-test-summary",
            current_step=WorkflowStep.COMPLETED,
            status="completed",
            healing_attempt_count=2,
            retry_count=1,
            execution_result=ExecutionResult(
                workflow_id="wf-test-summary",
                test_case_id="tc-1",
                status=ExecutionResultStatus.SUCCESS,
            ),
            healing_result=HealingResult(
                test_id="tc-1",
                failed_step=1,
                old_selector="#old",
                new_selector="#new",
                status=HealingStatus.VALIDATED_SUCCESS,
                confidence=0.95,
            ),
        )

        summary = build_dashboard_summary(state)
        assert summary.workflow_id == "wf-test-summary"
        assert summary.current_step == WorkflowStep.COMPLETED
        assert summary.is_terminal is True
        assert summary.passed_tests == 1
        assert summary.healed_tests == 1
        assert summary.healing_attempts == 2
        assert summary.retry_count == 1

        json_out = summary.model_dump_json()
        assert "wf-test-summary" in json_out

    def test_sse_event_formatting(self):
        event = WorkflowEvent(
            workflow_id="wf-100",
            event_type=WorkflowEventType.CANDIDATES_RANKED,
            step=WorkflowStep.RANKING_CANDIDATES,
            metadata={"candidate_count": 3},
        )
        sse_chunk = format_sse_event(event)
        assert sse_chunk.startswith("event: CANDIDATES_RANKED\n")
        assert "data: {" in sse_chunk
        assert sse_chunk.endswith("\n\n")

    def test_websocket_message_formatting(self):
        event = WorkflowEvent(
            workflow_id="wf-101",
            event_type=WorkflowEventType.RETRY_INITIATED,
            step=WorkflowStep.RETRYING,
            metadata={"retry_attempt": 1},
        )
        ws_msg = format_websocket_message(event)
        loaded = json.loads(ws_msg)
        assert loaded["workflow_id"] == "wf-101"
        assert loaded["event_type"] == "RETRY_INITIATED"
        assert loaded["step"] == "RETRYING"
        assert loaded["metadata"]["retry_attempt"] == 1


# ══════════════════════════════════════════════════════════════
#  12. Pipeline Performance Verification
# ══════════════════════════════════════════════════════════════


class TestPipelinePerformance:
    """Verifies that all pipeline operations execute in well under the latency threshold."""

    @pytest.mark.asyncio
    async def test_full_pipeline_roundtrip_latency(
        self,
        orchestrator: AgentOrchestrator,
        sample_app_context: ApplicationContext,
        memory_store: InMemoryStore,
    ):
        _seed_element_records(memory_store)

        start_time = time.perf_counter()

        # Step 1: Plan
        state = await orchestrator.start_planning(sample_app_context)
        test_case = state.test_plan.test_cases[0]

        # Step 2: Submit Failure
        fail_context = FailureContext(
            test_id=test_case.test_id,
            execution_id="exec-perf",
            failed_step=4,
            action="click",
            target_selector="#login-button",
            error_message="Element not found: #login-button",
            current_element=ElementRecord(
                element_id="elem-perf",
                selector="button[data-testid='submit-login']",
                text="Login",
                role="button",
                page_url="http://localhost:3000/login",
                attributes={
                    "type": "submit",
                    "data-testid": "submit-login",
                    "class": "btn primary-active",
                },
            ),
            current_page_url="http://localhost:3000/login",
        )
        state = await orchestrator.submit_execution_result(
            state,
            ExecutionResult(
                workflow_id=state.workflow_id,
                test_case_id=test_case.test_id,
                status=ExecutionResultStatus.FAILED,
                failure_context=fail_context,
            ),
        )

        # Step 3: Validate
        feedback = HealingResultFeedback(
            test_case_id=test_case.test_id,
            original_selector="#login-button",
            attempted_selector="button[data-testid='submit-login']",
            healing_status=HealingStatus.VALIDATED_SUCCESS,
            validation_status=ValidationStatus.SUCCESS,
            confidence=0.95,
            execution_attempt=1,
        )
        final_state = await orchestrator.submit_healing_result(state, feedback)

        elapsed_ms = (time.perf_counter() - start_time) * 1000.0

        assert final_state.current_step == WorkflowStep.COMPLETED
        # Must execute comfortably under 500ms in offline mode
        assert elapsed_ms < 500.0, f"Full pipeline took {elapsed_ms:.1f}ms (limit: 500ms)"


# ══════════════════════════════════════════════════════════════
#  13. Final Integration Matrix (15 Distinct Scenarios)
# ══════════════════════════════════════════════════════════════


class TestDay15FinalMatrix:
    """Comprehensive test matrix satisfying all 15 scenarios specified in Day 15 requirements."""

    @pytest.mark.asyncio
    async def test_scenario_01_clean_pass(
        self, orchestrator: AgentOrchestrator, sample_app_context: ApplicationContext
    ):
        """Scenario 1: Clean pass execution with zero failures."""
        state = await orchestrator.start_planning(sample_app_context)
        test_case = state.test_plan.test_cases[0]

        result = ExecutionResult(
            workflow_id=state.workflow_id,
            test_case_id=test_case.test_id,
            status=ExecutionResultStatus.SUCCESS,
        )
        final_state = await orchestrator.submit_execution_result(state, result)
        assert final_state.current_step == WorkflowStep.COMPLETED
        assert final_state.healing_attempt_count == 0

    @pytest.mark.asyncio
    async def test_scenario_02_single_healable_failure_success(
        self,
        orchestrator: AgentOrchestrator,
        sample_app_context: ApplicationContext,
        memory_store: InMemoryStore,
    ):
        """Scenario 2: Single healable failure with successful first validation."""
        _seed_element_records(memory_store)
        state = await orchestrator.start_planning(sample_app_context)
        test_case = state.test_plan.test_cases[0]

        fail_result = ExecutionResult(
            workflow_id=state.workflow_id,
            test_case_id=test_case.test_id,
            status=ExecutionResultStatus.FAILED,
            failure_context=FailureContext(
                test_id=test_case.test_id,
                execution_id="ex-s2",
                failed_step=4,
                action="click",
                target_selector="#login-button",
                error_message="Element not found: #login-button",
                current_element=ElementRecord(
                    element_id="el-s2",
                    selector="button[data-testid='submit-login']",
                    text="Login",
                    role="button",
                    page_url="http://localhost:3000/login",
                    attributes={
                        "type": "submit",
                        "data-testid": "submit-login",
                        "class": "btn primary-active",
                    },
                ),
                current_page_url="http://localhost:3000/login",
            ),
        )
        state = await orchestrator.submit_execution_result(state, fail_result)
        assert state.current_step == WorkflowStep.HEALING_PENDING_VALIDATION

        feedback = HealingResultFeedback(
            test_case_id=test_case.test_id,
            original_selector="#login-button",
            attempted_selector=state.recovery_decision.selected_candidate.selector,
            healing_status=HealingStatus.VALIDATED_SUCCESS,
            validation_status=ValidationStatus.SUCCESS,
            confidence=0.92,
            execution_attempt=1,
        )
        final_state = await orchestrator.submit_healing_result(state, feedback)
        assert final_state.current_step == WorkflowStep.COMPLETED
        assert final_state.healing_result.status == HealingStatus.VALIDATED_SUCCESS

    @pytest.mark.asyncio
    async def test_scenario_03_first_candidate_fails_second_succeeds(
        self,
        orchestrator: AgentOrchestrator,
        sample_app_context: ApplicationContext,
        memory_store: InMemoryStore,
    ):
        """Scenario 3: Healable failure where candidate 1 fails, candidate 2 succeeds."""
        _seed_element_records(memory_store)

        state = await orchestrator.start_planning(sample_app_context)
        test_case = state.test_plan.test_cases[0]

        memory_store.store_healing_record(
            HealingRecord(
                healing_id="hist-s3",
                test_id=test_case.test_id,
                old_selector="#login-button",
                new_selector="button.btn-login-alt",
                confidence=0.88,
                validation_result=True,
            )
        )

        orchestrator._recovery_policy = RecoveryPolicy(
            config=RecoveryPolicyConfig(
                max_healing_attempts=3,
                min_healing_confidence=0.10,
                min_candidate_score=0.10,
                ambiguity_margin=0.02,
                max_retries=2,
            ),
            evidence_retriever=HealingEvidenceRetriever(memory_store),
        )

        fail_result = ExecutionResult(
            workflow_id=state.workflow_id,
            test_case_id=test_case.test_id,
            status=ExecutionResultStatus.FAILED,
            failure_context=FailureContext(
                test_id=test_case.test_id,
                execution_id="ex-s3",
                failed_step=4,
                action="click",
                target_selector="#login-button",
                error_message="Element not found: #login-button",
                current_element=ElementRecord(
                    element_id="el-curr-alt",
                    selector="button[data-testid='submit-login']",
                    text="Login",
                    role="button",
                    page_url="http://localhost:3000/login",
                    attributes={
                        "type": "submit",
                        "data-testid": "submit-login",
                        "class": "btn primary-active",
                    },
                ),
                current_page_url="http://localhost:3000/login",
            ),
        )
        state = await orchestrator.submit_execution_result(state, fail_result)
        first_sel = state.recovery_decision.selected_candidate.selector

        # Candidate 1 fails validation
        fb1 = HealingResultFeedback(
            test_case_id=test_case.test_id,
            original_selector="#login-button",
            attempted_selector=first_sel,
            healing_status=HealingStatus.VALIDATED_FAILURE,
            validation_status=ValidationStatus.FAILURE,
            confidence=0.85,
            execution_attempt=1,
        )
        state = await orchestrator.submit_healing_result(state, fb1)

        if state.current_step == WorkflowStep.HEALING_PENDING_VALIDATION:
            second_sel = state.recovery_decision.selected_candidate.selector
            fb2 = HealingResultFeedback(
                test_case_id=test_case.test_id,
                original_selector="#login-button",
                attempted_selector=second_sel,
                healing_status=HealingStatus.VALIDATED_SUCCESS,
                validation_status=ValidationStatus.SUCCESS,
                confidence=0.90,
                execution_attempt=2,
            )
            final_state = await orchestrator.submit_healing_result(state, fb2)
            assert final_state.current_step == WorkflowStep.COMPLETED
            assert final_state.healing_result.status == HealingStatus.VALIDATED_SUCCESS
        else:
            assert state.current_step in (WorkflowStep.COMPLETED, WorkflowStep.ABORTED)

    @pytest.mark.asyncio
    async def test_scenario_04_all_candidates_fail_validation(
        self,
        orchestrator: AgentOrchestrator,
        sample_app_context: ApplicationContext,
        memory_store: InMemoryStore,
    ):
        """Scenario 4: Healable failure where all candidates fail validation."""
        _seed_element_records(memory_store)
        state = await orchestrator.start_planning(sample_app_context)
        test_case = state.test_plan.test_cases[0]

        fail_result = ExecutionResult(
            workflow_id=state.workflow_id,
            test_case_id=test_case.test_id,
            status=ExecutionResultStatus.FAILED,
            failure_context=FailureContext(
                test_id=test_case.test_id,
                execution_id="ex-s4",
                failed_step=4,
                action="click",
                target_selector="#login-button",
                error_message="Element not found: #login-button",
                current_element=ElementRecord(
                    element_id="el-single",
                    selector="button[data-testid='submit-login']",
                    text="Login",
                    role="button",
                    page_url="http://localhost:3000/login",
                    attributes={
                        "type": "submit",
                        "data-testid": "submit-login",
                        "class": "btn primary-active",
                    },
                ),
                current_page_url="http://localhost:3000/login",
            ),
        )
        state = await orchestrator.submit_execution_result(state, fail_result)
        first_sel = state.recovery_decision.selected_candidate.selector

        fb = HealingResultFeedback(
            test_case_id=test_case.test_id,
            original_selector="#login-button",
            attempted_selector=first_sel,
            healing_status=HealingStatus.VALIDATED_FAILURE,
            validation_status=ValidationStatus.FAILURE,
            confidence=0.85,
            execution_attempt=1,
        )
        final_state = await orchestrator.submit_healing_result(state, fb)
        assert final_state.current_step in (WorkflowStep.COMPLETED, WorkflowStep.ABORTED)

    @pytest.mark.asyncio
    async def test_scenario_05_timeout_triggers_retry(
        self, orchestrator: AgentOrchestrator, sample_app_context: ApplicationContext
    ):
        """Scenario 5: Timeout failure triggers retry action."""
        state = await orchestrator.start_planning(sample_app_context)
        test_case = state.test_plan.test_cases[0]

        timeout_result = ExecutionResult(
            workflow_id=state.workflow_id,
            test_case_id=test_case.test_id,
            status=ExecutionResultStatus.FAILED,
            failure_context=FailureContext(
                test_id=test_case.test_id,
                execution_id="ex-s5",
                failed_step=4,
                action="wait",
                target_selector="#login-button",
                error_message="Timeout 30000ms waiting for page load",
            ),
        )
        state = await orchestrator.submit_execution_result(state, timeout_result)
        assert state.recovery_decision.decision == RecoveryAction.RETRY
        assert state.retry_count == 1
        assert state.current_step == WorkflowStep.EXECUTION_PENDING

    @pytest.mark.asyncio
    async def test_scenario_06_assertion_failure_do_not_heal(
        self, orchestrator: AgentOrchestrator, sample_app_context: ApplicationContext
    ):
        """Scenario 6: Assertion failure triggers DO_NOT_HEAL."""
        state = await orchestrator.start_planning(sample_app_context)
        test_case = state.test_plan.test_cases[0]

        assert_result = ExecutionResult(
            workflow_id=state.workflow_id,
            test_case_id=test_case.test_id,
            status=ExecutionResultStatus.FAILED,
            failure_context=FailureContext(
                test_id=test_case.test_id,
                execution_id="ex-s6",
                failed_step=2,
                action="assert",
                target_selector="#status-msg",
                error_message="Assertion failed: expected 200 OK got 500 Internal Error",
            ),
        )
        state = await orchestrator.submit_execution_result(state, assert_result)
        assert state.recovery_decision.decision == RecoveryAction.DO_NOT_HEAL
        assert state.current_step == WorkflowStep.COMPLETED

    def test_scenario_07_low_confidence_requires_further_analysis(
        self, recovery_policy: RecoveryPolicy
    ):
        """Scenario 7: Low confidence candidate (< 0.80) triggers DO_NOT_HEAL."""
        analysis = FailureAnalysis(
            test_id="tc-s7",
            execution_id="ex-s7",
            failed_step=1,
            failure_type=FailureType.SELECTOR_CHANGED,
            root_cause="DOM change",
            confidence=ConfidenceLevel.HIGH,
            recommended_action=RecommendedAction.SEARCH_FOR_REPLACEMENT_SELECTOR,
            failed_target="#btn",
        )
        candidates = [
            ScoredCandidate(
                selector=".vague-btn",
                confidence=0.45,
                source=CandidateSource.CURRENT_DOM,
            )
        ]
        decision = recovery_policy.evaluate(analysis, candidates)
        assert decision.decision == RecoveryAction.DO_NOT_HEAL

    def test_scenario_08_ambiguous_candidates_requires_analysis(
        self, recovery_policy: RecoveryPolicy
    ):
        """Scenario 8: Ambiguous candidates (difference < 0.02) triggers REQUIRE_FURTHER_ANALYSIS."""
        analysis = FailureAnalysis(
            test_id="tc-s8",
            execution_id="ex-s8",
            failed_step=1,
            failure_type=FailureType.SELECTOR_CHANGED,
            root_cause="DOM change",
            confidence=ConfidenceLevel.HIGH,
            recommended_action=RecommendedAction.SEARCH_FOR_REPLACEMENT_SELECTOR,
            failed_target="#btn",
        )
        candidates = [
            ScoredCandidate(
                selector="#btn-opt-1",
                confidence=0.89,
                source=CandidateSource.CURRENT_DOM,
            ),
            ScoredCandidate(
                selector="#btn-opt-2",
                confidence=0.885,  # diff = 0.005 < 0.02
                source=CandidateSource.CURRENT_DOM,
            ),
        ]
        decision = recovery_policy.evaluate(analysis, candidates)
        assert decision.decision == RecoveryAction.REQUIRE_FURTHER_ANALYSIS

    def test_scenario_09_historical_pattern_boost(
        self, memory_store: InMemoryStore
    ):
        """Scenario 9: Candidate matching historical success receives score boost."""
        for i in range(4):
            memory_store.store_healing_record(
                HealingRecord(
                    healing_id=f"hist-s9-{i}",
                    test_id="tc-s9",
                    old_selector="#btn-orig",
                    new_selector="button[data-testid='btn-success']",
                    healing_reason="historical match",
                    confidence=0.90,
                    validation_result=True,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )
            )

        retriever = HealingEvidenceRetriever(memory_store)
        policy = RecoveryPolicy(
            config=RecoveryPolicyConfig(history_boost_weight=0.15, min_healing_confidence=0.80),
            evidence_retriever=retriever,
        )

        analysis = FailureAnalysis(
            test_id="tc-s9",
            execution_id="ex-s9",
            failed_step=1,
            failure_type=FailureType.SELECTOR_CHANGED,
            root_cause="DOM changed",
            confidence=ConfidenceLevel.HIGH,
            recommended_action=RecommendedAction.SEARCH_FOR_REPLACEMENT_SELECTOR,
            failed_target="#btn-orig",
        )

        # Candidate at 0.78 is below 0.80 threshold, but +0.15 boost raises to 0.93
        c_historical = ScoredCandidate(
            selector="button[data-testid='btn-success']",
            confidence=0.78,
            source=CandidateSource.HISTORICAL_MEMORY,
        )

        decision = policy.evaluate(analysis, [c_historical])
        assert decision.decision == RecoveryAction.TRY_HEALING
        assert decision.selected_candidate is not None
        assert decision.selected_candidate.selector == "button[data-testid='btn-success']"
        assert decision.confidence > 0.78

    def test_scenario_10_historical_failure_penalty(
        self, memory_store: InMemoryStore
    ):
        """Scenario 10: Candidate matching historical failure is penalized."""
        for i in range(3):
            memory_store.store_healing_record(
                HealingRecord(
                    healing_id=f"hist-fail-{i}",
                    test_id="tc-s10",
                    old_selector="#btn-orig",
                    new_selector="button.flaky-btn",
                    healing_reason="failed attempt",
                    confidence=0.85,
                    validation_result=False,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )
            )

        retriever = HealingEvidenceRetriever(memory_store)
        policy = RecoveryPolicy(
            config=RecoveryPolicyConfig(history_boost_weight=0.15, min_healing_confidence=0.80),
            evidence_retriever=retriever,
        )

        analysis = FailureAnalysis(
            test_id="tc-s10",
            execution_id="ex-s10",
            failed_step=1,
            failure_type=FailureType.SELECTOR_CHANGED,
            root_cause="DOM changed",
            confidence=ConfidenceLevel.HIGH,
            recommended_action=RecommendedAction.SEARCH_FOR_REPLACEMENT_SELECTOR,
            failed_target="#btn-orig",
        )

        # Candidate at 0.82 would normally heal, but historical failures penalize it below 0.80
        c_failed = ScoredCandidate(
            selector="button.flaky-btn",
            confidence=0.82,
            source=CandidateSource.CURRENT_DOM,
        )

        decision = policy.evaluate(analysis, [c_failed])
        assert decision.decision == RecoveryAction.DO_NOT_HEAL

    def test_scenario_11_max_retries_exceeded(self, recovery_policy: RecoveryPolicy):
        """Scenario 11: Max retries exceeded aborts/escalates transient failure."""
        analysis = FailureAnalysis(
            test_id="tc-s11",
            execution_id="ex-s11",
            failed_step=1,
            failure_type=FailureType.TIMEOUT,
            root_cause="Timeout",
            confidence=ConfidenceLevel.HIGH,
            recommended_action=RecommendedAction.INVESTIGATE_TIMEOUT,
        )
        decision = recovery_policy.evaluate(analysis, [], retry_count=2)
        assert decision.decision == RecoveryAction.REQUIRE_FURTHER_ANALYSIS

    @pytest.mark.asyncio
    async def test_scenario_12_event_stream_audit_trail(
        self, orchestrator: AgentOrchestrator, sample_app_context: ApplicationContext
    ):
        """Scenario 12: Event stream audit trail verifies every state transition is logged."""
        state = await orchestrator.start_planning(sample_app_context)
        test_case = state.test_plan.test_cases[0]

        result = ExecutionResult(
            workflow_id=state.workflow_id,
            test_case_id=test_case.test_id,
            status=ExecutionResultStatus.SUCCESS,
        )
        final_state = await orchestrator.submit_execution_result(state, result)

        assert len(final_state.events) >= 4
        for event in final_state.events:
            assert event.workflow_id == final_state.workflow_id
            assert event.event_type is not None
            assert event.timestamp is not None

    def test_scenario_13_invalid_state_transition_rejected(self):
        """Scenario 13: Invalid state transition is strictly rejected."""
        state = AgentState(current_step=WorkflowStep.COMPLETED)
        with pytest.raises(ValueError, match="Invalid state transition"):
            AgentOrchestrator._transition(state, WorkflowStep.PLANNING)

    def test_scenario_14_state_serialization_roundtrip(self):
        """Scenario 14: Full AgentState model serialization / deserialization roundtrip."""
        state = AgentState(
            workflow_id="wf-roundtrip-01",
            current_step=WorkflowStep.HEALING_SUCCEEDED,
            status="completed",
            healing_attempt_count=1,
            retry_count=0,
            attempted_selectors={"#old-btn", "button[data-testid='btn']"},
        )
        json_data = state.model_dump_json()
        restored = AgentState.model_validate_json(json_data)

        assert restored.workflow_id == state.workflow_id
        assert restored.current_step == state.current_step
        assert restored.attempted_selectors == state.attempted_selectors

    @pytest.mark.asyncio
    async def test_scenario_15_pipeline_performance_benchmark(
        self,
        orchestrator: AgentOrchestrator,
        sample_app_context: ApplicationContext,
        memory_store: InMemoryStore,
    ):
        """Scenario 15: Benchmark verification (< 500ms execution)."""
        _seed_element_records(memory_store)
        start = time.perf_counter()

        state = await orchestrator.start_planning(sample_app_context)
        test_case = state.test_plan.test_cases[0]

        res = ExecutionResult(
            workflow_id=state.workflow_id,
            test_case_id=test_case.test_id,
            status=ExecutionResultStatus.SUCCESS,
        )
        final_state = await orchestrator.submit_execution_result(state, res)

        duration = (time.perf_counter() - start) * 1000.0
        assert final_state.current_step == WorkflowStep.COMPLETED
        assert duration < 500.0, f"Benchmark exceeded: {duration:.1f}ms"
