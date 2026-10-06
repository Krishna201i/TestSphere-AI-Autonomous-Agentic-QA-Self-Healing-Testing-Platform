"""
TestSphere-AI — Day 12: Healing Result Feedback & Memory Learning Tests

Comprehensive test suite for the Day 12 feedback loop:

1.  HealingResultFeedback schema validation
2.  Successful healing result storage
3.  Failed healing result storage
4.  Healing history retrieval
5.  Historical success counting
6.  Historical failure counting
7.  Candidate ranking using historical evidence
8.  Candidate with no history (neutral, not penalized)
9.  Repeated selector-change detection
10. Repeated successful replacement detection
11. LLM cannot invent selectors (grounding validation)
12. Healing cannot be marked successful without validation
13. End-to-end feedback loop (full scenario)

All tests are offline, no browser, no API keys, no real models.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from agents.analyzer.schemas import (
    FailureAnalysis,
    FailureContext,
    FailureEvidence,
    HistoricalContext,
)
from agents.healer.candidate_scorer import CandidateScorer, ScoringWeights
from agents.healer.healing_decision import (
    ConfidenceThresholds,
    HealingDecisionEngine,
)
from agents.healer.healing_feedback import (
    HealingResultFeedback,
    HealingResultFeedbackProcessor,
)
from agents.healer.healing_result_mapper import (
    healing_result_to_memory_update,
    prepare_healing_result,
    recommendation_to_healing_candidate,
)
from agents.healer.healing_schemas import (
    HealingContext,
    HealingRecommendation,
    ScoredCandidate,
)
from agents.healer.llm_healing_evaluator import LLMHealingEvaluator
from agents.healer.schemas import HealingCandidate, HealingResult
from agents.memory.healing_evidence import (
    HealingEvidenceRetriever,
    ReplacementStats,
    SelectorHistory,
)
from agents.memory.in_memory_store import InMemoryStore
from agents.memory.memory_schemas import (
    ElementRecord,
    HealingRecord,
)
from agents.memory.pattern_detector import (
    HealingPattern,
    HealingPatternDetector,
)
from agents.schemas.enums import (
    CandidateSource,
    ConfidenceLevel,
    FailureType,
    HealingAction,
    HealingDecision,
    HealingPatternType,
    HealingStatus,
    RecommendedAction,
    ValidationStatus,
)


# ══════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════


@pytest.fixture
def memory_store() -> InMemoryStore:
    """Fresh in-memory store for each test."""
    return InMemoryStore()


@pytest.fixture
def evidence_retriever(memory_store: InMemoryStore) -> HealingEvidenceRetriever:
    """Evidence retriever backed by in-memory store."""
    return HealingEvidenceRetriever(memory_store)


@pytest.fixture
def pattern_detector(memory_store: InMemoryStore) -> HealingPatternDetector:
    """Pattern detector backed by in-memory store."""
    return HealingPatternDetector(memory_store)


@pytest.fixture
def feedback_processor(memory_store: InMemoryStore) -> HealingResultFeedbackProcessor:
    """Feedback processor backed by in-memory store."""
    return HealingResultFeedbackProcessor(memory_store)


def _make_healing_record(
    healing_id: str,
    test_id: str,
    old_selector: str,
    new_selector: str,
    confidence: float = 0.85,
    validation_result: bool | None = True,
    timestamp: str = "2026-01-01T00:00:00+00:00",
) -> HealingRecord:
    """Helper to create a HealingRecord."""
    return HealingRecord(
        healing_id=healing_id,
        test_id=test_id,
        old_selector=old_selector,
        new_selector=new_selector,
        healing_reason="Test healing",
        confidence=confidence,
        validation_result=validation_result,
        timestamp=timestamp,
    )


def _make_element(
    element_id: str,
    selector: str,
    text: str = "Login",
    role: str = "button",
    page_url: str = "https://app.example.com/login",
) -> ElementRecord:
    """Helper to create an ElementRecord."""
    return ElementRecord(
        element_id=element_id,
        selector=selector,
        text=text,
        role=role,
        page_url=page_url,
    )


def _make_failure_analysis(
    test_id: str = "TC_LOGIN_001",
    execution_id: str = "exec_001",
    failed_step: int = 3,
    failed_target: str = "#login-btn",
    failure_type: FailureType = FailureType.ELEMENT_NOT_FOUND,
    previous_element: ElementRecord | None = None,
) -> FailureAnalysis:
    """Helper to create a FailureAnalysis."""
    historical_context = None
    if previous_element is not None:
        historical_context = HistoricalContext(
            previous_element=previous_element,
        )

    return FailureAnalysis(
        test_id=test_id,
        execution_id=execution_id,
        failure_type=failure_type,
        root_cause="Element not found in the DOM",
        confidence=ConfidenceLevel.HIGH,
        failed_step=failed_step,
        failed_target=failed_target,
        evidence=[
            FailureEvidence(
                evidence_type="selector_missing",
                description=f"Selector '{failed_target}' not found",
            ),
        ],
        historical_context=historical_context,
        recommended_action=RecommendedAction.SEARCH_FOR_REPLACEMENT_SELECTOR,
    )


# ══════════════════════════════════════════════════════════════
# 1. HealingResultFeedback Schema Validation
# ══════════════════════════════════════════════════════════════


class TestHealingResultFeedbackSchema:
    """Test HealingResultFeedback schema validation."""

    def test_valid_success_feedback(self):
        """Valid success feedback should be accepted."""
        feedback = HealingResultFeedback(
            test_case_id="TC_LOGIN_001",
            original_selector="#login-btn",
            attempted_selector="#sign-in-btn",
            healing_status=HealingStatus.VALIDATED_SUCCESS,
            validation_status=ValidationStatus.SUCCESS,
            confidence=0.94,
        )
        assert feedback.test_case_id == "TC_LOGIN_001"
        assert feedback.validation_status == ValidationStatus.SUCCESS
        assert feedback.healing_status == HealingStatus.VALIDATED_SUCCESS
        assert feedback.confidence == 0.94
        assert feedback.execution_attempt == 1
        assert feedback.healing_id  # Auto-generated

    def test_valid_failure_feedback(self):
        """Valid failure feedback should be accepted."""
        feedback = HealingResultFeedback(
            test_case_id="TC_LOGIN_001",
            original_selector="#login-btn",
            attempted_selector=".bad-selector",
            healing_status=HealingStatus.VALIDATED_FAILURE,
            validation_status=ValidationStatus.FAILURE,
            confidence=0.45,
            error_reason="Element not found after healing",
        )
        assert feedback.validation_status == ValidationStatus.FAILURE
        assert feedback.error_reason == "Element not found after healing"

    def test_invalid_healing_status_proposed_rejected(self):
        """PROPOSED is not a valid post-validation status."""
        with pytest.raises(ValueError, match="post-validation status"):
            HealingResultFeedback(
                test_case_id="TC_LOGIN_001",
                original_selector="#login-btn",
                attempted_selector="#sign-in-btn",
                healing_status=HealingStatus.PROPOSED,
                validation_status=ValidationStatus.SUCCESS,
                confidence=0.94,
            )

    def test_invalid_healing_status_validation_pending_rejected(self):
        """VALIDATION_PENDING is not a valid post-validation status."""
        with pytest.raises(ValueError, match="post-validation status"):
            HealingResultFeedback(
                test_case_id="TC_LOGIN_001",
                original_selector="#login-btn",
                attempted_selector="#sign-in-btn",
                healing_status=HealingStatus.VALIDATION_PENDING,
                validation_status=ValidationStatus.SUCCESS,
                confidence=0.94,
            )

    def test_feedback_with_all_optional_fields(self):
        """Feedback with all optional fields should be accepted."""
        feedback = HealingResultFeedback(
            healing_id="heal_test123",
            test_case_id="TC_LOGIN_001",
            failure_id="fail_001",
            execution_id="exec_001",
            original_selector="#login-btn",
            attempted_selector="#sign-in-btn",
            candidate_id="cand_001",
            healing_status=HealingStatus.VALIDATED_SUCCESS,
            validation_status=ValidationStatus.SUCCESS,
            failure_category=FailureType.ELEMENT_NOT_FOUND,
            confidence=0.94,
            execution_attempt=2,
            error_reason=None,
            metadata={"browser": "chrome", "version": "120"},
        )
        assert feedback.healing_id == "heal_test123"
        assert feedback.failure_id == "fail_001"
        assert feedback.candidate_id == "cand_001"
        assert feedback.failure_category == FailureType.ELEMENT_NOT_FOUND
        assert feedback.execution_attempt == 2
        assert feedback.metadata["browser"] == "chrome"

    def test_confidence_bounds(self):
        """Confidence must be 0.0 to 1.0."""
        with pytest.raises(Exception):
            HealingResultFeedback(
                test_case_id="TC_LOGIN_001",
                original_selector="#login-btn",
                attempted_selector="#sign-in-btn",
                healing_status=HealingStatus.VALIDATED_SUCCESS,
                validation_status=ValidationStatus.SUCCESS,
                confidence=1.5,
            )


# ══════════════════════════════════════════════════════════════
# 2. Successful Healing Result Storage
# ══════════════════════════════════════════════════════════════


class TestSuccessfulHealingStorage:
    """Test storage of successful healing results."""

    def test_store_successful_feedback(
        self,
        memory_store: InMemoryStore,
        feedback_processor: HealingResultFeedbackProcessor,
    ):
        """Successful feedback should be stored with validation_result=True."""
        feedback = HealingResultFeedback(
            test_case_id="TC_LOGIN_001",
            original_selector="#login-btn",
            attempted_selector="#sign-in-btn",
            healing_status=HealingStatus.VALIDATED_SUCCESS,
            validation_status=ValidationStatus.SUCCESS,
            confidence=0.94,
        )

        record = feedback_processor.process_feedback(feedback)

        assert record.validation_result is True
        assert record.old_selector == "#login-btn"
        assert record.new_selector == "#sign-in-btn"
        assert record.confidence == 0.94

        # Verify stored in memory
        history = memory_store.get_healing_history("#login-btn")
        assert len(history) == 1
        assert history[0].validation_result is True

    def test_store_multiple_successes(
        self,
        memory_store: InMemoryStore,
        feedback_processor: HealingResultFeedbackProcessor,
    ):
        """Multiple successful results should all be stored."""
        for i in range(3):
            feedback = HealingResultFeedback(
                healing_id=f"heal_{i:03d}",
                test_case_id="TC_LOGIN_001",
                original_selector="#login-btn",
                attempted_selector="#sign-in-btn",
                healing_status=HealingStatus.VALIDATED_SUCCESS,
                validation_status=ValidationStatus.SUCCESS,
                confidence=0.9 + i * 0.01,
                timestamp=f"2026-01-0{i + 1}T00:00:00+00:00",
            )
            feedback_processor.process_feedback(feedback)

        history = memory_store.get_healing_history("#login-btn")
        assert len(history) == 3
        assert all(r.validation_result is True for r in history)


# ══════════════════════════════════════════════════════════════
# 3. Failed Healing Result Storage
# ══════════════════════════════════════════════════════════════


class TestFailedHealingStorage:
    """Test storage of failed healing results."""

    def test_store_failed_feedback(
        self,
        memory_store: InMemoryStore,
        feedback_processor: HealingResultFeedbackProcessor,
    ):
        """Failed feedback should be stored with validation_result=False."""
        feedback = HealingResultFeedback(
            test_case_id="TC_LOGIN_001",
            original_selector="#login-btn",
            attempted_selector=".wrong-selector",
            healing_status=HealingStatus.VALIDATED_FAILURE,
            validation_status=ValidationStatus.FAILURE,
            confidence=0.55,
            error_reason="Element not found",
        )

        record = feedback_processor.process_feedback(feedback)

        assert record.validation_result is False
        assert "failed" in record.healing_reason.lower()

        history = memory_store.get_healing_history("#login-btn")
        assert len(history) == 1
        assert history[0].validation_result is False

    def test_store_error_feedback_as_inconclusive(
        self,
        feedback_processor: HealingResultFeedbackProcessor,
    ):
        """ERROR validation should store as None (inconclusive)."""
        feedback = HealingResultFeedback(
            test_case_id="TC_LOGIN_001",
            original_selector="#login-btn",
            attempted_selector="#sign-in-btn",
            healing_status=HealingStatus.VALIDATED_FAILURE,
            validation_status=ValidationStatus.ERROR,
            confidence=0.80,
            error_reason="Browser crashed",
        )

        record = feedback_processor.process_feedback(feedback)
        assert record.validation_result is None

    def test_store_skipped_feedback_as_inconclusive(
        self,
        feedback_processor: HealingResultFeedbackProcessor,
    ):
        """SKIPPED validation should store as None (inconclusive)."""
        feedback = HealingResultFeedback(
            test_case_id="TC_LOGIN_001",
            original_selector="#login-btn",
            attempted_selector="#sign-in-btn",
            healing_status=HealingStatus.NO_SAFE_HEALING_FOUND,
            validation_status=ValidationStatus.SKIPPED,
            confidence=0.0,
        )

        record = feedback_processor.process_feedback(feedback)
        assert record.validation_result is None


# ══════════════════════════════════════════════════════════════
# 4. Healing History Retrieval
# ══════════════════════════════════════════════════════════════


class TestHealingHistoryRetrieval:
    """Test history retrieval via HealingEvidenceRetriever."""

    def test_has_selector_failed_true(
        self,
        memory_store: InMemoryStore,
        evidence_retriever: HealingEvidenceRetriever,
    ):
        """has_selector_failed returns True when records exist."""
        record = _make_healing_record(
            "heal_001", "TC_001", "#login-btn", "#sign-in-btn",
        )
        memory_store.store_healing_record(record)

        assert evidence_retriever.has_selector_failed("#login-btn") is True

    def test_has_selector_failed_false(
        self,
        evidence_retriever: HealingEvidenceRetriever,
    ):
        """has_selector_failed returns False for unknown selectors."""
        assert evidence_retriever.has_selector_failed("#unknown") is False

    def test_has_replacement_succeeded_true(
        self,
        memory_store: InMemoryStore,
        evidence_retriever: HealingEvidenceRetriever,
    ):
        """has_replacement_succeeded returns True when success exists."""
        record = _make_healing_record(
            "heal_001", "TC_001", "#login-btn", "#sign-in-btn",
            validation_result=True,
        )
        memory_store.store_healing_record(record)

        assert evidence_retriever.has_replacement_succeeded(
            "#login-btn", "#sign-in-btn",
        ) is True

    def test_has_replacement_succeeded_false(
        self,
        memory_store: InMemoryStore,
        evidence_retriever: HealingEvidenceRetriever,
    ):
        """has_replacement_succeeded returns False with only failures."""
        record = _make_healing_record(
            "heal_001", "TC_001", "#login-btn", ".bad-sel",
            validation_result=False,
        )
        memory_store.store_healing_record(record)

        assert evidence_retriever.has_replacement_succeeded(
            "#login-btn", ".bad-sel",
        ) is False

    def test_get_selector_history(
        self,
        memory_store: InMemoryStore,
        evidence_retriever: HealingEvidenceRetriever,
    ):
        """get_selector_history aggregates across all replacements."""
        # 3 successes with #sign-in-btn
        for i in range(3):
            memory_store.store_healing_record(_make_healing_record(
                f"heal_s{i}", "TC_001", "#login-btn", "#sign-in-btn",
                validation_result=True,
                timestamp=f"2026-01-0{i + 1}T00:00:00+00:00",
            ))
        # 2 failures with .bad-selector
        for i in range(2):
            memory_store.store_healing_record(_make_healing_record(
                f"heal_f{i}", "TC_001", "#login-btn", ".bad-selector",
                validation_result=False,
                timestamp=f"2026-01-0{i + 1}T00:00:00+00:00",
            ))

        history = evidence_retriever.get_selector_history("#login-btn")

        assert history.selector == "#login-btn"
        assert history.total_healings == 5
        assert history.total_successes == 3
        assert history.total_failures == 2
        assert history.distinct_replacements == 2
        # Best replacement first
        assert history.replacement_stats[0].new_selector == "#sign-in-btn"
        assert history.replacement_stats[0].success_rate == 1.0

    def test_get_last_successful_replacement(
        self,
        memory_store: InMemoryStore,
        evidence_retriever: HealingEvidenceRetriever,
    ):
        """get_last_successful_replacement returns most recent success."""
        memory_store.store_healing_record(_make_healing_record(
            "heal_001", "TC_001", "#login-btn", "#old-btn",
            validation_result=True,
            timestamp="2026-01-01T00:00:00+00:00",
        ))
        memory_store.store_healing_record(_make_healing_record(
            "heal_002", "TC_001", "#login-btn", "#new-btn",
            validation_result=True,
            timestamp="2026-01-02T00:00:00+00:00",
        ))

        result = evidence_retriever.get_last_successful_replacement("#login-btn")
        assert result == "#new-btn"

    def test_get_last_successful_replacement_none(
        self,
        evidence_retriever: HealingEvidenceRetriever,
    ):
        """get_last_successful_replacement returns None for unknown."""
        result = evidence_retriever.get_last_successful_replacement("#unknown")
        assert result is None


# ══════════════════════════════════════════════════════════════
# 5. Historical Success Counting
# ══════════════════════════════════════════════════════════════


class TestHistoricalSuccessCounting:
    """Test accurate success counting."""

    def test_success_count_accurate(
        self,
        memory_store: InMemoryStore,
        evidence_retriever: HealingEvidenceRetriever,
    ):
        """Success count should match actual successful validations."""
        for i in range(5):
            memory_store.store_healing_record(_make_healing_record(
                f"heal_{i:03d}", "TC_001", "#login-btn", "#sign-in-btn",
                validation_result=True,
                timestamp=f"2026-01-0{i + 1}T00:00:00+00:00",
            ))

        stats = evidence_retriever.get_replacement_stats(
            "#login-btn", "#sign-in-btn",
        )
        assert stats.successes == 5
        assert stats.attempts == 5
        assert stats.success_rate == 1.0

    def test_mixed_results_counting(
        self,
        memory_store: InMemoryStore,
        evidence_retriever: HealingEvidenceRetriever,
    ):
        """Mixed results should be counted correctly."""
        # 3 successes
        for i in range(3):
            memory_store.store_healing_record(_make_healing_record(
                f"heal_s{i}", "TC_001", "#login-btn", "#sign-in-btn",
                validation_result=True,
                timestamp=f"2026-01-0{i + 1}T00:00:00+00:00",
            ))
        # 2 failures
        for i in range(2):
            memory_store.store_healing_record(_make_healing_record(
                f"heal_f{i}", "TC_001", "#login-btn", "#sign-in-btn",
                validation_result=False,
                timestamp=f"2026-02-0{i + 1}T00:00:00+00:00",
            ))

        stats = evidence_retriever.get_replacement_stats(
            "#login-btn", "#sign-in-btn",
        )
        assert stats.successes == 3
        assert stats.failures == 2
        assert stats.attempts == 5
        assert stats.success_rate == 0.6


# ══════════════════════════════════════════════════════════════
# 6. Historical Failure Counting
# ══════════════════════════════════════════════════════════════


class TestHistoricalFailureCounting:
    """Test accurate failure counting."""

    def test_failure_count_accurate(
        self,
        memory_store: InMemoryStore,
        evidence_retriever: HealingEvidenceRetriever,
    ):
        """Failure count should match actual failed validations."""
        for i in range(3):
            memory_store.store_healing_record(_make_healing_record(
                f"heal_{i:03d}", "TC_001", "#login-btn", ".bad-selector",
                validation_result=False,
                timestamp=f"2026-01-0{i + 1}T00:00:00+00:00",
            ))

        stats = evidence_retriever.get_replacement_stats(
            "#login-btn", ".bad-selector",
        )
        assert stats.failures == 3
        assert stats.successes == 0
        assert stats.success_rate == 0.0

    def test_inconclusive_count(
        self,
        memory_store: InMemoryStore,
        evidence_retriever: HealingEvidenceRetriever,
    ):
        """Inconclusive (None) results should be counted separately."""
        memory_store.store_healing_record(_make_healing_record(
            "heal_001", "TC_001", "#login-btn", "#sign-in-btn",
            validation_result=None,
        ))

        stats = evidence_retriever.get_replacement_stats(
            "#login-btn", "#sign-in-btn",
        )
        assert stats.inconclusive == 1
        assert stats.successes == 0
        assert stats.failures == 0


# ══════════════════════════════════════════════════════════════
# 7. Candidate Ranking Using Historical Evidence
# ══════════════════════════════════════════════════════════════


class TestCandidateRankingWithHistory:
    """Test that historical evidence influences candidate ranking."""

    def test_history_boosts_successful_candidate(self):
        """A candidate with high historical success should rank higher."""
        weights = ScoringWeights(
            text_weight=0.25,
            role_weight=0.20,
            page_weight=0.15,
            historical_weight=0.10,
            type_weight=0.10,
            name_weight=0.0,
            stable_attribute_weight=0.0,
            healing_history_weight=0.20,
        )
        scorer = CandidateScorer(weights=weights)

        # Candidate A: moderate text match + strong history
        candidate_a = ScoredCandidate(
            selector="#sign-in-btn",
            source=CandidateSource.CURRENT_DOM,
            text_similarity=1.0,
            role_similarity=1.0,
            page_similarity=1.0,
            historical_similarity=0.0,
            healing_history_score=1.0,  # 100% success rate
        )

        # Candidate B: same current signals + bad history
        candidate_b = ScoredCandidate(
            selector=".login-button",
            source=CandidateSource.CURRENT_DOM,
            text_similarity=1.0,
            role_similarity=1.0,
            page_similarity=1.0,
            historical_similarity=0.0,
            healing_history_score=0.0,  # No history or 0% success
        )

        ranked = scorer.rank_candidates([candidate_b, candidate_a])

        # candidate_a should rank higher due to history
        assert ranked[0].selector == "#sign-in-btn"
        assert ranked[0].confidence > ranked[1].confidence

    def test_history_weight_at_zero_has_no_effect(self):
        """When healing_history_weight=0, history score has no effect."""
        weights = ScoringWeights(
            text_weight=0.50,
            role_weight=0.25,
            page_weight=0.25,
            type_weight=0.0,
            historical_weight=0.0,
            name_weight=0.0,
            stable_attribute_weight=0.0,
            healing_history_weight=0.0,
        )
        scorer = CandidateScorer(weights=weights)

        candidate_a = ScoredCandidate(
            selector="#a",
            source=CandidateSource.CURRENT_DOM,
            text_similarity=1.0,
            role_similarity=1.0,
            page_similarity=1.0,
            healing_history_score=1.0,
        )
        candidate_b = ScoredCandidate(
            selector="#b",
            source=CandidateSource.CURRENT_DOM,
            text_similarity=1.0,
            role_similarity=1.0,
            page_similarity=1.0,
            healing_history_score=0.0,
        )

        ranked = scorer.rank_candidates([candidate_a, candidate_b])
        # With weight=0, both should have the same score
        assert ranked[0].confidence == ranked[1].confidence

    def test_scenario_example_from_spec(self):
        """Scenario from the spec: #sign-in-btn (5/5) vs .login-button (1/4)."""
        weights = ScoringWeights(
            text_weight=0.20,
            role_weight=0.15,
            page_weight=0.10,
            historical_weight=0.10,
            type_weight=0.05,
            name_weight=0.0,
            stable_attribute_weight=0.0,
            healing_history_weight=0.40,
        )
        scorer = CandidateScorer(weights=weights)

        # #sign-in-btn: 5 attempts, 5 successes
        candidate_a = ScoredCandidate(
            selector="#sign-in-btn",
            source=CandidateSource.CURRENT_DOM,
            text_similarity=1.0,
            role_similarity=1.0,
            page_similarity=1.0,
            healing_history_score=1.0,  # 5/5 = 1.0
        )

        # .login-button: 4 attempts, 1 success, 3 failures
        candidate_b = ScoredCandidate(
            selector=".login-button",
            source=CandidateSource.CURRENT_DOM,
            text_similarity=1.0,
            role_similarity=1.0,
            page_similarity=1.0,
            healing_history_score=0.25,  # 1/4 = 0.25
        )

        ranked = scorer.rank_candidates([candidate_b, candidate_a])

        assert ranked[0].selector == "#sign-in-btn"
        assert ranked[0].confidence > ranked[1].confidence


