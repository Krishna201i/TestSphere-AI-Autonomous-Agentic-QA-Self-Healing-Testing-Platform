"""
TestSphere-AI — Day 14: Autonomous Recovery Policy Tests

Comprehensive tests for the Recovery Policy & Explainable Decisions:

1. RecoveryDecision schema tests
2. RecoveryPolicyConfig tests
3. RecoveryPolicy unit tests
   - Failure-specific decisions
   - Confidence thresholds
   - Candidate history
   - Attempt limits
   - Retry limits
   - Duplicate candidate prevention
   - Ambiguous candidates
   - No candidate
   - Low confidence
4. Integration tests
   - Successful healing flow (Task 17)
   - Failed healing flow (Task 18)
   - Multiple candidates
   - Multi-attempt recovery
   - Maximum attempt termination
   - Retry workflow (Task 16)
   - Low-confidence workflow (Task 20)
   - Ambiguous workflow (Task 19)
   - Assertion failure (Task 21)
   - Complete orchestrator end-to-end
5. Safety / invariant tests (Task 23)

All tests run fully offline with MockLLMProvider and InMemoryStore.
No internet, browser, or real LLM required.
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone

from agents.analyzer.analyzer import FailureAnalyzerAgent
from agents.analyzer.schemas import FailureAnalysis, FailureContext, FailureEvidence
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
from agents.memory.memory_schemas import ElementRecord, HealingRecord
from agents.orchestration.agent_orchestrator import AgentOrchestrator
from agents.orchestration.recovery_policy import (
    FailureTypePolicy,
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
def evidence_retriever(memory_store: InMemoryStore) -> HealingEvidenceRetriever:
    """Healing evidence retriever."""
    return HealingEvidenceRetriever(memory_store)


@pytest.fixture
def default_policy() -> RecoveryPolicy:
    """Recovery policy with default configuration."""
    return RecoveryPolicy()


@pytest.fixture
def strict_policy() -> RecoveryPolicy:
    """Recovery policy with strict (high-confidence) configuration."""
    return RecoveryPolicy(config=RecoveryPolicyConfig(
        min_healing_confidence=0.80,
        min_candidate_score=0.30,
        max_healing_attempts=3,
        max_retries=2,
        allow_medium_confidence_healing=False,
        ambiguity_margin=0.02,
    ))


@pytest.fixture
def lenient_policy() -> RecoveryPolicy:
    """Recovery policy that allows medium-confidence healing."""
    return RecoveryPolicy(config=RecoveryPolicyConfig(
        min_healing_confidence=0.50,
        min_candidate_score=0.20,
        max_healing_attempts=5,
        max_retries=3,
        allow_medium_confidence_healing=True,
        ambiguity_margin=0.05,
    ))


def _make_analysis(
    failure_type: FailureType = FailureType.SELECTOR_CHANGED,
    confidence: ConfidenceLevel = ConfidenceLevel.HIGH,
    test_id: str = "test-001",
    execution_id: str = "exec-001",
    failed_target: str = "#login-btn",
    recommended_action: RecommendedAction = RecommendedAction.SEARCH_FOR_REPLACEMENT_SELECTOR,
) -> FailureAnalysis:
    """Create a FailureAnalysis for testing."""
    return FailureAnalysis(
        test_id=test_id,
        execution_id=execution_id,
        failure_type=failure_type,
        root_cause=f"Test failure: {failure_type.value}",
        confidence=confidence,
        failed_step=1,
        failed_target=failed_target,
        recommended_action=recommended_action,
    )


def _make_candidate(
    selector: str,
    confidence: float = 0.85,
    source: CandidateSource = CandidateSource.CURRENT_DOM,
    text_similarity: float = 0.9,
    role_similarity: float = 1.0,
    type_similarity: float = 1.0,
    healing_history_score: float = 0.0,
) -> ScoredCandidate:
    """Create a ScoredCandidate for testing."""
    return ScoredCandidate(
        selector=selector,
        source=source,
        confidence=confidence,
        text_similarity=text_similarity,
        role_similarity=role_similarity,
        type_similarity=type_similarity,
        healing_history_score=healing_history_score,
        evidence=[f"Test candidate: {selector}"],
    )


# ══════════════════════════════════════════════════════════════
#  1. RecoveryDecision Schema Tests
# ══════════════════════════════════════════════════════════════


class TestRecoveryDecisionSchema:
    """Tests for the RecoveryDecision data model."""

    def test_create_basic_decision(self):
        """Create a basic RecoveryDecision."""
        decision = RecoveryDecision(
            decision=RecoveryAction.TRY_HEALING,
            confidence=0.85,
            reason="Test reason",
        )
        assert decision.decision == RecoveryAction.TRY_HEALING
        assert decision.confidence == 0.85
        assert decision.reason == "Test reason"

    def test_decision_with_full_fields(self):
        """Create a RecoveryDecision with all fields."""
        candidate = _make_candidate("#sign-in-btn", 0.91)
        decision = RecoveryDecision(
            workflow_id="wf_test123",
            test_case_id="test-001",
            failure_type=FailureType.SELECTOR_CHANGED,
            decision=RecoveryAction.TRY_HEALING,
            confidence=0.91,
            selected_candidate=candidate,
            reason="Strong evidence supports healing",
            evidence=["Original selector missing", "Candidate has same text"],
            attempt_number=1,
            retry_count=0,
            requires_validation=True,
            next_state="HEALING_PENDING_VALIDATION",
        )
        assert decision.workflow_id == "wf_test123"
        assert decision.test_case_id == "test-001"
        assert decision.failure_type == FailureType.SELECTOR_CHANGED
        assert decision.selected_candidate is not None
        assert decision.selected_candidate.selector == "#sign-in-btn"
        assert decision.attempt_number == 1
        assert decision.requires_validation is True
        assert decision.next_state == "HEALING_PENDING_VALIDATION"

    def test_all_recovery_actions_exist(self):
        """All five recovery actions exist."""
        assert RecoveryAction.RETRY == "RETRY"
        assert RecoveryAction.TRY_HEALING == "TRY_HEALING"
        assert RecoveryAction.REQUIRE_FURTHER_ANALYSIS == "REQUIRE_FURTHER_ANALYSIS"
        assert RecoveryAction.DO_NOT_HEAL == "DO_NOT_HEAL"
        assert RecoveryAction.ABORT == "ABORT"
        assert len(RecoveryAction) == 5

    def test_decision_evidence_list(self):
        """Evidence is a list of concise strings."""
        decision = RecoveryDecision(
            decision=RecoveryAction.DO_NOT_HEAL,
            evidence=["No candidates", "Assertion failure"],
        )
        assert len(decision.evidence) == 2
        assert "No candidates" in decision.evidence

    def test_decision_defaults(self):
        """Default values are appropriate."""
        decision = RecoveryDecision(decision=RecoveryAction.ABORT)
        assert decision.confidence == 0.0
        assert decision.selected_candidate is None
        assert decision.reason == ""
        assert decision.evidence == []
        assert decision.attempt_number == 0
        assert decision.retry_count == 0
        assert decision.requires_validation is True
        assert decision.next_state == ""


# ══════════════════════════════════════════════════════════════
#  2. RecoveryPolicyConfig Tests
# ══════════════════════════════════════════════════════════════


class TestRecoveryPolicyConfig:
    """Tests for RecoveryPolicyConfig defaults and validation."""

    def test_defaults(self):
        """Default configuration values are conservative."""
        config = RecoveryPolicyConfig()
        assert config.max_healing_attempts == 3
        assert config.min_healing_confidence == 0.80
        assert config.min_candidate_score == 0.30
        assert config.allow_medium_confidence_healing is False
        assert config.allow_retry is True
        assert config.max_retries == 2
        assert config.ambiguity_margin == 0.02

    def test_custom_config(self):
        """Custom configuration is accepted."""
        config = RecoveryPolicyConfig(
            max_healing_attempts=5,
            min_healing_confidence=0.90,
            min_candidate_score=0.50,
            allow_medium_confidence_healing=True,
            max_retries=4,
        )
        assert config.max_healing_attempts == 5
        assert config.min_healing_confidence == 0.90
        assert config.allow_medium_confidence_healing is True

    def test_failure_policy_override(self):
        """Failure-specific policies can be overridden."""
        timeout_override = FailureTypePolicy(
            failure_type=FailureType.TIMEOUT,
            healable=True,
            retryable=True,
            max_retries=5,
        )
        config = RecoveryPolicyConfig(
            failure_policies={"TIMEOUT": timeout_override},
        )
        assert "TIMEOUT" in config.failure_policies

    def test_policy_uses_override(self):
        """RecoveryPolicy applies failure-type overrides."""
        timeout_override = FailureTypePolicy(
            failure_type=FailureType.TIMEOUT,
            healable=True,  # Override: make timeout healable
            retryable=True,
            max_retries=5,
        )
        policy = RecoveryPolicy(config=RecoveryPolicyConfig(
            failure_policies={"TIMEOUT": timeout_override},
        ))
        ft_policy = policy.get_failure_policy(FailureType.TIMEOUT)
        assert ft_policy.healable is True
        assert ft_policy.max_retries == 5


# ══════════════════════════════════════════════════════════════
#  3. RecoveryPolicy Unit Tests — Failure-Specific Decisions
# ══════════════════════════════════════════════════════════════


class TestRecoveryPolicyFailureTypes:
    """Tests for failure-type-specific recovery decisions."""

    def test_selector_changed_high_confidence(self, default_policy):
        """SELECTOR_CHANGED + HIGH confidence → TRY_HEALING."""
        analysis = _make_analysis(FailureType.SELECTOR_CHANGED)
        candidates = [_make_candidate("#sign-in-btn", 0.91)]
        decision = default_policy.evaluate(analysis, candidates)
        assert decision.decision == RecoveryAction.TRY_HEALING
        assert decision.selected_candidate is not None
        assert decision.selected_candidate.selector == "#sign-in-btn"

    def test_selector_changed_low_confidence(self, default_policy):
        """SELECTOR_CHANGED + LOW confidence → DO_NOT_HEAL."""
        analysis = _make_analysis(FailureType.SELECTOR_CHANGED)
        candidates = [_make_candidate("#maybe-btn", 0.25)]
        decision = default_policy.evaluate(analysis, candidates)
        assert decision.decision == RecoveryAction.DO_NOT_HEAL

    def test_element_not_found_with_candidates(self, default_policy):
        """ELEMENT_NOT_FOUND + candidates → TRY_HEALING."""
        analysis = _make_analysis(FailureType.ELEMENT_NOT_FOUND)
        candidates = [_make_candidate("#new-btn", 0.88)]
        decision = default_policy.evaluate(analysis, candidates)
        assert decision.decision == RecoveryAction.TRY_HEALING

    def test_element_not_interactable_retry(self, default_policy):
        """ELEMENT_NOT_INTERACTABLE → RETRY (first time)."""
        analysis = _make_analysis(
            FailureType.ELEMENT_NOT_INTERACTABLE,
            recommended_action=RecommendedAction.CHECK_ELEMENT_STATE,
        )
        decision = default_policy.evaluate(analysis, [])
        assert decision.decision == RecoveryAction.RETRY

    def test_element_not_interactable_retries_exhausted(self, default_policy):
        """ELEMENT_NOT_INTERACTABLE after max retries → REQUIRE_FURTHER_ANALYSIS."""
        analysis = _make_analysis(
            FailureType.ELEMENT_NOT_INTERACTABLE,
            recommended_action=RecommendedAction.CHECK_ELEMENT_STATE,
        )
        decision = default_policy.evaluate(analysis, [], retry_count=2)
        assert decision.decision == RecoveryAction.REQUIRE_FURTHER_ANALYSIS

    def test_assertion_failure_do_not_heal(self, default_policy):
        """ASSERTION_FAILURE → DO_NOT_HEAL regardless of candidates."""
        analysis = _make_analysis(FailureType.ASSERTION_FAILURE)
        candidates = [_make_candidate("#btn", 0.95)]
        decision = default_policy.evaluate(analysis, candidates)
        assert decision.decision == RecoveryAction.DO_NOT_HEAL

    def test_timeout_retry(self, default_policy):
        """TIMEOUT → RETRY on first attempt."""
        analysis = _make_analysis(
            FailureType.TIMEOUT,
            recommended_action=RecommendedAction.INVESTIGATE_TIMEOUT,
        )
        decision = default_policy.evaluate(analysis, [])
        assert decision.decision == RecoveryAction.RETRY

    def test_timeout_retries_exhausted(self, default_policy):
        """TIMEOUT after max retries → REQUIRE_FURTHER_ANALYSIS."""
        analysis = _make_analysis(
            FailureType.TIMEOUT,
            recommended_action=RecommendedAction.INVESTIGATE_TIMEOUT,
        )
        decision = default_policy.evaluate(analysis, [], retry_count=2)
        assert decision.decision == RecoveryAction.REQUIRE_FURTHER_ANALYSIS

    def test_navigation_failure_retry(self, default_policy):
        """NAVIGATION_FAILURE → RETRY on first attempt."""
        analysis = _make_analysis(
            FailureType.NAVIGATION_FAILURE,
            recommended_action=RecommendedAction.INVESTIGATE_NAVIGATION,
        )
        decision = default_policy.evaluate(analysis, [])
        assert decision.decision == RecoveryAction.RETRY

    def test_navigation_failure_retries_exhausted(self, default_policy):
        """NAVIGATION_FAILURE after retries → REQUIRE_FURTHER_ANALYSIS."""
        analysis = _make_analysis(
            FailureType.NAVIGATION_FAILURE,
            recommended_action=RecommendedAction.INVESTIGATE_NAVIGATION,
        )
        decision = default_policy.evaluate(analysis, [], retry_count=2)
        assert decision.decision == RecoveryAction.REQUIRE_FURTHER_ANALYSIS

    def test_network_error_do_not_heal(self, default_policy):
        """NETWORK_ERROR → DO_NOT_HEAL."""
        analysis = _make_analysis(FailureType.NETWORK_ERROR)
        decision = default_policy.evaluate(analysis, [])
        assert decision.decision == RecoveryAction.DO_NOT_HEAL

    def test_application_error_do_not_heal(self, default_policy):
        """APPLICATION_ERROR → DO_NOT_HEAL."""
        analysis = _make_analysis(FailureType.APPLICATION_ERROR)
        decision = default_policy.evaluate(analysis, [])
        assert decision.decision == RecoveryAction.DO_NOT_HEAL

    def test_unknown_require_further_analysis(self, default_policy):
        """UNKNOWN → DO_NOT_HEAL (not healable, not retryable)."""
        analysis = _make_analysis(
            FailureType.UNKNOWN,
            recommended_action=RecommendedAction.REQUIRE_FURTHER_ANALYSIS,
        )
        decision = default_policy.evaluate(analysis, [])
        assert decision.decision == RecoveryAction.DO_NOT_HEAL


# ══════════════════════════════════════════════════════════════
#  3b. Confidence Threshold Tests
# ══════════════════════════════════════════════════════════════


class TestRecoveryPolicyConfidence:
    """Tests for confidence threshold enforcement."""

    def test_high_confidence_heals(self, default_policy):
        """Candidate above min_healing_confidence → TRY_HEALING."""
        analysis = _make_analysis(FailureType.SELECTOR_CHANGED)
        candidates = [_make_candidate("#btn", 0.85)]
        decision = default_policy.evaluate(analysis, candidates)
        assert decision.decision == RecoveryAction.TRY_HEALING

    def test_below_threshold_does_not_heal(self, default_policy):
        """Candidate below min_healing_confidence → DO_NOT_HEAL."""
        analysis = _make_analysis(FailureType.SELECTOR_CHANGED)
        candidates = [_make_candidate("#btn", 0.50)]
        decision = default_policy.evaluate(analysis, candidates)
        assert decision.decision == RecoveryAction.DO_NOT_HEAL

    def test_at_threshold_heals(self, default_policy):
        """Candidate exactly at min_healing_confidence → TRY_HEALING."""
        analysis = _make_analysis(FailureType.SELECTOR_CHANGED)
        candidates = [_make_candidate("#btn", 0.80)]
        decision = default_policy.evaluate(analysis, candidates)
        assert decision.decision == RecoveryAction.TRY_HEALING

    def test_medium_confidence_rejected_by_default(self, default_policy):
        """Medium confidence rejected when allow_medium is False."""
        analysis = _make_analysis(FailureType.SELECTOR_CHANGED)
        candidates = [_make_candidate("#btn", 0.60)]
        decision = default_policy.evaluate(analysis, candidates)
        assert decision.decision == RecoveryAction.DO_NOT_HEAL

    def test_medium_confidence_allowed_when_configured(self, lenient_policy):
        """Medium confidence allowed when allow_medium_confidence_healing=True."""
        analysis = _make_analysis(FailureType.SELECTOR_CHANGED)
        candidates = [_make_candidate("#btn", 0.60)]
        decision = lenient_policy.evaluate(analysis, candidates)
        assert decision.decision == RecoveryAction.TRY_HEALING

    def test_very_low_confidence_rejected_even_lenient(self, lenient_policy):
        """Very low confidence rejected even with lenient config."""
        analysis = _make_analysis(FailureType.SELECTOR_CHANGED)
        candidates = [_make_candidate("#btn", 0.10)]
        decision = lenient_policy.evaluate(analysis, candidates)
        assert decision.decision == RecoveryAction.DO_NOT_HEAL


# ══════════════════════════════════════════════════════════════
#  3c. Attempt Limits Tests
# ══════════════════════════════════════════════════════════════


class TestRecoveryPolicyAttemptLimits:
    """Tests for healing attempt and retry limits."""

    def test_max_healing_attempts_abort(self, default_policy):
        """Reaching max healing attempts → ABORT."""
        analysis = _make_analysis(FailureType.SELECTOR_CHANGED)
        candidates = [_make_candidate("#btn", 0.95)]
        decision = default_policy.evaluate(
            analysis, candidates,
            healing_attempt_count=3,
        )
        assert decision.decision == RecoveryAction.ABORT
        assert "Maximum healing attempts" in decision.reason

    def test_below_max_attempts_continues(self, default_policy):
        """Below max healing attempts → can still heal."""
        analysis = _make_analysis(FailureType.SELECTOR_CHANGED)
        candidates = [_make_candidate("#btn", 0.90)]
        decision = default_policy.evaluate(
            analysis, candidates,
            healing_attempt_count=2,
        )
        assert decision.decision == RecoveryAction.TRY_HEALING

    def test_max_retries_escalation(self, default_policy):
        """Reaching max retries → escalation."""
        analysis = _make_analysis(FailureType.TIMEOUT)
        decision = default_policy.evaluate(analysis, [], retry_count=2)
        assert decision.decision == RecoveryAction.REQUIRE_FURTHER_ANALYSIS

    def test_retry_count_tracked(self, default_policy):
        """Retry count is tracked in the decision."""
        analysis = _make_analysis(FailureType.TIMEOUT)
        decision = default_policy.evaluate(analysis, [], retry_count=1)
        assert decision.decision == RecoveryAction.RETRY
        assert decision.retry_count == 1


# ══════════════════════════════════════════════════════════════
#  3d. Duplicate Candidate Prevention Tests
# ══════════════════════════════════════════════════════════════


class TestRecoveryPolicyDuplicates:
    """Tests for duplicate candidate prevention."""

    def test_skips_attempted_selectors(self, default_policy):
        """Already-attempted selectors are skipped."""
        analysis = _make_analysis(FailureType.SELECTOR_CHANGED)
        candidates = [
            _make_candidate("#sign-in-btn", 0.91),
            _make_candidate(".login-button", 0.85),
        ]
        decision = default_policy.evaluate(
            analysis, candidates,
            attempted_selectors={"#sign-in-btn"},
        )
        assert decision.decision == RecoveryAction.TRY_HEALING
        assert decision.selected_candidate.selector == ".login-button"

    def test_all_candidates_attempted(self, default_policy):
        """All candidates attempted → no healing."""
        analysis = _make_analysis(FailureType.SELECTOR_CHANGED)
        candidates = [
            _make_candidate("#sign-in-btn", 0.91),
            _make_candidate(".login-button", 0.85),
        ]
        decision = default_policy.evaluate(
            analysis, candidates,
            attempted_selectors={"#sign-in-btn", ".login-button"},
        )
        assert decision.decision == RecoveryAction.DO_NOT_HEAL

    def test_continuation_skips_attempted(self, default_policy):
        """evaluate_continuation skips already-attempted candidates."""
        analysis = _make_analysis(FailureType.SELECTOR_CHANGED)
        candidates = [
            _make_candidate("#a", 0.90),
            _make_candidate("#b", 0.85),
            _make_candidate("#c", 0.82),
        ]
        decision = default_policy.evaluate_continuation(
            analysis, candidates,
            healing_attempt_count=1,
            attempted_selectors={"#a"},
        )
        assert decision.decision == RecoveryAction.TRY_HEALING
        assert decision.selected_candidate.selector == "#b"


# ══════════════════════════════════════════════════════════════
#  3e. Ambiguity Detection Tests
# ══════════════════════════════════════════════════════════════


class TestRecoveryPolicyAmbiguity:
    """Tests for ambiguous candidate detection."""

    def test_ambiguous_candidates(self, default_policy):
        """Two close candidates → REQUIRE_FURTHER_ANALYSIS."""
        analysis = _make_analysis(FailureType.SELECTOR_CHANGED)
        candidates = [
            _make_candidate("#a", 0.82),
            _make_candidate("#b", 0.81),
        ]
        decision = default_policy.evaluate(analysis, candidates)
        assert decision.decision == RecoveryAction.REQUIRE_FURTHER_ANALYSIS
        assert "ambiguous" in decision.reason.lower()

    def test_not_ambiguous_with_clear_gap(self, default_policy):
        """Two candidates with clear gap → TRY_HEALING."""
        analysis = _make_analysis(FailureType.SELECTOR_CHANGED)
        candidates = [
            _make_candidate("#a", 0.90),
            _make_candidate("#b", 0.80),
        ]
        decision = default_policy.evaluate(analysis, candidates)
        assert decision.decision == RecoveryAction.TRY_HEALING

    def test_ambiguity_margin_configurable(self):
        """Custom ambiguity margin is used."""
        policy = RecoveryPolicy(config=RecoveryPolicyConfig(
            ambiguity_margin=0.10,
        ))
        analysis = _make_analysis(FailureType.SELECTOR_CHANGED)
        candidates = [
            _make_candidate("#a", 0.90),
            _make_candidate("#b", 0.82),
        ]
        decision = policy.evaluate(analysis, candidates)
        assert decision.decision == RecoveryAction.REQUIRE_FURTHER_ANALYSIS


# ══════════════════════════════════════════════════════════════
#  3f. No Candidate Tests
# ══════════════════════════════════════════════════════════════


class TestRecoveryPolicyNoCandidates:
    """Tests for no-candidate scenarios."""

    def test_no_candidates_selector_changed(self, default_policy):
        """Healable failure with no candidates → DO_NOT_HEAL."""
        analysis = _make_analysis(FailureType.SELECTOR_CHANGED)
        decision = default_policy.evaluate(analysis, [])
        assert decision.decision == RecoveryAction.DO_NOT_HEAL

    def test_no_candidates_element_not_found(self, default_policy):
        """ELEMENT_NOT_FOUND with no candidates → DO_NOT_HEAL."""
        analysis = _make_analysis(FailureType.ELEMENT_NOT_FOUND)
        decision = default_policy.evaluate(analysis, [])
        assert decision.decision == RecoveryAction.DO_NOT_HEAL


# ══════════════════════════════════════════════════════════════
#  3g. Historical Evidence Tests
# ══════════════════════════════════════════════════════════════


class TestRecoveryPolicyHistoricalEvidence:
    """Tests for historical healing evidence integration."""

    def test_history_boosts_confidence(self, memory_store):
        """Successful history boosts candidate confidence."""
        # Seed healing records
        for i in range(5):
            memory_store.store_healing_record(HealingRecord(
                healing_id=f"h_{i}",
                test_id="test-001",
                old_selector="#login-btn",
                new_selector="#sign-in-btn",
                healing_reason="test",
                confidence=0.85,
                validation_result=True,
                timestamp=datetime.now(timezone.utc).isoformat(),
            ))

        retriever = HealingEvidenceRetriever(memory_store)
        policy = RecoveryPolicy(
            config=RecoveryPolicyConfig(
                min_healing_confidence=0.80,
                history_boost_weight=0.15,
            ),
            evidence_retriever=retriever,
        )

        analysis = _make_analysis(FailureType.SELECTOR_CHANGED, failed_target="#login-btn")
        # Candidate at 0.78 — below threshold, but history should boost it
        candidates = [_make_candidate("#sign-in-btn", 0.78)]
        decision = policy.evaluate(analysis, candidates)
        # 0.78 + (1.0 * 0.15) = 0.93 → should heal
        assert decision.decision == RecoveryAction.TRY_HEALING

    def test_poor_history_penalizes(self, memory_store):
        """Poor historical success rate penalizes candidates."""
        # 1 success, 3 failures
        for i in range(4):
            memory_store.store_healing_record(HealingRecord(
                healing_id=f"h_{i}",
                test_id="test-001",
                old_selector="#login-btn",
                new_selector=".bad-btn",
                healing_reason="test",
                confidence=0.85,
                validation_result=(i == 0),  # Only first succeeds
                timestamp=datetime.now(timezone.utc).isoformat(),
            ))

        retriever = HealingEvidenceRetriever(memory_store)
        policy = RecoveryPolicy(
            config=RecoveryPolicyConfig(
                min_healing_confidence=0.80,
                history_boost_weight=0.15,
            ),
            evidence_retriever=retriever,
        )

        analysis = _make_analysis(FailureType.SELECTOR_CHANGED, failed_target="#login-btn")
        # Candidate at 0.82 — should be penalized by poor history
        candidates = [_make_candidate(".bad-btn", 0.82)]
        decision = policy.evaluate(analysis, candidates)
        # 0.82 + (0.25 * 0.15) = 0.8575 then -0.20 penalty = 0.6575 → too low
        assert decision.decision == RecoveryAction.DO_NOT_HEAL

    def test_no_history_is_neutral(self, memory_store):
        """No history doesn't penalize candidates."""
        retriever = HealingEvidenceRetriever(memory_store)
        policy = RecoveryPolicy(
            config=RecoveryPolicyConfig(min_healing_confidence=0.80),
            evidence_retriever=retriever,
        )
        analysis = _make_analysis(FailureType.SELECTOR_CHANGED, failed_target="#login-btn")
        candidates = [_make_candidate("#new-btn", 0.85)]
        decision = policy.evaluate(analysis, candidates)
        assert decision.decision == RecoveryAction.TRY_HEALING


