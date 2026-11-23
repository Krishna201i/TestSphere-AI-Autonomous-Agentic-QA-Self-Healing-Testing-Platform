"""
TestSphere-AI — Unit Tests for Failure Classifier

Tests:
  - Every supported failure category:
    * ELEMENT_NOT_FOUND
    * ELEMENT_NOT_INTERACTABLE
    * TIMEOUT
    * ASSERTION_FAILURE
    * NAVIGATION_FAILURE
    * NETWORK_ERROR
    * APPLICATION_ERROR
    * UNKNOWN
  - Missing or ambiguous evidence (empty message, empty action)
  - Confidence scoring, adjustments, and bounds validation
  - State mismatch detection
  - Batch classification
"""

from __future__ import annotations

import pytest

from agents.analyzer.failure_classifier import (
    ClassificationResult,
    FailureClassifier,
)
from agents.schemas.enums import FailureType


@pytest.fixture
def classifier() -> FailureClassifier:
    """Fixture providing a FailureClassifier instance."""
    return FailureClassifier()


# ── Supported Categories Tests ─────────────────────────────────


class TestFailureClassifierCategories:
    """Tests covering all 8 supported failure types plus UNKNOWN."""

    def test_classify_element_not_found(self, classifier: FailureClassifier):
        result = classifier.classify(
            error_message="Error: element not found: unable to locate element #submit-btn",
            action="click",
            target_selector="#submit-btn",
        )
        assert result.failure_type == FailureType.ELEMENT_NOT_FOUND
        assert result.confidence >= 0.8
        assert "target element could not be located" in result.explanation

    def test_classify_element_not_interactable(self, classifier: FailureClassifier):
        result = classifier.classify(
            error_message="Element is not interactable: another element would receive the click",
            action="click",
            target_selector="#login-btn",
        )
        assert result.failure_type == FailureType.ELEMENT_NOT_INTERACTABLE
        assert result.confidence >= 0.85
        assert "cannot currently be interacted with" in result.explanation

    def test_classify_timeout(self, classifier: FailureClassifier):
        result = classifier.classify(
            error_message="Timeout 30000ms exceeded while waiting for selector '#table'",
            action="wait",
            target_selector="#table",
        )
        assert result.failure_type == FailureType.TIMEOUT
        assert result.confidence >= 0.85
        assert "time limit" in result.explanation

    def test_classify_assertion_failure(self, classifier: FailureClassifier):
        result = classifier.classify(
            error_message="AssertionError: expected value 'Welcome' but got 'Login'",
            action="assert",
        )
        assert result.failure_type == FailureType.ASSERTION_FAILURE
        assert result.confidence >= 0.85
        assert "assertion" in result.explanation.lower()

    def test_classify_navigation_failure(self, classifier: FailureClassifier):
        result = classifier.classify(
            error_message="Navigation failed: net::ERR_NAME_NOT_RESOLVED at https://invalid.domain",
            action="navigate",
            current_url="https://invalid.domain",
        )
        assert result.failure_type == FailureType.NAVIGATION_FAILURE
        assert result.confidence >= 0.85
        assert "navigation" in result.explanation.lower()

    def test_classify_network_error(self, classifier: FailureClassifier):
        result = classifier.classify(
            error_message="Fetch failed: ECONNREFUSED 127.0.0.1:8000",
            action="click",
        )
        assert result.failure_type == FailureType.NETWORK_ERROR
        assert result.confidence >= 0.8
        assert "network" in result.explanation.lower()

    def test_classify_application_error(self, classifier: FailureClassifier):
        result = classifier.classify(
            error_message="Server responded with 500 Internal Server Error unhandled exception",
            action="click",
        )
        assert result.failure_type == FailureType.APPLICATION_ERROR
        assert result.confidence >= 0.8
        assert "application" in result.explanation.lower() or "error" in result.explanation.lower()

    def test_classify_unknown(self, classifier: FailureClassifier):
        result = classifier.classify(
            error_message="Something unexpected and completely unstructured happened",
            action="custom_action",
        )
        assert result.failure_type == FailureType.UNKNOWN
        assert result.confidence <= 0.4
        assert "does not match any known failure pattern" in result.explanation