# ══════════════════════════════════════════════════════════════
# 8. Candidate With No History (Neutral)
# ══════════════════════════════════════════════════════════════


class TestCandidateNoHistory:
    """Test that candidates with no history are NOT penalized."""

    def test_no_history_score_is_zero(
        self,
        evidence_retriever: HealingEvidenceRetriever,
    ):
        """Candidates with no history should get score 0.0 (neutral)."""
        score = evidence_retriever.compute_history_score(
            "#unknown-old", "#unknown-new",
        )
        assert score == 0.0

    def test_no_history_candidate_ranks_normally(self):
        """A candidate with no history should rank based on other signals."""
        weights = ScoringWeights(
            text_weight=0.30,
            role_weight=0.25,
            page_weight=0.15,
            historical_weight=0.10,
            type_weight=0.10,
            name_weight=0.0,
            stable_attribute_weight=0.0,
            healing_history_weight=0.10,
        )
        scorer = CandidateScorer(weights=weights)

        # No history but strong current signals
        candidate = ScoredCandidate(
            selector="#new-btn",
            source=CandidateSource.CURRENT_DOM,
            text_similarity=1.0,
            role_similarity=1.0,
            page_similarity=1.0,
            type_similarity=1.0,
            healing_history_score=0.0,  # No history
        )

        scored = scorer.score_and_update(candidate)
        # Should still get a reasonable score from other dimensions
        assert scored.confidence > 0.5

    def test_empty_stats_for_unknown_pair(
        self,
        evidence_retriever: HealingEvidenceRetriever,
    ):
        """get_replacement_stats for unknown pair returns empty stats."""
        stats = evidence_retriever.get_replacement_stats("#x", "#y")
        assert stats.attempts == 0
        assert stats.successes == 0
        assert stats.failures == 0
        assert stats.success_rate == 0.0