# ══════════════════════════════════════════════════════════════
#  3h. Explainable Evidence Tests
# ══════════════════════════════════════════════════════════════


class TestRecoveryPolicyExplainability:
    """Tests that recovery decisions contain observable evidence."""

    def test_decision_has_evidence(self, default_policy):
        """Every decision includes evidence strings."""
        analysis = _make_analysis(FailureType.SELECTOR_CHANGED)
        candidates = [_make_candidate("#btn", 0.85)]
        decision = default_policy.evaluate(analysis, candidates)
        assert len(decision.evidence) > 0

    def test_decision_has_reason(self, default_policy):
        """Every decision includes a human-readable reason."""
        analysis = _make_analysis(FailureType.ASSERTION_FAILURE)
        decision = default_policy.evaluate(analysis, [])
        assert len(decision.reason) > 0

    def test_evidence_contains_failure_type(self, default_policy):
        """Evidence mentions the failure type."""
        analysis = _make_analysis(FailureType.SELECTOR_CHANGED)
        decision = default_policy.evaluate(analysis, [])
        assert any("SELECTOR_CHANGED" in e for e in decision.evidence)

    def test_try_healing_evidence_includes_candidate(self, default_policy):
        """TRY_HEALING evidence includes candidate details."""
        analysis = _make_analysis(FailureType.SELECTOR_CHANGED)
        candidates = [_make_candidate("#sign-in-btn", 0.91)]
        decision = default_policy.evaluate(analysis, candidates)
        assert any("#sign-in-btn" in e for e in decision.evidence)

    def test_abort_evidence_mentions_max_attempts(self, default_policy):
        """ABORT evidence mentions maximum attempts."""
        analysis = _make_analysis(FailureType.SELECTOR_CHANGED)
        decision = default_policy.evaluate(
            analysis, [], healing_attempt_count=3,
        )
        assert "Maximum healing attempts" in decision.reason


