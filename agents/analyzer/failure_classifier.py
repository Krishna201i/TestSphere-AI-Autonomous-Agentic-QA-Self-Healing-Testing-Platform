"""
TestSphere-AI — Failure Classifier

Deterministic rule-based classifier that categorizes test failures
into structured ``FailureType`` categories.

The classifier uses error message pattern matching, structured failure
evidence, and contextual signals to determine:
  - The failure category (``FailureType``)
  - A confidence score (0.0–1.0)
  - A human-readable explanation

Design Principles:
  - Deterministic rules where possible (no LLM for simple cases).
  - Does NOT classify every failure as a selector problem.
  - Distinguishes automation failures from application defects.
  - Handles missing or ambiguous evidence safely.
  - Returns UNKNOWN with low confidence when evidence is insufficient.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from agents.schemas.enums import FailureType

logger = logging.getLogger(__name__)


# ── Classification Result ────────────────────────────────────


@dataclass(frozen=True)
class ClassificationResult:
    """Result of classifying a test failure.

    Attributes
    ----------
    failure_type:
        The classified failure category.
    confidence:
        Confidence score for the classification (0.0 to 1.0).
    explanation:
        Human-readable explanation of why this category was chosen.
    matched_patterns:
        Error message patterns that contributed to the classification.
    """

    failure_type: FailureType
    confidence: float
    explanation: str
    matched_patterns: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Validate confidence bounds."""
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"Confidence must be between 0.0 and 1.0, got {self.confidence}"
            )


# ── Pattern Definitions ──────────────────────────────────────

# Each rule is a tuple of (patterns, FailureType, base_confidence, explanation).
# Patterns are matched case-insensitively against the error message.
# Rules are ordered by specificity — more specific patterns come first.

_CLASSIFICATION_RULES: list[
    tuple[list[str], FailureType, float, str]
] = [
    # ── ELEMENT_NOT_INTERACTABLE ──────────────────────────────
    # Must come before ELEMENT_NOT_FOUND since "not clickable" ≠ "not found"
    (
        [
            "not interactable",
            "not clickable",
            "element is disabled",
            "element is hidden",
            "element is obscured",
            "intercepted",
            "another element would receive",
            "pointer-events: none",
            "element is not visible",
            "cannot interact",
        ],
        FailureType.ELEMENT_NOT_INTERACTABLE,
        0.90,
        "The element exists but cannot currently be interacted with",
    ),

    # ── ASSERTION_FAILURE ─────────────────────────────────────
    # Must come before generic "expected" patterns
    (
        [
            "assertion",
            "assert failed",
            "assert error",
            "assertionerror",
            "expected value",
            "mismatch",
            "does not match expected",
            "text content mismatch",
            "value mismatch",
        ],
        FailureType.ASSERTION_FAILURE,
        0.90,
        "An assertion check failed — expected state does not match actual state",
    ),

    # ── TIMEOUT ───────────────────────────────────────────────
    (
        [
            "timeout",
            "timed out",
            "time out",
            "exceeded timeout",
            "deadline exceeded",
            "waiting for selector",
            "waiting for navigation",
            "wait timeout",
        ],
        FailureType.TIMEOUT,
        0.90,
        "An operation did not complete within the allowed time limit",
    ),

    # ── NAVIGATION_FAILURE ────────────────────────────────────
    (
        [
            "navigation failed",
            "page load failed",
            "404",
            "page not found",
            "net::err_",
            "net::err_name_not_resolved",
            "net::err_connection_refused",
            "err_connection_reset",
            "cannot navigate",
            "invalid url",
            "failed to navigate",
        ],
        FailureType.NAVIGATION_FAILURE,
        0.90,
        "Page navigation did not complete successfully",
    ),

    # ── NETWORK_ERROR ─────────────────────────────────────────
    (
        [
            "network error",
            "network failure",
            "fetch failed",
            "xhr failed",
            "connection refused",
            "connection reset",
            "dns resolution failed",
            "econnrefused",
            "econnreset",
            "enotfound",
            "socket hang up",
            "cors error",
            "ssl error",
            "certificate error",
        ],
        FailureType.NETWORK_ERROR,
        0.85,
        "A network-level error occurred during the test",
    ),

    # ── APPLICATION_ERROR ─────────────────────────────────────
    (
        [
            "500 internal server error",
            "503 service unavailable",
            "502 bad gateway",
            "application error",
            "server error",
            "unhandled exception",
            "runtime error",
            "uncaught exception",
            "javascript error",
            "react error boundary",
            "chunk load error",
            "script error",
        ],
        FailureType.APPLICATION_ERROR,
        0.85,
        "The application under test threw an error or crashed",
    ),

    # ── ELEMENT_NOT_FOUND ─────────────────────────────────────
    # This is the broadest selector-related pattern — checked last
    # among specific categories.
    (
        [
            "element not found",
            "element_not_found",
            "no element",
            "no such element",
            "could not find element",
            "unable to locate element",
            "selector not found",
            "no matching element",
            "target element not found",
            "locator resolved to no elements",
        ],
        FailureType.ELEMENT_NOT_FOUND,
        0.85,
        "The target element could not be located in the current page",
    ),
]