# ══════════════════════════════════════════════════════════════
# 9. Repeated Selector-Change Detection
# ══════════════════════════════════════════════════════════════


class TestSelectorChainDetection:
    """Test detection of repeated selector changes (A → B → C)."""

    def test_detect_simple_chain(
        self,
        memory_store: InMemoryStore,
        pattern_detector: HealingPatternDetector,
    ):
        """Detect A → B → C chain."""
        # A was replaced by B
        memory_store.store_healing_record(_make_healing_record(
            "heal_001", "TC_001", "#login-btn", "#sign-in-btn",
            validation_result=True,
            timestamp="2026-01-01T00:00:00+00:00",
        ))
        # B was later replaced by C
        memory_store.store_healing_record(_make_healing_record(
            "heal_002", "TC_001", "#sign-in-btn", "#user-login",
            validation_result=True,
            timestamp="2026-01-02T00:00:00+00:00",
        ))

        pattern = pattern_detector.detect_selector_chain("#login-btn")

        assert pattern is not None
        assert pattern.pattern_type == HealingPatternType.SELECTOR_CHAIN
        assert pattern.selectors == ["#login-btn", "#sign-in-btn", "#user-login"]
        assert pattern.occurrences == 2

    def test_no_chain_for_single_replacement(
        self,
        memory_store: InMemoryStore,
        pattern_detector: HealingPatternDetector,
    ):
        """No chain pattern for just one replacement."""
        memory_store.store_healing_record(_make_healing_record(
            "heal_001", "TC_001", "#login-btn", "#sign-in-btn",
            validation_result=True,
        ))

        pattern = pattern_detector.detect_selector_chain("#login-btn")
        # A single A→B is just 1 replacement, chain requires 2+
        assert pattern is None

    def test_no_chain_for_unknown_selector(
        self,
        pattern_detector: HealingPatternDetector,
    ):
        """No chain for unknown selectors."""
        pattern = pattern_detector.detect_selector_chain("#unknown")
        assert pattern is None

    def test_detect_all_patterns_includes_chain(
        self,
        memory_store: InMemoryStore,
        pattern_detector: HealingPatternDetector,
    ):
        """detect_all_patterns includes chain patterns."""
        memory_store.store_healing_record(_make_healing_record(
            "heal_001", "TC_001", "#a", "#b",
            validation_result=True,
            timestamp="2026-01-01T00:00:00+00:00",
        ))
        memory_store.store_healing_record(_make_healing_record(
            "heal_002", "TC_001", "#b", "#c",
            validation_result=True,
            timestamp="2026-01-02T00:00:00+00:00",
        ))

        patterns = pattern_detector.detect_all_patterns("#a")
        chain_patterns = [
            p for p in patterns
            if p.pattern_type == HealingPatternType.SELECTOR_CHAIN
        ]
        assert len(chain_patterns) == 1