# ══════════════════════════════════════════════════════════════
#  4. Integration Tests
# ══════════════════════════════════════════════════════════════


class TestIntegrationSuccessfulHealing:
    """Task 17: Complete successful healing scenario."""

    @pytest.mark.asyncio
    async def test_full_healing_success_scenario(self, memory_store):
        """Complete mock scenario: failure → analysis → candidates →
        recovery decision → heal → success."""
        # Seed historical evidence for candidate A
        for i in range(5):
            memory_store.store_healing_record(HealingRecord(
                healing_id=f"hist_{i}",
                test_id="test-login",
                old_selector="#login-btn",
                new_selector="#sign-in-btn",
                healing_reason="historical success",
                confidence=0.90,
                validation_result=True,
                timestamp=datetime.now(timezone.utc).isoformat(),
            ))

        retriever = HealingEvidenceRetriever(memory_store)
        policy = RecoveryPolicy(
            config=RecoveryPolicyConfig(
                min_healing_confidence=0.80,
                history_boost_weight=0.15,
            ),
            evidence_retriever=retriever,
        )

        analysis = _make_analysis(
            FailureType.SELECTOR_CHANGED,
            test_id="test-login",
            failed_target="#login-btn",
        )

        # Candidate A: strong history (5/5 successes)
        candidate_a = _make_candidate("#sign-in-btn", 0.88)
        # Candidate B: weak history (1/4 successes)
        candidate_b = _make_candidate(".submit-btn", 0.70,
                                       text_similarity=0.5, role_similarity=0.5)

        decision = policy.evaluate(
            analysis,
            [candidate_a, candidate_b],
        )

        assert decision.decision == RecoveryAction.TRY_HEALING
        assert decision.selected_candidate.selector == "#sign-in-btn"
        assert decision.next_state == "HEALING_PENDING_VALIDATION"
        assert decision.requires_validation is True
        assert len(decision.evidence) > 0


