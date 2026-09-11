"""
TestSphere-AI — Healing Decision Schemas

Internal data models for the Healing Decision Layer (Day 10).

These schemas support the candidate generation, scoring, ranking,
and recommendation pipeline.  They are distinct from the inter-member
``HealingCandidate`` contract in ``healer/schemas.py``, which defines
the format that Member 2 consumes.

Schemas
-------
- ScoredCandidate      — A candidate selector with similarity scores
- HealingRecommendation — The final structured healing recommendation
- HealingContext        — Input context for the healing decision layer
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING, Optional

from pydantic import BaseModel, Field, field_validator

from agents.memory.memory_schemas import ElementRecord
from agents.schemas.enums import (
    CandidateSource,
    ConfidenceLevel,
    FailureType,
    HealingAction,
)

if TYPE_CHECKING:
    from agents.analyzer.schemas import FailureAnalysis


# ── Scored Candidate ─────────────────────────────────────────


class ScoredCandidate(BaseModel):
    """A candidate replacement selector with similarity scores.

    Produced by the ``CandidateGenerator`` and scored by the
    ``CandidateScorer``.  Contains individual similarity scores
    for transparency and debugging, plus concise observable evidence.

    The ``confidence`` field is the final computed score (0.0–1.0)
    after weighted scoring.  It does NOT represent a mathematical
    probability — it is a heuristic similarity measure.
    """

    selector: str = Field(
        ..., min_length=1,
        description="Candidate replacement selector string",
    )
    selector_type: str = Field(
        default="css",
        description="Type of selector: 'id', 'css', 'xpath', 'name', etc.",
    )
    source: CandidateSource = Field(
        ...,
        description="Where this candidate originated from",
    )
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Computed confidence score (0.0 to 1.0)",
    )
    evidence: list[str] = Field(
        default_factory=list,
        description="Concise, observable evidence strings supporting this candidate",
    )

    # Individual similarity component scores (0.0–1.0 each)
    text_similarity: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Text content match score",
    )
    role_similarity: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="ARIA/semantic role match score",
    )
    type_similarity: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Element type match score",
    )
    page_similarity: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Page context match score",
    )
    historical_similarity: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Historical relationship match score",
    )
    name_similarity: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Name attribute match score",
    )


# ── Healing Recommendation ───────────────────────────────────


class HealingRecommendation(BaseModel):
    """Structured healing recommendation from the intelligence layer.

    This is the primary output of the Healing Decision Engine.
    It contains ranked candidates, the selected best candidate
    (if any), and the recommended action for Member 2.

    The ``requires_validation`` field is always ``True`` — the
    intelligence layer NEVER declares a candidate as validated.
    Validation is exclusively Member 2's responsibility.
    """

    test_id: str = Field(
        ..., min_length=1,
        description="ID of the failed test case",
    )
    execution_id: str = Field(
        ..., min_length=1,
        description="Unique execution identifier",
    )
    failed_step: int = Field(
        ..., ge=1,
        description="1-based step number that failed",
    )
    original_selector: str = Field(
        default="",
        description="The original selector that failed",
    )
    failure_type: FailureType = Field(
        ...,
        description="Classified failure type from the analysis",
    )
    candidates: list[ScoredCandidate] = Field(
        default_factory=list,
        description="Candidate selectors, ranked by confidence (highest first)",
    )
    selected_candidate: Optional[ScoredCandidate] = Field(
        default=None,
        description=(
            "Top candidate if it meets the confidence threshold. "
            "None if no candidate is suitable."
        ),
    )
    confidence: ConfidenceLevel = Field(
        ...,
        description="Overall recommendation confidence level",
    )
    recommended_action: HealingAction = Field(
        ...,
        description="Recommended action for Member 2's Self-Healing Engine",
    )
    evidence: list[str] = Field(
        default_factory=list,
        description="Summary evidence supporting the recommendation",
    )
    requires_validation: bool = Field(
        default=True,
        description=(
            "Whether Member 2 must validate the recommendation "
            "(always True — intelligence layer never self-validates)"
        ),
    )

    @field_validator("requires_validation")
    @classmethod
    def _must_require_validation(cls, v: bool) -> bool:
        """Enforce that requires_validation is always True."""
        if not v:
            raise ValueError(
                "requires_validation must always be True — "
                "the intelligence layer never self-validates healing"
            )
        return v


# ── Healing Context (input) ──────────────────────────────────


class HealingContext(BaseModel):
    """Input context for the Healing Decision Engine.

    Aggregates the failure analysis result with current UI element
    information so the candidate generator can produce candidates.
    """

    model_config = {"arbitrary_types_allowed": True}

    failure_analysis: Any = Field(
        ...,
        description="The failure analysis from the Failure Analyzer Agent",
    )
    current_elements: list[ElementRecord] = Field(
        default_factory=list,
        description=(
            "Current UI elements that may be candidates for healing. "
            "Provided by the execution engine or test context."
        ),
    )
    page_url: Optional[str] = Field(
        default=None,
        description="Current page URL at time of failure",
    )
    page_title: Optional[str] = Field(
        default=None,
        description="Current page title at time of failure",
    )

    @field_validator("failure_analysis")
    @classmethod
    def _validate_failure_analysis(cls, v: Any) -> Any:
        """Validate that failure_analysis is a FailureAnalysis instance."""
        from agents.analyzer.schemas import FailureAnalysis

        if not isinstance(v, FailureAnalysis):
            raise TypeError(
                f"failure_analysis must be a FailureAnalysis instance, "
                f"got {type(v).__name__}"
            )
        return v
