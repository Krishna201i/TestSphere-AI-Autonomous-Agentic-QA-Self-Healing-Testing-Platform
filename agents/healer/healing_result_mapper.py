"""
TestSphere-AI — Healing Result Mapper

Maps between the intelligence layer's internal schemas and
Member 2's inter-member contracts.

This module provides the clean interface between:

    MEMBER 1 (Intelligence Layer):
        HealingRecommendation → recommendation_to_healing_candidate()

    MEMBER 2 (Execution Engine):
        HealingCandidate → browser validation → HealingResult

    MEMBER 1 (Memory Update):
        healing_result_to_memory_update() → MemoryStore

Day 10: Foundation implementation.
Day 11: Added prepare_healing_result() and contract documentation.

Member 1 ↔ Member 2 Contract
=============================

INPUT (from Member 2 to Member 1):
    FailureAnalysis + Current UI Context (HealingContext)
    - FailureAnalysis contains: test_id, execution_id, failure_type,
      failed_target, evidence, historical_context
    - HealingContext adds: current_elements, page_url

OUTPUT (from Member 1 to Member 2):
    HealingRecommendation (mapped to HealingCandidate)
    - test_id, failed_step, old_selector, new_selector
    - confidence, requires_validation (always True)
    - decision: RECOMMEND_HEALING / REQUIRE_VALIDATION /
                REQUIRE_FURTHER_ANALYSIS / DO_NOT_HEAL
    - alternative_selectors: other ranked candidates

FEEDBACK (from Member 2 back to Member 1):
    HealingResult
    - test_id, old_selector, new_selector
    - status: VALIDATED_SUCCESS / VALIDATED_FAILURE
    - confidence, validated_by: "execution_engine"

Member 1 NEVER:
    - Executes browser actions
    - Modifies selectors in actual tests
    - Declares healing successful (that's Member 2's job)
"""

from __future__ import annotations

from typing import Any, Optional

from agents.healer.healing_schemas import HealingRecommendation
from agents.healer.schemas import HealingCandidate, HealingResult
from agents.schemas.enums import HealingAction, HealingStatus


def recommendation_to_healing_candidate(
    recommendation: HealingRecommendation,
) -> HealingCandidate:
    """Convert a HealingRecommendation to the Member 2 HealingCandidate.

    Maps the intelligence layer's internal recommendation format
    to the existing inter-member ``HealingCandidate`` contract
    that Member 2's execution engine consumes.

    Parameters
    ----------
    recommendation:
        The healing recommendation from the Healing Decision Engine.

    Returns
    -------
    HealingCandidate
        A ``HealingCandidate`` ready for Member 2 consumption.
    """
    selected = recommendation.selected_candidate
    healing_attempted = (
        recommendation.recommended_action == HealingAction.TRY_REPLACEMENT_SELECTOR
        and selected is not None
    )

    new_selector = selected.selector if selected else ""
    confidence = selected.confidence if selected else 0.0

    # Build reason string from evidence
    reason_parts: list[str] = []
    if selected and selected.evidence:
        reason_parts.extend(selected.evidence[:5])  # Limit to 5
    if not reason_parts:
        reason_parts.append(
            f"Action: {recommendation.recommended_action.value}"
        )
    reason = "; ".join(reason_parts)

    # Collect alternative selectors (excluding the selected one)
    alternative_selectors: list[str] = []
    for candidate in recommendation.candidates:
        if selected and candidate.selector == selected.selector:
            continue
        alternative_selectors.append(candidate.selector)

    return HealingCandidate(
        test_id=recommendation.test_id,
        failed_step=recommendation.failed_step,
        healing_attempted=healing_attempted,
        old_selector=recommendation.original_selector,
        new_selector=new_selector,
        confidence=confidence,
        reason=reason,
        requires_validation=True,
        status=HealingStatus.PROPOSED,
        alternative_selectors=alternative_selectors,
    )


def healing_result_to_memory_update(
    result: HealingResult,
) -> dict[str, Any]:
    """Prepare a healing result for memory storage.

    Converts a validated ``HealingResult`` (from Member 2) into
    the data structure needed to update the Historical Memory
    layer, so future healing decisions can benefit from past
    outcomes.

    Parameters
    ----------
    result:
        The validated healing result from Member 2.

    Returns
    -------
    dict[str, Any]
        A dictionary with keys needed to create a ``HealingRecord``
        and optionally update element records.

    Example
    -------
    >>> update = healing_result_to_memory_update(result)
    >>> memory_store.store_healing_record(
    ...     HealingRecord(**update["healing_record"])
    ... )
    """
    import uuid

    is_success = result.status == HealingStatus.VALIDATED_SUCCESS

    healing_record_data = {
        "healing_id": f"heal_{uuid.uuid4().hex[:12]}",
        "test_id": result.test_id,
        "old_selector": result.old_selector,
        "new_selector": result.new_selector,
        "healing_reason": f"Healing {'succeeded' if is_success else 'failed'}",
        "confidence": result.confidence,
        "validation_result": is_success,
    }

    return {
        "healing_record": healing_record_data,
        "is_success": is_success,
        "old_selector": result.old_selector,
        "new_selector": result.new_selector,
    }


def prepare_healing_result(
    test_id: str,
    old_selector: str,
    new_selector: str,
    validation_success: bool,
    confidence: float = 0.0,
    failed_step: int = 1,
    validation_error: Optional[str] = None,
) -> HealingResult:
    """Prepare a HealingResult from Member 2's validation feedback.

    This is a convenience function for creating ``HealingResult``
    instances from Member 2's browser validation feedback.  The
    result can then be passed to ``healing_result_to_memory_update()``
    for storage in Historical Memory.

    Parameters
    ----------
    test_id:
        ID of the test case that was healed.
    old_selector:
        Original selector that failed.
    new_selector:
        Replacement selector that was attempted.
    validation_success:
        Whether the replacement selector worked (True) or not (False).
    confidence:
        Confidence score of the original healing recommendation.
    failed_step:
        Step number that was healed.
    validation_error:
        Optional error message if validation failed.

    Returns
    -------
    HealingResult
        A validated ``HealingResult`` ready for memory storage.

    Example
    -------
    >>> result = prepare_healing_result(
    ...     test_id="TC_LOGIN_001",
    ...     old_selector="#login-btn",
    ...     new_selector="#sign-in-btn",
    ...     validation_success=True,
    ...     confidence=0.94,
    ... )
    >>> update = healing_result_to_memory_update(result)
    """
    status = (
        HealingStatus.VALIDATED_SUCCESS
        if validation_success
        else HealingStatus.VALIDATED_FAILURE
    )

    return HealingResult(
        test_id=test_id,
        failed_step=failed_step,
        old_selector=old_selector,
        new_selector=new_selector,
        status=status,
        confidence=confidence,
        validated_by="execution_engine",
        validation_error=validation_error,
    )