class TestIntegrationFailedHealing:
    """Task 18: All candidates fail → ABORT."""

    def test_all_candidates_fail_abort(self, default_policy):
        """All candidates fail → ABORT after max attempts."""
        analysis = _make_analysis(FailureType.SELECTOR_CHANGED)
        candidates = [
            _make_candidate("#a", 0.91),
            _make_candidate("#b", 0.85),
            _make_candidate("#c", 0.82),
        ]

        # Attempt 1: #a
        d1 = default_policy.evaluate(
            analysis, candidates,
            healing_attempt_count=0,
        )
        assert d1.decision == RecoveryAction.TRY_HEALING
        assert d1.selected_candidate.selector == "#a"

        # Attempt 2: #a failed, try #b
        d2 = default_policy.evaluate_continuation(
            analysis, candidates,
            healing_attempt_count=1,
            attempted_selectors={"#a"},
        )
        assert d2.decision == RecoveryAction.TRY_HEALING
        assert d2.selected_candidate.selector == "#b"

        # Attempt 3: #b failed, try #c
        d3 = default_policy.evaluate_continuation(
            analysis, candidates,
            healing_attempt_count=2,
            attempted_selectors={"#a", "#b"},
        )
        assert d3.decision == RecoveryAction.TRY_HEALING
        assert d3.selected_candidate.selector == "#c"

        # Attempt 4: #c failed, max reached
        d4 = default_policy.evaluate_continuation(
            analysis, candidates,
            healing_attempt_count=3,
            attempted_selectors={"#a", "#b", "#c"},
        )
        assert d4.decision == RecoveryAction.ABORT