# ── Edge Cases and Ambiguous Evidence ──────────────────────────


class TestFailureClassifierEdgeCases:
    """Tests for edge cases, missing data, and ambiguous evidence."""

    def test_empty_error_and_action(self, classifier: FailureClassifier):
        result = classifier.classify(error_message="", action="")
        assert result.failure_type == FailureType.UNKNOWN
        assert result.confidence == 0.1
        assert "insufficient evidence" in result.explanation

    def test_empty_error_with_action(self, classifier: FailureClassifier):
        result = classifier.classify(error_message="", action="click")
        assert result.failure_type == FailureType.UNKNOWN
        assert result.confidence == 0.1
        assert "No error message provided" in result.explanation

    def test_state_mismatch_detection(self, classifier: FailureClassifier):
        result = classifier.classify(
            error_message="Check failed",
            action="verify",
            expected_result="Dashboard",
            actual_result="Login Page",
        )
        assert result.failure_type == FailureType.ASSERTION_FAILURE
        assert result.confidence >= 0.85
        assert "Dashboard" in result.explanation
        assert "Login Page" in result.explanation

    def test_dom_evidence_confidence_boost_not_found(self, classifier: FailureClassifier):
        result_without_dom = classifier.classify(
            error_message="element not found",
            action="click",
        )
        result_with_dom = classifier.classify(
            error_message="element not found",
            action="click",
            dom_evidence={"element_exists": False},
        )
        assert result_with_dom.confidence >= result_without_dom.confidence

    def test_dom_evidence_confidence_boost_not_interactable(self, classifier: FailureClassifier):
        result_without_dom = classifier.classify(
            error_message="element not clickable",
            action="click",
        )
        result_with_dom = classifier.classify(
            error_message="element not clickable",
            action="click",
            dom_evidence={"element_visible": False, "element_disabled": True},
        )
        assert result_with_dom.confidence >= result_without_dom.confidence

    def test_short_error_message_confidence_penalty(self, classifier: FailureClassifier):
        result_short = classifier.classify(
            error_message="timeout",  # < 10 characters
            action="wait",
        )
        result_detailed = classifier.classify(
            error_message="timeout waiting for selector to be visible",
            action="wait",
        )
        assert result_short.confidence < result_detailed.confidence

    def test_inconsistent_action_penalty(self, classifier: FailureClassifier):
        result_inconsistent = classifier.classify(
            error_message="element not found in page",
            action="navigate",
        )
        result_consistent = classifier.classify(
            error_message="element not found in page",
            action="click",
        )
        assert result_inconsistent.confidence < result_consistent.confidence

    def test_batch_classification(self, classifier: FailureClassifier):
        batch = [
            {"error_message": "element not found", "action": "click"},
            {"error_message": "timed out after 5000ms", "action": "wait"},
            {"error_message": "500 internal server error", "action": "click"},
        ]
        results = classifier.classify_batch(batch)
        assert len(results) == 3
        assert results[0].failure_type == FailureType.ELEMENT_NOT_FOUND
        assert results[1].failure_type == FailureType.TIMEOUT
        assert results[2].failure_type == FailureType.APPLICATION_ERROR

    def test_confidence_validation_bounds(self):
        with pytest.raises(ValueError, match="Confidence must be between 0.0 and 1.0"):
            ClassificationResult(
                failure_type=FailureType.UNKNOWN,
                confidence=1.5,
                explanation="Invalid",
            )
        with pytest.raises(ValueError, match="Confidence must be between 0.0 and 1.0"):
            ClassificationResult(
                failure_type=FailureType.UNKNOWN,
                confidence=-0.1,
                explanation="Invalid",
            )