# ══════════════════════════════════════════════════════════════
# 10. Repeated Successful Replacement Detection
# ══════════════════════════════════════════════════════════════


class TestReliableReplacementDetection:
    """Test detection of reliable (repeated success) replacements."""

    def test_detect_reliable_replacement(
        self,
        memory_store: InMemoryStore,
        pattern_detector: HealingPatternDetector,
    ):
        """Detect a replacement that succeeded multiple times."""
        for i in range(3):
            memory_store.store_healing_record(_make_healing_record(
                f"heal_{i:03d}", "TC_001", "#login-btn", "#sign-in-btn",
                validation_result=True,
                timestamp=f"2026-01-0{i + 1}T00:00:00+00:00",
            ))

        patterns = pattern_detector.detect_reliable_replacements("#login-btn")

        assert len(patterns) == 1
        assert patterns[0].pattern_type == HealingPatternType.RELIABLE_REPLACEMENT
        assert patterns[0].selectors == ["#login-btn", "#sign-in-btn"]
        assert patterns[0].occurrences == 3
        assert patterns[0].confidence_signal == 1.0

    def test_detect_unreliable_replacement(
        self,
        memory_store: InMemoryStore,
        pattern_detector: HealingPatternDetector,
    ):
        """Detect a replacement that failed repeatedly."""
        for i in range(3):
            memory_store.store_healing_record(_make_healing_record(
                f"heal_{i:03d}", "TC_001", "#login-btn", ".bad-selector",
                validation_result=False,
                timestamp=f"2026-01-0{i + 1}T00:00:00+00:00",
            ))

        patterns = pattern_detector.detect_unreliable_replacements("#login-btn")

        assert len(patterns) == 1
        assert patterns[0].pattern_type == HealingPatternType.UNRELIABLE_REPLACEMENT
        assert patterns[0].selectors == ["#login-btn", ".bad-selector"]
        assert patterns[0].occurrences == 3

    def test_no_pattern_below_threshold(
        self,
        memory_store: InMemoryStore,
        pattern_detector: HealingPatternDetector,
    ):
        """No pattern detected if occurrences < threshold."""
        memory_store.store_healing_record(_make_healing_record(
            "heal_001", "TC_001", "#login-btn", "#sign-in-btn",
            validation_result=True,
        ))

        # Only 1 success, threshold is 2
        patterns = pattern_detector.detect_reliable_replacements("#login-btn")
        assert len(patterns) == 0


