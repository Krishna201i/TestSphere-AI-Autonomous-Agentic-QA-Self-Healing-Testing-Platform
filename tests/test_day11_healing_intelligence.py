"""
TestSphere-AI — Day 11: AI-Assisted Healing Decision & Candidate Ranking Tests

Comprehensive test suite for the Day 11 intelligence layer:

- Candidate evidence with stable attributes
- Deterministic scoring with stable_attribute dimension
- Candidate ranking (multiple candidates, verify order)
- Confidence threshold classification (HIGH, MEDIUM, LOW)
- Ambiguity detection (scores within threshold → REQUIRE_FURTHER_ANALYSIS)
- Final HealingDecision structure
- Invalid LLM candidate rejection (grounding validation)
- Valid LLM recommendation passes validation
- No-candidate behavior → DO_NOT_HEAL
- Low-confidence behavior → DO_NOT_HEAL / REQUIRE_FURTHER_ANALYSIS
- High-confidence behavior → RECOMMEND_HEALING
- Member 2 contract mapping with decision field
- Healing result preparation (prepare_healing_result)

Scenario Tests (Task 12):
- Scenario 1: Clear winner (0.94 vs 0.55) → RECOMMEND_HEALING
- Scenario 2: Ambiguous (0.84 vs 0.82) → REQUIRE_FURTHER_ANALYSIS
- Scenario 3: Low confidence (best = 0.32) → DO_NOT_HEAL
- Scenario 4: Invalid LLM candidate → rejection
- Scenario 5: Valid LLM recommendation → passes validation
- Scenario 6: No candidates → DO_NOT_HEAL

Integration Test (Task 14):
- Full pipeline: Memory → Analyzer → Decision Engine → HealingRecommendation

All tests are offline, no browser, no API keys, no real models.
"""

from __future__ import annotations

import json
from typing import Optional

import pytest
import pytest_asyncio

from agents.analyzer.analyzer import FailureAnalyzerAgent
from agents.analyzer.schemas import (
    FailureAnalysis,
    FailureContext,
    FailureEvidence,
    HistoricalContext,
)
from agents.healer.candidate_generator import CandidateGenerator
from agents.healer.candidate_scorer import CandidateScorer, ScoringWeights
from agents.healer.healing_decision import (
    ConfidenceThresholds,
    HealingDecisionEngine,
)
from agents.healer.healing_result_mapper import (
    healing_result_to_memory_update,
    prepare_healing_result,
    recommendation_to_healing_candidate,
)
from agents.healer.healing_schemas import (
    HealingContext,
    HealingRecommendation,
    LLMEvaluationResult,
    ScoredCandidate,
)
from agents.healer.llm_healing_evaluator import LLMHealingEvaluator
from agents.healer.schemas import HealingCandidate, HealingResult
from agents.llm.client import LLMClient, LLMClientSession
from agents.llm.config import LLMConfig
from agents.llm.schemas import LLMRequest, LLMResponse, LLMUsage
from agents.memory.context_comparator import ContextComparator
from agents.memory.in_memory_store import InMemoryStore
from agents.memory.memory_schemas import (
    ElementRecord,
    FailureInfo,
    HealingRecord,
    TestExecutionRecord,
)
from agents.schemas.enums import (
    CandidateSource,
    ConfidenceLevel,
    ExecutionStatus,
    FailureType,
    HealingAction,
    HealingDecision,
    HealingStatus,
)


# ═══════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def memory_store() -> InMemoryStore:
    """Fresh in-memory store for each test."""
    return InMemoryStore()


@pytest.fixture
def comparator() -> ContextComparator:
    return ContextComparator()


@pytest.fixture
def generator(memory_store: InMemoryStore) -> CandidateGenerator:
    return CandidateGenerator(memory_store=memory_store)


@pytest.fixture
def scorer() -> CandidateScorer:
    return CandidateScorer()


@pytest.fixture
def engine(memory_store: InMemoryStore) -> HealingDecisionEngine:
    return HealingDecisionEngine(memory_store=memory_store)


def _make_element(
    element_id: str = "elem_login_btn",
    selector: str = "#login-btn",
    text: str = "Login",
    role: str = "button",
    page_url: str = "https://app.example.com/login",
    page_name: str = "Login Page",
    attributes: Optional[dict] = None,
) -> ElementRecord:
    """Helper to create an ElementRecord."""
    return ElementRecord(
        element_id=element_id,
        selector=selector,
        text=text,
        role=role,
        page_url=page_url,
        page_name=page_name,
        attributes=attributes or {"type": "submit", "name": "login"},
    )


def _make_failure_analysis(
    test_id: str = "TC_LOGIN_001",
    execution_id: str = "exec_001",
    failure_type: FailureType = FailureType.ELEMENT_NOT_FOUND,
    failed_target: str = "#login-btn",
    failed_step: int = 3,
    confidence: ConfidenceLevel = ConfidenceLevel.HIGH,
    previous_element: Optional[ElementRecord] = None,
) -> FailureAnalysis:
    """Helper to create a FailureAnalysis."""
    historical = None
    if previous_element is not None:
        historical = HistoricalContext(
            previous_executions_count=5,
            previous_successes_count=4,
            previous_failures_count=1,
            previous_element=previous_element,
        )

    return FailureAnalysis(
        test_id=test_id,
        execution_id=execution_id,
        failure_type=failure_type,
        root_cause="Target element not found",
        confidence=confidence,
        failed_step=failed_step,
        failed_target=failed_target,
        evidence=[
            FailureEvidence(
                evidence_type="element_not_found",
                description="Target element cannot be located",
            ),
        ],
        historical_context=historical,
        recommended_action=(
            __import__("agents.schemas.enums", fromlist=["RecommendedAction"])
            .RecommendedAction
            .SEARCH_FOR_REPLACEMENT_SELECTOR
        ),
    )