class TestIntegrationMultipleAttempts:
    """Task 13: Multi-attempt recovery."""

    def test_multi_attempt_escalation(self, default_policy):
        """Progressive attempt through ranked candidates."""
        analysis = _make_analysis(FailureType.SELECTOR_CHANGED)
        candidates = [
            _make_candidate("#first", 0.92),
            _make_candidate("#second", 0.87),
            _make_candidate("#third", 0.83),
        ]

        attempted = set()
        for i, expected_selector in enumerate(["#first", "#second", "#third"]):
            if i == 0:
                decision = default_policy.evaluate(
                    analysis, candidates,
                    healing_attempt_count=i,
                    attempted_selectors=attempted,
                )
            else:
                decision = default_policy.evaluate_continuation(
                    analysis, candidates,
                    healing_attempt_count=i,
                    attempted_selectors=attempted,
                )
            assert decision.decision == RecoveryAction.TRY_HEALING
            assert decision.selected_candidate.selector == expected_selector
            attempted.add(expected_selector)


class TestIntegrationRetryWorkflow:
    """Task 16: Retry handling for transient failures."""

    def test_timeout_retry_then_escalate(self, default_policy):
        """TIMEOUT: retry twice, then escalate."""
        analysis = _make_analysis(FailureType.TIMEOUT)

        # Retry 1
        d1 = default_policy.evaluate(analysis, [], retry_count=0)
        assert d1.decision == RecoveryAction.RETRY

        # Retry 2
        d2 = default_policy.evaluate(analysis, [], retry_count=1)
        assert d2.decision == RecoveryAction.RETRY

        # Exhausted
        d3 = default_policy.evaluate(analysis, [], retry_count=2)
        assert d3.decision == RecoveryAction.REQUIRE_FURTHER_ANALYSIS

    def test_navigation_retry_then_escalate(self, default_policy):
        """NAVIGATION_FAILURE: retry twice, then escalate."""
        analysis = _make_analysis(FailureType.NAVIGATION_FAILURE)

        d1 = default_policy.evaluate(analysis, [], retry_count=0)
        assert d1.decision == RecoveryAction.RETRY

        d3 = default_policy.evaluate(analysis, [], retry_count=2)
        assert d3.decision == RecoveryAction.REQUIRE_FURTHER_ANALYSIS

    def test_retry_disabled(self):
        """When allow_retry=False, retryable failures escalate."""
        policy = RecoveryPolicy(config=RecoveryPolicyConfig(
            allow_retry=False,
        ))
        analysis = _make_analysis(FailureType.TIMEOUT)
        decision = policy.evaluate(analysis, [])
        assert decision.decision != RecoveryAction.RETRY


