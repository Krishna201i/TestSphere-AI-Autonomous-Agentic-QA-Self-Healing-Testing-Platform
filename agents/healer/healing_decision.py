"""
TestSphere-AI — Healing Decision Engine

Orchestrates the full healing recommendation pipeline:

    FailureAnalysis
         ↓
    Safety Rules Check
         ↓
    Candidate Generation
         ↓
    Candidate Scoring
         ↓
    Candidate Ranking
         ↓
    Ambiguity Detection
         ↓
    Confidence Threshold Check
         ↓
    Optional LLM Disambiguation (ambiguous only)
         ↓
    Grounding Validation
         ↓
    Final Healing Decision
         ↓
    HealingRecommendation

Day 10: Foundation implementation.
Day 11: Ambiguity detection, LLM evaluator integration,
        HealingDecision enum, grounding validation.

IMPORTANT: This engine does NOT execute browser actions.
It produces a structured ``HealingRecommendation`` that
Member 2's Self-Healing Engine can consume.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Optional

from pydantic import BaseModel, Field

from agents.healer.candidate_generator import CandidateGenerator
from agents.healer.candidate_scorer import CandidateScorer, ScoringWeights
from agents.healer.healing_schemas import (
    HealingContext,
    HealingRecommendation,
    ScoredCandidate,
)
from agents.memory.context_comparator import ContextComparator
from agents.memory.memory_interface import MemoryStore
from agents.schemas.enums import (
    ConfidenceLevel,
    FailureType,
    HealingAction,
    HealingDecision,
)

if TYPE_CHECKING:
    from agents.analyzer.schemas import FailureAnalysis

logger = logging.getLogger(__name__)


# ── Failure types that should NEVER be healed ─────────────────

_NON_HEALABLE_FAILURES: frozenset[FailureType] = frozenset({
    FailureType.ASSERTION_FAILURE,
    FailureType.NETWORK_ERROR,
    FailureType.APPLICATION_ERROR,
})


# ── Confidence Thresholds ─────────────────────────────────────


class ConfidenceThresholds(BaseModel):
    """Configurable confidence thresholds for healing decisions.

    Thresholds
    ----------
    high_threshold:
        Confidence score at or above which a candidate is considered
        HIGH confidence (0.80 default).
    medium_threshold:
        Confidence score at or above which a candidate is considered
        MEDIUM confidence (0.50 default).
    minimum_healing_threshold:
        Minimum confidence score required for any healing attempt
        (0.30 default).  Below this, DO_NOT_HEAL is recommended.
    ambiguity_threshold:
        Maximum score gap between the top two candidates for them
        to be considered ambiguous (0.05 default).  If the gap is
        <= this value, the candidates are considered ambiguous and
        further analysis or LLM disambiguation is triggered.
    """

    high_threshold: float = Field(
        default=0.80, ge=0.0, le=1.0,
        description="Threshold for HIGH confidence (default 0.80)",
    )
    medium_threshold: float = Field(
        default=0.50, ge=0.0, le=1.0,
        description="Threshold for MEDIUM confidence (default 0.50)",
    )
    minimum_healing_threshold: float = Field(
        default=0.30, ge=0.0, le=1.0,
        description="Minimum confidence for any healing attempt (default 0.30)",
    )
    ambiguity_threshold: float = Field(
        default=0.05, ge=0.0, le=1.0,
        description=(
            "Maximum gap between top two candidates to be considered "
            "ambiguous (default 0.05)"
        ),
    )


# ── Healing Decision Engine ───────────────────────────────────


class HealingDecisionEngine:
    """Orchestrates the healing recommendation pipeline.

    Takes a ``HealingContext`` (containing a ``FailureAnalysis``
    and current UI elements), generates and scores candidates,
    applies safety rules, detects ambiguity, and produces a
    ``HealingRecommendation``.

    Parameters
    ----------
    memory_store:
        Memory store for historical context.
    llm_client:
        Optional LLM client session for ambiguous candidate
        disambiguation.  If ``None``, only deterministic rules
        are used.
    weights:
        Optional custom scoring weights.
    thresholds:
        Optional custom confidence thresholds.
    """

    def __init__(
        self,
        memory_store: MemoryStore,
        llm_client: object | None = None,
        weights: ScoringWeights | None = None,
        thresholds: ConfidenceThresholds | None = None,
    ) -> None:
        self._memory = memory_store
        self._llm_client = llm_client
        self._generator = CandidateGenerator(
            memory_store=memory_store,
            comparator=ContextComparator(),
        )
        self._scorer = CandidateScorer(weights=weights)
        self._thresholds = thresholds or ConfidenceThresholds()

        # Initialize LLM evaluator if client is available
        self._llm_evaluator = None
        if llm_client is not None:
            from agents.healer.llm_healing_evaluator import LLMHealingEvaluator
            self._llm_evaluator = LLMHealingEvaluator(llm_client)

        logger.info(
            "HealingDecisionEngine initialized — llm_available=%s",
            llm_client is not None,
        )

    # ── Public API ────────────────────────────────────────────

    async def generate_recommendation(
        self, context: HealingContext,
    ) -> HealingRecommendation:
        """Generate a healing recommendation for a failed test step.

        Parameters
        ----------
        context:
            Healing context with failure analysis and current elements.

        Returns
        -------
        HealingRecommendation
            A structured recommendation with ranked candidates
            and recommended action.
        """
        analysis = context.failure_analysis

        logger.info(
            "Generating recommendation — test_id=%s, failure_type=%s",
            analysis.test_id,
            analysis.failure_type.value,
        )

        # 1. Check safety rules
        safety_result = self._check_safety_rules(analysis)
        if safety_result is not None:
            logger.info(
                "Safety rule triggered — action=%s",
                safety_result.recommended_action.value,
            )
            return safety_result

        # 2. Generate candidates
        candidates = self._generator.generate_candidates(context)

        # 3. Score and rank
        ranked = self._scorer.rank_candidates(candidates)

        # 4. Detect ambiguity
        is_ambiguous = self._detect_ambiguity(ranked)

        # 5. Apply confidence thresholds and determine action
        selected, confidence_level, action = self._evaluate_candidates(
            ranked, analysis, is_ambiguous,
        )

        # 6. Optional LLM disambiguation for ambiguous cases
        if (
            is_ambiguous
            and self._llm_evaluator is not None
            and len(ranked) >= 2
            and action == HealingAction.REQUIRE_FURTHER_ANALYSIS
        ):
            llm_result = await self._attempt_llm_disambiguation(
                ranked, analysis,
            )
            if llm_result is not None:
                selected = llm_result
                confidence_level = self._classify_confidence(
                    llm_result.confidence,
                )
                action = self._determine_action_for_confidence(
                    llm_result.confidence,
                )
                is_ambiguous = False  # LLM resolved ambiguity

        # 7. Determine final healing decision
        decision = self._determine_decision(
            selected, confidence_level, action, is_ambiguous,
        )

        # 8. Build evidence summary
        evidence = self._build_evidence_summary(
            analysis, ranked, selected, action, is_ambiguous,
        )

        recommendation = HealingRecommendation(
            test_id=analysis.test_id,
            execution_id=analysis.execution_id,
            failed_step=analysis.failed_step,
            original_selector=analysis.failed_target,
            failure_type=analysis.failure_type,
            candidates=ranked,
            selected_candidate=selected,
            confidence=confidence_level,
            recommended_action=action,
            decision=decision,
            evidence=evidence,
            requires_validation=True,
        )

        logger.info(
            "Recommendation complete — decision=%s, action=%s, "
            "confidence=%s, candidates=%d, selected=%s, ambiguous=%s",
            decision.value,
            action.value,
            confidence_level.value,
            len(ranked),
            selected.selector if selected else "None",
            is_ambiguous,
        )

        return recommendation

    # ── Safety Rules ──────────────────────────────────────────

    def _check_safety_rules(
        self, analysis: FailureAnalysis,
    ) -> Optional[HealingRecommendation]:
        """Check if healing should be blocked for this failure type.

        Returns a DO_NOT_HEAL recommendation if healing is unsafe,
        or None if healing may proceed.
        """
        if analysis.failure_type in _NON_HEALABLE_FAILURES:
            reason = (
                f"Failure type '{analysis.failure_type.value}' is not "
                f"eligible for selector-based healing"
            )
            return HealingRecommendation(
                test_id=analysis.test_id,
                execution_id=analysis.execution_id,
                failed_step=analysis.failed_step,
                original_selector=analysis.failed_target,
                failure_type=analysis.failure_type,
                candidates=[],
                selected_candidate=None,
                confidence=ConfidenceLevel.HIGH,
                recommended_action=HealingAction.DO_NOT_HEAL,
                decision=HealingDecision.DO_NOT_HEAL,
                evidence=[reason],
                requires_validation=True,
            )

        return None

    # ── Ambiguity Detection ───────────────────────────────────

    def _detect_ambiguity(
        self, ranked: list[ScoredCandidate],
    ) -> bool:
        """Detect if the top two candidates have ambiguous scores.

        Two candidates are considered ambiguous when the gap between
        their confidence scores is <= the configured ambiguity_threshold.

        Parameters
        ----------
        ranked:
            Candidates sorted by confidence (highest first).

        Returns
        -------
        bool
            True if top two candidates are ambiguous, False otherwise.
        """
        if len(ranked) < 2:
            return False

        gap = ranked[0].confidence - ranked[1].confidence
        is_ambiguous = gap <= self._thresholds.ambiguity_threshold

        if is_ambiguous:
            logger.info(
                "Ambiguity detected — top=%s (%.4f), second=%s (%.4f), "
                "gap=%.4f <= threshold=%.4f",
                ranked[0].selector,
                ranked[0].confidence,
                ranked[1].selector,
                ranked[1].confidence,
                gap,
                self._thresholds.ambiguity_threshold,
            )

        return is_ambiguous

    # ── Candidate Evaluation ──────────────────────────────────

    def _evaluate_candidates(
        self,
        ranked: list[ScoredCandidate],
        analysis: FailureAnalysis,
        is_ambiguous: bool = False,
    ) -> tuple[Optional[ScoredCandidate], ConfidenceLevel, HealingAction]:
        """Evaluate ranked candidates and determine action.

        Returns (selected_candidate, confidence_level, action).
        """
        if not ranked:
            # No candidates at all
            if analysis.failure_type == FailureType.UNKNOWN:
                return (
                    None,
                    ConfidenceLevel.LOW,
                    HealingAction.REQUIRE_FURTHER_ANALYSIS,
                )
            return (
                None,
                ConfidenceLevel.LOW,
                HealingAction.DO_NOT_HEAL,
            )

        top = ranked[0]
        confidence_level = self._classify_confidence(top.confidence)

        # Below minimum threshold
        if top.confidence < self._thresholds.minimum_healing_threshold:
            return (
                None,
                ConfidenceLevel.LOW,
                HealingAction.REQUIRE_FURTHER_ANALYSIS,
            )

        # Ambiguous candidates — require further analysis or LLM
        if is_ambiguous and top.confidence >= self._thresholds.medium_threshold:
            return (
                top,
                confidence_level,
                HealingAction.REQUIRE_FURTHER_ANALYSIS,
            )

        # Between minimum and medium threshold
        if top.confidence < self._thresholds.medium_threshold:
            return (
                top,
                ConfidenceLevel.LOW,
                HealingAction.SEARCH_CURRENT_UI,
            )

        # Medium confidence
        if top.confidence < self._thresholds.high_threshold:
            return (
                top,
                ConfidenceLevel.MEDIUM,
                HealingAction.TRY_REPLACEMENT_SELECTOR,
            )

        # High confidence
        return (
            top,
            ConfidenceLevel.HIGH,
            HealingAction.TRY_REPLACEMENT_SELECTOR,
        )

    # ── Final Decision ────────────────────────────────────────

    @staticmethod
    def _determine_decision(
        selected: Optional[ScoredCandidate],
        confidence_level: ConfidenceLevel,
        action: HealingAction,
        is_ambiguous: bool,
    ) -> HealingDecision:
        """Determine the final healing decision.

        Maps confidence level and action into one of:
        RECOMMEND_HEALING, REQUIRE_VALIDATION,
        REQUIRE_FURTHER_ANALYSIS, or DO_NOT_HEAL.
        """
        if action == HealingAction.DO_NOT_HEAL:
            return HealingDecision.DO_NOT_HEAL

        if is_ambiguous:
            return HealingDecision.REQUIRE_FURTHER_ANALYSIS

        if action == HealingAction.REQUIRE_FURTHER_ANALYSIS:
            return HealingDecision.REQUIRE_FURTHER_ANALYSIS

        if selected is None:
            return HealingDecision.DO_NOT_HEAL

        if confidence_level == ConfidenceLevel.HIGH:
            return HealingDecision.RECOMMEND_HEALING

        if confidence_level == ConfidenceLevel.MEDIUM:
            return HealingDecision.REQUIRE_VALIDATION

        return HealingDecision.REQUIRE_FURTHER_ANALYSIS

    # ── Confidence Classification ─────────────────────────────

    def _classify_confidence(self, score: float) -> ConfidenceLevel:
        """Map a numeric confidence score to a ConfidenceLevel enum.

        HIGH:   score >= high_threshold (default 0.80)
        MEDIUM: score >= medium_threshold (default 0.50)
        LOW:    score < medium_threshold
        """
        if score >= self._thresholds.high_threshold:
            return ConfidenceLevel.HIGH
        if score >= self._thresholds.medium_threshold:
            return ConfidenceLevel.MEDIUM
        return ConfidenceLevel.LOW

    def _determine_action_for_confidence(
        self, confidence: float,
    ) -> HealingAction:
        """Map a confidence score to a HealingAction."""
        if confidence >= self._thresholds.medium_threshold:
            return HealingAction.TRY_REPLACEMENT_SELECTOR
        if confidence >= self._thresholds.minimum_healing_threshold:
            return HealingAction.SEARCH_CURRENT_UI
        return HealingAction.REQUIRE_FURTHER_ANALYSIS

    # ── Evidence Summary ──────────────────────────────────────

    @staticmethod
    def _build_evidence_summary(
        analysis: FailureAnalysis,
        ranked: list[ScoredCandidate],
        selected: Optional[ScoredCandidate],
        action: HealingAction,
        is_ambiguous: bool = False,
    ) -> list[str]:
        """Build a concise evidence summary for the recommendation."""
        evidence: list[str] = []

        evidence.append(
            f"Failure type: {analysis.failure_type.value}"
        )
        evidence.append(
            f"Original selector: {analysis.failed_target}"
        )
        evidence.append(
            f"Candidates evaluated: {len(ranked)}"
        )

        if selected:
            evidence.append(
                f"Selected candidate: {selected.selector} "
                f"(confidence: {selected.confidence:.4f})"
            )
        else:
            evidence.append("No candidate selected")

        if is_ambiguous:
            evidence.append("Ambiguous candidates detected")

        evidence.append(f"Recommended action: {action.value}")

        return evidence

    # ── LLM Disambiguation ────────────────────────────────────

    async def _attempt_llm_disambiguation(
        self,
        ranked: list[ScoredCandidate],
        analysis: FailureAnalysis,
    ) -> Optional[ScoredCandidate]:
        """Use the LLM evaluator to disambiguate ambiguous candidates.

        Only called when:
        - Ambiguity is detected between top candidates
        - LLM evaluator is available
        - At least 2 candidates exist

        The LLM's recommendation is strictly validated:
        - Schema validation (required fields + types)
        - Grounding check (selected_candidate must be in candidate list)

        Returns the LLM's preferred candidate as a ScoredCandidate,
        or None if the LLM fails or returns an invalid response.
        """
        if self._llm_evaluator is None:
            return None

        if len(ranked) < 2:
            return None

        result = await self._llm_evaluator.evaluate_candidates(
            candidates=ranked,
            original_selector=analysis.failed_target,
            failure_type=analysis.failure_type.value,
        )

        if result is None:
            return None

        # Find the matching candidate and return updated copy
        for candidate in ranked:
            if candidate.selector == result.selected_selector:
                updated = candidate.model_copy(
                    update={"confidence": result.confidence},
                )
                logger.info(
                    "LLM disambiguation resolved — "
                    "selector=%s, confidence=%.4f, reason=%s",
                    result.selected_selector,
                    result.confidence,
                    result.reason,
                )
                return updated

        # Should not reach here due to grounding validation
        logger.warning(
            "LLM selected selector '%s' not found in candidates "
            "(post-grounding — should not happen)",
            result.selected_selector,
        )
        return None
