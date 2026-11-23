"""
TestSphere-AI — Unit Tests for Failure Analysis Agent

Tests:
  - Failure analysis on FailureContext / TestFailure
  - Healable vs non-healable decisions
  - Severity calculation
  - Recommended action generation
  - Evidence building
  - Missing/empty evidence handling
  - Invalid inputs
"""

from __future__ import annotations

import pytest

from agents.analyzer.failure_analysis_agent import (
    FailureAnalysisAgent,
    FailureAnalysisResult,
    Severity,
)
from agents.analyzer.schemas import FailureContext, TestFailure
from agents.schemas.enums import (
    ConfidenceLevel,
    FailureType,
    RecommendedAction,
)


@pytest.fixture
def agent() -> FailureAnalysisAgent:
    """Fixture providing a FailureAnalysisAgent instance."""
    return FailureAnalysisAgent()


# ── Healability and Classification Tests ───────────────────────


class TestFailureAnalysisAgentDecisions:
    """Tests for healability, classification, and recommended action decisions."""

    def test_element_not_found_is_healable(self, agent: FailureAnalysisAgent):
        failure = FailureContext(
            test_id="TC-001",
            execution_id="exec-123",
            failed_step=2,
            action="click",
            target_selector="#submit-button",
            error_message="element not found in page: #submit-button",
        )
        result = agent.analyze(failure)

        assert isinstance(result, FailureAnalysisResult)
        assert result.failure_classification == FailureType.ELEMENT_NOT_FOUND
        assert result.is_healable is True
        assert result.severity == Severity.MEDIUM
        assert result.recommended_action == RecommendedAction.INSPECT_CURRENT_UI
        assert result.confidence_score >= 0.8
        assert result.confidence_level == ConfidenceLevel.HIGH

    def test_assertion_failure_is_not_healable(self, agent: FailureAnalysisAgent):
        failure = FailureContext(
            test_id="TC-002",
            execution_id="exec-123",
            failed_step=4,
            action="assert",
            target_selector=".status-badge",
            expected_result="Completed",
            actual_result="Pending",
            error_message="AssertionError: expected 'Completed' but got 'Pending'",
        )
        result = agent.analyze(failure)

        assert result.failure_classification == FailureType.ASSERTION_FAILURE
        assert result.is_healable is False
        assert result.severity == Severity.HIGH
        assert result.recommended_action == RecommendedAction.ANALYZE_APPLICATION_STATE
        assert "defect" in result.action_explanation.lower()

    def test_application_error_is_critical_and_not_healable(self, agent: FailureAnalysisAgent):
        failure = FailureContext(
            test_id="TC-003",
            execution_id="exec-123",
            failed_step=3,
            action="click",
            error_message="500 Internal Server Error: Unhandled database exception",
        )
        result = agent.analyze(failure)

        assert result.failure_classification == FailureType.APPLICATION_ERROR
        assert result.is_healable is False
        assert result.severity == Severity.CRITICAL
        assert result.recommended_action == RecommendedAction.REQUIRE_FURTHER_ANALYSIS

    def test_network_error_is_high_and_not_healable(self, agent: FailureAnalysisAgent):
        failure = FailureContext(
            test_id="TC-004",
            execution_id="exec-123",
            failed_step=1,
            action="click",
            error_message="Fetch failed: ECONNREFUSED",
        )
        result = agent.analyze(failure)

        assert result.failure_classification == FailureType.NETWORK_ERROR
        assert result.is_healable is False
        assert result.severity == Severity.HIGH
        assert result.recommended_action == RecommendedAction.REQUIRE_FURTHER_ANALYSIS

    def test_timeout_is_not_healable(self, agent: FailureAnalysisAgent):
        failure = FailureContext(
            test_id="TC-005",
            execution_id="exec-123",
            failed_step=2,
            action="wait",
            error_message="Timeout 30000ms exceeded waiting for selector",
        )
        result = agent.analyze(failure)

        assert result.failure_classification == FailureType.TIMEOUT
        assert result.is_healable is False
        assert result.recommended_action == RecommendedAction.INVESTIGATE_TIMEOUT

    def test_element_not_interactable_disabled_is_not_healable(self, agent: FailureAnalysisAgent):
        failure = FailureContext(
            test_id="TC-006",
            execution_id="exec-123",
            failed_step=3,
            action="click",
            target_selector="#btn-pay",
            error_message="Element is disabled and cannot be clicked",
        )
        dom_evidence = {"element_disabled": True}
        result = agent.analyze(failure, dom_evidence=dom_evidence)

        assert result.failure_classification == FailureType.ELEMENT_NOT_INTERACTABLE
        assert result.is_healable is False
        assert result.recommended_action == RecommendedAction.CHECK_ELEMENT_STATE

    def test_unknown_failure_handling(self, agent: FailureAnalysisAgent):
        failure = FailureContext(
            test_id="TC-007",
            execution_id="exec-123",
            failed_step=1,
            action="custom",
            error_message="Unrecognized error format 9987",
        )
        result = agent.analyze(failure)

        assert result.failure_classification == FailureType.UNKNOWN
        assert result.is_healable is False
        assert result.confidence_level == ConfidenceLevel.LOW
        assert result.recommended_action == RecommendedAction.REQUIRE_FURTHER_ANALYSIS


# ── Evidence and Contract Tests ────────────────────────────────


class TestFailureAnalysisEvidenceAndContracts:
    """Tests for evidence building and contract compliance."""

    def test_supporting_evidence_structure(self, agent: FailureAnalysisAgent):
        failure = TestFailure(
            test_id="TC-101",
            execution_id="exec-456",
            failed_step=2,
            action="fill",
            target_selector="input[name='email']",
            error_message="unable to locate element input[name='email']",
            current_page_url="https://example.com/login",
            current_page_title="Login Page",
        )
        dom_evidence = {"element_exists": False, "dom_depth": 5}
        result = agent.analyze(failure, dom_evidence=dom_evidence)

        evidence_types = [e.evidence_type for e in result.supporting_evidence]
        assert "classification" in evidence_types
        assert "error_message" in evidence_types
        assert "action_context" in evidence_types
        assert "page_context" in evidence_types
        assert "dom_evidence" in evidence_types

    def test_metadata_and_timestamps(self, agent: FailureAnalysisAgent):
        failure = TestFailure(
            test_id="TC-102",
            execution_id="exec-789",
            failed_step=1,
            action="click",
            target_selector="#menu",
            error_message="Element #menu not found",
        )
        result = agent.analyze(failure)

        assert result.test_id == "TC-102"
        assert result.failed_step_id == 1
        assert result.timestamp is not None
        assert result.metadata["action"] == "click"
        assert result.metadata["target_selector"] == "#menu"
        assert result.metadata["execution_id"] == "exec-789"

    def test_root_cause_composition(self, agent: FailureAnalysisAgent):
        failure = TestFailure(
            test_id="TC-103",
            execution_id="exec-000",
            failed_step=3,
            action="click",
            target_selector="#checkout-btn",
            error_message="element not found",
        )
        result = agent.analyze(failure)
        assert "#checkout-btn" in result.root_cause
