"""
TestSphere-AI — Autonomous Recovery Policy

Deterministic policy engine that evaluates failure context, candidate
availability, confidence, and historical evidence to produce an
explainable ``RecoveryDecision`` controlling what happens after a
failure.

Day 14: Autonomous Recovery Policy & Explainable Agent Decisions.

Architecture::

    FailureAnalysis
         ↓
    Candidate Ranking
         ↓
    RecoveryPolicy.evaluate()
         ↓
    RecoveryDecision
         ↓
    Next State (RETRY / TRY_HEALING / ABORT / ...)

IMPORTANT:
- The policy is deterministic: same inputs → same output.
- An LLM may assist upstream (candidate generation, disambiguation),
  but the policy itself enforces all rules and limits.
- The LLM CANNOT bypass attempt limits, confidence thresholds,
  or invent candidates.
- No browser actions are executed by this module.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

from agents.analyzer.schemas import FailureAnalysis
from agents.healer.healing_schemas import ScoredCandidate
from agents.memory.healing_evidence import (
    HealingEvidenceRetriever,
    ReplacementStats,
)
from agents.schemas.enums import (
    ConfidenceLevel,
    FailureType,
)

logger = logging.getLogger(__name__)


# ── Recovery Action Enum ─────────────────────────────────────


class RecoveryAction(str, Enum):
    """Possible autonomous recovery decisions.

    Definitions
    -----------
    RETRY:
        Re-execute the same test without changing selectors.
        Appropriate for transient failures (TIMEOUT, NAVIGATION).
    TRY_HEALING:
        Attempt selector replacement using the selected candidate.
        Requires Member 2 browser validation.
    REQUIRE_FURTHER_ANALYSIS:
        Evidence is insufficient or ambiguous.  Do not attempt
        healing automatically — flag for investigation.
    DO_NOT_HEAL:
        Healing is not appropriate for this failure type or
        no candidate meets the minimum confidence threshold.
    ABORT:
        Maximum attempts reached or unrecoverable error.
        Terminate the workflow.
    """

    RETRY = "RETRY"
    TRY_HEALING = "TRY_HEALING"
    REQUIRE_FURTHER_ANALYSIS = "REQUIRE_FURTHER_ANALYSIS"
    DO_NOT_HEAL = "DO_NOT_HEAL"
    ABORT = "ABORT"


# ── Recovery Decision Schema ─────────────────────────────────


class RecoveryDecision(BaseModel):
    """Structured, explainable output of the recovery policy.

    Every decision includes concise observable evidence and a
    human-readable reason.  No chain-of-thought is stored.
    """

    workflow_id: str = Field(
        default="",
        description="Workflow this decision belongs to",
    )
    test_case_id: str = Field(
        default="",
        description="Test case this decision applies to",
    )
    failure_type: Optional[FailureType] = Field(
        default=None,
        description="Classified failure type from the analysis",
    )
    decision: RecoveryAction = Field(
        ...,
        description="The autonomous recovery decision",
    )
    confidence: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Confidence in the decision (0.0 to 1.0)",
    )
    selected_candidate: Optional[ScoredCandidate] = Field(
        default=None,
        description=(
            "Selected candidate for TRY_HEALING. "
            "None for all other decisions."
        ),
    )
    reason: str = Field(
        default="",
        description=(
            "Concise human-readable reason for the decision. "
            "No chain-of-thought — only observable evidence."
        ),
    )
    evidence: list[str] = Field(
        default_factory=list,
        description="Concise, observable evidence strings",
    )
    attempt_number: int = Field(
        default=0, ge=0,
        description="Current healing attempt number (0 if no healing)",
    )
    retry_count: int = Field(
        default=0, ge=0,
        description="Current retry count for transient failures",
    )
    requires_validation: bool = Field(
        default=True,
        description=(
            "Whether Member 2 must validate the action. "
            "Always True for TRY_HEALING."
        ),
    )
    next_state: str = Field(
        default="",
        description=(
            "Recommended next WorkflowStep value "
            "(e.g. 'HEALING_PENDING_VALIDATION', 'COMPLETED')"
        ),
    )


# ── Failure-Type Policy ──────────────────────────────────────


class FailureTypePolicy(BaseModel):
    """Per-failure-type recovery rules.

    Configures whether a failure type is healable, retryable,
    and how many retries are allowed before escalation.
    """

    failure_type: FailureType = Field(
        ..., description="The failure type this policy applies to",
    )
    healable: bool = Field(
        default=True,
        description="Whether healing (selector replacement) is appropriate",
    )
    retryable: bool = Field(
        default=False,
        description="Whether simple retry is appropriate",
    )
    max_retries: int = Field(
        default=0, ge=0,
        description="Maximum retries for this failure type (0 = no retry)",
    )


# Default failure-type policies
_DEFAULT_FAILURE_POLICIES: dict[FailureType, FailureTypePolicy] = {
    FailureType.SELECTOR_CHANGED: FailureTypePolicy(
        failure_type=FailureType.SELECTOR_CHANGED,
        healable=True,
        retryable=False,
        max_retries=0,
    ),
    FailureType.ELEMENT_NOT_FOUND: FailureTypePolicy(
        failure_type=FailureType.ELEMENT_NOT_FOUND,
        healable=True,
        retryable=False,
        max_retries=0,
    ),
    FailureType.ELEMENT_NOT_INTERACTABLE: FailureTypePolicy(
        failure_type=FailureType.ELEMENT_NOT_INTERACTABLE,
        healable=False,
        retryable=True,
        max_retries=2,
    ),
    FailureType.ASSERTION_FAILURE: FailureTypePolicy(
        failure_type=FailureType.ASSERTION_FAILURE,
        healable=False,
        retryable=False,
        max_retries=0,
    ),
    FailureType.TIMEOUT: FailureTypePolicy(
        failure_type=FailureType.TIMEOUT,
        healable=False,
        retryable=True,
        max_retries=2,
    ),
    FailureType.NAVIGATION_FAILURE: FailureTypePolicy(
        failure_type=FailureType.NAVIGATION_FAILURE,
        healable=False,
        retryable=True,
        max_retries=2,
    ),
    FailureType.NETWORK_ERROR: FailureTypePolicy(
        failure_type=FailureType.NETWORK_ERROR,
        healable=False,
        retryable=False,
        max_retries=0,
    ),
    FailureType.APPLICATION_ERROR: FailureTypePolicy(
        failure_type=FailureType.APPLICATION_ERROR,
        healable=False,
        retryable=False,
        max_retries=0,
    ),
    FailureType.UNKNOWN: FailureTypePolicy(
        failure_type=FailureType.UNKNOWN,
        healable=False,
        retryable=False,
        max_retries=0,
    ),
}


# ── Recovery Policy Configuration ────────────────────────────


class RecoveryPolicyConfig(BaseModel):
    """Configurable parameters for the RecoveryPolicy.

    All thresholds and limits are configurable — nothing is
    hard-coded throughout the codebase.
    """

    max_healing_attempts: int = Field(
        default=3, ge=1,
        description=(
            "Maximum number of healing attempts per workflow. "
            "After this limit, the workflow is ABORTED."
        ),
    )
    min_healing_confidence: float = Field(
        default=0.80, ge=0.0, le=1.0,
        description=(
            "Minimum confidence score required for automatic "
            "healing.  Below this, DO_NOT_HEAL is returned."
        ),
    )
    min_candidate_score: float = Field(
        default=0.30, ge=0.0, le=1.0,
        description=(
            "Absolute minimum candidate score.  Candidates below "
            "this are never considered for healing."
        ),
    )
    allow_medium_confidence_healing: bool = Field(
        default=False,
        description=(
            "If True, candidates between min_candidate_score and "
            "min_healing_confidence may be sent for healing with "
            "REQUIRE_VALIDATION.  If False, only HIGH confidence "
            "candidates are healed automatically."
        ),
    )
    allow_retry: bool = Field(
        default=True,
        description="Whether RETRY is allowed for transient failures",
    )
    max_retries: int = Field(
        default=2, ge=0,
        description=(
            "Global maximum retry count for transient failures. "
            "Per-failure-type limits may be lower."
        ),
    )
    ambiguity_margin: float = Field(
        default=0.02, ge=0.0, le=1.0,
        description=(
            "Maximum score gap between top two candidates for "
            "them to be considered ambiguous."
        ),
    )
    history_boost_weight: float = Field(
        default=0.15, ge=0.0, le=1.0,
        description=(
            "Weight applied to historical success rate when "
            "adjusting candidate confidence."
        ),
    )
    failure_policies: dict[str, FailureTypePolicy] = Field(
        default_factory=dict,
        description=(
            "Override failure-type policies.  Keys are FailureType "
            "values (e.g. 'TIMEOUT').  Missing types use defaults."
        ),
    )


# ── Recovery Policy ──────────────────────────────────────────


class RecoveryPolicy:
    """Deterministic autonomous recovery policy engine.

    Evaluates failure context, candidate availability, confidence,
    historical evidence, and agent state to produce an explainable
    ``RecoveryDecision``.

    The policy is deterministic: given the same inputs, it always
    produces the same output.

    Parameters
    ----------
    config:
        Recovery policy configuration.  Uses conservative defaults
        if not provided.
    evidence_retriever:
        Optional retriever for historical healing evidence.
    """

    def __init__(
        self,
        config: RecoveryPolicyConfig | None = None,
        evidence_retriever: HealingEvidenceRetriever | None = None,
    ) -> None:
        self._config = config or RecoveryPolicyConfig()
        self._evidence_retriever = evidence_retriever

        # Merge default and custom failure-type policies
        self._failure_policies: dict[FailureType, FailureTypePolicy] = dict(
            _DEFAULT_FAILURE_POLICIES
        )
        for key, policy in self._config.failure_policies.items():
            try:
                ft = FailureType(key)
                self._failure_policies[ft] = policy
            except ValueError:
                logger.warning(
                    "Unknown failure type in policy config: %s", key,
                )

        logger.info(
            "RecoveryPolicy initialized — "
            "max_healing=%d, min_confidence=%.2f, max_retries=%d",
            self._config.max_healing_attempts,
            self._config.min_healing_confidence,
            self._config.max_retries,
        )

    # ── Primary Entry Point ──────────────────────────────────

    def evaluate(
        self,
        failure_analysis: FailureAnalysis,
        ranked_candidates: list[ScoredCandidate],
        healing_attempt_count: int = 0,
        retry_count: int = 0,
        attempted_selectors: set[str] | None = None,
        workflow_id: str = "",
        test_case_id: str = "",
    ) -> RecoveryDecision:
        """Evaluate and produce a recovery decision.

        This is the primary entry point.  It evaluates all rules
        in order and returns the first matching decision.

        Parameters
        ----------
        failure_analysis:
            The failure analysis from the Failure Analyzer.
        ranked_candidates:
            Candidates ranked by confidence (highest first).
        healing_attempt_count:
            Number of healing attempts already made.
        retry_count:
            Number of retries already attempted.
        attempted_selectors:
            Set of selectors already attempted (to prevent repeats).
        workflow_id:
            Workflow ID for the decision record.
        test_case_id:
            Test case ID for the decision record.

        Returns
        -------
        RecoveryDecision
            The autonomous recovery decision with evidence.
        """
        attempted = attempted_selectors or set()
        evidence: list[str] = []
        ft = failure_analysis.failure_type
        ft_policy = self._failure_policies.get(
            ft,
            FailureTypePolicy(failure_type=ft, healable=False),
        )

        evidence.append(f"Failure type: {ft.value}")
        evidence.append(
            f"Analysis confidence: {failure_analysis.confidence.value}"
        )
        evidence.append(
            f"Healing attempts: {healing_attempt_count}/{self._config.max_healing_attempts}"
        )
        evidence.append(f"Retry count: {retry_count}")
        evidence.append(
            f"Candidates available: {len(ranked_candidates)}"
        )

        # ── Rule 1: Max healing attempts → ABORT ─────────────
        if healing_attempt_count >= self._config.max_healing_attempts:
            evidence.append(
                "Maximum healing attempts reached"
            )
            return RecoveryDecision(
                workflow_id=workflow_id,
                test_case_id=test_case_id,
                failure_type=ft,
                decision=RecoveryAction.ABORT,
                confidence=1.0,
                reason=(
                    f"Maximum healing attempts "
                    f"({self._config.max_healing_attempts}) reached. "
                    f"Aborting workflow."
                ),
                evidence=evidence,
                attempt_number=healing_attempt_count,
                retry_count=retry_count,
                requires_validation=False,
                next_state="ABORTED",
            )

        # ── Rule 2: Non-healable, non-retryable → DO_NOT_HEAL ──
        if not ft_policy.healable and not ft_policy.retryable:
            evidence.append(
                f"Failure type {ft.value} is neither healable nor retryable"
            )
            return RecoveryDecision(
                workflow_id=workflow_id,
                test_case_id=test_case_id,
                failure_type=ft,
                decision=RecoveryAction.DO_NOT_HEAL,
                confidence=1.0,
                reason=(
                    f"Failure type {ft.value} does not support "
                    f"automatic healing or retry."
                ),
                evidence=evidence,
                attempt_number=healing_attempt_count,
                retry_count=retry_count,
                requires_validation=False,
                next_state="COMPLETED",
            )

        # ── Rule 3: Retryable + under retry limit → RETRY ────
        if ft_policy.retryable and self._config.allow_retry:
            effective_max = min(
                ft_policy.max_retries,
                self._config.max_retries,
            )
            if retry_count < effective_max:
                evidence.append(
                    f"Failure type {ft.value} is retryable "
                    f"({retry_count}/{effective_max} retries used)"
                )
                return RecoveryDecision(
                    workflow_id=workflow_id,
                    test_case_id=test_case_id,
                    failure_type=ft,
                    decision=RecoveryAction.RETRY,
                    confidence=0.9,
                    reason=(
                        f"Transient failure ({ft.value}). "
                        f"Retrying ({retry_count + 1}/{effective_max})."
                    ),
                    evidence=evidence,
                    attempt_number=healing_attempt_count,
                    retry_count=retry_count,
                    requires_validation=False,
                    next_state="RETRYING",
                )
            else:
                # Retries exhausted
                evidence.append(
                    f"Retry limit reached ({retry_count}/{effective_max})"
                )
                # If also healable, fall through to healing evaluation
                if not ft_policy.healable:
                    evidence.append(
                        f"Failure type {ft.value} is not healable — "
                        f"require further analysis"
                    )
                    return RecoveryDecision(
                        workflow_id=workflow_id,
                        test_case_id=test_case_id,
                        failure_type=ft,
                        decision=RecoveryAction.REQUIRE_FURTHER_ANALYSIS,
                        confidence=0.7,
                        reason=(
                            f"Retries exhausted for {ft.value}. "
                            f"Require further analysis."
                        ),
                        evidence=evidence,
                        attempt_number=healing_attempt_count,
                        retry_count=retry_count,
                        requires_validation=False,
                        next_state="COMPLETED",
                    )

        # ── Rule 4: Not healable → DO_NOT_HEAL ───────────────
        if not ft_policy.healable:
            evidence.append(
                f"Failure type {ft.value} is not healable"
            )
            return RecoveryDecision(
                workflow_id=workflow_id,
                test_case_id=test_case_id,
                failure_type=ft,
                decision=RecoveryAction.DO_NOT_HEAL,
                confidence=1.0,
                reason=(
                    f"Failure type {ft.value} does not support "
                    f"automatic selector healing."
                ),
                evidence=evidence,
                attempt_number=healing_attempt_count,
                retry_count=retry_count,
                requires_validation=False,
                next_state="COMPLETED",
            )

        # ── Rule 5: Healable — filter eligible candidates ─────
        eligible = self._filter_eligible_candidates(
            ranked_candidates, attempted, evidence,
        )

        # ── Rule 6: No eligible candidates → DO_NOT_HEAL ─────
        if not eligible:
            evidence.append("No eligible candidates available")
            return RecoveryDecision(
                workflow_id=workflow_id,
                test_case_id=test_case_id,
                failure_type=ft,
                decision=RecoveryAction.DO_NOT_HEAL,
                confidence=1.0,
                reason="No eligible healing candidates available.",
                evidence=evidence,
                attempt_number=healing_attempt_count,
                retry_count=retry_count,
                requires_validation=False,
                next_state="COMPLETED",
            )

        # ── Rule 7: Evaluate healing with candidates ──────────
        return self._evaluate_healing(
            failure_analysis=failure_analysis,
            eligible_candidates=eligible,
            healing_attempt_count=healing_attempt_count,
            retry_count=retry_count,
            attempted_selectors=attempted,
            workflow_id=workflow_id,
            test_case_id=test_case_id,
            evidence=evidence,
        )

    # ── Continuation After Failed Healing ─────────────────────

    def evaluate_continuation(
        self,
        failure_analysis: FailureAnalysis,
        ranked_candidates: list[ScoredCandidate],
        healing_attempt_count: int,
        attempted_selectors: set[str],
        workflow_id: str = "",
        test_case_id: str = "",
    ) -> RecoveryDecision:
        """Evaluate whether to continue healing after a failed attempt.

        Called when Member 2 reports a healing attempt as FAILED.
        Determines whether to try the next candidate or stop.

        Parameters
        ----------
        failure_analysis:
            The original failure analysis.
        ranked_candidates:
            All ranked candidates (including already-attempted ones).
        healing_attempt_count:
            Number of healing attempts made (including the failed one).
        attempted_selectors:
            Set of selectors already attempted.
        workflow_id:
            Workflow ID for the decision record.
        test_case_id:
            Test case ID for the decision record.

        Returns
        -------
        RecoveryDecision
            Decision on whether to continue or stop.
        """
        evidence: list[str] = []
        ft = (
            failure_analysis.failure_type
            if failure_analysis is not None
            else FailureType.UNKNOWN
        )

        evidence.append(f"Failure type: {ft.value}")
        evidence.append(
            f"Healing attempts: {healing_attempt_count}/{self._config.max_healing_attempts}"
        )
        evidence.append(
            f"Attempted selectors: {len(attempted_selectors)}"
        )

        # ── Check max attempts ────────────────────────────────
        if healing_attempt_count >= self._config.max_healing_attempts:
            evidence.append("Maximum healing attempts reached")
            return RecoveryDecision(
                workflow_id=workflow_id,
                test_case_id=test_case_id,
                failure_type=ft,
                decision=RecoveryAction.ABORT,
                confidence=1.0,
                reason=(
                    f"Maximum healing attempts "
                    f"({self._config.max_healing_attempts}) reached."
                ),
                evidence=evidence,
                attempt_number=healing_attempt_count,
                requires_validation=False,
                next_state="ABORTED",
            )

        # ── Find next eligible candidate ──────────────────────
        eligible = self._filter_eligible_candidates(
            ranked_candidates, attempted_selectors, evidence,
        )

        if not eligible:
            evidence.append("No more unattempted candidates")
            return RecoveryDecision(
                workflow_id=workflow_id,
                test_case_id=test_case_id,
                failure_type=ft,
                decision=RecoveryAction.ABORT,
                confidence=1.0,
                reason=(
                    "No more eligible candidates. "
                    "All candidates exhausted or below threshold."
                ),
                evidence=evidence,
                attempt_number=healing_attempt_count,
                requires_validation=False,
                next_state="ABORTED",
            )

        # ── Evaluate the next candidate ───────────────────────
        return self._evaluate_healing(
            failure_analysis=failure_analysis,
            eligible_candidates=eligible,
            healing_attempt_count=healing_attempt_count,
            retry_count=0,
            attempted_selectors=attempted_selectors,
            workflow_id=workflow_id,
            test_case_id=test_case_id,
            evidence=evidence,
        )

    # ── Internal: Filter Eligible Candidates ──────────────────

    def _filter_eligible_candidates(
        self,
        candidates: list[ScoredCandidate],
        attempted: set[str],
        evidence: list[str],
    ) -> list[ScoredCandidate]:
        """Filter candidates to eligible ones.

        Removes:
        - Candidates already attempted
        - Candidates below min_candidate_score
        """
        eligible: list[ScoredCandidate] = []
        skipped_attempted = 0
        skipped_low = 0

        for c in candidates:
            if c.selector in attempted:
                skipped_attempted += 1
                continue
            if c.confidence < self._config.min_candidate_score:
                skipped_low += 1
                continue
            eligible.append(c)

        if skipped_attempted > 0:
            evidence.append(
                f"Skipped {skipped_attempted} already-attempted candidate(s)"
            )
        if skipped_low > 0:
            evidence.append(
                f"Skipped {skipped_low} candidate(s) below min score "
                f"({self._config.min_candidate_score})"
            )

        return eligible

    # ── Internal: Evaluate Healing Decision ───────────────────

    def _evaluate_healing(
        self,
        failure_analysis: FailureAnalysis,
        eligible_candidates: list[ScoredCandidate],
        healing_attempt_count: int,
        retry_count: int,
        attempted_selectors: set[str],
        workflow_id: str,
        test_case_id: str,
        evidence: list[str],
    ) -> RecoveryDecision:
        """Evaluate whether to heal with the best eligible candidate.

        Checks:
        1. Ambiguity between top candidates
        2. Historical evidence adjustment
        3. Confidence threshold enforcement
        """
        ft = (
            failure_analysis.failure_type
            if failure_analysis is not None
            else FailureType.UNKNOWN
        )

        # Get the best candidate
        best = eligible_candidates[0]
        adjusted_confidence = best.confidence

        # ── Historical evidence adjustment ────────────────────
        if self._evidence_retriever is not None and failure_analysis is not None:
            original_selector = failure_analysis.failed_target
            if original_selector:
                stats = self._evidence_retriever.get_replacement_stats(
                    original_selector, best.selector,
                )
                if stats.attempts > 0:
                    history_boost = (
                        stats.success_rate
                        * self._config.history_boost_weight
                    )
                    adjusted_confidence = min(
                        1.0,
                        best.confidence + history_boost,
                    )
                    evidence.append(
                        f"Historical evidence for '{best.selector}': "
                        f"{stats.successes}/{stats.attempts} successes "
                        f"(boost: +{history_boost:.3f})"
                    )

                    # Penalize candidates with poor history
                    if (
                        stats.attempts >= 3
                        and stats.success_rate < 0.3
                    ):
                        adjusted_confidence = max(
                            0.0,
                            adjusted_confidence - 0.2,
                        )
                        evidence.append(
                            f"Candidate '{best.selector}' penalized: "
                            f"poor historical success rate "
                            f"({stats.success_rate:.2f})"
                        )

        evidence.append(
            f"Best candidate: '{best.selector}' "
            f"(score={best.confidence:.4f}, "
            f"adjusted={adjusted_confidence:.4f})"
        )

        # ── Ambiguity detection ───────────────────────────────
        if len(eligible_candidates) >= 2:
            second = eligible_candidates[1]
            gap = best.confidence - second.confidence
            evidence.append(
                f"Second candidate: '{second.selector}' "
                f"(score={second.confidence:.4f}, gap={gap:.4f})"
            )

            if gap <= self._config.ambiguity_margin:
                evidence.append(
                    f"Candidates are ambiguous "
                    f"(gap {gap:.4f} <= margin {self._config.ambiguity_margin})"
                )
                return RecoveryDecision(
                    workflow_id=workflow_id,
                    test_case_id=test_case_id,
                    failure_type=ft,
                    decision=RecoveryAction.REQUIRE_FURTHER_ANALYSIS,
                    confidence=adjusted_confidence,
                    reason=(
                        f"Top candidates are ambiguous "
                        f"(gap={gap:.4f}). "
                        f"Require further analysis to disambiguate."
                    ),
                    evidence=evidence,
                    attempt_number=healing_attempt_count,
                    retry_count=retry_count,
                    requires_validation=False,
                    next_state="COMPLETED",
                )

        # ── Confidence threshold enforcement ──────────────────
        if adjusted_confidence >= self._config.min_healing_confidence:
            # HIGH confidence → TRY_HEALING
            evidence.append(
                f"Confidence {adjusted_confidence:.4f} >= "
                f"threshold {self._config.min_healing_confidence} — "
                f"recommend healing"
            )
            # Add candidate-specific evidence
            candidate_evidence = self._build_candidate_evidence(best)
            evidence.extend(candidate_evidence)

            return RecoveryDecision(
                workflow_id=workflow_id,
                test_case_id=test_case_id,
                failure_type=ft,
                decision=RecoveryAction.TRY_HEALING,
                confidence=adjusted_confidence,
                selected_candidate=best,
                reason=(
                    f"Strong evidence supports trying "
                    f"replacement selector '{best.selector}'."
                ),
                evidence=evidence,
                attempt_number=healing_attempt_count + 1,
                retry_count=retry_count,
                requires_validation=True,
                next_state="HEALING_PENDING_VALIDATION",
            )

        elif (
            self._config.allow_medium_confidence_healing
            and adjusted_confidence >= self._config.min_candidate_score
        ):
            # MEDIUM confidence with allow_medium → TRY_HEALING
            evidence.append(
                f"Medium confidence {adjusted_confidence:.4f} — "
                f"healing allowed (allow_medium_confidence_healing=True)"
            )
            candidate_evidence = self._build_candidate_evidence(best)
            evidence.extend(candidate_evidence)

            return RecoveryDecision(
                workflow_id=workflow_id,
                test_case_id=test_case_id,
                failure_type=ft,
                decision=RecoveryAction.TRY_HEALING,
                confidence=adjusted_confidence,
                selected_candidate=best,
                reason=(
                    f"Medium-confidence candidate '{best.selector}' "
                    f"sent for healing with validation."
                ),
                evidence=evidence,
                attempt_number=healing_attempt_count + 1,
                retry_count=retry_count,
                requires_validation=True,
                next_state="HEALING_PENDING_VALIDATION",
            )

        else:
            # LOW confidence → DO_NOT_HEAL
            evidence.append(
                f"Confidence {adjusted_confidence:.4f} < "
                f"threshold {self._config.min_healing_confidence} — "
                f"do not heal"
            )
            return RecoveryDecision(
                workflow_id=workflow_id,
                test_case_id=test_case_id,
                failure_type=ft,
                decision=RecoveryAction.DO_NOT_HEAL,
                confidence=adjusted_confidence,
                reason=(
                    f"Best candidate confidence "
                    f"({adjusted_confidence:.4f}) is below the "
                    f"minimum threshold "
                    f"({self._config.min_healing_confidence})."
                ),
                evidence=evidence,
                attempt_number=healing_attempt_count,
                retry_count=retry_count,
                requires_validation=False,
                next_state="COMPLETED",
            )

    # ── Internal: Build Candidate Evidence ────────────────────

    @staticmethod
    def _build_candidate_evidence(
        candidate: ScoredCandidate,
    ) -> list[str]:
        """Build concise evidence strings for a candidate."""
        ev: list[str] = []

        if candidate.text_similarity > 0:
            ev.append(
                f"Text similarity: {candidate.text_similarity:.2f}"
            )
        if candidate.role_similarity > 0:
            ev.append(
                f"Role similarity: {candidate.role_similarity:.2f}"
            )
        if candidate.type_similarity > 0:
            ev.append(
                f"Type similarity: {candidate.type_similarity:.2f}"
            )
        if candidate.page_similarity > 0:
            ev.append(
                f"Page similarity: {candidate.page_similarity:.2f}"
            )
        if candidate.stable_attribute_similarity > 0:
            ev.append(
                f"Stable attribute similarity: "
                f"{candidate.stable_attribute_similarity:.2f}"
            )
        if candidate.healing_history_score > 0:
            ev.append(
                f"Healing history score: "
                f"{candidate.healing_history_score:.2f}"
            )

        # Include candidate's own evidence strings
        ev.extend(candidate.evidence)

        return ev

    # ── Public: Get failure-type policy ───────────────────────

    def get_failure_policy(
        self, failure_type: FailureType,
    ) -> FailureTypePolicy:
        """Return the policy for a specific failure type.

        Parameters
        ----------
        failure_type:
            The failure type to look up.

        Returns
        -------
        FailureTypePolicy
            The policy for this failure type.
        """
        return self._failure_policies.get(
            failure_type,
            FailureTypePolicy(failure_type=failure_type, healable=False),
        )

    @property
    def config(self) -> RecoveryPolicyConfig:
        """Return the current policy configuration."""
        return self._config
