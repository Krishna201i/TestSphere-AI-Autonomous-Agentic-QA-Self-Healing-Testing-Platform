"""
TestSphere-AI — Day 10: Healing Decision & Candidate Generation Tests

Comprehensive test suite for the Self-Healing Decision Layer:

- Schema validation (ScoredCandidate, HealingRecommendation, HealingContext)
- Candidate generation (from current elements, from historical memory)
- Candidate scoring (individual weights, custom weights)
- Candidate ranking (multiple candidates, single, empty)
- Confidence thresholds (HIGH, MEDIUM, LOW classification)
- Decision engine (end-to-end pipeline, safety rules)
- Safety rules (assertion failure, no candidates, low confidence)
- LLM disambiguation (ambiguous candidates, clear winner, failure)
- Integration test (Memory → Analyzer → Decision Engine → Recommendation)
- Member 2 interface mapping

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
    recommendation_to_healing_candidate,
)
from agents.healer.healing_schemas import (
    HealingContext,
    HealingRecommendation,
    ScoredCandidate,
)
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
# SCHEMA VALIDATION TESTS
# ═══════════════════════════════════════════════════════════════


class TestScoredCandidateSchema:
    """Validate ScoredCandidate schema."""

    def test_create_valid_candidate(self):
        c = ScoredCandidate(
            selector="#sign-in-btn",
            selector_type="id",
            source=CandidateSource.CURRENT_DOM,
            confidence=0.92,
            evidence=["Same visible text: Login", "Same role: button"],
            text_similarity=1.0,
            role_similarity=1.0,
        )
        assert c.selector == "#sign-in-btn"
        assert c.selector_type == "id"
        assert c.source == CandidateSource.CURRENT_DOM
        assert c.confidence == 0.92
        assert len(c.evidence) == 2

    def test_confidence_bounds(self):
        with pytest.raises(Exception):
            ScoredCandidate(
                selector="#btn",
                source=CandidateSource.CURRENT_DOM,
                confidence=1.5,
            )

        with pytest.raises(Exception):
            ScoredCandidate(
                selector="#btn",
                source=CandidateSource.CURRENT_DOM,
                confidence=-0.1,
            )

    def test_empty_selector_rejected(self):
        with pytest.raises(Exception):
            ScoredCandidate(
                selector="",
                source=CandidateSource.CURRENT_DOM,
            )

    def test_default_values(self):
        c = ScoredCandidate(
            selector="#btn",
            source=CandidateSource.CURRENT_DOM,
        )
        assert c.confidence == 0.0
        assert c.selector_type == "css"
        assert c.evidence == []
        assert c.text_similarity == 0.0
        assert c.role_similarity == 0.0
        assert c.historical_similarity == 0.0

    def test_all_sources(self):
        for source in CandidateSource:
            c = ScoredCandidate(
                selector="#btn",
                source=source,
            )
            assert c.source == source


class TestHealingRecommendationSchema:
    """Validate HealingRecommendation schema."""

    def test_create_valid_recommendation(self):
        r = HealingRecommendation(
            test_id="TC_LOGIN_001",
            execution_id="exec_001",
            failed_step=3,
            original_selector="#login-btn",
            failure_type=FailureType.SELECTOR_CHANGED,
            candidates=[],
            confidence=ConfidenceLevel.HIGH,
            recommended_action=HealingAction.TRY_REPLACEMENT_SELECTOR,
            evidence=["Selector changed"],
        )
        assert r.test_id == "TC_LOGIN_001"
        assert r.requires_validation is True

    def test_requires_validation_always_true(self):
        with pytest.raises(Exception, match="requires_validation must always be True"):
            HealingRecommendation(
                test_id="TC_001",
                execution_id="exec_001",
                failed_step=1,
                failure_type=FailureType.ELEMENT_NOT_FOUND,
                confidence=ConfidenceLevel.LOW,
                recommended_action=HealingAction.DO_NOT_HEAL,
                requires_validation=False,
            )

    def test_all_healing_actions(self):
        for action in HealingAction:
            r = HealingRecommendation(
                test_id="TC_001",
                execution_id="exec_001",
                failed_step=1,
                failure_type=FailureType.ELEMENT_NOT_FOUND,
                confidence=ConfidenceLevel.LOW,
                recommended_action=action,
            )
            assert r.recommended_action == action


class TestHealingContextSchema:
    """Validate HealingContext schema."""

    def test_create_valid_context(self):
        analysis = _make_failure_analysis()
        ctx = HealingContext(
            failure_analysis=analysis,
            current_elements=[_make_element(selector="#sign-in-btn")],
            page_url="https://app.example.com/login",
        )
        assert ctx.failure_analysis.test_id == "TC_LOGIN_001"
        assert len(ctx.current_elements) == 1

    def test_empty_elements_allowed(self):
        ctx = _make_healing_context(current_elements=[])
        assert ctx.current_elements == []


# ═══════════════════════════════════════════════════════════════
# CANDIDATE GENERATION TESTS
# ═══════════════════════════════════════════════════════════════


class TestCandidateGeneration:
    """Test candidate generation from current elements and history."""

    def test_generate_from_current_elements(
        self, memory_store: InMemoryStore,
    ):
        """Simple selector change — candidate with matching text/role."""
        previous = _make_element(
            selector="#login-btn", text="Login", role="button",
        )
        current = _make_element(
            element_id="elem_signin_btn",
            selector="#sign-in-btn",
            text="Login",
            role="button",
        )

        analysis = _make_failure_analysis(previous_element=previous)
        ctx = _make_healing_context(
            failure_analysis=analysis,
            current_elements=[current],
        )

        gen = CandidateGenerator(memory_store=memory_store)
        candidates = gen.generate_candidates(ctx)

        assert len(candidates) == 1
        assert candidates[0].selector == "#sign-in-btn"
        assert candidates[0].source == CandidateSource.CURRENT_DOM
        assert candidates[0].text_similarity == 1.0
        assert candidates[0].role_similarity == 1.0

    def test_generate_multiple_candidates(
        self, memory_store: InMemoryStore,
    ):
        """Multiple current elements should all be generated as candidates."""
        previous = _make_element(
            selector="#login-btn", text="Login", role="button",
        )

        current_1 = _make_element(
            element_id="elem_1",
            selector="#sign-in-btn",
            text="Login",
            role="button",
        )
        current_2 = _make_element(
            element_id="elem_2",
            selector="#submit-btn",
            text="Submit",
            role="button",
        )
        current_3 = _make_element(
            element_id="elem_3",
            selector=".button-primary",
            text="Go",
            role="link",
        )

        analysis = _make_failure_analysis(previous_element=previous)
        ctx = _make_healing_context(
            failure_analysis=analysis,
            current_elements=[current_1, current_2, current_3],
        )

        gen = CandidateGenerator(memory_store=memory_store)
        candidates = gen.generate_candidates(ctx)

        assert len(candidates) == 3
        selectors = {c.selector for c in candidates}
        assert "#sign-in-btn" in selectors
        assert "#submit-btn" in selectors
        assert ".button-primary" in selectors

    def test_skip_same_selector(self, memory_store: InMemoryStore):
        """The exact failed selector should not appear as a candidate."""
        previous = _make_element(selector="#login-btn")
        current_same = _make_element(
            element_id="elem_same", selector="#login-btn",
        )

        analysis = _make_failure_analysis(previous_element=previous)
        ctx = _make_healing_context(
            failure_analysis=analysis,
            current_elements=[current_same],
        )

        gen = CandidateGenerator(memory_store=memory_store)
        candidates = gen.generate_candidates(ctx)

        assert len(candidates) == 0

    def test_no_candidates_when_no_elements(
        self, memory_store: InMemoryStore,
    ):
        """No current elements → no candidates."""
        analysis = _make_failure_analysis(
            previous_element=_make_element(),
        )
        ctx = _make_healing_context(
            failure_analysis=analysis,
            current_elements=[],
        )

        gen = CandidateGenerator(memory_store=memory_store)
        candidates = gen.generate_candidates(ctx)

        assert len(candidates) == 0

    def test_generate_from_historical_healing(
        self, memory_store: InMemoryStore,
    ):
        """Previously successful healing should produce a candidate."""
        memory_store.store_healing_record(
            HealingRecord(
                healing_id="heal_001",
                test_id="TC_LOGIN_001",
                old_selector="#login-btn",
                new_selector="#sign-in-btn",
                healing_reason="Selector was renamed",
                confidence=0.95,
                validation_result=True,
            )
        )

        analysis = _make_failure_analysis(
            failed_target="#login-btn",
            previous_element=None,
        )
        ctx = _make_healing_context(
            failure_analysis=analysis,
            current_elements=[],
        )

        gen = CandidateGenerator(memory_store=memory_store)
        candidates = gen.generate_candidates(ctx)

        assert len(candidates) == 1
        assert candidates[0].selector == "#sign-in-btn"
        assert candidates[0].source == CandidateSource.HISTORICAL_MEMORY
        assert candidates[0].historical_similarity == 1.0

    def test_historical_context_usage(
        self, memory_store: InMemoryStore,
    ):
        """Historical element should be retrieved from analysis context."""
        previous = _make_element(
            selector="#login-btn", text="Login", role="button",
            page_url="https://app.example.com/login",
        )
        current = _make_element(
            element_id="elem_new",
            selector="#sign-in-btn",
            text="Login",
            role="button",
            page_url="https://app.example.com/login",
        )

        analysis = _make_failure_analysis(previous_element=previous)
        ctx = _make_healing_context(
            failure_analysis=analysis,
            current_elements=[current],
            page_url="https://app.example.com/login",
        )

        gen = CandidateGenerator(memory_store=memory_store)
        candidates = gen.generate_candidates(ctx)

        assert len(candidates) == 1
        c = candidates[0]
        assert c.text_similarity == 1.0
        assert c.role_similarity == 1.0
        assert c.page_similarity == 1.0
        assert "Same visible text: Login" in c.evidence
        assert "Same role: button" in c.evidence
        assert "Same page context" in c.evidence

    def test_evidence_building(self, memory_store: InMemoryStore):
        """Evidence strings should be concise and observable."""
        previous = _make_element(
            selector="#login-btn",
            text="Login",
            role="button",
            attributes={"type": "submit", "name": "login"},
        )
        current = _make_element(
            element_id="elem_new",
            selector="#sign-in-btn",
            text="Login",
            role="button",
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
        evidence = candidates[0].evidence
        assert any("text" in e.lower() for e in evidence)
        assert any("role" in e.lower() for e in evidence)


# ═══════════════════════════════════════════════════════════════
# CANDIDATE SCORING TESTS
# ═══════════════════════════════════════════════════════════════


class TestCandidateScoring:
    """Test deterministic candidate scoring."""

    def test_text_match_scoring(self, scorer: CandidateScorer):
        """Full text match should contribute strongly."""
        c = ScoredCandidate(
            selector="#btn",
            source=CandidateSource.CURRENT_DOM,
            text_similarity=1.0,
        )
        score = scorer.score_candidate(c)
        assert score > 0.0
        # Text weight is 0.30/1.0, so text-only should be ~0.30
        assert abs(score - 0.30) < 0.01

    def test_role_match_scoring(self, scorer: CandidateScorer):
        """Full role match should contribute strongly."""
        c = ScoredCandidate(
            selector="#btn",
            source=CandidateSource.CURRENT_DOM,
            role_similarity=1.0,
        )
        score = scorer.score_candidate(c)
        assert abs(score - 0.25) < 0.01

    def test_type_match_scoring(self, scorer: CandidateScorer):
        """Type match contributes moderately."""
        c = ScoredCandidate(
            selector="#btn",
            source=CandidateSource.CURRENT_DOM,
            type_similarity=1.0,
        )
        score = scorer.score_candidate(c)
        assert abs(score - 0.10) < 0.01

    def test_page_match_scoring(self, scorer: CandidateScorer):
        """Page match contributes moderately."""
        c = ScoredCandidate(
            selector="#btn",
            source=CandidateSource.CURRENT_DOM,
            page_similarity=1.0,
        )
        score = scorer.score_candidate(c)
        assert abs(score - 0.15) < 0.01

    def test_historical_match_scoring(self, scorer: CandidateScorer):
        """Historical match contributes strongly."""
        c = ScoredCandidate(
            selector="#btn",
            source=CandidateSource.HISTORICAL_MEMORY,
            historical_similarity=1.0,
        )
        score = scorer.score_candidate(c)
        assert abs(score - 0.15) < 0.01

    def test_full_match_scoring(self, scorer: CandidateScorer):
        """All matches should produce confidence close to 1.0."""
        c = ScoredCandidate(
            selector="#btn",
            source=CandidateSource.CURRENT_DOM,
            text_similarity=1.0,
            role_similarity=1.0,
            type_similarity=1.0,
            page_similarity=1.0,
            historical_similarity=1.0,
            name_similarity=1.0,
        )
        score = scorer.score_candidate(c)
        assert abs(score - 1.0) < 0.01

    def test_no_match_scoring(self, scorer: CandidateScorer):
        """No matches should produce 0.0."""
        c = ScoredCandidate(
            selector="#btn",
            source=CandidateSource.CURRENT_DOM,
        )
        score = scorer.score_candidate(c)
        assert score == 0.0

    def test_custom_weights(self):
        """Custom weights should change scoring."""
        weights = ScoringWeights(
            text_weight=1.0,
            role_weight=0.0,
            type_weight=0.0,
            page_weight=0.0,
            historical_weight=0.0,
            name_weight=0.0,
        )
        scorer = CandidateScorer(weights=weights)

        c = ScoredCandidate(
            selector="#btn",
            source=CandidateSource.CURRENT_DOM,
            text_similarity=1.0,
            role_similarity=1.0,
        )
        score = scorer.score_candidate(c)
        assert abs(score - 1.0) < 0.01

    def test_weights_must_sum_positive(self):
        """Weights must sum to a positive value."""
        with pytest.raises(Exception, match="positive"):
            ScoringWeights(
                text_weight=0.0,
                role_weight=0.0,
                type_weight=0.0,
                page_weight=0.0,
                historical_weight=0.0,
                name_weight=0.0,
            )


# ═══════════════════════════════════════════════════════════════
# CANDIDATE RANKING TESTS
# ═══════════════════════════════════════════════════════════════


class TestCandidateRanking:
    """Test candidate ranking by confidence."""

    def test_rank_multiple_candidates(self, scorer: CandidateScorer):
        """Candidates should be sorted by confidence, highest first."""
        candidates = [
            ScoredCandidate(
                selector=".button-primary",
                source=CandidateSource.CURRENT_DOM,
                text_similarity=0.0,
                role_similarity=1.0,
            ),
            ScoredCandidate(
                selector="#sign-in-btn",
                source=CandidateSource.CURRENT_DOM,
                text_similarity=1.0,
                role_similarity=1.0,
                page_similarity=1.0,
            ),
            ScoredCandidate(
                selector="#submit-btn",
                source=CandidateSource.CURRENT_DOM,
                text_similarity=0.0,
                role_similarity=1.0,
                page_similarity=1.0,
            ),
        ]

        ranked = scorer.rank_candidates(candidates)

        assert len(ranked) == 3
        assert ranked[0].selector == "#sign-in-btn"
        assert ranked[0].confidence >= ranked[1].confidence
        assert ranked[1].confidence >= ranked[2].confidence

    def test_rank_single_candidate(self, scorer: CandidateScorer):
        """Single candidate should still work."""
        candidates = [
            ScoredCandidate(
                selector="#btn",
                source=CandidateSource.CURRENT_DOM,
                text_similarity=1.0,
            ),
        ]
        ranked = scorer.rank_candidates(candidates)
        assert len(ranked) == 1
        assert ranked[0].confidence > 0.0

    def test_rank_empty_list(self, scorer: CandidateScorer):
        """Empty list should return empty."""
        ranked = scorer.rank_candidates([])
        assert ranked == []


# ═══════════════════════════════════════════════════════════════
# CONFIDENCE THRESHOLD TESTS
# ═══════════════════════════════════════════════════════════════


class TestConfidenceThresholds:
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

    def test_custom_thresholds(self, memory_store: InMemoryStore):
        thresholds = ConfidenceThresholds(
            high_threshold=0.90,
            medium_threshold=0.60,
            minimum_healing_threshold=0.40,
        )
        engine = HealingDecisionEngine(
            memory_store=memory_store, thresholds=thresholds,
        )
        assert engine._classify_confidence(0.85) == ConfidenceLevel.MEDIUM
        assert engine._classify_confidence(0.90) == ConfidenceLevel.HIGH
        assert engine._classify_confidence(0.55) == ConfidenceLevel.LOW


# ═══════════════════════════════════════════════════════════════
# DECISION ENGINE TESTS
# ═══════════════════════════════════════════════════════════════


class TestHealingDecisionEngine:
    """Test the full healing decision engine."""

    @pytest.mark.asyncio
    async def test_simple_selector_change_high_confidence(
        self, memory_store: InMemoryStore,
    ):
        """SCENARIO 1: Simple selector change → HIGH → TRY_REPLACEMENT."""
        previous = _make_element(
            selector="#login-btn", text="Login", role="button",
            page_url="https://app.example.com/login",
            attributes={"type": "submit", "name": "login"},
        )
        current = _make_element(
            element_id="elem_new",
            selector="#sign-in-btn",
            text="Login",
            role="button",
            page_url="https://app.example.com/login",
            attributes={"type": "submit", "name": "login"},
        )

        analysis = _make_failure_analysis(
            failure_type=FailureType.SELECTOR_CHANGED,
            previous_element=previous,
        )
        ctx = _make_healing_context(
            failure_analysis=analysis,
            current_elements=[current],
            page_url="https://app.example.com/login",
        )

        engine = HealingDecisionEngine(memory_store=memory_store)
        rec = await engine.generate_recommendation(ctx)

        assert rec.recommended_action == HealingAction.TRY_REPLACEMENT_SELECTOR
        assert rec.confidence == ConfidenceLevel.HIGH
        assert rec.selected_candidate is not None
        assert rec.selected_candidate.selector == "#sign-in-btn"
        assert len(rec.candidates) == 1
        assert rec.requires_validation is True

    @pytest.mark.asyncio
    async def test_multiple_candidates_ranked(
        self, memory_store: InMemoryStore,
    ):
        """SCENARIO 2: Multiple candidates → ranked by confidence."""
        previous = _make_element(
            selector="#login-btn", text="Login", role="button",
        )

        candidates = [
            _make_element(
                element_id="c1", selector="#sign-in-btn",
                text="Login", role="button",
            ),
            _make_element(
                element_id="c2", selector="#submit-btn",
                text="Submit", role="button",
            ),
            _make_element(
                element_id="c3", selector=".button-primary",
                text="Go", role="link",
            ),
        ]

        analysis = _make_failure_analysis(
            failure_type=FailureType.SELECTOR_CHANGED,
            previous_element=previous,
        )
        ctx = _make_healing_context(
            failure_analysis=analysis,
            current_elements=candidates,
        )

        engine = HealingDecisionEngine(memory_store=memory_store)
        rec = await engine.generate_recommendation(ctx)

        assert len(rec.candidates) == 3
        # First candidate should be the best match
        assert rec.candidates[0].selector == "#sign-in-btn"
        # Candidates should be in descending confidence order
        for i in range(len(rec.candidates) - 1):
            assert rec.candidates[i].confidence >= rec.candidates[i + 1].confidence

    @pytest.mark.asyncio
    async def test_no_candidates(self, memory_store: InMemoryStore):
        """SCENARIO 3: No candidates → DO_NOT_HEAL."""
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

        assert rec.recommended_action == HealingAction.DO_NOT_HEAL
        assert rec.selected_candidate is None
        assert len(rec.candidates) == 0
        assert rec.confidence == ConfidenceLevel.LOW

    @pytest.mark.asyncio
    async def test_low_confidence_candidate(
        self, memory_store: InMemoryStore,
    ):
        """SCENARIO 4: Weak similarity → low confidence recommendation."""
        previous = _make_element(
            selector="#login-btn", text="Login", role="button",
            page_url="https://app.example.com/login",
        )
        # Very different element — only page matches
        current = _make_element(
            element_id="elem_unrelated",
            selector="#footer-link",
            text="About Us",
            role="link",
            page_url="https://app.example.com/login",
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

        # Should be low confidence — only page matches
        assert rec.confidence == ConfidenceLevel.LOW
        # Action should indicate further analysis or search needed
        assert rec.recommended_action in (
            HealingAction.REQUIRE_FURTHER_ANALYSIS,
            HealingAction.SEARCH_CURRENT_UI,
        )


# ═══════════════════════════════════════════════════════════════
# SAFETY RULES TESTS
# ═══════════════════════════════════════════════════════════════


class TestSafetyRules:
    """Test that unsafe healing is prevented."""

    @pytest.mark.asyncio
    async def test_assertion_failure_not_healed(
        self, memory_store: InMemoryStore,
    ):
        """SCENARIO 5: Assertion failure → DO_NOT_HEAL."""
        analysis = _make_failure_analysis(
            failure_type=FailureType.ASSERTION_FAILURE,
        )
        ctx = _make_healing_context(
            failure_analysis=analysis,
            current_elements=[_make_element(selector="#sign-in-btn")],
        )

        engine = HealingDecisionEngine(memory_store=memory_store)
        rec = await engine.generate_recommendation(ctx)

        assert rec.recommended_action == HealingAction.DO_NOT_HEAL
        assert rec.selected_candidate is None
        assert len(rec.candidates) == 0

    @pytest.mark.asyncio
    async def test_network_error_not_healed(
        self, memory_store: InMemoryStore,
    ):
        """Network errors should not be healed."""
        analysis = _make_failure_analysis(
            failure_type=FailureType.NETWORK_ERROR,
        )
        ctx = _make_healing_context(failure_analysis=analysis)

        engine = HealingDecisionEngine(memory_store=memory_store)
        rec = await engine.generate_recommendation(ctx)

        assert rec.recommended_action == HealingAction.DO_NOT_HEAL

    @pytest.mark.asyncio
    async def test_application_error_not_healed(
        self, memory_store: InMemoryStore,
    ):
        """Application errors should not be healed."""
        analysis = _make_failure_analysis(
            failure_type=FailureType.APPLICATION_ERROR,
        )
        ctx = _make_healing_context(failure_analysis=analysis)

        engine = HealingDecisionEngine(memory_store=memory_store)
        rec = await engine.generate_recommendation(ctx)

        assert rec.recommended_action == HealingAction.DO_NOT_HEAL

    @pytest.mark.asyncio
    async def test_unknown_failure_further_analysis(
        self, memory_store: InMemoryStore,
    ):
        """SCENARIO 6: Unknown failure with no candidates → REQUIRE_FURTHER_ANALYSIS."""
        analysis = _make_failure_analysis(
            failure_type=FailureType.UNKNOWN,
            previous_element=_make_element(),
        )
        ctx = _make_healing_context(
            failure_analysis=analysis,
            current_elements=[],
        )

        engine = HealingDecisionEngine(memory_store=memory_store)
        rec = await engine.generate_recommendation(ctx)

        assert rec.recommended_action == HealingAction.REQUIRE_FURTHER_ANALYSIS
        assert rec.confidence == ConfidenceLevel.LOW


# ═══════════════════════════════════════════════════════════════
# LLM INTEGRATION TESTS
# ═══════════════════════════════════════════════════════════════


class _MockHealingLLMProvider(LLMClient):
    """Mock LLM provider for healing disambiguation tests."""

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


class TestLLMDisambiguation:
    """Test optional LLM-assisted disambiguation."""

    @pytest.mark.asyncio
    async def test_clear_winner_skips_llm(
        self, memory_store: InMemoryStore,
    ):
        """When one candidate is clearly better, LLM is not needed."""
        previous = _make_element(
            selector="#login-btn", text="Login", role="button",
            page_url="https://app.example.com/login",
            attributes={"type": "submit", "name": "login"},
        )
        current = _make_element(
            element_id="c1", selector="#sign-in-btn",
            text="Login", role="button",
            page_url="https://app.example.com/login",
            attributes={"type": "submit", "name": "login"},
        )

        mock_provider = _MockHealingLLMProvider(
            {"selected_index": 0, "confidence": 0.99},
        )
        llm_session = LLMClientSession(
            provider=mock_provider,
            config=LLMConfig(provider="mock", model="mock-healing"),
        )

        analysis = _make_failure_analysis(
            failure_type=FailureType.SELECTOR_CHANGED,
            previous_element=previous,
        )
        ctx = _make_healing_context(
            failure_analysis=analysis,
            current_elements=[current],
            page_url="https://app.example.com/login",
        )

        engine = HealingDecisionEngine(
            memory_store=memory_store,
            llm_client=llm_session,
        )
        rec = await engine.generate_recommendation(ctx)

        # Should still get the right result without needing LLM
        assert rec.selected_candidate is not None
        assert rec.selected_candidate.selector == "#sign-in-btn"
        assert rec.recommended_action == HealingAction.TRY_REPLACEMENT_SELECTOR

    @pytest.mark.asyncio
    async def test_llm_failure_falls_back_gracefully(
        self, memory_store: InMemoryStore,
    ):
        """If LLM fails, the engine should still produce a recommendation."""

        class _FailingProvider(LLMClient):
            def __init__(self):
                super().__init__(
                    LLMConfig(provider="mock", model="mock-fail"),
                )

            async def generate(self, request: LLMRequest) -> LLMResponse:
                raise RuntimeError("LLM unavailable")

        llm_session = LLMClientSession(
            provider=_FailingProvider(),
            config=LLMConfig(provider="mock", model="mock-fail"),
        )

        previous = _make_element(selector="#login-btn", text="Login", role="button")
        current = _make_element(
            element_id="c1", selector="#sign-in-btn", text="Login", role="button",
        )

        analysis = _make_failure_analysis(
            failure_type=FailureType.SELECTOR_CHANGED,
            previous_element=previous,
        )
        ctx = _make_healing_context(
            failure_analysis=analysis,
            current_elements=[current],
        )

        engine = HealingDecisionEngine(
            memory_store=memory_store, llm_client=llm_session,
        )
        rec = await engine.generate_recommendation(ctx)

        # Should still work — deterministic path
        assert rec is not None
        assert rec.test_id == "TC_LOGIN_001"


# ═══════════════════════════════════════════════════════════════
# MEMBER 2 INTERFACE TESTS
# ═══════════════════════════════════════════════════════════════


class TestMember2Interface:
    """Test the mapping between Member 1 and Member 2 contracts."""

    def test_recommendation_to_healing_candidate(self):
        """HealingRecommendation should map to HealingCandidate."""
        selected = ScoredCandidate(
            selector="#sign-in-btn",
            selector_type="id",
            source=CandidateSource.CURRENT_DOM,
            confidence=0.92,
            evidence=["Same visible text: Login", "Same role: button"],
        )

        rec = HealingRecommendation(
            test_id="TC_LOGIN_001",
            execution_id="exec_001",
            failed_step=3,
            original_selector="#login-btn",
            failure_type=FailureType.SELECTOR_CHANGED,
            candidates=[
                selected,
                ScoredCandidate(
                    selector="#submit-btn",
                    source=CandidateSource.CURRENT_DOM,
                    confidence=0.45,
                ),
            ],
            selected_candidate=selected,
            confidence=ConfidenceLevel.HIGH,
            recommended_action=HealingAction.TRY_REPLACEMENT_SELECTOR,
        )

        hc = recommendation_to_healing_candidate(rec)

        assert isinstance(hc, HealingCandidate)
        assert hc.test_id == "TC_LOGIN_001"
        assert hc.failed_step == 3
        assert hc.healing_attempted is True
        assert hc.old_selector == "#login-btn"
        assert hc.new_selector == "#sign-in-btn"
        assert hc.confidence == 0.92
        assert hc.requires_validation is True
        assert hc.status == HealingStatus.PROPOSED
        assert "#submit-btn" in hc.alternative_selectors

    def test_recommendation_do_not_heal_maps_correctly(self):
        """DO_NOT_HEAL should set healing_attempted to False."""
        rec = HealingRecommendation(
            test_id="TC_001",
            execution_id="exec_001",
            failed_step=1,
            failure_type=FailureType.ASSERTION_FAILURE,
            confidence=ConfidenceLevel.HIGH,
            recommended_action=HealingAction.DO_NOT_HEAL,
        )

        hc = recommendation_to_healing_candidate(rec)

        assert hc.healing_attempted is False
        assert hc.new_selector == ""
        assert hc.confidence == 0.0

    def test_healing_result_to_memory_update_success(self):
        """Successful healing result should map to memory update."""
        result = HealingResult(
            test_id="TC_LOGIN_001",
            failed_step=3,
            old_selector="#login-btn",
            new_selector="#sign-in-btn",
            status=HealingStatus.VALIDATED_SUCCESS,
            confidence=0.92,
        )

        update = healing_result_to_memory_update(result)

        assert update["is_success"] is True
        assert update["old_selector"] == "#login-btn"
        assert update["new_selector"] == "#sign-in-btn"
        assert "healing_record" in update
        assert update["healing_record"]["validation_result"] is True
        assert update["healing_record"]["confidence"] == 0.92

    def test_healing_result_to_memory_update_failure(self):
        """Failed healing result should map correctly."""
        result = HealingResult(
            test_id="TC_LOGIN_001",
            failed_step=3,
            old_selector="#login-btn",
            new_selector="#wrong-btn",
            status=HealingStatus.VALIDATED_FAILURE,
            confidence=0.45,
        )

        update = healing_result_to_memory_update(result)

        assert update["is_success"] is False
        assert update["healing_record"]["validation_result"] is False


# ═══════════════════════════════════════════════════════════════
# INTEGRATION TEST
# ═══════════════════════════════════════════════════════════════


class TestEndToEndIntegration:
    """End-to-end integration test:

    Historical Memory
         ↓
    Previous Successful Execution
         ↓
    Current Failed Execution
         ↓
    Failure Analyzer
         ↓
    FailureAnalysis
         ↓
    Healing Decision Layer
         ↓
    Candidate Generation
         ↓
    Candidate Ranking
         ↓
    HealingRecommendation

    No browser is launched.  No real model is required.
    """

    @pytest.mark.asyncio
    async def test_full_pipeline_selector_change(self):
        """Full pipeline: memory → analyzer → decision → recommendation."""
        # 1. Set up memory with historical data
        store = InMemoryStore()

        # Store a previous successful execution
        store.store_execution(
            TestExecutionRecord(
                execution_id="exec_success_001",
                test_id="TC_LOGIN_001",
                test_name="Login Test",
                status=ExecutionStatus.PASSED,
                duration_ms=1200.0,
            )
        )

        # Store the historical element
        previous_element = _make_element(
            element_id="elem_login_btn",
            selector="#login-btn",
            text="Login",
            role="button",
            page_url="https://app.example.com/login",
            attributes={"type": "submit", "name": "login"},
        )
        store.store_element(previous_element)

        # Store a failed execution
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

        # 2. Create the failure context (as Member 2 would provide)
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

        # Verify analyzer output
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

        # 6. Verify the recommendation
        assert recommendation.test_id == "TC_LOGIN_001"
        assert recommendation.execution_id == "exec_fail_001"
        assert recommendation.failure_type == FailureType.SELECTOR_CHANGED
        assert recommendation.recommended_action == HealingAction.TRY_REPLACEMENT_SELECTOR
        assert recommendation.confidence == ConfidenceLevel.HIGH
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

    @pytest.mark.asyncio
    async def test_full_pipeline_assertion_failure(self):
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
        assert recommendation.selected_candidate is None
        assert recommendation.requires_validation is True

    @pytest.mark.asyncio
    async def test_full_pipeline_no_match(self):
        """Full pipeline: no matching element → appropriate action."""
        store = InMemoryStore()

        previous = _make_element(
            selector="#login-btn", text="Login", role="button",
        )
        store.store_element(previous)

        failure_context = FailureContext(
            test_id="TC_LOGIN_001",
            execution_id="exec_fail_003",
            failed_step=3,
            action="click",
            target_selector="#login-btn",
            error_message="Element not found: #login-btn",
        )

        analyzer = FailureAnalyzerAgent(memory_store=store)
        analysis = await analyzer.analyze(failure_context)

        healing_ctx = HealingContext(
            failure_analysis=analysis,
            current_elements=[],
        )

        engine = HealingDecisionEngine(memory_store=store)
        recommendation = await engine.generate_recommendation(healing_ctx)

        # No candidates → should not try replacement
        assert recommendation.selected_candidate is None
        assert recommendation.recommended_action in (
            HealingAction.DO_NOT_HEAL,
            HealingAction.REQUIRE_FURTHER_ANALYSIS,
        )
