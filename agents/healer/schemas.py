"""
TestSphere-AI — Self-Healing Agent Schemas

Data contracts for the Self-Healing Agent.
These schemas define how healing candidates are proposed and
how validation results are recorded.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from agents.schemas.enums import HealingStatus


class HealingCandidate(BaseModel):
    """A proposed healing fix from the Self-Healing Agent.

    Sent to Member 2's execution engine for validation.
    The AI proposes a new selector but NEVER declares it valid
    on its own — Member 2 must verify.

    This is a core inter-member contract.
    """

    test_id: str = Field(
        ..., description="ID of the test case being healed"
    )
    failed_step: int = Field(
        ..., description="Step number that failed"
    )
    healing_attempted: bool = Field(
        ..., description="Whether healing was attempted"
    )
    old_selector: str = Field(
        ..., description="Original selector that failed"
    )
    new_selector: str = Field(
        default="",
        description="Proposed replacement selector (empty if no healing found)",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score for the proposed healing (0.0 to 1.0)",
    )
    reason: str = Field(
        default="",
        description="Explanation of why this candidate was chosen",
    )
    requires_validation: bool = Field(
        default=True,
        description="Whether Member 2 needs to validate this candidate (always True)",
    )
    status: HealingStatus = Field(
        default=HealingStatus.PROPOSED,
        description="Current status of this healing candidate",
    )
    alternative_selectors: list[str] = Field(
        default_factory=list,
        description="Other candidate selectors considered, ranked by confidence",
    )


class HealingResult(BaseModel):
    """Final result after Member 2 validates a healing candidate.

    Recorded in healing memory for future reference.

    This is a core inter-member contract.
    """

    test_id: str = Field(
        ..., description="ID of the test case that was healed"
    )
    failed_step: int = Field(
        ..., description="Step number that was healed"
    )
    old_selector: str = Field(
        ..., description="Original selector that failed"
    )
    new_selector: str = Field(
        ..., description="Selector that was attempted"
    )
    status: HealingStatus = Field(
        ..., description="Final healing status after validation"
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score of the healing attempt",
    )
    validated_by: str = Field(
        default="execution_engine",
        description="What validated the result (always 'execution_engine')",
    )
    validation_error: Optional[str] = Field(
        default=None,
        description="Error message if validation failed",
    )
