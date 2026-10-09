"""
TestSphere-AI — Self-Healing Foundation Contracts

Defines the structured data contracts for the Self-Healing Agent's
candidate generation and ranking pipeline.

These contracts define:
  - ``HealingCandidateDetail`` — A structured healing candidate
    with selector, locator strategy, element info, attributes,
    text/accessible name, DOM context, similarity/confidence scores,
    explanation, and supporting evidence.
  - ``HealingInput`` — Input contract for the healing pipeline.
  - ``HealingOutput`` — Output contract with ranked candidates.
  - ``NO_SAFE_HEALING_FOUND`` sentinel result.

IMPORTANT:
  - Candidate generation MUST use actual DOM evidence supplied by
    Member 2. No selectors are invented.
  - If no suitable evidence exists, return NO_SAFE_HEALING_FOUND.
  - The intelligence layer NEVER declares healing successful
    without browser validation by Member 2.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

from agents.schemas.enums import (
    CandidateSource,
    ConfidenceLevel,
    FailureType,
    HealingDecision,
    HealingStatus,
)


# ── Locator Strategy ─────────────────────────────────────────


class LocatorStrategy:
    """Constants for locator strategy types."""

    CSS = "css"
    XPATH = "xpath"
    ID = "id"
    NAME = "name"
    DATA_TESTID = "data-testid"
    ARIA_LABEL = "aria-label"
    TEXT = "text"
    ROLE = "role"


# ── Healing Candidate Detail ─────────────────────────────────


class HealingCandidateDetail(BaseModel):
    """Detailed healing candidate with full context.

    This is the primary data contract for a single healing candidate
    in the candidate generation and ranking pipeline.

    All fields derive from actual DOM evidence provided by Member 2.
    No selectors or DOM elements are invented by the intelligence layer.
    """

    # ── Core identification ──────────────────────────────────

    candidate_selector: str = Field(
        ..., min_length=1,
        description="The proposed replacement selector string",
    )
    locator_strategy: str = Field(
        default=LocatorStrategy.CSS,
        description=(
            "Type of locator strategy: 'css', 'xpath', 'id', 'name', "
            "'data-testid', 'aria-label', 'text', 'role'"
        ),
    )
    source: CandidateSource = Field(
        ...,
        description="Where this candidate originated (DOM, memory, LLM)",
    )

    # ── Element information ──────────────────────────────────

    tag_name: str = Field(
        default="",
        description="HTML tag name of the candidate element (e.g. 'button')",
    )
    element_type: Optional[str] = Field(
        default=None,
        description="Element type attribute (e.g. 'submit', 'text')",
    )
    element_role: Optional[str] = Field(
        default=None,
        description="ARIA role of the element",
    )

    # ── Attributes ───────────────────────────────────────────

    element_id: Optional[str] = Field(
        default=None,
        description="Element 'id' attribute",
    )
    element_name: Optional[str] = Field(
        default=None,
        description="Element 'name' attribute",
    )
    element_classes: list[str] = Field(
        default_factory=list,
        description="CSS class names on the element",
    )
    relevant_attributes: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Key attributes: data-testid, aria-label, aria-describedby, "
            "placeholder, title, etc."
        ),
    )

    # ── Text / Accessible Name ───────────────────────────────

    text_content: Optional[str] = Field(
        default=None,
        description="Visible text content of the element",
    )
    accessible_name: Optional[str] = Field(
        default=None,
        description=(
            "Computed accessible name (from aria-label, "
            "aria-labelledby, or text content)"
        ),
    )

    # ── DOM Context ──────────────────────────────────────────

    parent_selector: Optional[str] = Field(
        default=None,
        description="Selector of the parent element (for context)",
    )
    siblings_count: Optional[int] = Field(
        default=None, ge=0,
        description="Number of sibling elements in the same parent",
    )
    dom_depth: Optional[int] = Field(
        default=None, ge=0,
        description="Depth of the element in the DOM tree",
    )
    page_url: Optional[str] = Field(
        default=None,
        description="Page URL where this candidate was found",
    )

    # ── Scoring ──────────────────────────────────────────────

    similarity_score: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description=(
            "Overall similarity to the original element (0.0 to 1.0). "
            "Computed from weighted individual similarity components."
        ),
    )
    confidence_score: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description=(
            "Confidence that this candidate is the correct replacement "
            "(0.0 to 1.0). Factors in similarity, historical success, "
            "and evidence quality."
        ),
    )

    # ── Explanation & Evidence ───────────────────────────────

    explanation: str = Field(
        default="",
        description="Human-readable explanation of why this candidate was selected",
    )
    supporting_evidence: list[str] = Field(
        default_factory=list,
        description=(
            "Concise, observable evidence strings supporting this candidate. "
            "Example: 'Text content matches: Submit → Submit Form'"
        ),
    )

    @field_validator("confidence_score")
    @classmethod
    def _validate_confidence(cls, v: float) -> float:
        """Ensure confidence is within bounds."""
        if not 0.0 <= v <= 1.0:
            raise ValueError(
                f"confidence_score must be between 0.0 and 1.0, got {v}"
            )
        return v

    @field_validator("similarity_score")
    @classmethod
    def _validate_similarity(cls, v: float) -> float:
        """Ensure similarity is within bounds."""
        if not 0.0 <= v <= 1.0:
            raise ValueError(
                f"similarity_score must be between 0.0 and 1.0, got {v}"
            )
        return v


# ── Healing Input ────────────────────────────────────────────


class HealingInput(BaseModel):
    """Input contract for the healing candidate pipeline.

    Contains all information needed to generate and rank healing
    candidates. All DOM evidence must come from Member 2's execution
    engine — the intelligence layer does NOT invent selectors.
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
        ..., min_length=1,
        description="The original selector that failed",
    )
    failure_type: FailureType = Field(
        ...,
        description="Classified failure type from the analysis",
    )
    action: str = Field(
        default="",
        description="Action that was being performed",
    )

    # ── DOM Evidence (from Member 2) ─────────────────────────

    current_page_url: Optional[str] = Field(
        default=None,
        description="Current page URL at time of failure",
    )
    current_page_title: Optional[str] = Field(
        default=None,
        description="Current page title at time of failure",
    )
    current_dom_elements: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Current DOM elements from Member 2 that may be healing "
            "candidates. Each dict should have: tag, id, name, type, "
            "role, text, selector, classes, attributes"
        ),
    )

    # ── Historical Context ───────────────────────────────────

    previous_element: Optional[dict[str, Any]] = Field(
        default=None,
        description=(
            "Historical element record from memory. Contains the "
            "previous state of the target element."
        ),
    )
    healing_history: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Previous healing attempts for this selector",
    )

    # ── Screenshot / Trace References ────────────────────────

    screenshot_path: Optional[str] = Field(
        default=None,
        description="Path to a screenshot at time of failure (if available)",
    )
    trace_path: Optional[str] = Field(
        default=None,
        description="Path to a trace file (if available)",
    )