# ══════════════════════════════════════════════════════════════
# 11. LLM Cannot Invent Selectors
# ══════════════════════════════════════════════════════════════


class TestLLMGrounding:
    """Test that LLM cannot invent selectors (existing grounding validation)."""

    def test_grounding_rejects_invented_selector(self):
        """LLM evaluation rejects selectors not in the candidate list."""
        from agents.healer.healing_schemas import LLMEvaluationResult

        result = LLMEvaluationResult(
            selected_selector="#invented-selector",
            confidence=0.95,
            reason="Looks good",
        )

        valid_selectors = {"#sign-in-btn", ".login-button"}

        is_grounded = LLMHealingEvaluator._validate_grounding(
            result, valid_selectors,
        )
        assert is_grounded is False

    def test_grounding_accepts_valid_selector(self):
        """LLM evaluation accepts selectors in the candidate list."""
        from agents.healer.healing_schemas import LLMEvaluationResult

        result = LLMEvaluationResult(
            selected_selector="#sign-in-btn",
            confidence=0.90,
            reason="Best match",
        )

        valid_selectors = {"#sign-in-btn", ".login-button"}

        is_grounded = LLMHealingEvaluator._validate_grounding(
            result, valid_selectors,
        )
        assert is_grounded is True


# ══════════════════════════════════════════════════════════════
# 12. Healing Cannot Be Marked Successful Without Validation
# ══════════════════════════════════════════════════════════════