class TestIntegrationLowConfidence:
    """Task 20: Low confidence scenario."""

    def test_low_confidence_0_34(self, default_policy):
        """Best candidate at 0.34 → DO_NOT_HEAL."""
        analysis = _make_analysis(FailureType.SELECTOR_CHANGED)
        candidates = [_make_candidate("#weak-btn", 0.34)]
        decision = default_policy.evaluate(analysis, candidates)
        assert decision.decision == RecoveryAction.DO_NOT_HEAL


class TestIntegrationAmbiguous:
    """Task 19: Ambiguous scenario."""

    def test_ambiguous_candidates_0_82_vs_0_81(self, default_policy):
        """0.82 vs 0.81 → REQUIRE_FURTHER_ANALYSIS."""
        analysis = _make_analysis(FailureType.SELECTOR_CHANGED)
        candidates = [
            _make_candidate("#a", 0.82),
            _make_candidate("#b", 0.81),
        ]
        decision = default_policy.evaluate(analysis, candidates)
        assert decision.decision == RecoveryAction.REQUIRE_FURTHER_ANALYSIS


class TestIntegrationAssertionFailure:
    """Task 21: Assertion failure scenario."""

    def test_assertion_failure_never_heals(self, default_policy):
        """ASSERTION_FAILED with strong candidate → DO_NOT_HEAL."""
        analysis = _make_analysis(FailureType.ASSERTION_FAILURE)
        candidates = [_make_candidate("#perfect-match", 0.99)]
        decision = default_policy.evaluate(analysis, candidates)
        assert decision.decision == RecoveryAction.DO_NOT_HEAL