# ── Failure Classifier ───────────────────────────────────────


class FailureClassifier:
    """Deterministic rule-based failure classifier.

    Classifies test failures into ``FailureType`` categories using
    error message pattern matching and structured evidence.

    The classifier:
    - Uses ordered rules with decreasing specificity.
    - Boosts confidence when multiple patterns match.
    - Reduces confidence when evidence is ambiguous.
    - Returns UNKNOWN with low confidence for unrecognizable failures.
    - Never classifies everything as a selector problem.

    Usage
    -----
    >>> classifier = FailureClassifier()
    >>> result = classifier.classify(
    ...     error_message="Element #submit-btn not found",
    ...     action="click",
    ... )
    >>> result.failure_type
    <FailureType.ELEMENT_NOT_FOUND: 'ELEMENT_NOT_FOUND'>
    """

    def classify(
        self,
        error_message: str,
        action: str = "",
        target_selector: str = "",
        expected_result: Optional[str] = None,
        actual_result: Optional[str] = None,
        current_url: Optional[str] = None,
        dom_evidence: Optional[dict] = None,
    ) -> ClassificationResult:
        """Classify a test failure based on available evidence.

        Parameters
        ----------
        error_message:
            The error message from the execution engine.
        action:
            The action being performed when failure occurred.
        target_selector:
            The selector being used when failure occurred.
        expected_result:
            Expected outcome, if known.
        actual_result:
            Actual observed outcome, if known.
        current_url:
            Current page URL at time of failure.
        dom_evidence:
            Additional DOM evidence, if available.

        Returns
        -------
        ClassificationResult
            The classification with failure type, confidence,
            and explanation.
        """
        if not error_message and not action:
            return ClassificationResult(
                failure_type=FailureType.UNKNOWN,
                confidence=0.1,
                explanation="No error message or action provided — insufficient evidence",
                matched_patterns=[],
            )

        error_lower = error_message.lower() if error_message else ""

        # ── Check state mismatch (assertion failure) ──────────
        if self._has_state_mismatch(expected_result, actual_result):
            result = self._classify_state_mismatch(
                expected_result, actual_result, error_lower,
            )
            if result is not None:
                return result

        # ── Pattern-based classification ──────────────────────
        for patterns, failure_type, base_confidence, explanation in _CLASSIFICATION_RULES:
            matched = [p for p in patterns if p in error_lower]
            if matched:
                # Boost confidence slightly when multiple patterns match
                confidence = min(
                    base_confidence + 0.02 * (len(matched) - 1),
                    1.0,
                )

                # Adjust for evidence quality
                confidence = self._adjust_confidence(
                    confidence,
                    failure_type=failure_type,
                    error_message=error_message,
                    action=action,
                    target_selector=target_selector,
                    dom_evidence=dom_evidence,
                )

                logger.debug(
                    "Classified as %s (confidence=%.2f, patterns=%s)",
                    failure_type.value,
                    confidence,
                    matched,
                )

                return ClassificationResult(
                    failure_type=failure_type,
                    confidence=confidence,
                    explanation=explanation,
                    matched_patterns=matched,
                )

        # ── Fallback: UNKNOWN ─────────────────────────────────
        confidence = 0.3
        explanation = (
            "Available evidence is insufficient to determine the failure cause"
        )

        # Check if error_message has any useful content
        if error_message and len(error_message.strip()) > 10:
            confidence = 0.2
            explanation = (
                f"Error message does not match any known failure pattern: "
                f"'{error_message[:100]}'"
            )
        elif not error_message:
            confidence = 0.1
            explanation = "No error message provided"

        return ClassificationResult(
            failure_type=FailureType.UNKNOWN,
            confidence=confidence,
            explanation=explanation,
            matched_patterns=[],
        )

    # ── Private Helpers ───────────────────────────────────────

    @staticmethod
    def _has_state_mismatch(
        expected: Optional[str], actual: Optional[str],
    ) -> bool:
        """Check if expected and actual results indicate a mismatch."""
        return (
            expected is not None
            and actual is not None
            and expected != actual
        )

    @staticmethod
    def _classify_state_mismatch(
        expected: Optional[str],
        actual: Optional[str],
        error_lower: str,
    ) -> Optional[ClassificationResult]:
        """Classify a state mismatch as an assertion failure."""
        # Only classify if there's a clear expected/actual mismatch
        if expected is None or actual is None:
            return None

        # Higher confidence if error message also mentions assertion
        if any(kw in error_lower for kw in ("assert", "mismatch", "expected")):
            confidence = 0.95
        else:
            confidence = 0.85

        return ClassificationResult(
            failure_type=FailureType.ASSERTION_FAILURE,
            confidence=confidence,
            explanation=(
                f"Expected state does not match actual state. "
                f"Expected: '{expected}', Actual: '{actual}'"
            ),
            matched_patterns=["state_mismatch"],
        )

    @staticmethod
    def _adjust_confidence(
        base_confidence: float,
        *,
        failure_type: FailureType,
        error_message: str,
        action: str,
        target_selector: str,
        dom_evidence: Optional[dict],
    ) -> float:
        """Adjust confidence based on supporting evidence."""
        confidence = base_confidence

        # Boost if DOM evidence supports the classification
        if dom_evidence:
            if failure_type == FailureType.ELEMENT_NOT_FOUND:
                if dom_evidence.get("element_exists") is False:
                    confidence = min(confidence + 0.05, 1.0)
            elif failure_type == FailureType.ELEMENT_NOT_INTERACTABLE:
                if dom_evidence.get("element_visible") is False:
                    confidence = min(confidence + 0.05, 1.0)
                if dom_evidence.get("element_disabled") is True:
                    confidence = min(confidence + 0.05, 1.0)

        # Reduce confidence slightly if error message is very short
        if error_message and len(error_message.strip()) < 10:
            confidence = max(confidence - 0.10, 0.1)

        # Reduce confidence if action seems inconsistent with failure type
        if failure_type == FailureType.ELEMENT_NOT_FOUND and action == "navigate":
            confidence = max(confidence - 0.15, 0.1)

        return round(confidence, 2)

    def classify_batch(
        self,
        failures: list[dict],
    ) -> list[ClassificationResult]:
        """Classify multiple failures at once.

        Parameters
        ----------
        failures:
            List of dicts with keys: error_message, action,
            target_selector, expected_result, actual_result,
            current_url, dom_evidence.

        Returns
        -------
        list[ClassificationResult]
            Classifications for each failure.
        """
        return [
            self.classify(
                error_message=f.get("error_message", ""),
                action=f.get("action", ""),
                target_selector=f.get("target_selector", ""),
                expected_result=f.get("expected_result"),
                actual_result=f.get("actual_result"),
                current_url=f.get("current_url"),
                dom_evidence=f.get("dom_evidence"),
            )
            for f in failures
        ]