class TestHealingValidationRequirement:
    """Test that healing success requires actual browser validation."""

    def test_recommendation_always_requires_validation(self):
        """HealingRecommendation.requires_validation is always True."""
        with pytest.raises(ValueError, match="requires_validation must always be True"):
            HealingRecommendation(
                test_id="TC_001",
                execution_id="exec_001",
                failed_step=1,
                failure_type=FailureType.ELEMENT_NOT_FOUND,
                confidence=ConfidenceLevel.HIGH,
                recommended_action=HealingAction.TRY_REPLACEMENT_SELECTOR,
                decision=HealingDecision.RECOMMEND_HEALING,
                requires_validation=False,  # Must be True
            )

    def test_candidate_always_requires_validation(self):
        """HealingCandidate.requires_validation defaults to True."""
        candidate = HealingCandidate(
            test_id="TC_001",
            failed_step=1,
            healing_attempted=True,
            old_selector="#login-btn",
            new_selector="#sign-in-btn",
            confidence=0.90,
        )
        assert candidate.requires_validation is True

    def test_feedback_processor_derives_from_validation_status(
        self,
        feedback_processor: HealingResultFeedbackProcessor,
    ):
        """Processor derives validation_result from Member 2 status only."""
        # SUCCESS → True
        success_feedback = HealingResultFeedback(
            test_case_id="TC_001",
            original_selector="#login-btn",
            attempted_selector="#sign-in-btn",
            healing_status=HealingStatus.VALIDATED_SUCCESS,
            validation_status=ValidationStatus.SUCCESS,
            confidence=0.90,
        )
        record = feedback_processor.process_feedback(success_feedback)
        assert record.validation_result is True

        # FAILURE → False
        failure_feedback = HealingResultFeedback(
            test_case_id="TC_002",
            original_selector="#login-btn",
            attempted_selector=".bad",
            healing_status=HealingStatus.VALIDATED_FAILURE,
            validation_status=ValidationStatus.FAILURE,
            confidence=0.50,
        )
        record = feedback_processor.process_feedback(failure_feedback)
        assert record.validation_result is False


# ══════════════════════════════════════════════════════════════
# 13. End-to-End Feedback Loop
# ══════════════════════════════════════════════════════════════