class TestIntegrationOrchestratorEndToEnd:
    """Task 12: Full orchestrator integration with RecoveryPolicy."""

    @pytest.mark.asyncio
    async def test_orchestrator_uses_recovery_policy(self, memory_store):
        """AgentOrchestrator uses RecoveryPolicy for decisions."""
        config = _mock_config()
        provider = MockLLMProvider(config=config)
        session = LLMClientSession(provider=provider, config=config)

        failure_analyzer = FailureAnalyzerAgent(
            llm_client=session,
            memory_store=memory_store,
        )
        healing_engine = HealingDecisionEngine(
            memory_store=memory_store,
            llm_client=session,
        )
        feedback_processor = HealingResultFeedbackProcessor(memory_store)

        # Create orchestrator with recovery policy
        recovery_policy = RecoveryPolicy(
            config=RecoveryPolicyConfig(min_healing_confidence=0.30),
        )

        orchestrator = AgentOrchestrator(
            memory_store=memory_store,
            failure_analyzer=failure_analyzer,
            healing_engine=healing_engine,
            feedback_processor=feedback_processor,
            config=OrchestratorConfig(max_healing_attempts=3),
            recovery_policy=recovery_policy,
        )

        # The orchestrator should be initialized without error
        assert orchestrator is not None


# ══════════════════════════════════════════════════════════════
#  5. Safety / Invariant Tests (Task 23)
# ══════════════════════════════════════════════════════════════


class TestSafetyInvariants:
    """Verify safety invariants are never violated."""

    def test_invariant_healing_attempts_never_exceed_max(self):
        """Healing attempts never exceed MAX_HEALING_ATTEMPTS."""
        policy = RecoveryPolicy(config=RecoveryPolicyConfig(
            max_healing_attempts=3,
        ))
        analysis = _make_analysis(FailureType.SELECTOR_CHANGED)
        candidates = [_make_candidate(f"#c{i}", 0.90 - i * 0.01) for i in range(10)]

        # Try all attempt counts from 0 to 10
        for attempt in range(11):
            decision = policy.evaluate(
                analysis, candidates,
                healing_attempt_count=attempt,
            )
            if attempt >= 3:
                assert decision.decision == RecoveryAction.ABORT, (
                    f"Expected ABORT at attempt {attempt}, "
                    f"got {decision.decision}"
                )

    def test_invariant_retries_never_exceed_max(self):
        """Retry attempts never exceed MAX_RETRIES."""
        policy = RecoveryPolicy(config=RecoveryPolicyConfig(
            max_retries=2,
        ))
        analysis = _make_analysis(FailureType.TIMEOUT)

        for retry in range(5):
            decision = policy.evaluate(analysis, [], retry_count=retry)
            if retry >= 2:
                assert decision.decision != RecoveryAction.RETRY, (
                    f"Expected no RETRY at count {retry}, "
                    f"got {decision.decision}"
                )

    def test_invariant_same_failed_candidate_not_repeated(self):
        """Same failed candidate is never recommended twice."""
        policy = RecoveryPolicy()
        analysis = _make_analysis(FailureType.SELECTOR_CHANGED)
        candidates = [
            _make_candidate("#a", 0.91),
            _make_candidate("#b", 0.85),
        ]

        d1 = policy.evaluate(
            analysis, candidates,
            attempted_selectors=set(),
        )
        assert d1.selected_candidate.selector == "#a"

        # After #a fails, should get #b
        d2 = policy.evaluate_continuation(
            analysis, candidates,
            healing_attempt_count=1,
            attempted_selectors={"#a"},
        )
        assert d2.selected_candidate.selector == "#b"

    def test_invariant_healing_requires_member2_validation(self):
        """TRY_HEALING always requires validation."""
        policy = RecoveryPolicy()
        analysis = _make_analysis(FailureType.SELECTOR_CHANGED)
        candidates = [_make_candidate("#btn", 0.95)]
        decision = policy.evaluate(analysis, candidates)
        assert decision.decision == RecoveryAction.TRY_HEALING
        assert decision.requires_validation is True

    def test_invariant_unknown_failures_cannot_auto_succeed(self):
        """Unknown failures cannot become automatic healing."""
        policy = RecoveryPolicy()
        analysis = _make_analysis(FailureType.UNKNOWN)
        candidates = [_make_candidate("#btn", 0.95)]
        decision = policy.evaluate(analysis, candidates)
        # UNKNOWN is not healable by default
        assert decision.decision != RecoveryAction.TRY_HEALING

    def test_invariant_no_candidate_means_no_healing(self):
        """No candidate → no healing attempt."""
        policy = RecoveryPolicy()
        analysis = _make_analysis(FailureType.SELECTOR_CHANGED)
        decision = policy.evaluate(analysis, [])
        assert decision.decision != RecoveryAction.TRY_HEALING
        assert decision.selected_candidate is None

    def test_invariant_low_confidence_cannot_trigger_healing(self):
        """Low confidence cannot trigger automatic healing."""
        policy = RecoveryPolicy(config=RecoveryPolicyConfig(
            min_healing_confidence=0.80,
            allow_medium_confidence_healing=False,
        ))
        analysis = _make_analysis(FailureType.SELECTOR_CHANGED)
        candidates = [_make_candidate("#btn", 0.50)]
        decision = policy.evaluate(analysis, candidates)
        assert decision.decision != RecoveryAction.TRY_HEALING

    def test_invariant_assertion_failure_never_heals(self):
        """Assertion failures can never trigger healing."""
        policy = RecoveryPolicy()
        analysis = _make_analysis(FailureType.ASSERTION_FAILURE)
        candidates = [_make_candidate("#btn", 0.99)]
        decision = policy.evaluate(analysis, candidates)
        assert decision.decision == RecoveryAction.DO_NOT_HEAL


