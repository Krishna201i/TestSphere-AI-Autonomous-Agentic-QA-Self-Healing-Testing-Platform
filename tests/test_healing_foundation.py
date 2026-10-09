"""
TestSphere-AI — Unit Tests for Self-Healing Foundation Contracts

Tests:
  - HealingCandidateDetail schema validation
  - LocatorStrategy constants
  - HealingInput and HealingOutput contracts
  - create_no_safe_healing sentinel helper
  - requires_validation safety invariant (always True)
  - Score bounds validation (0.0 to 1.0)
"""

from __future__ import annotations

import pytest

from agents.healer.healing_foundation import (
    HealingCandidateDetail,
    HealingInput,
    HealingOutput,
    LocatorStrategy,
    create_no_safe_healing,
)
from agents.schemas.enums import (
    CandidateSource,
    ConfidenceLevel,
    FailureType,
    HealingDecision,
    HealingStatus,
)


class TestHealingCandidateDetail:
    """Tests for HealingCandidateDetail model and constraints."""

    def test_valid_candidate_detail(self):
        candidate = HealingCandidateDetail(
            candidate_selector="button[data-testid='submit-btn']",
            locator_strategy=LocatorStrategy.DATA_TESTID,
            source=CandidateSource.CURRENT_DOM,
            tag_name="button",
            element_id="submit-btn",
            relevant_attributes={"data-testid": "submit-btn"},
            text_content="Submit Form",
            similarity_score=0.92,
            confidence_score=0.88,
            explanation="Matches tag, text, and role of original element",
            supporting_evidence=["Text matches: Submit Form", "Tag matches: button"],
        )
        assert candidate.candidate_selector == "button[data-testid='submit-btn']"
        assert candidate.locator_strategy == "data-testid"
        assert candidate.similarity_score == 0.92
        assert candidate.confidence_score == 0.88

    def test_similarity_score_bounds_validation(self):
        with pytest.raises(Exception):
            HealingCandidateDetail(
                candidate_selector="#btn",
                source=CandidateSource.CURRENT_DOM,
                similarity_score=1.5,
            )
        with pytest.raises(Exception):
            HealingCandidateDetail(
                candidate_selector="#btn",
                source=CandidateSource.CURRENT_DOM,
                similarity_score=-0.1,
            )

    def test_confidence_score_bounds_validation(self):
        with pytest.raises(Exception):
            HealingCandidateDetail(
                candidate_selector="#btn",
                source=CandidateSource.CURRENT_DOM,
                confidence_score=1.1,
            )


class TestHealingContracts:
    """Tests for HealingInput, HealingOutput, and safety rules."""

    def test_healing_input_construction(self):
        inp = HealingInput(
            test_id="TC-200",
            execution_id="exec-999",
            failed_step=3,
            original_selector="#old-button",
            failure_type=FailureType.ELEMENT_NOT_FOUND,
            action="click",
            current_dom_elements=[
                {"tag": "button", "id": "new-button", "text": "Click me"}
            ],
            screenshot_path="/tmp/screens/fail.png",
        )
        assert inp.test_id == "TC-200"
        assert inp.failed_step == 3
        assert len(inp.current_dom_elements) == 1

    def test_no_safe_healing_sentinel(self):
        output = create_no_safe_healing(
            test_id="TC-201",
            execution_id="exec-999",
            failed_step=2,
            original_selector="#missing-el",
            reason="No DOM elements matched threshold",
        )
        assert output.healing_status == HealingStatus.NO_SAFE_HEALING_FOUND
        assert output.healing_decision == HealingDecision.DO_NOT_HEAL
        assert output.candidates == []
        assert output.selected_candidate is None
        assert output.requires_validation is True
        assert "No DOM elements matched threshold" in output.evidence_summary[0]

    def test_requires_validation_cannot_be_false(self):
        with pytest.raises(ValueError, match="requires_validation must always be True"):
            HealingOutput(
                test_id="TC-202",
                execution_id="exec-999",
                failed_step=1,
                requires_validation=False,
            )

    def test_locator_strategies_constants(self):
        assert LocatorStrategy.CSS == "css"
        assert LocatorStrategy.XPATH == "xpath"
        assert LocatorStrategy.ID == "id"
        assert LocatorStrategy.DATA_TESTID == "data-testid"
        assert LocatorStrategy.ARIA_LABEL == "aria-label"
