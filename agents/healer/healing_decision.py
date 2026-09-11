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
    Confidence Threshold Check
         ↓
    Optional LLM Disambiguation
         ↓
    HealingRecommendation

Day 10: Foundation implementation.

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


# ── Healing Decision Engine ───────────────────────────────────


class HealingDecisionEngine:
    """Orchestrates the healing recommendation pipeline.

    Takes a ``HealingContext`` (containing a ``FailureAnalysis``
    and current UI elements), generates and scores candidates,
    applies safety rules, and produces a ``HealingRecommendation``.

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

        # 4. Apply confidence thresholds and determine action
        selected, confidence_level, action = self._evaluate_candidates(
            ranked, analysis,
        )

        # 5. Optional LLM disambiguation
        if (
            action == HealingAction.SEARCH_CURRENT_UI
            and self._llm_client is not None
            and len(ranked) >= 2
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

        # 6. Build evidence summary
        evidence = self._build_evidence_summary(
            analysis, ranked, selected, action,
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
            evidence=evidence,
            requires_validation=True,
        )

        logger.info(
            "Recommendation complete — action=%s, confidence=%s, "
            "candidates=%d, selected=%s",
            action.value,
            confidence_level.value,
            len(ranked),
            selected.selector if selected else "None",
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
                evidence=[reason],
                requires_validation=True,
            )

        return None

    # ── Candidate Evaluation ──────────────────────────────────

    def _evaluate_candidates(
        self,
        ranked: list[ScoredCandidate],
        analysis: FailureAnalysis,
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

        evidence.append(f"Recommended action: {action.value}")

        return evidence

    # ── LLM Disambiguation ────────────────────────────────────

    async def _attempt_llm_disambiguation(
        self,
        ranked: list[ScoredCandidate],
        analysis: FailureAnalysis,
    ) -> Optional[ScoredCandidate]:
        """Use the LLM to disambiguate tied or ambiguous candidates.

        Only called when:
        - Multiple candidates exist
        - No clear winner (top candidates are close in confidence)
        - LLM client is available

        Returns the LLM's preferred candidate, or None if the LLM
        fails or returns an invalid response.
        """
        if self._llm_client is None:
            return None

        # Check if top candidates are close (within 0.1)
        if len(ranked) < 2:
            return None

        top_score = ranked[0].confidence
        second_score = ranked[1].confidence
        if top_score - second_score > 0.1:
            # Clear winner — no LLM needed
            return ranked[0]

        # Build concise prompt
        candidates_data = [
            {
                "selector": c.selector,
                "confidence": c.confidence,
                "evidence": c.evidence[:3],  # Limit evidence
            }
            for c in ranked[:5]  # Limit to top 5
        ]

        prompt_data = {
            "task": "Select the best replacement selector candidate.",
            "original_selector": analysis.failed_target,
            "failure_type": analysis.failure_type.value,
            "candidates": candidates_data,
            "instruction": (
                "Return a JSON object with 'selected_index' (0-based) "
                "and 'confidence' (0.0-1.0)."
            ),
        }

        from agents.llm.schemas import LLMRequest

        try:
            request = LLMRequest(
                prompt=json.dumps(prompt_data, indent=2),
                system_instruction=(
                    "You are a test healing disambiguation engine. "
                    "Respond ONLY with a JSON object containing: "
                    "selected_index, confidence. "
                    "Do not include any other text."
                ),
                response_format="json",
                temperature=0.1,
            )

            response_data = await self._llm_client.generate_json(request)

            idx = response_data.get("selected_index", 0)
            conf = response_data.get("confidence", 0.0)

            if not isinstance(idx, int) or idx < 0 or idx >= len(ranked):
                logger.warning(
                    "LLM returned invalid selected_index: %s", idx,
                )
                return None

            if not isinstance(conf, (int, float)):
                conf = ranked[idx].confidence

            conf = min(max(float(conf), 0.0), 1.0)

            selected = ranked[idx].model_copy(update={"confidence": conf})
            logger.info(
                "LLM disambiguation selected index=%d, "
                "selector=%s, confidence=%.4f",
                idx,
                selected.selector,
                conf,
            )
            return selected

        except Exception as exc:
            logger.warning(
                "LLM disambiguation failed: %s: %s",
                type(exc).__name__,
                exc,
            )
            return None
