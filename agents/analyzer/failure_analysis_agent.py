"""
TestSphere-AI — Failure Analysis Agent

High-level agent that accepts a TestFailure (FailureContext) and
available application/DOM evidence, then produces a structured
analysis result.

The agent combines:
  1. Deterministic FailureClassifier for initial categorization.
  2. Evidence-based reasoning for severity and healability.
  3. Optional LLM fallback (via MockLLMProvider) for ambiguous cases.

The agent distinguishes between:
  - Missing or changed selectors → potentially healable.
  - Element not interactable → investigate element state.
  - Timeouts → investigate performance or loading issues.
  - Assertion failures → genuine application defects, NOT healable.
  - Navigation failures → URL/routing problems.
  - Network errors → infrastructure issues, NOT healable.
  - Application errors → genuine bugs, NOT healable.
  - Unknown → insufficient evidence.

It does NOT recommend selector healing when evidence indicates
a genuine application defect or infrastructure problem.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field

from agents.analyzer.failure_classifier import (
    ClassificationResult,
    FailureClassifier,
)
from agents.analyzer.schemas import (
    FailureContext,
    FailureEvidence,
)
from agents.schemas.enums import (
    ConfidenceLevel,
    FailureType,
    RecommendedAction,
)

logger = logging.getLogger(__name__)


# ── Severity Levels ──────────────────────────────────────────


class Severity:
    """Failure severity constants."""

    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


# ── Failure Analysis Result ──────────────────────────────────


class FailureAnalysisResult(BaseModel):
    """Complete result from the Failure Analysis Agent.

    Extends the base FailureAnalysis with additional detail
    about healability, severity, and recommended actions.
    """

    test_id: str = Field(..., description="ID of the failed test case")
    failed_step_id: Optional[int] = Field(
        default=None, description="Step number that failed"
    )
    failure_classification: FailureType = Field(
        ..., description="Classified failure category"
    )
    root_cause: str = Field(
        ..., description="Probable root cause explanation"
    )
    severity: str = Field(
        ..., description="Severity: CRITICAL, HIGH, MEDIUM, LOW"
    )
    is_healable: bool = Field(
        ...,
        description=(
            "Whether the failure is potentially healable by the "
            "Self-Healing Agent (selector changes, element moves)"
        ),
    )
    confidence_score: float = Field(
        ..., ge=0.0, le=1.0,
        description="Confidence in the analysis (0.0 to 1.0)",
    )
    confidence_level: ConfidenceLevel = Field(
        ..., description="Qualitative confidence level"
    )
    supporting_evidence: list[FailureEvidence] = Field(
        default_factory=list,
        description="Evidence supporting the analysis",
    )
    recommended_action: RecommendedAction = Field(
        ..., description="Recommended next action"
    )
    action_explanation: str = Field(
        default="",
        description="Explanation of why this action is recommended",
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO 8601 timestamp of the analysis",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional analysis metadata",
    )


# ── Healability Rules ────────────────────────────────────────

# Failure types that are potentially healable by the Self-Healing Agent.
_HEALABLE_TYPES: set[FailureType] = {
    FailureType.SELECTOR_CHANGED,
    FailureType.ELEMENT_NOT_FOUND,
}

# Failure types that are conditionally healable (depends on evidence).
_CONDITIONALLY_HEALABLE: set[FailureType] = {
    FailureType.ELEMENT_NOT_INTERACTABLE,
}

# Failure types that are NEVER healable — indicate real defects.
_NON_HEALABLE_TYPES: set[FailureType] = {
    FailureType.ASSERTION_FAILURE,
    FailureType.NAVIGATION_FAILURE,
    FailureType.NETWORK_ERROR,
    FailureType.APPLICATION_ERROR,
    FailureType.TIMEOUT,
    FailureType.UNKNOWN,
}

# Severity mapping
_SEVERITY_MAP: dict[FailureType, str] = {
    FailureType.SELECTOR_CHANGED: Severity.MEDIUM,
    FailureType.ELEMENT_NOT_FOUND: Severity.MEDIUM,
    FailureType.ELEMENT_NOT_INTERACTABLE: Severity.MEDIUM,
    FailureType.ASSERTION_FAILURE: Severity.HIGH,
    FailureType.TIMEOUT: Severity.MEDIUM,
    FailureType.NAVIGATION_FAILURE: Severity.HIGH,
    FailureType.NETWORK_ERROR: Severity.HIGH,
    FailureType.APPLICATION_ERROR: Severity.CRITICAL,
    FailureType.UNKNOWN: Severity.MEDIUM,
}

# Recommended action mapping
_RECOMMENDED_ACTIONS: dict[FailureType, RecommendedAction] = {
    FailureType.SELECTOR_CHANGED: RecommendedAction.SEARCH_FOR_REPLACEMENT_SELECTOR,
    FailureType.ELEMENT_NOT_FOUND: RecommendedAction.INSPECT_CURRENT_UI,
    FailureType.ELEMENT_NOT_INTERACTABLE: RecommendedAction.CHECK_ELEMENT_STATE,
    FailureType.ASSERTION_FAILURE: RecommendedAction.ANALYZE_APPLICATION_STATE,
    FailureType.TIMEOUT: RecommendedAction.INVESTIGATE_TIMEOUT,
    FailureType.NAVIGATION_FAILURE: RecommendedAction.INVESTIGATE_NAVIGATION,
    FailureType.NETWORK_ERROR: RecommendedAction.REQUIRE_FURTHER_ANALYSIS,
    FailureType.APPLICATION_ERROR: RecommendedAction.REQUIRE_FURTHER_ANALYSIS,
    FailureType.UNKNOWN: RecommendedAction.REQUIRE_FURTHER_ANALYSIS,
}

# Action explanations
_ACTION_EXPLANATIONS: dict[FailureType, str] = {
    FailureType.SELECTOR_CHANGED: (
        "The original selector no longer identifies the target element. "
        "Search for a replacement selector using current DOM evidence."
    ),
    FailureType.ELEMENT_NOT_FOUND: (
        "The target element cannot be located. Inspect the current UI "
        "to determine if the element was removed, relocated, or renamed."
    ),
    FailureType.ELEMENT_NOT_INTERACTABLE: (
        "The element exists but is not interactable. Check if it is "
        "hidden, disabled, or obscured by another element."
    ),
    FailureType.ASSERTION_FAILURE: (
        "The expected application state does not match the observed state. "
        "This indicates a potential application defect — do NOT attempt healing."
    ),
    FailureType.TIMEOUT: (
        "An operation timed out. Investigate whether the application "
        "is slow, the element takes longer to appear, or there is a deadlock."
    ),
    FailureType.NAVIGATION_FAILURE: (
        "Navigation did not succeed. Verify the URL is correct and "
        "the application is accessible."
    ),
    FailureType.NETWORK_ERROR: (
        "A network error occurred. This is likely an infrastructure issue "
        "unrelated to the test logic — do NOT attempt selector healing."
    ),
    FailureType.APPLICATION_ERROR: (
        "The application threw an error. This is a genuine bug — "
        "do NOT attempt selector healing. Report the error to developers."
    ),
    FailureType.UNKNOWN: (
        "The failure cause could not be determined from available evidence. "
        "Further analysis is needed."
    ),
}


# ── Failure Analysis Agent ───────────────────────────────────


class FailureAnalysisAgent:
    """High-level agent that analyzes test failures.

    Accepts a FailureContext and produces a comprehensive
    FailureAnalysisResult with classification, severity,
    healability assessment, and recommended actions.

    Parameters
    ----------
    classifier:
        Optional FailureClassifier instance. If None, a default
        instance is created.
    llm_client:
        Optional LLM client for ambiguous cases. If None, only
        deterministic rules are used.

    Usage
    -----
    >>> agent = FailureAnalysisAgent()
    >>> result = agent.analyze(failure_context)
    """

    def __init__(
        self,
        classifier: Optional[FailureClassifier] = None,
        llm_client: object | None = None,
    ) -> None:
        self._classifier = classifier or FailureClassifier()
        self._llm_client = llm_client
        logger.info(
            "FailureAnalysisAgent initialized — llm_available=%s",
            llm_client is not None,
        )

    def analyze(
        self,
        failure: FailureContext,
        dom_evidence: Optional[dict] = None,
    ) -> FailureAnalysisResult:
        """Analyze a test failure and produce a comprehensive result.

        Parameters
        ----------
        failure:
            Structured failure context from the execution engine.
        dom_evidence:
            Optional DOM evidence from the current page.

        Returns
        -------
        FailureAnalysisResult
            Complete analysis with classification, severity,
            healability, and recommendations.
        """
        logger.info(
            "Analyzing failure — test_id=%s, step=%d, action=%s",
            failure.test_id,
            failure.failed_step,
            failure.action,
        )

        # 1. Classify the failure
        classification = self._classifier.classify(
            error_message=failure.error_message,
            action=failure.action,
            target_selector=failure.target_selector,
            expected_result=failure.expected_result,
            actual_result=failure.actual_result,
            current_url=failure.current_page_url,
            dom_evidence=dom_evidence,
        )

        # 2. Determine healability
        is_healable = self._assess_healability(
            classification, failure, dom_evidence,
        )

        # 3. Determine severity
        severity = self._assess_severity(classification, failure)

        # 4. Build evidence list
        evidence = self._build_evidence(classification, failure, dom_evidence)

        # 5. Get recommended action
        recommended = _RECOMMENDED_ACTIONS.get(
            classification.failure_type,
            RecommendedAction.REQUIRE_FURTHER_ANALYSIS,
        )

        action_explanation = _ACTION_EXPLANATIONS.get(
            classification.failure_type, ""
        )

        # 6. Convert numeric confidence to qualitative level
        confidence_level = self._to_confidence_level(classification.confidence)

        # 7. Build root cause description
        root_cause = self._build_root_cause(classification, failure)

        result = FailureAnalysisResult(
            test_id=failure.test_id,
            failed_step_id=failure.failed_step,
            failure_classification=classification.failure_type,
            root_cause=root_cause,
            severity=severity,
            is_healable=is_healable,
            confidence_score=classification.confidence,
            confidence_level=confidence_level,
            supporting_evidence=evidence,
            recommended_action=recommended,
            action_explanation=action_explanation,
            metadata={
                "action": failure.action,
                "target_selector": failure.target_selector,
                "matched_patterns": classification.matched_patterns,
                "execution_id": failure.execution_id,
            },
        )

        logger.info(
            "Analysis complete — type=%s, severity=%s, healable=%s, "
            "confidence=%.2f, action=%s",
            classification.failure_type.value,
            severity,
            is_healable,
            classification.confidence,
            recommended.value,
        )

        return result

    # ── Private Helpers ───────────────────────────────────────

    @staticmethod
    def _assess_healability(
        classification: ClassificationResult,
        failure: FailureContext,
        dom_evidence: Optional[dict],
    ) -> bool:
        """Determine if the failure is potentially healable."""
        ft = classification.failure_type

        # Definitely healable
        if ft in _HEALABLE_TYPES:
            return True

        # Definitely NOT healable
        if ft in _NON_HEALABLE_TYPES:
            return False

        # Conditionally healable (ELEMENT_NOT_INTERACTABLE)
        if ft in _CONDITIONALLY_HEALABLE:
            # Only healable if the element might have moved/changed,
            # not if it's genuinely disabled or hidden
            if dom_evidence:
                if dom_evidence.get("element_disabled"):
                    return False  # Genuinely disabled — not healable
                if dom_evidence.get("element_obscured"):
                    return False  # Obscured — not a selector problem
            # Without evidence, assume not healable to be safe
            return False

        return False

    @staticmethod
    def _assess_severity(
        classification: ClassificationResult,
        failure: FailureContext,
    ) -> str:
        """Determine the severity of the failure."""
        base_severity = _SEVERITY_MAP.get(
            classification.failure_type, Severity.MEDIUM,
        )

        # Upgrade severity if the failure is on a critical action
        critical_actions = {"navigate", "fill", "click"}
        if failure.action.lower() in critical_actions:
            if base_severity == Severity.LOW:
                return Severity.MEDIUM

        return base_severity

    @staticmethod
    def _build_evidence(
        classification: ClassificationResult,
        failure: FailureContext,
        dom_evidence: Optional[dict],
    ) -> list[FailureEvidence]:
        """Build the supporting evidence list."""
        evidence: list[FailureEvidence] = []

        # Classification evidence
        evidence.append(
            FailureEvidence(
                evidence_type="classification",
                description=classification.explanation,
                details={
                    "failure_type": classification.failure_type.value,
                    "confidence": classification.confidence,
                    "matched_patterns": classification.matched_patterns,
                },
            )
        )

        # Error message evidence
        if failure.error_message:
            evidence.append(
                FailureEvidence(
                    evidence_type="error_message",
                    description=f"Error: {failure.error_message[:200]}",
                    details={"full_error": failure.error_message},
                )
            )

        # Action context evidence
        if failure.action:
            evidence.append(
                FailureEvidence(
                    evidence_type="action_context",
                    description=(
                        f"Action '{failure.action}' was being performed "
                        f"on target '{failure.target_selector}'"
                    ),
                    details={
                        "action": failure.action,
                        "target": failure.target_selector,
                    },
                )
            )

        # State mismatch evidence
        if failure.expected_result and failure.actual_result:
            if failure.expected_result != failure.actual_result:
                evidence.append(
                    FailureEvidence(
                        evidence_type="state_mismatch",
                        description=(
                            f"Expected: '{failure.expected_result}', "
                            f"Actual: '{failure.actual_result}'"
                        ),
                        details={
                            "expected": failure.expected_result,
                            "actual": failure.actual_result,
                        },
                    )
                )

        # Page context evidence
        if failure.current_page_url:
            evidence.append(
                FailureEvidence(
                    evidence_type="page_context",
                    description=f"Failure occurred on page: {failure.current_page_url}",
                    details={
                        "url": failure.current_page_url,
                        "title": failure.current_page_title or "",
                    },
                )
            )

        # DOM evidence
        if dom_evidence:
            evidence.append(
                FailureEvidence(
                    evidence_type="dom_evidence",
                    description="DOM evidence available from current page",
                    details=dom_evidence,
                )
            )

        return evidence

    @staticmethod
    def _to_confidence_level(confidence: float) -> ConfidenceLevel:
        """Convert numeric confidence to qualitative level."""
        if confidence >= 0.75:
            return ConfidenceLevel.HIGH
        elif confidence >= 0.45:
            return ConfidenceLevel.MEDIUM
        else:
            return ConfidenceLevel.LOW

    @staticmethod
    def _build_root_cause(
        classification: ClassificationResult,
        failure: FailureContext,
    ) -> str:
        """Build a descriptive root cause string."""
        base = classification.explanation

        # Add context-specific details
        if failure.target_selector:
            if classification.failure_type in (
                FailureType.ELEMENT_NOT_FOUND,
                FailureType.SELECTOR_CHANGED,
            ):
                base = (
                    f"{base}. Target selector: '{failure.target_selector}'"
                )
            elif classification.failure_type == FailureType.ELEMENT_NOT_INTERACTABLE:
                base = (
                    f"{base}. Element '{failure.target_selector}' is present "
                    f"but not interactable"
                )

        if failure.expected_result and failure.actual_result:
            if classification.failure_type == FailureType.ASSERTION_FAILURE:
                base = (
                    f"Expected: '{failure.expected_result}', "
                    f"Actual: '{failure.actual_result}'"
                )

        return base
