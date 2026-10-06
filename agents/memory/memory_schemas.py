"""
TestSphere-AI — Historical Memory Schemas

Data models for the Historical Memory and Context Management Layer.
These schemas define how test execution history, element history,
and healing history are stored and retrieved.

Day 8: Foundation for historical context tracking.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

from agents.schemas.enums import ChangeType, ExecutionStatus, FailureType


# ── Failure Info (embedded in execution records) ──────────────


class FailureInfo(BaseModel):
    """Details about a test execution failure.

    Embedded within a ``TestExecutionRecord`` when the execution
    status is ``FAILED`` or ``ERROR``.
    """

    error_message: str = Field(
        ..., min_length=1, description="Error message from the execution engine"
    )
    failure_type: Optional[FailureType] = Field(
        default=None, description="Classified failure type"
    )
    failed_step: Optional[int] = Field(
        default=None, description="1-based step number that failed", ge=1
    )
    selector: Optional[str] = Field(
        default=None, description="Selector that was being used when failure occurred"
    )
    page_url: Optional[str] = Field(
        default=None, description="Page URL at time of failure"
    )
    stack_trace: Optional[str] = Field(
        default=None, description="Stack trace if available"
    )


# ── Test Execution Record ─────────────────────────────────────


class TestExecutionRecord(BaseModel):
    """A single test execution record.

    Captures the outcome of running a test case, including timing,
    status, and optional failure details.  Stored by the memory
    layer for historical analysis.
    """

    execution_id: str = Field(
        ..., min_length=1, description="Unique execution identifier"
    )
    test_id: str = Field(
        ..., min_length=1, description="ID of the test case that was executed"
    )
    test_name: str = Field(
        ..., min_length=1, description="Human-readable test name"
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO 8601 execution timestamp",
    )
    status: ExecutionStatus = Field(
        ..., description="Execution outcome"
    )
    duration_ms: Optional[float] = Field(
        default=None, description="Execution duration in milliseconds", ge=0
    )
    failure_info: Optional[FailureInfo] = Field(
        default=None,
        description="Failure details (present when status is FAILED or ERROR)",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional execution metadata",
    )

    @field_validator("timestamp")
    @classmethod
    def _validate_timestamp(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("timestamp must not be empty")
        return v


# ── Element Record ────────────────────────────────────────────


class ElementRecord(BaseModel):
    """Historical record of a DOM element's state.

    Tracks how an element appeared at a given point in time.
    Used for UI change detection and context comparison.
    """

    element_id: str = Field(
        ..., min_length=1, description="Unique element identifier"
    )
    selector: str = Field(
        ..., min_length=1, description="CSS/XPath selector for the element"
    )
    text: Optional[str] = Field(
        default=None, description="Visible text content"
    )
    role: Optional[str] = Field(
        default=None, description="ARIA role or semantic role"
    )
    page_url: Optional[str] = Field(
        default=None, description="Page URL where the element was found"
    )
    page_name: Optional[str] = Field(
        default=None, description="Human-readable page name"
    )
    attributes: dict[str, str] = Field(
        default_factory=dict,
        description="Relevant HTML attributes (data-testid, aria-label, etc.)",
    )
    last_seen_timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO 8601 timestamp when this element state was recorded",
    )
    last_successful_execution_id: Optional[str] = Field(
        default=None,
        description="Execution ID of the last successful test involving this element",
    )


# ── Healing Record ────────────────────────────────────────────


class HealingRecord(BaseModel):
    """Record of a healing attempt.

    Prepared for future use by the Self-Healing Agent.
    Tracks what selector was replaced, why, and whether
    the replacement was validated successfully.
    """

    healing_id: str = Field(
        ..., min_length=1, description="Unique healing attempt identifier"
    )
    test_id: str = Field(
        ..., min_length=1, description="ID of the test case being healed"
    )
    old_selector: str = Field(
        ..., min_length=1, description="Original selector that failed"
    )
    new_selector: str = Field(
        ..., min_length=1, description="Proposed replacement selector"
    )
    healing_reason: str = Field(
        default="", description="Explanation of why healing was applied"
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score for the healing (0.0 to 1.0)",
    )
    validation_result: Optional[bool] = Field(
        default=None,
        description="Whether the healing was validated successfully (None if pending)",
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO 8601 timestamp of the healing attempt",
    )


# ── Context Comparison Schemas ────────────────────────────────


class FieldChange(BaseModel):
    """Describes a single field-level change between two element snapshots.

    Produced by the ``ContextComparator`` when comparing previous
    and current element states.
    """

    field_name: str = Field(
        ..., description="Name of the field that changed"
    )
    old_value: Optional[Any] = Field(
        default=None, description="Previous value"
    )
    new_value: Optional[Any] = Field(
        default=None, description="Current value"
    )
    change_type: ChangeType = Field(
        ..., description="Type of change detected"
    )


class ContextComparisonResult(BaseModel):
    """Result of comparing two element snapshots.

    Provides structured information about what changed between
    a previous and current element state.  Designed to be consumed
    by the future Self-Healing Agent and Failure Analyzer.
    """

    element_id: str = Field(
        ..., description="Element identifier being compared"
    )
    previous_selector: str = Field(
        ..., description="Selector from the previous snapshot"
    )
    current_selector: str = Field(
        ..., description="Selector from the current snapshot"
    )
    changes: list[FieldChange] = Field(
        default_factory=list,
        description="List of field-level changes detected",
    )
    is_identical: bool = Field(
        default=True,
        description="True if no changes were detected between snapshots",
    )
    comparison_timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO 8601 timestamp of when comparison was performed",
    )
