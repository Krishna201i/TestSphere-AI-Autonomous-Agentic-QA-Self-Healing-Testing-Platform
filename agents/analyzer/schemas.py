"""
TestSphere-AI — Failure Analyzer Schemas

Data contracts for the Failure Analysis Agent.
These schemas define how test failures arrive from Member 2
and how the analysis result flows to the Self-Healing Agent.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from agents.schemas.enums import FailureType


class TestFailure(BaseModel):
    """A test failure reported by Member 2's execution engine.

    This is the primary input to the Failure Analysis Agent.
    Member 2 populates this after a test step fails.

    This is a core inter-member contract.
    """

    test_id: str = Field(..., description="ID of the failed test case")
    failed_step: int = Field(..., description="1-based step number that failed")
    action: str = Field(
        ..., description="Action that was being performed when failure occurred"
    )
    selector: str = Field(
        ..., description="Selector that was being used when failure occurred"
    )
    error: str = Field(..., description="Error message from the execution engine")
    url: str = Field(default="", description="Page URL at time of failure")
    dom_snapshot: Optional[str] = Field(
        default=None,
        description="DOM snapshot at time of failure (provided by Member 2)",
    )
    screenshot_path: Optional[str] = Field(
        default=None,
        description="Path to screenshot at time of failure (provided by Member 2)",
    )
    expected: Optional[str] = Field(
        default=None, description="Expected outcome"
    )
    actual: Optional[str] = Field(
        default=None, description="Actual outcome observed"
    )


class FailureAnalysis(BaseModel):
    """Result of the Failure Analysis Agent's investigation.

    Classifies the failure, identifies root cause, and determines
    whether self-healing should be attempted.

    This is a core inter-member contract.
    """

    failure_type: FailureType = Field(
        ..., description="Classified failure category"
    )
    root_cause: str = Field(
        ..., description="Explanation of why the failure occurred"
    )
    healable: bool = Field(
        ...,
        description="Whether the AI believes this failure can be healed",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score for the analysis (0.0 to 1.0)",
    )
    reasoning: str = Field(
        default="",
        description="Step-by-step reasoning behind the analysis",
    )