class TestEndToEndFeedbackLoop:
    """Full scenario: failure → recommendation → validation → feedback → future evidence."""

    @pytest.mark.asyncio
    async def test_full_feedback_loop(self):
        """End-to-end: healing result feeds into future decisions."""
        memory_store = InMemoryStore()
        feedback_processor = HealingResultFeedbackProcessor(memory_store)
        evidence_retriever = HealingEvidenceRetriever(memory_store)

        # ── Step 1: Store previous element in memory ──
        previous_element = _make_element(
            element_id="elem_login_btn",
            selector="#login-btn",
            text="Login",
            role="button",
            page_url="https://app.example.com/login",
        )
        memory_store.store_element(previous_element)

        # ── Step 2: Simulate previous successful healing ──
        # #sign-in-btn succeeded twice before
        for i in range(2):
            feedback = HealingResultFeedback(
                healing_id=f"heal_prev_{i}",
                test_case_id="TC_LOGIN_001",
                original_selector="#login-btn",
                attempted_selector="#sign-in-btn",
                healing_status=HealingStatus.VALIDATED_SUCCESS,
                validation_status=ValidationStatus.SUCCESS,
                confidence=0.85,
                failure_category=FailureType.ELEMENT_NOT_FOUND,
                timestamp=f"2026-01-0{i + 1}T00:00:00+00:00",
            )
            feedback_processor.process_feedback(feedback)

        # .login-button failed 3 times before
        for i in range(3):
            feedback = HealingResultFeedback(
                healing_id=f"heal_fail_{i}",
                test_case_id="TC_LOGIN_001",
                original_selector="#login-btn",
                attempted_selector=".login-button",
                healing_status=HealingStatus.VALIDATED_FAILURE,
                validation_status=ValidationStatus.FAILURE,
                confidence=0.60,
                failure_category=FailureType.ELEMENT_NOT_FOUND,
                timestamp=f"2026-01-0{i + 1}T00:00:00+00:00",
            )
            feedback_processor.process_feedback(feedback)

        # ── Step 3: Verify historical evidence ──
        stats_good = evidence_retriever.get_replacement_stats(
            "#login-btn", "#sign-in-btn",
        )
        assert stats_good.successes == 2
        assert stats_good.failures == 0
        assert stats_good.success_rate == 1.0

        stats_bad = evidence_retriever.get_replacement_stats(
            "#login-btn", ".login-button",
        )
        assert stats_bad.successes == 0
        assert stats_bad.failures == 3
        assert stats_bad.success_rate == 0.0

        # ── Step 4: Create healing decision with history-aware weights ──
        weights = ScoringWeights(
            text_weight=0.20,
            role_weight=0.15,
            page_weight=0.10,
            historical_weight=0.10,
            type_weight=0.05,
            name_weight=0.0,
            stable_attribute_weight=0.0,
            healing_history_weight=0.40,
        )

        engine = HealingDecisionEngine(
            memory_store=memory_store,
            weights=weights,
        )

        # ── Step 5: Build current UI with two candidate elements ──
        current_elements = [
            _make_element(
                element_id="elem_sign_in",
                selector="#sign-in-btn",
                text="Login",
                role="button",
                page_url="https://app.example.com/login",
            ),
            _make_element(
                element_id="elem_login_button",
                selector=".login-button",
                text="Login",
                role="button",
                page_url="https://app.example.com/login",
            ),
        ]

        analysis = _make_failure_analysis(
            previous_element=previous_element,
        )

        context = HealingContext(
            failure_analysis=analysis,
            current_elements=current_elements,
            page_url="https://app.example.com/login",
        )

        # ── Step 6: Generate recommendation ──
        recommendation = await engine.generate_recommendation(context)

        assert recommendation.requires_validation is True
        assert recommendation.candidates  # Should have candidates

        # The top candidate should be #sign-in-btn (100% history)
        # over .login-button (0% history)
        if recommendation.selected_candidate:
            assert recommendation.selected_candidate.selector == "#sign-in-btn"

        # ── Step 7: Simulate Member 2 validating ──
        new_feedback = HealingResultFeedback(
            healing_id="heal_new_001",
            test_case_id="TC_LOGIN_001",
            original_selector="#login-btn",
            attempted_selector="#sign-in-btn",
            healing_status=HealingStatus.VALIDATED_SUCCESS,
            validation_status=ValidationStatus.SUCCESS,
            confidence=0.95,
            failure_category=FailureType.ELEMENT_NOT_FOUND,
        )
        feedback_processor.process_feedback(new_feedback)

        # ── Step 8: Verify updated historical evidence ──
        updated_stats = evidence_retriever.get_replacement_stats(
            "#login-btn", "#sign-in-btn",
        )
        assert updated_stats.successes == 3  # Was 2, now 3
        assert updated_stats.success_rate == 1.0

        # ── Step 9: Verify pattern detection ──
        pattern_detector = HealingPatternDetector(memory_store)
        patterns = pattern_detector.detect_all_patterns("#login-btn")

        # Should detect reliable replacement pattern (3 successes)
        reliable = [
            p for p in patterns
            if p.pattern_type == HealingPatternType.RELIABLE_REPLACEMENT
        ]
        assert len(reliable) >= 1
        assert reliable[0].selectors == ["#login-btn", "#sign-in-btn"]

        # Should detect unreliable replacement pattern (3 failures)
        unreliable = [
            p for p in patterns
            if p.pattern_type == HealingPatternType.UNRELIABLE_REPLACEMENT
        ]
        assert len(unreliable) >= 1
        assert unreliable[0].selectors == ["#login-btn", ".login-button"]

    @pytest.mark.asyncio
    async def test_history_score_enrichment_in_engine(self):
        """Verify the decision engine enriches candidates with history scores."""
        memory_store = InMemoryStore()

        # Seed a previous success
        memory_store.store_healing_record(_make_healing_record(
            "heal_001", "TC_001", "#old-btn", "#new-btn",
            validation_result=True,
        ))

        # Previous element
        previous_element = _make_element(
            element_id="elem_old",
            selector="#old-btn",
            text="Submit",
            role="button",
        )
        memory_store.store_element(previous_element)

        current_elements = [
            _make_element(
                element_id="elem_new",
                selector="#new-btn",
                text="Submit",
                role="button",
            ),
        ]

        weights = ScoringWeights(
            text_weight=0.30,
            role_weight=0.20,
            page_weight=0.15,
            historical_weight=0.10,
            type_weight=0.05,
            name_weight=0.0,
            stable_attribute_weight=0.0,
            healing_history_weight=0.20,
        )

        engine = HealingDecisionEngine(
            memory_store=memory_store,
            weights=weights,
        )

        analysis = _make_failure_analysis(
            test_id="TC_001",
            failed_target="#old-btn",
            previous_element=previous_element,
        )

        context = HealingContext(
            failure_analysis=analysis,
            current_elements=current_elements,
            page_url="https://app.example.com/login",
        )

        recommendation = await engine.generate_recommendation(context)

        # Verify the candidate was enriched with history score
        found = False
        for c in recommendation.candidates:
            if c.selector == "#new-btn":
                found = True
                # Should have healing_history_score > 0 from the seeded success
                assert c.healing_history_score > 0.0
                break

        assert found, "Expected #new-btn candidate not found"