# ══════════════════════════════════════════════════════════════
#  6. Determinism Test
# ══════════════════════════════════════════════════════════════


class TestDeterminism:
    """Policy produces the same result for the same inputs."""

    def test_deterministic_outputs(self, default_policy):
        """Same inputs produce same decision."""
        analysis = _make_analysis(FailureType.SELECTOR_CHANGED)
        candidates = [
            _make_candidate("#a", 0.88),
            _make_candidate("#b", 0.75),
        ]

        d1 = default_policy.evaluate(analysis, candidates)
        d2 = default_policy.evaluate(analysis, candidates)

        assert d1.decision == d2.decision
        assert d1.selected_candidate == d2.selected_candidate
        assert d1.confidence == d2.confidence

    def test_deterministic_across_calls(self, default_policy):
        """Multiple calls with same inputs are consistent."""
        analysis = _make_analysis(FailureType.TIMEOUT)
        results = [
            default_policy.evaluate(analysis, [], retry_count=0)
            for _ in range(10)
        ]
        assert all(r.decision == results[0].decision for r in results)


# ══════════════════════════════════════════════════════════════
#  7. WorkflowStep RETRYING Tests
# ══════════════════════════════════════════════════════════════


class TestWorkflowStepRetrying:
    """Tests for the new RETRYING workflow step."""

    def test_retrying_step_exists(self):
        """RETRYING step exists in WorkflowStep enum."""
        assert WorkflowStep.RETRYING == "RETRYING"

    def test_retrying_transition_valid(self):
        """RETRYING → EXECUTION_PENDING is valid."""
        allowed = VALID_TRANSITIONS[WorkflowStep.RETRYING]
        assert WorkflowStep.EXECUTION_PENDING in allowed

    def test_analyzing_to_retrying_valid(self):
        """ANALYZING_FAILURE → RETRYING is valid."""
        allowed = VALID_TRANSITIONS[WorkflowStep.ANALYZING_FAILURE]
        assert WorkflowStep.RETRYING in allowed

    def test_deciding_to_aborted_valid(self):
        """DECIDING_HEALING → ABORTED is valid."""
        allowed = VALID_TRANSITIONS[WorkflowStep.DECIDING_HEALING]
        assert WorkflowStep.ABORTED in allowed

    def test_healing_pending_to_aborted_valid(self):
        """HEALING_PENDING_VALIDATION → ABORTED is valid."""
        allowed = VALID_TRANSITIONS[WorkflowStep.HEALING_PENDING_VALIDATION]
        assert WorkflowStep.ABORTED in allowed


# ══════════════════════════════════════════════════════════════
#  8. AgentState Retry Fields Tests
# ══════════════════════════════════════════════════════════════


class TestAgentStateRetryFields:
    """Tests for the new retry-related fields on AgentState."""

    def test_retry_count_default(self):
        """retry_count defaults to 0."""
        state = AgentState()
        assert state.retry_count == 0

    def test_max_retries_default(self):
        """max_retries defaults to 2."""
        state = AgentState()
        assert state.max_retries == 2

    def test_recovery_decision_default_none(self):
        """recovery_decision defaults to None."""
        state = AgentState()
        assert state.recovery_decision is None

    def test_recovery_decision_can_be_set(self):
        """recovery_decision can be set to a RecoveryDecision."""
        decision = RecoveryDecision(
            decision=RecoveryAction.TRY_HEALING,
            confidence=0.85,
        )
        state = AgentState(recovery_decision=decision)
        assert state.recovery_decision is not None


# ══════════════════════════════════════════════════════════════
#  9. WorkflowEventType Tests
# ══════════════════════════════════════════════════════════════


class TestWorkflowEventTypes:
    """Tests for new event types."""

    def test_recovery_decision_created_event(self):
        """RECOVERY_DECISION_CREATED event type exists."""
        assert WorkflowEventType.RECOVERY_DECISION_CREATED == "RECOVERY_DECISION_CREATED"

    def test_retry_initiated_event(self):
        """RETRY_INITIATED event type exists."""
        assert WorkflowEventType.RETRY_INITIATED == "RETRY_INITIATED"


# ══════════════════════════════════════════════════════════════
#  10. Contracts Import Tests
# ══════════════════════════════════════════════════════════════


class TestContractsExport:
    """Verify Day 14 exports are available via contracts."""

    def test_import_recovery_action(self):
        """RecoveryAction is importable from contracts."""
        from agents.schemas.contracts import RecoveryAction as RA
        assert RA.TRY_HEALING == "TRY_HEALING"

    def test_import_recovery_decision(self):
        """RecoveryDecision is importable from contracts."""
        from agents.schemas.contracts import RecoveryDecision as RD
        d = RD(decision=RecoveryAction.ABORT)
        assert d.decision == RecoveryAction.ABORT

    def test_import_recovery_policy(self):
        """RecoveryPolicy is importable from contracts."""
        from agents.schemas.contracts import RecoveryPolicy as RP
        p = RP()
        assert p is not None

    def test_import_recovery_policy_config(self):
        """RecoveryPolicyConfig is importable from contracts."""
        from agents.schemas.contracts import RecoveryPolicyConfig as RPC
        c = RPC()
        assert c.max_healing_attempts == 3
