"""
TestSphere-AI — Healing Result Feedback Schema & Processor

Defines the enriched inter-member contract for healing feedback
from Member 2 (Browser Validation) to Member 1 (Intelligence Layer).

Day 12: Healing Result Feedback & Memory Learning.

Member 2 → Member 1 Contract
==============================

After Member 2 validates a healing recommendation in the browser,
it sends back a ``HealingResultFeedback`` to Member 1.  This is
richer than the existing ``HealingResult`` in ``healer/schemas.py``
and supports the feedback loop for learning.

The ``HealingResultFeedbackProcessor`` validates the feedback,
enforces safety rules, and stores it in the memory layer.

SAFETY RULES
------------
- Healing is NEVER marked as successful without
  ``validation_status == ValidationStatus.SUCCESS``.
- Member 1 never claims healing succeeded merely because
  the AI recommended a selector.
- Only Member 2's validation result establishes success.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

from agents.memory.memory_interface import MemoryStore
from agents.memory.memory_schemas import HealingRecord
from agents.schemas.enums import (
    FailureType,
    HealingStatus,
    ValidationStatus,
)

logger = logging.getLogger(__name__)


# ── Healing Result Feedback (Member 2 → Member 1) ────────────


class HealingResultFeedback(BaseModel):
    """Structured feedback from Member 2 after browser validation.

    This is the primary input that Member 2's execution engine
    sends back after attempting a healing recommendation.

    It extends the simpler ``HealingResult`` with richer metadata
    for the feedback loop.
    """

    healing_id: str = Field(
        default_factory=lambda: f"heal_{uuid.uuid4().hex[:12]}",
        min_length=1,
        description="Unique identifier for this healing attempt",
    )
    test_case_id: str = Field(
        ..., min_length=1,
        description="ID of the test case being healed",
    )
    failure_id: Optional[str] = Field(
        default=None,
        description="ID of the specific failure being addressed",
    )
    execution_id: Optional[str] = Field(
        default=None,
        description="Execution ID of the test run",
    )
    original_selector: str = Field(
        ..., min_length=1,
        description="The original selector that failed",
    )
    attempted_selector: str = Field(
        ..., min_length=1,
        description="The replacement selector that was attempted",
    )
    candidate_id: Optional[str] = Field(
        default=None,
        description="ID of the healing candidate, if tracked",
    )
    healing_status: HealingStatus = Field(
        ...,
        description="Final healing lifecycle status",
    )
    validation_status: ValidationStatus = Field(
        ...,
        description="Browser validation outcome from Member 2",
    )
    failure_category: Optional[FailureType] = Field(
        default=None,
        description="Type of failure that triggered healing",
    )
    confidence: float = Field(
        ..., ge=0.0, le=1.0,
        description="Confidence score of the original recommendation",
    )
    execution_attempt: int = Field(
        default=1, ge=1,
        description="Which attempt number this represents",
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO 8601 timestamp of when validation was performed",
    )
    error_reason: Optional[str] = Field(
        default=None,
        description="Error message if healing/validation failed",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata from the execution engine",
    )

    @field_validator("healing_status")
    @classmethod
    def _validate_healing_status_consistency(
        cls, v: HealingStatus,
    ) -> HealingStatus:
        """Ensure healing_status is a valid post-validation status."""
        valid_post_validation = {
            HealingStatus.VALIDATED_SUCCESS,
            HealingStatus.VALIDATED_FAILURE,
            HealingStatus.NO_SAFE_HEALING_FOUND,
        }
        if v not in valid_post_validation:
            raise ValueError(
                f"healing_status must be a post-validation status "
                f"({', '.join(s.value for s in valid_post_validation)}), "
                f"got '{v.value}'"
            )
        return v


# ── Feedback Processor ────────────────────────────────────────


class HealingResultFeedbackProcessor:
    """Processes healing feedback from Member 2 and stores it in memory.

    Responsibilities:
    - Validate feedback safety rules
    - Convert feedback to a ``HealingRecord`` for memory storage
    - Store the record in the ``MemoryStore``

    Parameters
    ----------
    memory_store:
        The memory store for persisting healing records.
    """

    def __init__(self, memory_store: MemoryStore) -> None:
        self._memory = memory_store

    def process_feedback(
        self, feedback: HealingResultFeedback,
    ) -> HealingRecord:
        """Process and store healing feedback from Member 2.

        Safety rules enforced:
        - Healing is ONLY marked as successful when
          ``validation_status == ValidationStatus.SUCCESS``
        - The ``HealingRecord.validation_result`` is derived
          solely from Member 2's validation_status

        Parameters
        ----------
        feedback:
            Validated ``HealingResultFeedback`` from Member 2.

        Returns
        -------
        HealingRecord
            The stored healing record.
        """
        # Derive validation_result strictly from Member 2's status
        validation_result = self._derive_validation_result(feedback)

        # Build the healing record
        record = HealingRecord(
            healing_id=feedback.healing_id,
            test_id=feedback.test_case_id,
            old_selector=feedback.original_selector,
            new_selector=feedback.attempted_selector,
            healing_reason=self._build_healing_reason(feedback),
            confidence=feedback.confidence,
            validation_result=validation_result,
            timestamp=feedback.timestamp,
        )

        # Store in memory
        self._memory.store_healing_record(record)

        logger.info(
            "Stored healing feedback — healing_id=%s, "
            "test_id=%s, selector='%s' → '%s', "
            "validation=%s, confidence=%.4f",
            feedback.healing_id,
            feedback.test_case_id,
            feedback.original_selector,
            feedback.attempted_selector,
            validation_result,
            feedback.confidence,
        )

        return record

    @staticmethod
    def _derive_validation_result(
        feedback: HealingResultFeedback,
    ) -> bool | None:
        """Derive the validation_result from Member 2's validation.

        Only ``ValidationStatus.SUCCESS`` maps to ``True``.
        ``FAILURE`` maps to ``False``.
        ``ERROR`` and ``SKIPPED`` map to ``None`` (inconclusive).
        """
        if feedback.validation_status == ValidationStatus.SUCCESS:
            return True
        if feedback.validation_status == ValidationStatus.FAILURE:
            return False
        # ERROR / SKIPPED — inconclusive
        return None

    @staticmethod
    def _build_healing_reason(
        feedback: HealingResultFeedback,
    ) -> str:
        """Build a descriptive healing reason from the feedback."""
        parts: list[str] = []

        if feedback.validation_status == ValidationStatus.SUCCESS:
            parts.append("Healing validated successfully by execution engine")
        elif feedback.validation_status == ValidationStatus.FAILURE:
            parts.append("Healing validation failed")
        elif feedback.validation_status == ValidationStatus.ERROR:
            parts.append("Healing validation encountered an error")
        else:
            parts.append("Healing validation was skipped")

        if feedback.failure_category:
            parts.append(
                f"failure_category={feedback.failure_category.value}"
            )

        if feedback.error_reason:
            parts.append(f"error: {feedback.error_reason}")

        if feedback.execution_attempt > 1:
            parts.append(f"attempt #{feedback.execution_attempt}")

        return "; ".join(parts)
