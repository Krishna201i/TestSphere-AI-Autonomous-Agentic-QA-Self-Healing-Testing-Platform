"""
TestSphere-AI — Failure Analyzer Schemas

Data contracts for the Failure Analysis Agent.

Day 1: Initial placeholders (TestFailure, FailureAnalysis).
Day 9: Full structured schemas for failure context, evidence,
       historical context, and analysis result.

These schemas define:
- How test failures arrive from Member 2 (FailureContext)
- How evidence is represented (FailureEvidence)
- How historical information is structured (HistoricalContext)
- How the analysis result flows to the Self-Healing Agent (FailureAnalysis)
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

from agents.memory.memory_schemas import (
    ContextComparisonResult,
    ElementRecord,
    TestExecutionRecord,
)
from agents.schemas.enums import (
    ConfidenceLevel,
    FailureType,
    RecommendedAction,
)


# ── Failure Context (input) ──────────────────────────────────


class FailureContext(BaseModel):
    """Structured failure input for the Failure Analysis Agent.

    This is the primary input that Member 2's execution engine
    provides when a test step fails.  It contains all observable
    information about the failure.

    Design: structured fields, not raw log strings.
    """

    test_id: str = Field(
        ..., min_length=1, description="ID of the failed test case"
    )
    execution_id: str = Field(
        ..., min_length=1, description="Unique execution identifier"
    )
    failed_step: int = Field(
        ..., ge=1, description="1-based step number that failed"
    )
    action: str = Field(
        ..., min_length=1,
        description="Action that was being performed when failure occurred",
    )
    target_selector: str = Field(
        default="",
        description="Selector that was being used when failure occurred",
    )
    expected_result: Optional[str] = Field(
        default=None, description="Expected outcome of the step"
    )
    actual_result: Optional[str] = Field(
        default=None, description="Actual observed outcome"
    )
    error_message: str = Field(
        default="", description="Error message from the execution engine"
    )
    current_page_url: Optional[str] = Field(
        default=None, description="Page URL at time of failure"
    )
    current_page_title: Optional[str] = Field(
        default=None, description="Page title at time of failure"
    )
    current_element: Optional[ElementRecord] = Field(
        default=None,
        description=(
            "Current element information if an alternative element "
            "was found in the UI"
        ),
    )


# Backward-compatible alias for the Day 1 inter-member contract
TestFailure = FailureContext


# ── Evidence ─────────────────────────────────────────────────


class FailureEvidence(BaseModel):
    """A single piece of observable evidence supporting the analysis.

    Evidence items are concise, factual observations — not
    chain-of-thought or private model reasoning.
    """

    evidence_type: str = Field(
        ..., min_length=1,
        description="Category of evidence (e.g. 'selector_missing', 'text_match')",
    )
    description: str = Field(
        ..., min_length=1, description="Human-readable description of the evidence"
    )
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured details for programmatic consumption",
    )


# ── Historical Context ───────────────────────────────────────


class HistoricalContext(BaseModel):
    """Historical information retrieved from the memory store.

    Aggregated context about previous executions and element
    history, structured for consumption by the analysis logic.
    """

    previous_executions_count: int = Field(
        default=0, ge=0,
        description="Total number of previous executions for this test",
    )
    previous_successes_count: int = Field(
        default=0, ge=0,
        description="Number of previous successful executions",
    )
    previous_failures_count: int = Field(
        default=0, ge=0,
        description="Number of previous failed executions",
    )
    latest_successful_execution: Optional[TestExecutionRecord] = Field(
        default=None,
        description="Most recent successful execution record, if any",
    )
    previous_element: Optional[ElementRecord] = Field(
        default=None,
        description="Historical element record for the failed target, if any",
    )
    context_comparison: Optional[ContextComparisonResult] = Field(
        default=None,
        description="Comparison between previous and current element, if both exist",
    )


# ── Failure Analysis (output) ────────────────────────────────


class FailureAnalysis(BaseModel):
    """Result of the Failure Analysis Agent's investigation.

    Structured output designed for consumption by:
    - The future Self-Healing Agent (Member 2)
    - Human operators reviewing test failures
    - Historical memory for future reference

    The analysis contains only concise, observable evidence.
    No chain-of-thought or private model reasoning is stored.

    This is a core inter-member contract.
    """

    test_id: str = Field(
        ..., min_length=1, description="ID of the failed test case"
    )
    execution_id: str = Field(
        ..., min_length=1, description="Unique execution identifier"
    )
    failure_type: FailureType = Field(
        ..., description="Classified failure category"
    )
    root_cause: str = Field(
        ..., min_length=1,
        description="Concise explanation of why the failure occurred",
    )
    confidence: ConfidenceLevel = Field(
        ..., description="Confidence level for the analysis"
    )
    failed_step: int = Field(
        ..., ge=1, description="1-based step number that failed"
    )
    failed_target: str = Field(
        default="",
        description="Selector or target that failed",
    )
    expected_state: Optional[str] = Field(
        default=None, description="Expected application/element state"
    )
    actual_state: Optional[str] = Field(
        default=None, description="Actual observed application/element state"
    )
    evidence: list[FailureEvidence] = Field(
        default_factory=list,
        description="Observable evidence supporting the analysis",
    )
    historical_context: Optional[HistoricalContext] = Field(
        default=None,
        description="Historical context used during analysis",
    )
    recommended_action: RecommendedAction = Field(
        ...,
        description="Recommended next action for the Self-Healing Agent",
    )

    @field_validator("evidence")
    @classmethod
    def _evidence_must_not_be_empty_strings(
        cls, v: list[FailureEvidence],
    ) -> list[FailureEvidence]:
        """Ensure evidence items are well-formed."""
        return v