# ── Healing Output ───────────────────────────────────────────


class HealingOutput(BaseModel):
    """Output contract from the healing candidate pipeline.

    Contains ranked healing candidates and the overall healing
    decision. If no suitable candidates are found, the status
    is set to NO_SAFE_HEALING_FOUND.
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

    # ── Candidates ───────────────────────────────────────────

    candidates: list[HealingCandidateDetail] = Field(
        default_factory=list,
        description=(
            "Healing candidates ranked by confidence "
            "(highest first)"
        ),
    )
    selected_candidate: Optional[HealingCandidateDetail] = Field(
        default=None,
        description=(
            "Top candidate if it meets the confidence threshold. "
            "None if no safe healing is found."
        ),
    )

    # ── Decision ─────────────────────────────────────────────

    healing_decision: HealingDecision = Field(
        default=HealingDecision.DO_NOT_HEAL,
        description="Final healing decision",
    )
    healing_status: HealingStatus = Field(
        default=HealingStatus.NO_SAFE_HEALING_FOUND,
        description="Status of the healing attempt",
    )
    confidence_level: ConfidenceLevel = Field(
        default=ConfidenceLevel.LOW,
        description="Overall confidence in the healing recommendation",
    )

    # ── Evidence & Metadata ──────────────────────────────────

    evidence_summary: list[str] = Field(
        default_factory=list,
        description="Summary of evidence supporting the decision",
    )
    requires_validation: bool = Field(
        default=True,
        description=(
            "Whether Member 2 must validate the healing "
            "(always True — intelligence layer never self-validates)"
        ),
    )
    generated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO 8601 timestamp of generation",
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


# ── Sentinel: No Safe Healing Found ──────────────────────────


def create_no_safe_healing(
    test_id: str,
    execution_id: str,
    failed_step: int,
    original_selector: str = "",
    reason: str = "No safe healing candidates found from available evidence",
) -> HealingOutput:
    """Create a NO_SAFE_HEALING_FOUND result.

    Used when no suitable DOM evidence exists to generate candidates,
    or when all candidates fall below the minimum confidence threshold.

    Parameters
    ----------
    test_id:
        ID of the failed test case.
    execution_id:
        Unique execution identifier.
    failed_step:
        1-based step number that failed.
    original_selector:
        The original selector that failed.
    reason:
        Explanation of why no healing was found.

    Returns
    -------
    HealingOutput
        A result with NO_SAFE_HEALING_FOUND status and no candidates.
    """
    return HealingOutput(
        test_id=test_id,
        execution_id=execution_id,
        failed_step=failed_step,
        original_selector=original_selector,
        candidates=[],
        selected_candidate=None,
        healing_decision=HealingDecision.DO_NOT_HEAL,
        healing_status=HealingStatus.NO_SAFE_HEALING_FOUND,
        confidence_level=ConfidenceLevel.LOW,
        evidence_summary=[reason],
        requires_validation=True,
    )