# ══════════════════════════════════════════════════════════════
# Additional Edge Case Tests
# ══════════════════════════════════════════════════════════════


class TestEdgeCases:
    """Additional edge case and safety tests."""

    def test_get_healing_history_for_replacement(
        self,
        memory_store: InMemoryStore,
    ):
        """Verify replacement-specific history filtering works."""
        # Store records for different replacements
        memory_store.store_healing_record(_make_healing_record(
            "heal_001", "TC_001", "#btn", "#new-btn-1",
            validation_result=True,
        ))
        memory_store.store_healing_record(_make_healing_record(
            "heal_002", "TC_001", "#btn", "#new-btn-2",
            validation_result=False,
        ))
        memory_store.store_healing_record(_make_healing_record(
            "heal_003", "TC_001", "#btn", "#new-btn-1",
            validation_result=True,
        ))

        # Filter for #new-btn-1 only
        records = memory_store.get_healing_history_for_replacement(
            "#btn", "#new-btn-1",
        )
        assert len(records) == 2
        assert all(r.new_selector == "#new-btn-1" for r in records)

        # Filter for #new-btn-2
        records = memory_store.get_healing_history_for_replacement(
            "#btn", "#new-btn-2",
        )
        assert len(records) == 1
        assert records[0].new_selector == "#new-btn-2"

    def test_avg_confidence_in_stats(
        self,
        memory_store: InMemoryStore,
        evidence_retriever: HealingEvidenceRetriever,
    ):
        """Average confidence is computed correctly."""
        memory_store.store_healing_record(_make_healing_record(
            "heal_001", "TC_001", "#btn", "#new-btn",
            confidence=0.80, validation_result=True,
        ))
        memory_store.store_healing_record(_make_healing_record(
            "heal_002", "TC_001", "#btn", "#new-btn",
            confidence=0.90, validation_result=True,
        ))

        stats = evidence_retriever.get_replacement_stats("#btn", "#new-btn")
        assert stats.avg_confidence == 0.85

    def test_validation_status_enum_values(self):
        """Verify ValidationStatus enum has expected values."""
        assert ValidationStatus.SUCCESS.value == "SUCCESS"
        assert ValidationStatus.FAILURE.value == "FAILURE"
        assert ValidationStatus.ERROR.value == "ERROR"
        assert ValidationStatus.SKIPPED.value == "SKIPPED"

    def test_healing_pattern_type_enum_values(self):
        """Verify HealingPatternType enum has expected values."""
        assert HealingPatternType.SELECTOR_CHAIN.value == "SELECTOR_CHAIN"
        assert HealingPatternType.RELIABLE_REPLACEMENT.value == "RELIABLE_REPLACEMENT"
        assert HealingPatternType.UNRELIABLE_REPLACEMENT.value == "UNRELIABLE_REPLACEMENT"

    def test_prepare_healing_result_backward_compat(self):
        """Verify existing prepare_healing_result still works."""
        result = prepare_healing_result(
            test_id="TC_001",
            old_selector="#login-btn",
            new_selector="#sign-in-btn",
            validation_success=True,
            confidence=0.94,
        )
        assert result.status == HealingStatus.VALIDATED_SUCCESS
        assert result.old_selector == "#login-btn"
        assert result.new_selector == "#sign-in-btn"

    def test_healing_result_to_memory_update_backward_compat(self):
        """Verify existing healing_result_to_memory_update still works."""
        result = HealingResult(
            test_id="TC_001",
            failed_step=1,
            old_selector="#login-btn",
            new_selector="#sign-in-btn",
            status=HealingStatus.VALIDATED_SUCCESS,
            confidence=0.94,
        )
        update = healing_result_to_memory_update(result)
        assert update["is_success"] is True
        assert update["healing_record"]["old_selector"] == "#login-btn"
        assert update["healing_record"]["validation_result"] is True

    def test_healing_feedback_reason_includes_category(self):
        """Feedback reason includes failure category when provided."""
        feedback = HealingResultFeedback(
            test_case_id="TC_001",
            original_selector="#login-btn",
            attempted_selector="#sign-in-btn",
            healing_status=HealingStatus.VALIDATED_SUCCESS,
            validation_status=ValidationStatus.SUCCESS,
            confidence=0.90,
            failure_category=FailureType.ELEMENT_NOT_FOUND,
        )
        reason = HealingResultFeedbackProcessor._build_healing_reason(feedback)
        assert "ELEMENT_NOT_FOUND" in reason

    def test_healing_feedback_reason_includes_error(self):
        """Feedback reason includes error when provided."""
        feedback = HealingResultFeedback(
            test_case_id="TC_001",
            original_selector="#login-btn",
            attempted_selector="#sign-in-btn",
            healing_status=HealingStatus.VALIDATED_FAILURE,
            validation_status=ValidationStatus.FAILURE,
            confidence=0.50,
            error_reason="Timeout after 30s",
        )
        reason = HealingResultFeedbackProcessor._build_healing_reason(feedback)
        assert "Timeout after 30s" in reason
