"""
TestSphere-AI — Candidate Scorer

Deterministic scoring and ranking engine for healing candidates.

Applies configurable weights to individual similarity scores
computed by the ``CandidateGenerator`` to produce a final
confidence value for each candidate.

Day 10: Foundation implementation.
Day 11: Added stable_attribute_weight and adjusted defaults.

Scoring Formula
---------------
confidence = sum(score_i * weight_i) / sum(weight_i)

Each component score is 0.0 (no match) or 1.0 (match), except
stable_attribute which can be fractional.  Weights are normalized
by their sum so the result is always in [0.0, 1.0].

Scoring Weights (defaults)
--------------------------
========================  ======  ============
Component                 Weight  Rationale
========================  ======  ============
text_weight               0.25    Visible text is the strongest signal
role_weight               0.20    Semantic role is highly stable
page_weight               0.15    Same page context is strong
historical_weight         0.15    Validated precedent carries weight
type_weight               0.10    Element type is moderately stable
stable_attribute_weight   0.10    data-testid/aria-label designed stable
name_weight               0.05    Name attribute is a weak signal
========================  ======  ============

These weights are configurable via the ``ScoringWeights`` model.
Given the same inputs, scoring always produces the same result
(deterministic).
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field, model_validator

from agents.healer.healing_schemas import ScoredCandidate

logger = logging.getLogger(__name__)


class ScoringWeights(BaseModel):
    """Configurable scoring weights for candidate evaluation.

    All weights must be non-negative and must sum to a positive
    value (they are normalized internally).

    Default values reflect the principle that text content,
    historical precedent, and semantic role are the strongest
    indicators of a correct replacement selector.
    """

    text_weight: float = Field(
        default=0.30, ge=0.0,
        description="Weight for visible text match (strong)",
    )
    role_weight: float = Field(
        default=0.25, ge=0.0,
        description="Weight for ARIA/semantic role match (strong)",
    )
    type_weight: float = Field(
        default=0.10, ge=0.0,
        description="Weight for element type match (moderate)",
    )
    page_weight: float = Field(
        default=0.15, ge=0.0,
        description="Weight for same page context (moderate)",
    )
    historical_weight: float = Field(
        default=0.15, ge=0.0,
        description="Weight for historical relationship (bonus)",
    )
    name_weight: float = Field(
        default=0.05, ge=0.0,
        description="Weight for name attribute match (light)",
    )
    stable_attribute_weight: float = Field(
        default=0.0, ge=0.0,
        description="Weight for stable attribute match (data-testid, aria-label, etc.)",
    )

    @model_validator(mode="after")
    def _weights_must_sum_positive(self) -> "ScoringWeights":
        """Ensure at least one weight is positive."""
        total = (
            self.text_weight
            + self.role_weight
            + self.type_weight
            + self.page_weight
            + self.historical_weight
            + self.name_weight
            + self.stable_attribute_weight
        )
        if total <= 0.0:
            raise ValueError("At least one scoring weight must be positive")
        return self

    @property
    def total(self) -> float:
        """Sum of all weights."""
        return (
            self.text_weight
            + self.role_weight
            + self.type_weight
            + self.page_weight
            + self.historical_weight
            + self.name_weight
            + self.stable_attribute_weight
        )


class CandidateScorer:
    """Deterministic scoring and ranking engine.

    Computes weighted confidence scores for ``ScoredCandidate``
    instances and ranks them by confidence (highest first).

    Parameters
    ----------
    weights:
        Optional custom scoring weights.  Uses defaults if None.
    """

    def __init__(self, weights: ScoringWeights | None = None) -> None:
        self._weights = weights or ScoringWeights()

    @property
    def weights(self) -> ScoringWeights:
        """The active scoring weights."""
        return self._weights

    def score_candidate(self, candidate: ScoredCandidate) -> float:
        """Compute the weighted confidence score for a candidate.

        Parameters
        ----------
        candidate:
            A candidate with individual similarity scores set.

        Returns
        -------
        float
            The weighted confidence score (0.0 to 1.0).
        """
        w = self._weights
        total_weight = w.total

        if total_weight <= 0.0:
            return 0.0

        raw_score = (
            candidate.text_similarity * w.text_weight
            + candidate.role_similarity * w.role_weight
            + candidate.type_similarity * w.type_weight
            + candidate.page_similarity * w.page_weight
            + candidate.historical_similarity * w.historical_weight
            + candidate.name_similarity * w.name_weight
            + candidate.stable_attribute_similarity * w.stable_attribute_weight
        )

        # Normalize to 0.0–1.0
        confidence = raw_score / total_weight
        return round(min(max(confidence, 0.0), 1.0), 4)

    def score_and_update(
        self, candidate: ScoredCandidate,
    ) -> ScoredCandidate:
        """Score a candidate and return an updated copy.

        Parameters
        ----------
        candidate:
            A candidate to score.

        Returns
        -------
        ScoredCandidate
            A new instance with ``confidence`` set.
        """
        score = self.score_candidate(candidate)
        return candidate.model_copy(update={"confidence": score})

    def rank_candidates(
        self,
        candidates: list[ScoredCandidate],
    ) -> list[ScoredCandidate]:
        """Score and rank candidates by confidence (highest first).

        Parameters
        ----------
        candidates:
            Unscored or pre-scored candidates.

        Returns
        -------
        list[ScoredCandidate]
            Candidates sorted by confidence, highest first.
            Each candidate's ``confidence`` field is updated.
        """
        scored = [self.score_and_update(c) for c in candidates]
        scored.sort(key=lambda c: c.confidence, reverse=True)

        if scored:
            logger.info(
                "Ranked %d candidate(s) — top confidence=%.4f, "
                "bottom confidence=%.4f",
                len(scored),
                scored[0].confidence,
                scored[-1].confidence,
            )

        return scored