def _make_healing_context(
    failure_analysis: Optional[FailureAnalysis] = None,
    current_elements: Optional[list[ElementRecord]] = None,
    page_url: str = "https://app.example.com/login",
) -> HealingContext:
    """Helper to create a HealingContext."""
    if failure_analysis is None:
        previous = _make_element()
        failure_analysis = _make_failure_analysis(previous_element=previous)

    return HealingContext(
        failure_analysis=failure_analysis,
        current_elements=current_elements or [],
        page_url=page_url,
    )


# ═══════════════════════════════════════════════════════════════
# MOCK LLM PROVIDERS
# ═══════════════════════════════════════════════════════════════


class _MockHealingLLMProvider(LLMClient):
    """Mock LLM provider that returns configurable responses."""

    def __init__(self, response_data: dict):
        config = LLMConfig(provider="mock", model="mock-healing")
        super().__init__(config)
        self._response_data = response_data

    async def generate(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(
            content=json.dumps(self._response_data),
            model="mock-healing",
            provider="mock",
            usage=LLMUsage(prompt_tokens=50, completion_tokens=20),
        )


class _FailingLLMProvider(LLMClient):
    """Mock LLM provider that always raises an error."""

    def __init__(self):
        super().__init__(
            LLMConfig(provider="mock", model="mock-fail"),
        )

    async def generate(self, request: LLMRequest) -> LLMResponse:
        raise RuntimeError("LLM unavailable")


# ═══════════════════════════════════════════════════════════════
# CANDIDATE EVIDENCE WITH STABLE ATTRIBUTES
# ═══════════════════════════════════════════════════════════════


class TestCandidateEvidenceStableAttributes:
    """Test that candidate evidence includes stable attribute information."""

    def test_stable_attribute_evidence_generated(
        self, memory_store: InMemoryStore,
    ):
        """Elements with matching stable attributes should produce evidence."""
        previous = _make_element(
            selector="#login-btn",
            text="Login",
            role="button",
            attributes={
                "type": "submit",
                "name": "login",
                "data-testid": "login-button",
                "aria-label": "Login to your account",
            },
        )
        current = _make_element(
            element_id="elem_new",
            selector="#sign-in-btn",
            text="Login",
            role="button",
            attributes={
                "type": "submit",
                "name": "login",
                "data-testid": "login-button",
                "aria-label": "Login to your account",
            },
        )

        analysis = _make_failure_analysis(previous_element=previous)
        ctx = _make_healing_context(
            failure_analysis=analysis,
            current_elements=[current],
        )

        gen = CandidateGenerator(memory_store=memory_store)
        candidates = gen.generate_candidates(ctx)

        assert len(candidates) == 1
        c = candidates[0]
        assert c.stable_attribute_similarity > 0.0
        assert any("stable attribute" in e.lower() for e in c.evidence)

    def test_no_stable_attributes_no_evidence(
        self, memory_store: InMemoryStore,
    ):
        """Elements without stable attributes should not produce stable attr evidence."""
        previous = _make_element(
            selector="#login-btn",
            attributes={"type": "submit", "name": "login"},
        )
        current = _make_element(
            element_id="elem_new",
            selector="#sign-in-btn",
            attributes={"type": "submit", "name": "login"},
        )

        analysis = _make_failure_analysis(previous_element=previous)
        ctx = _make_healing_context(
            failure_analysis=analysis,
            current_elements=[current],
        )

        gen = CandidateGenerator(memory_store=memory_store)
        candidates = gen.generate_candidates(ctx)

        assert len(candidates) == 1
        c = candidates[0]
        assert c.stable_attribute_similarity == 0.0
        assert not any("stable attribute" in e.lower() for e in c.evidence)

    def test_partial_stable_attribute_match(
        self, memory_store: InMemoryStore,
    ):
        """Partial stable attribute matches should produce fractional score."""
        previous = _make_element(
            selector="#login-btn",
            attributes={
                "type": "submit",
                "data-testid": "login-button",
                "aria-label": "Login",
                "class": "btn-primary",
            },
        )
        current = _make_element(
            element_id="elem_new",
            selector="#sign-in-btn",
            attributes={
                "type": "submit",
                "data-testid": "login-button",
                "aria-label": "Sign in",  # Different!
                "class": "btn-primary",
            },
        )

        analysis = _make_failure_analysis(previous_element=previous)
        ctx = _make_healing_context(
            failure_analysis=analysis,
            current_elements=[current],
        )

        gen = CandidateGenerator(memory_store=memory_store)
        candidates = gen.generate_candidates(ctx)

        assert len(candidates) == 1
        c = candidates[0]
        # 2 out of 3 stable attributes match (data-testid, class)
        assert 0.0 < c.stable_attribute_similarity < 1.0


# ═══════════════════════════════════════════════════════════════
# DETERMINISTIC SCORING WITH STABLE ATTRIBUTES
# ═══════════════════════════════════════════════════════════════


class TestDeterministicScoring:
    """Test deterministic scoring with the new stable_attribute dimension."""

    def test_stable_attribute_contributes_to_score(self):
        """stable_attribute_similarity should contribute to the final score."""
        scorer = CandidateScorer(weights=ScoringWeights(stable_attribute_weight=0.10))
        c = ScoredCandidate(
            selector="#btn",
            source=CandidateSource.CURRENT_DOM,
            stable_attribute_similarity=1.0,
        )
        score = scorer.score_candidate(c)
        assert score > 0.0
        assert abs(score - 0.0909) < 0.01

    def test_full_match_with_stable_attributes(self):
        """All dimensions including stable_attribute should produce ~1.0."""
        scorer = CandidateScorer()
        c = ScoredCandidate(
            selector="#btn",
            source=CandidateSource.CURRENT_DOM,
            text_similarity=1.0,
            role_similarity=1.0,
            type_similarity=1.0,
            page_similarity=1.0,
            historical_similarity=1.0,
            name_similarity=1.0,
            stable_attribute_similarity=1.0,
        )
        score = scorer.score_candidate(c)
        assert abs(score - 1.0) < 0.01

    def test_scoring_is_deterministic(self):
        """Given the same inputs, score must be identical every time."""
        scorer = CandidateScorer()
        c = ScoredCandidate(
            selector="#btn",
            source=CandidateSource.CURRENT_DOM,
            text_similarity=0.8,
            role_similarity=0.6,
            type_similarity=0.4,
            page_similarity=1.0,
            stable_attribute_similarity=0.5,
        )
        score1 = scorer.score_candidate(c)
        score2 = scorer.score_candidate(c)
        score3 = scorer.score_candidate(c)
        assert score1 == score2 == score3

    def test_custom_weights_with_stable_attribute(self):
        """Custom weights should include stable_attribute_weight."""
        weights = ScoringWeights(
            text_weight=0.0,
            role_weight=0.0,
            type_weight=0.0,
            page_weight=0.0,
            historical_weight=0.0,
            name_weight=0.0,
            stable_attribute_weight=1.0,
        )
        scorer = CandidateScorer(weights=weights)
        c = ScoredCandidate(
            selector="#btn",
            source=CandidateSource.CURRENT_DOM,
            stable_attribute_similarity=0.75,
        )
        score = scorer.score_candidate(c)
        assert abs(score - 0.75) < 0.01

    def test_weights_sum_includes_stable_attribute(self):
        """ScoringWeights.total should include stable_attribute_weight."""
        weights = ScoringWeights(stable_attribute_weight=0.10)
        assert weights.stable_attribute_weight == 0.10
        assert abs(weights.total - 1.10) < 0.01


# ═══════════════════════════════════════════════════════════════
# CANDIDATE RANKING
# ═══════════════════════════════════════════════════════════════


class TestCandidateRankingDay11:
    """Test candidate ranking with Day 11 scoring."""

    def test_ranking_order(self):
        """Candidates should be ranked by confidence, highest first."""
        scorer = CandidateScorer()
        candidates = [
            ScoredCandidate(
                selector="#continue-btn",
                source=CandidateSource.CURRENT_DOM,
                role_similarity=1.0,
            ),
            ScoredCandidate(
                selector="#sign-in-btn",
                source=CandidateSource.CURRENT_DOM,
                text_similarity=1.0,
                role_similarity=1.0,
                page_similarity=1.0,
                stable_attribute_similarity=0.8,
            ),
            ScoredCandidate(
                selector="#submit-btn",
                source=CandidateSource.CURRENT_DOM,
                role_similarity=1.0,
                page_similarity=1.0,
            ),
        ]

        ranked = scorer.rank_candidates(candidates)

        assert len(ranked) == 3
        assert ranked[0].selector == "#sign-in-btn"
        assert ranked[0].confidence > ranked[1].confidence
        assert ranked[1].confidence > ranked[2].confidence

    def test_ranking_preserves_candidate_data(self):
        """Ranking should preserve all candidate fields except confidence."""
        scorer = CandidateScorer()
        c = ScoredCandidate(
            selector="#sign-in-btn",
            selector_type="id",
            source=CandidateSource.CURRENT_DOM,
            evidence=["Same text", "Same role"],
            text_similarity=1.0,
            role_similarity=1.0,
        )
        ranked = scorer.rank_candidates([c])
        assert ranked[0].selector == "#sign-in-btn"
        assert ranked[0].selector_type == "id"
        assert ranked[0].evidence == ["Same text", "Same role"]
        assert ranked[0].confidence > 0.0


# ═══════════════════════════════════════════════════════════════
# CONFIDENCE THRESHOLDS
# ═══════════════════════════════════════════════════════════════


class TestConfidenceThresholdsDay11:
    """Test confidence level classification."""

    def test_high_confidence(self, engine: HealingDecisionEngine):
        assert engine._classify_confidence(0.85) == ConfidenceLevel.HIGH
        assert engine._classify_confidence(0.80) == ConfidenceLevel.HIGH
        assert engine._classify_confidence(1.0) == ConfidenceLevel.HIGH

    def test_medium_confidence(self, engine: HealingDecisionEngine):
        assert engine._classify_confidence(0.50) == ConfidenceLevel.MEDIUM
        assert engine._classify_confidence(0.65) == ConfidenceLevel.MEDIUM
        assert engine._classify_confidence(0.79) == ConfidenceLevel.MEDIUM

    def test_low_confidence(self, engine: HealingDecisionEngine):
        assert engine._classify_confidence(0.0) == ConfidenceLevel.LOW
        assert engine._classify_confidence(0.30) == ConfidenceLevel.LOW
        assert engine._classify_confidence(0.49) == ConfidenceLevel.LOW

    def test_configurable_thresholds(self, memory_store: InMemoryStore):
        thresholds = ConfidenceThresholds(
            high_threshold=0.90,
            medium_threshold=0.60,
            minimum_healing_threshold=0.40,
            ambiguity_threshold=0.08,
        )
        engine = HealingDecisionEngine(
            memory_store=memory_store, thresholds=thresholds,
        )
        assert engine._classify_confidence(0.85) == ConfidenceLevel.MEDIUM
        assert engine._classify_confidence(0.90) == ConfidenceLevel.HIGH
        assert engine._classify_confidence(0.55) == ConfidenceLevel.LOW


# ═══════════════════════════════════════════════════════════════
# AMBIGUITY DETECTION
# ═══════════════════════════════════════════════════════════════


class TestAmbiguityDetection:
    """Test ambiguity detection between top candidates."""

    def test_ambiguous_when_gap_within_threshold(
        self, engine: HealingDecisionEngine,
    ):
        """Candidates within 0.05 gap should be ambiguous."""
        ranked = [
            ScoredCandidate(
                selector="#a",
                source=CandidateSource.CURRENT_DOM,
                confidence=0.84,
            ),
            ScoredCandidate(
                selector="#b",
                source=CandidateSource.CURRENT_DOM,
                confidence=0.82,
            ),
        ]
        assert engine._detect_ambiguity(ranked) is True

    def test_not_ambiguous_when_gap_exceeds_threshold(
        self, engine: HealingDecisionEngine,
    ):
        """Candidates with gap > 0.05 should not be ambiguous."""
        ranked = [
            ScoredCandidate(
                selector="#a",
                source=CandidateSource.CURRENT_DOM,
                confidence=0.94,
            ),
            ScoredCandidate(
                selector="#b",
                source=CandidateSource.CURRENT_DOM,
                confidence=0.55,
            ),
        ]
        assert engine._detect_ambiguity(ranked) is False

    def test_not_ambiguous_with_single_candidate(
        self, engine: HealingDecisionEngine,
    ):
        """Single candidate cannot be ambiguous."""
        ranked = [
            ScoredCandidate(
                selector="#a",
                source=CandidateSource.CURRENT_DOM,
                confidence=0.90,
            ),
        ]
        assert engine._detect_ambiguity(ranked) is False

    def test_not_ambiguous_with_no_candidates(
        self, engine: HealingDecisionEngine,
    ):
        """Empty list is not ambiguous."""
        assert engine._detect_ambiguity([]) is False

    def test_ambiguity_exactly_at_threshold(
        self, engine: HealingDecisionEngine,
    ):
        """Gap equal to threshold should be considered ambiguous."""
        ranked = [
            ScoredCandidate(
                selector="#a",
                source=CandidateSource.CURRENT_DOM,
                confidence=0.85,
            ),
            ScoredCandidate(
                selector="#b",
                source=CandidateSource.CURRENT_DOM,
                confidence=0.80,
            ),
        ]
        # Default ambiguity_threshold is 0.05, gap is exactly 0.05
        assert engine._detect_ambiguity(ranked) is True

    def test_custom_ambiguity_threshold(self, memory_store: InMemoryStore):
        """Custom ambiguity threshold should be respected."""
        thresholds = ConfidenceThresholds(ambiguity_threshold=0.10)
        engine = HealingDecisionEngine(
            memory_store=memory_store, thresholds=thresholds,
        )
        ranked = [
            ScoredCandidate(
                selector="#a",
                source=CandidateSource.CURRENT_DOM,
                confidence=0.85,
            ),
            ScoredCandidate(
                selector="#b",
                source=CandidateSource.CURRENT_DOM,
                confidence=0.76,
            ),
        ]
        # Gap is 0.09, threshold is 0.10 → ambiguous
        assert engine._detect_ambiguity(ranked) is True


# ═══════════════════════════════════════════════════════════════
# HEALING DECISION STRUCTURE
# ═══════════════════════════════════════════════════════════════


class TestHealingDecisionStructure:
    """Test the HealingDecision enum and its mapping."""

    def test_healing_decision_enum_values(self):
        """HealingDecision should have all four values."""
        assert HealingDecision.RECOMMEND_HEALING == "RECOMMEND_HEALING"
        assert HealingDecision.REQUIRE_VALIDATION == "REQUIRE_VALIDATION"
        assert HealingDecision.REQUIRE_FURTHER_ANALYSIS == "REQUIRE_FURTHER_ANALYSIS"
        assert HealingDecision.DO_NOT_HEAL == "DO_NOT_HEAL"

    def test_recommendation_includes_decision_field(self):
        """HealingRecommendation should include the decision field."""
        rec = HealingRecommendation(
            test_id="TC_001",
            execution_id="exec_001",
            failed_step=1,
            failure_type=FailureType.SELECTOR_CHANGED,
            confidence=ConfidenceLevel.HIGH,
            recommended_action=HealingAction.TRY_REPLACEMENT_SELECTOR,
            decision=HealingDecision.RECOMMEND_HEALING,
        )
        assert rec.decision == HealingDecision.RECOMMEND_HEALING

    def test_decision_default_value(self):
        """Default decision should be REQUIRE_FURTHER_ANALYSIS."""
        rec = HealingRecommendation(
            test_id="TC_001",
            execution_id="exec_001",
            failed_step=1,
            failure_type=FailureType.ELEMENT_NOT_FOUND,
            confidence=ConfidenceLevel.LOW,
            recommended_action=HealingAction.DO_NOT_HEAL,
        )
        assert rec.decision == HealingDecision.REQUIRE_FURTHER_ANALYSIS


# ═══════════════════════════════════════════════════════════════
# LLM EVALUATION RESULT
# ═══════════════════════════════════════════════════════════════


class TestLLMEvaluationResult:
    """Test the LLMEvaluationResult schema."""

    def test_valid_evaluation_result(self):
        result = LLMEvaluationResult(
            selected_selector="#sign-in-btn",
            confidence=0.92,
            reason="Same visible text and role in the same page context",
        )
        assert result.selected_selector == "#sign-in-btn"
        assert result.confidence == 0.92
        assert "text" in result.reason.lower()

    def test_empty_selector_rejected(self):
        with pytest.raises(Exception):
            LLMEvaluationResult(
                selected_selector="",
                confidence=0.5,
            )

    def test_confidence_bounds(self):
        with pytest.raises(Exception):
            LLMEvaluationResult(
                selected_selector="#btn",
                confidence=1.5,
            )

    def test_optional_reason(self):
        result = LLMEvaluationResult(
            selected_selector="#btn",
            confidence=0.5,
        )
        assert result.reason == ""


# ═══════════════════════════════════════════════════════════════
# LLM HEALING EVALUATOR
# ═══════════════════════════════════════════════════════════════


class TestLLMHealingEvaluator:
    """Test the LLM healing evaluator with grounding validation."""

    @pytest.mark.asyncio
    async def test_valid_llm_recommendation(self):
        """LLM selects an existing candidate → passes validation."""
        provider = _MockHealingLLMProvider({
            "selected_candidate": "#sign-in-btn",
            "confidence": 0.90,
            "reason": "Same visible text and role",
        })
        session = LLMClientSession(
            provider=provider,
            config=LLMConfig(provider="mock", model="mock"),
        )
        evaluator = LLMHealingEvaluator(session)

        candidates = [
            ScoredCandidate(
                selector="#sign-in-btn",
                source=CandidateSource.CURRENT_DOM,
                confidence=0.84,
                evidence=["Same text: Login", "Same role: button"],
                text_similarity=1.0,
                role_similarity=1.0,
            ),
            ScoredCandidate(
                selector="#submit-btn",
                source=CandidateSource.CURRENT_DOM,
                confidence=0.82,
                evidence=["Same role: button"],
                role_similarity=1.0,
            ),
        ]

        result = await evaluator.evaluate_candidates(
            candidates=candidates,
            original_selector="#login-btn",
            failure_type="ELEMENT_NOT_FOUND",
        )

        assert result is not None
        assert result.selected_selector == "#sign-in-btn"
        assert result.confidence == 0.90
        assert result.reason == "Same visible text and role"

    @pytest.mark.asyncio
    async def test_invalid_llm_candidate_rejected(self):
        """LLM recommends a selector not in candidates → rejected."""
        provider = _MockHealingLLMProvider({
            "selected_candidate": "#fake-selector",
            "confidence": 0.99,
            "reason": "Invented this",
        })
        session = LLMClientSession(
            provider=provider,
            config=LLMConfig(provider="mock", model="mock"),
        )
        evaluator = LLMHealingEvaluator(session)

        candidates = [
            ScoredCandidate(
                selector="#sign-in-btn",
                source=CandidateSource.CURRENT_DOM,
                confidence=0.84,
            ),
            ScoredCandidate(
                selector="#submit-btn",
                source=CandidateSource.CURRENT_DOM,
                confidence=0.82,
            ),
        ]

        result = await evaluator.evaluate_candidates(
            candidates=candidates,
            original_selector="#login-btn",
            failure_type="ELEMENT_NOT_FOUND",
        )

        # Must be rejected — #fake-selector is not in candidates
        assert result is None

    @pytest.mark.asyncio
    async def test_llm_failure_returns_none(self):
        """LLM error should return None gracefully."""
        provider = _FailingLLMProvider()
        session = LLMClientSession(
            provider=provider,
            config=LLMConfig(provider="mock", model="mock"),
        )
        evaluator = LLMHealingEvaluator(session)

        candidates = [
            ScoredCandidate(
                selector="#a",
                source=CandidateSource.CURRENT_DOM,
                confidence=0.84,
            ),
            ScoredCandidate(
                selector="#b",
                source=CandidateSource.CURRENT_DOM,
                confidence=0.82,
            ),
        ]

        result = await evaluator.evaluate_candidates(
            candidates=candidates,
            original_selector="#login-btn",
            failure_type="ELEMENT_NOT_FOUND",
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_less_than_two_candidates_skipped(self):
        """Evaluation with fewer than 2 candidates should be skipped."""
        provider = _MockHealingLLMProvider({})
        session = LLMClientSession(
            provider=provider,
            config=LLMConfig(provider="mock", model="mock"),
        )
        evaluator = LLMHealingEvaluator(session)

        result = await evaluator.evaluate_candidates(
            candidates=[
                ScoredCandidate(
                    selector="#a",
                    source=CandidateSource.CURRENT_DOM,
                ),
            ],
            original_selector="#login-btn",
            failure_type="ELEMENT_NOT_FOUND",
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_missing_confidence_field_rejected(self):
        """Missing confidence field in LLM response → rejected."""
        provider = _MockHealingLLMProvider({
            "selected_candidate": "#sign-in-btn",
            # Missing "confidence" field
        })
        session = LLMClientSession(
            provider=provider,
            config=LLMConfig(provider="mock", model="mock"),
        )
        evaluator = LLMHealingEvaluator(session)

        candidates = [
            ScoredCandidate(
                selector="#sign-in-btn",
                source=CandidateSource.CURRENT_DOM,
                confidence=0.84,
            ),
            ScoredCandidate(
                selector="#submit-btn",
                source=CandidateSource.CURRENT_DOM,
                confidence=0.82,
            ),
        ]

        result = await evaluator.evaluate_candidates(
            candidates=candidates,
            original_selector="#login-btn",
            failure_type="ELEMENT_NOT_FOUND",
        )

        assert result is None


# ═══════════════════════════════════════════════════════════════
# SCENARIO TESTS (TASK 12)
# ═══════════════════════════════════════════════════════════════


class TestScenarios:
    """Deterministic scenario test fixtures."""

    @pytest.mark.asyncio
    async def test_scenario_1_clear_winner(
        self, memory_store: InMemoryStore,
    ):
        """SCENARIO 1: Clear winner (0.94 vs 0.55) → RECOMMEND_HEALING."""
        previous = _make_element(
            selector="#login-btn", text="Login", role="button",
            page_url="https://app.example.com/login",
            attributes={"type": "submit", "name": "login"},
        )
        # Strong match
        current_a = _make_element(
            element_id="c_a",
            selector="#sign-in-btn",
            text="Login", role="button",
            page_url="https://app.example.com/login",
            attributes={"type": "submit", "name": "login"},
        )
        # Weak match
        current_b = _make_element(
            element_id="c_b",
            selector="#submit-btn",
            text="Submit", role="button",
            page_url="https://app.example.com/register",
            attributes={"type": "submit", "name": "submit"},
        )

        analysis = _make_failure_analysis(
            failure_type=FailureType.SELECTOR_CHANGED,
            previous_element=previous,
        )
        ctx = _make_healing_context(
            failure_analysis=analysis,
            current_elements=[current_a, current_b],
            page_url="https://app.example.com/login",
        )

        engine = HealingDecisionEngine(memory_store=memory_store)
        rec = await engine.generate_recommendation(ctx)

        assert rec.decision == HealingDecision.RECOMMEND_HEALING
        assert rec.confidence == ConfidenceLevel.HIGH
        assert rec.recommended_action == HealingAction.TRY_REPLACEMENT_SELECTOR
        assert rec.selected_candidate is not None
        assert rec.selected_candidate.selector == "#sign-in-btn"
        assert rec.selected_candidate.confidence >= 0.80
        # Verify score gap — not ambiguous
        assert len(rec.candidates) == 2
        gap = rec.candidates[0].confidence - rec.candidates[1].confidence
        assert gap > 0.05

    @pytest.mark.asyncio
    async def test_scenario_2_ambiguous(
        self, memory_store: InMemoryStore,
    ):
        """SCENARIO 2: Ambiguous (close scores) → REQUIRE_FURTHER_ANALYSIS."""
        previous = _make_element(
            selector="#login-btn", text="Login", role="button",
            page_url="https://app.example.com/login",
            attributes={"type": "submit", "name": "login"},
        )
        # Both very similar to previous
        current_a = _make_element(
            element_id="c_a",
            selector="#sign-in-btn",
            text="Login", role="button",
            page_url="https://app.example.com/login",
            attributes={"type": "submit", "name": "login"},
        )
        current_b = _make_element(
            element_id="c_b",
            selector="#login-button",
            text="Login", role="button",
            page_url="https://app.example.com/login",
            attributes={"type": "submit", "name": "login"},
        )

        analysis = _make_failure_analysis(
            failure_type=FailureType.SELECTOR_CHANGED,
            previous_element=previous,
        )
        ctx = _make_healing_context(
            failure_analysis=analysis,
            current_elements=[current_a, current_b],
            page_url="https://app.example.com/login",
        )

        engine = HealingDecisionEngine(memory_store=memory_store)
        rec = await engine.generate_recommendation(ctx)

        # Both candidates should have very similar scores
        assert len(rec.candidates) >= 2
        gap = rec.candidates[0].confidence - rec.candidates[1].confidence
        assert gap <= 0.05  # Ambiguous
        assert rec.decision == HealingDecision.REQUIRE_FURTHER_ANALYSIS
        assert rec.recommended_action == HealingAction.REQUIRE_FURTHER_ANALYSIS

    @pytest.mark.asyncio
    async def test_scenario_3_low_confidence(
        self, memory_store: InMemoryStore,
    ):
        """SCENARIO 3: Low confidence (best = 0.32) → DO_NOT_HEAL."""
        previous = _make_element(
            selector="#login-btn", text="Login", role="button",
            page_url="https://app.example.com/login",
        )
        # Very different element
        current = _make_element(
            element_id="elem_unrelated",
            selector="#footer-link",
            text="About Us",
            role="link",
            page_url="https://app.example.com/about",
            attributes={"type": "link", "name": "about"},
        )

        analysis = _make_failure_analysis(
            failure_type=FailureType.ELEMENT_NOT_FOUND,
            previous_element=previous,
        )
        ctx = _make_healing_context(
            failure_analysis=analysis,
            current_elements=[current],
            page_url="https://app.example.com/login",
        )

        engine = HealingDecisionEngine(memory_store=memory_store)
        rec = await engine.generate_recommendation(ctx)

        assert rec.confidence == ConfidenceLevel.LOW
        assert rec.decision in (
            HealingDecision.DO_NOT_HEAL,
            HealingDecision.REQUIRE_FURTHER_ANALYSIS,
        )

    @pytest.mark.asyncio
    async def test_scenario_4_invalid_llm_candidate(
        self, memory_store: InMemoryStore,
    ):
        """SCENARIO 4: LLM recommends invalid selector → rejected."""
        provider = _MockHealingLLMProvider({
            "selected_candidate": "#invented-selector",
            "confidence": 0.99,
            "reason": "I made this up",
        })
        session = LLMClientSession(
            provider=provider,
            config=LLMConfig(provider="mock", model="mock"),
        )

        previous = _make_element(
            selector="#login-btn", text="Login", role="button",
            page_url="https://app.example.com/login",
            attributes={"type": "submit", "name": "login"},
        )
        current_a = _make_element(
            element_id="c_a",
            selector="#sign-in-btn",
            text="Login", role="button",
            page_url="https://app.example.com/login",
            attributes={"type": "submit", "name": "login"},
        )
        current_b = _make_element(
            element_id="c_b",
            selector="#login-button",
            text="Login", role="button",
            page_url="https://app.example.com/login",
            attributes={"type": "submit", "name": "login"},
        )

        analysis = _make_failure_analysis(
            failure_type=FailureType.SELECTOR_CHANGED,
            previous_element=previous,
        )
        ctx = _make_healing_context(
            failure_analysis=analysis,
            current_elements=[current_a, current_b],
            page_url="https://app.example.com/login",
        )

        engine = HealingDecisionEngine(
            memory_store=memory_store, llm_client=session,
        )
        rec = await engine.generate_recommendation(ctx)

        # LLM was rejected — should still produce a valid recommendation
        assert rec is not None
        assert rec.test_id == "TC_LOGIN_001"
        # Ambiguity should be detected but LLM failed
        assert rec.decision == HealingDecision.REQUIRE_FURTHER_ANALYSIS

    @pytest.mark.asyncio
    async def test_scenario_5_valid_llm_recommendation(
        self, memory_store: InMemoryStore,
    ):
        """SCENARIO 5: LLM selects valid candidate → passes validation."""
        provider = _MockHealingLLMProvider({
            "selected_candidate": "#sign-in-btn",
            "confidence": 0.92,
            "reason": "Same visible text and role",
        })
        session = LLMClientSession(
            provider=provider,
            config=LLMConfig(provider="mock", model="mock"),
        )

        previous = _make_element(
            selector="#login-btn", text="Login", role="button",
            page_url="https://app.example.com/login",
            attributes={"type": "submit", "name": "login"},
        )
        current_a = _make_element(
            element_id="c_a",
            selector="#sign-in-btn",
            text="Login", role="button",
            page_url="https://app.example.com/login",
            attributes={"type": "submit", "name": "login"},
        )
        current_b = _make_element(
            element_id="c_b",
            selector="#login-button",
            text="Login", role="button",
            page_url="https://app.example.com/login",
            attributes={"type": "submit", "name": "login"},
        )

        analysis = _make_failure_analysis(
            failure_type=FailureType.SELECTOR_CHANGED,
            previous_element=previous,
        )
        ctx = _make_healing_context(
            failure_analysis=analysis,
            current_elements=[current_a, current_b],
            page_url="https://app.example.com/login",
        )

        engine = HealingDecisionEngine(
            memory_store=memory_store, llm_client=session,
        )
        rec = await engine.generate_recommendation(ctx)

        assert rec is not None
        assert rec.selected_candidate is not None
        assert rec.selected_candidate.selector == "#sign-in-btn"
        # LLM resolved ambiguity with high confidence
        assert rec.recommended_action == HealingAction.TRY_REPLACEMENT_SELECTOR
        assert rec.decision in (
            HealingDecision.RECOMMEND_HEALING,
            HealingDecision.REQUIRE_VALIDATION,
        )

    @pytest.mark.asyncio
    async def test_scenario_6_no_candidates(
        self, memory_store: InMemoryStore,
    ):
        """SCENARIO 6: No candidates → DO_NOT_HEAL."""
        analysis = _make_failure_analysis(
            failure_type=FailureType.ELEMENT_NOT_FOUND,
            previous_element=_make_element(),
        )
        ctx = _make_healing_context(
            failure_analysis=analysis,
            current_elements=[],
        )

        engine = HealingDecisionEngine(memory_store=memory_store)
        rec = await engine.generate_recommendation(ctx)

        assert rec.decision == HealingDecision.DO_NOT_HEAL
        assert rec.recommended_action == HealingAction.DO_NOT_HEAL
        assert rec.selected_candidate is None
        assert len(rec.candidates) == 0
        assert rec.confidence == ConfidenceLevel.LOW


# ═══════════════════════════════════════════════════════════════
# MEMBER 2 CONTRACT TESTS
# ═══════════════════════════════════════════════════════════════


class TestMember2ContractDay11:
    """Test Member 2 interface with Day 11 additions."""

    def test_recommendation_with_decision_maps_correctly(self):
        """HealingRecommendation with decision maps to HealingCandidate."""
        selected = ScoredCandidate(
            selector="#sign-in-btn",
            source=CandidateSource.CURRENT_DOM,
            confidence=0.94,
            evidence=["Same text: Login", "Same role: button"],
        )
        rec = HealingRecommendation(
            test_id="TC_LOGIN_001",
            execution_id="exec_001",
            failed_step=3,
            original_selector="#login-btn",
            failure_type=FailureType.SELECTOR_CHANGED,
            candidates=[selected],
            selected_candidate=selected,
            confidence=ConfidenceLevel.HIGH,
            recommended_action=HealingAction.TRY_REPLACEMENT_SELECTOR,
            decision=HealingDecision.RECOMMEND_HEALING,
        )

        hc = recommendation_to_healing_candidate(rec)
        assert isinstance(hc, HealingCandidate)
        assert hc.healing_attempted is True
        assert hc.new_selector == "#sign-in-btn"
        assert hc.requires_validation is True

    def test_do_not_heal_decision_maps_correctly(self):
        """DO_NOT_HEAL decision maps to healing_attempted=False."""
        rec = HealingRecommendation(
            test_id="TC_001",
            execution_id="exec_001",
            failed_step=1,
            failure_type=FailureType.ASSERTION_FAILURE,
            confidence=ConfidenceLevel.HIGH,
            recommended_action=HealingAction.DO_NOT_HEAL,
            decision=HealingDecision.DO_NOT_HEAL,
        )

        hc = recommendation_to_healing_candidate(rec)
        assert hc.healing_attempted is False
        assert hc.new_selector == ""


# ═══════════════════════════════════════════════════════════════
# HEALING RESULT PREPARATION
# ═══════════════════════════════════════════════════════════════


class TestHealingResultPreparation:
    """Test prepare_healing_result() for Member 2 feedback."""

    def test_prepare_success_result(self):
        result = prepare_healing_result(
            test_id="TC_LOGIN_001",
            old_selector="#login-btn",
            new_selector="#sign-in-btn",
            validation_success=True,
            confidence=0.94,
            failed_step=3,
        )
        assert result.test_id == "TC_LOGIN_001"
        assert result.old_selector == "#login-btn"
        assert result.new_selector == "#sign-in-btn"
        assert result.status == HealingStatus.VALIDATED_SUCCESS
        assert result.confidence == 0.94
        assert result.validated_by == "execution_engine"

    def test_prepare_failure_result(self):
        result = prepare_healing_result(
            test_id="TC_LOGIN_001",
            old_selector="#login-btn",
            new_selector="#wrong-btn",
            validation_success=False,
            confidence=0.45,
            validation_error="Element not interactable",
        )
        assert result.status == HealingStatus.VALIDATED_FAILURE
        assert result.validation_error == "Element not interactable"

    def test_prepare_result_to_memory_update(self):
        """Prepared result should be storable in memory."""
        result = prepare_healing_result(
            test_id="TC_LOGIN_001",
            old_selector="#login-btn",
            new_selector="#sign-in-btn",
            validation_success=True,
            confidence=0.94,
        )
        update = healing_result_to_memory_update(result)
        assert update["is_success"] is True
        assert update["old_selector"] == "#login-btn"
        assert update["new_selector"] == "#sign-in-btn"
        assert update["healing_record"]["validation_result"] is True


# ═══════════════════════════════════════════════════════════════
# INTEGRATION TEST (TASK 14)
# ═══════════════════════════════════════════════════════════════


class TestEndToEndIntegrationDay11:
    """End-to-end integration test:

    Historical Memory
         ↓
    Previous Successful Context
         ↓
    Current Failure
         ↓
    Failure Analyzer
         ↓
    FailureAnalysis
         ↓
    Candidate Generation
         ↓
    Candidate Scoring
         ↓
    Candidate Ranking
         ↓
    Decision Layer
         ↓
    HealingRecommendation

    Uses:
    Previous: #login-btn, text="Login", role="button"
    Current:  #sign-in-btn, text="Login", role="button"

    Expected:
    Failure Type: SELECTOR_CHANGED
    Candidate: #sign-in-btn
    Confidence: HIGH
    Decision: RECOMMEND_HEALING
    Action: TRY_REPLACEMENT_SELECTOR

    No browser is launched.  No real model is required.
    """

    @pytest.mark.asyncio
    async def test_full_pipeline_selector_change_day11(self):
        """Full pipeline with Day 11 features."""
        # 1. Set up memory with historical data
        store = InMemoryStore()

        store.store_execution(
            TestExecutionRecord(
                execution_id="exec_success_001",
                test_id="TC_LOGIN_001",
                test_name="Login Test",
                status=ExecutionStatus.PASSED,
                duration_ms=1200.0,
            )
        )

        previous_element = _make_element(
            element_id="elem_login_btn",
            selector="#login-btn",
            text="Login",
            role="button",
            page_url="https://app.example.com/login",
            attributes={"type": "submit", "name": "login"},
        )
        store.store_element(previous_element)

        store.store_execution(
            TestExecutionRecord(
                execution_id="exec_fail_001",
                test_id="TC_LOGIN_001",
                test_name="Login Test",
                status=ExecutionStatus.FAILED,
                duration_ms=500.0,
                failure_info=FailureInfo(
                    error_message="Element not found: #login-btn",
                    failure_type=FailureType.ELEMENT_NOT_FOUND,
                    failed_step=3,
                    selector="#login-btn",
                    page_url="https://app.example.com/login",
                ),
            )
        )

        # 2. Current element (replacement candidate)
        current_element = _make_element(
            element_id="elem_signin_btn",
            selector="#sign-in-btn",
            text="Login",
            role="button",
            page_url="https://app.example.com/login",
            attributes={"type": "submit", "name": "login"},
        )

        failure_context = FailureContext(
            test_id="TC_LOGIN_001",
            execution_id="exec_fail_001",
            failed_step=3,
            action="click",
            target_selector="#login-btn",
            error_message="Element not found: #login-btn",
            current_page_url="https://app.example.com/login",
            current_element=current_element,
        )

        # 3. Run Failure Analyzer
        analyzer = FailureAnalyzerAgent(memory_store=store)
        analysis = await analyzer.analyze(failure_context)

        assert analysis.failure_type == FailureType.SELECTOR_CHANGED
        assert analysis.confidence == ConfidenceLevel.HIGH

        # 4. Build healing context
        healing_ctx = HealingContext(
            failure_analysis=analysis,
            current_elements=[current_element],
            page_url="https://app.example.com/login",
        )

        # 5. Run Healing Decision Engine
        engine = HealingDecisionEngine(memory_store=store)
        recommendation = await engine.generate_recommendation(healing_ctx)

        # 6. Verify recommendation — Day 11 assertions
        assert recommendation.test_id == "TC_LOGIN_001"
        assert recommendation.execution_id == "exec_fail_001"
        assert recommendation.failure_type == FailureType.SELECTOR_CHANGED
        assert recommendation.recommended_action == HealingAction.TRY_REPLACEMENT_SELECTOR
        assert recommendation.confidence == ConfidenceLevel.HIGH
        assert recommendation.decision == HealingDecision.RECOMMEND_HEALING
        assert recommendation.requires_validation is True

        # Verify selected candidate
        assert recommendation.selected_candidate is not None
        assert recommendation.selected_candidate.selector == "#sign-in-btn"
        assert recommendation.selected_candidate.confidence >= 0.80

        # Verify candidates are ranked
        assert len(recommendation.candidates) >= 1
        assert recommendation.candidates[0].selector == "#sign-in-btn"

        # 7. Verify Member 2 interface mapping
        hc = recommendation_to_healing_candidate(recommendation)
        assert isinstance(hc, HealingCandidate)
        assert hc.test_id == "TC_LOGIN_001"
        assert hc.healing_attempted is True
        assert hc.new_selector == "#sign-in-btn"
        assert hc.requires_validation is True

        # 8. Verify healing result can be prepared
        result = prepare_healing_result(
            test_id="TC_LOGIN_001",
            old_selector="#login-btn",
            new_selector="#sign-in-btn",
            validation_success=True,
            confidence=recommendation.selected_candidate.confidence,
            failed_step=3,
        )
        assert result.status == HealingStatus.VALIDATED_SUCCESS

        # 9. Verify result can be stored in memory
        update = healing_result_to_memory_update(result)
        assert update["is_success"] is True
        healing_record_data = update["healing_record"]
        from agents.memory.memory_schemas import HealingRecord as HR
        hr = HR(**healing_record_data)
        store.store_healing_record(hr)

    @pytest.mark.asyncio
    async def test_full_pipeline_assertion_failure_day11(self):
        """Full pipeline: assertion failure → DO_NOT_HEAL."""
        store = InMemoryStore()

        failure_context = FailureContext(
            test_id="TC_LOGIN_002",
            execution_id="exec_fail_002",
            failed_step=5,
            action="assert",
            target_selector="",
            error_message="Assertion failed: expected 'Dashboard' got 'Error Page'",
            expected_result="Dashboard",
            actual_result="Error Page",
        )

        analyzer = FailureAnalyzerAgent(memory_store=store)
        analysis = await analyzer.analyze(failure_context)

        assert analysis.failure_type == FailureType.ASSERTION_FAILURE

        healing_ctx = HealingContext(
            failure_analysis=analysis,
            current_elements=[],
        )

        engine = HealingDecisionEngine(memory_store=store)
        recommendation = await engine.generate_recommendation(healing_ctx)

        assert recommendation.recommended_action == HealingAction.DO_NOT_HEAL
        assert recommendation.decision == HealingDecision.DO_NOT_HEAL
        assert recommendation.selected_candidate is None
        assert recommendation.requires_validation is True
