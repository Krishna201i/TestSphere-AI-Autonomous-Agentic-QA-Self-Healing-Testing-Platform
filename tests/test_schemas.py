"""
TestSphere-AI — Schema Validation Tests

Validates that all Pydantic schemas can be instantiated,
serialized, and deserialized correctly. Ensures the inter-member
data contracts are structurally sound.
"""

import json

import pytest

from agents.schemas.enums import (
    AssertionType,
    FailureType,
    HealingStatus,
    TestAction,
    TestCategory,
    TestPriority,
)
from agents.planner.schemas import (
    ApplicationContext,
    Assertion,
    ElementContext,
    PageContext,
    PageInfo,
    TestCase,
    TestPlan,
    TestStep,
)
from agents.analyzer.schemas import FailureAnalysis, TestFailure
from agents.healer.schemas import HealingCandidate, HealingResult


# ── Enum Tests ──────────────────────────────────────────────


class TestFailureTypeEnum:
    """Validate FailureType enum values."""

    def test_all_failure_types_exist(self):
        expected = {
            "ELEMENT_NOT_FOUND",
            "ELEMENT_NOT_INTERACTABLE",
            "TIMEOUT",
            "ASSERTION_FAILURE",
            "NAVIGATION_FAILURE",
            "NETWORK_ERROR",
            "APPLICATION_ERROR",
            "UNKNOWN",
        }
        actual = {ft.value for ft in FailureType}
        assert actual == expected

    def test_failure_type_count(self):
        assert len(FailureType) == 8

    def test_failure_type_is_string(self):
        assert FailureType.ELEMENT_NOT_FOUND == "ELEMENT_NOT_FOUND"


class TestHealingStatusEnum:
    """Validate HealingStatus enum values."""

    def test_all_statuses_exist(self):
        expected = {
            "PROPOSED",
            "VALIDATION_PENDING",
            "VALIDATED_SUCCESS",
            "VALIDATED_FAILURE",
            "NO_SAFE_HEALING_FOUND",
        }
        actual = {hs.value for hs in HealingStatus}
        assert actual == expected


class TestPriorityAndCategoryEnums:
    """Validate TestPriority and TestCategory enums."""

    def test_priorities(self):
        assert len(TestPriority) == 4

    def test_categories(self):
        # Day 4: added NEGATIVE and BOUNDARY → 7 total
        assert len(TestCategory) == 7

    def test_negative_category_exists(self):
        assert TestCategory.NEGATIVE == "negative"

    def test_boundary_category_exists(self):
        assert TestCategory.BOUNDARY == "boundary"


class TestActionAndAssertionEnums:
    """Validate TestAction and AssertionType enums (Day 4)."""

    def test_action_count(self):
        assert len(TestAction) == 8

    def test_action_values(self):
        expected = {
            "navigate", "click", "fill", "select",
            "check", "uncheck", "press", "wait",
        }
        actual = {a.value for a in TestAction}
        assert actual == expected

    def test_assertion_type_count(self):
        assert len(AssertionType) == 7

    def test_assertion_type_values(self):
        expected = {
            "element_visible", "element_not_visible",
            "element_contains_text", "element_has_text",
            "url_contains", "url_equals", "value_equals",
        }
        actual = {at.value for at in AssertionType}
        assert actual == expected


# ── Planner Schema Tests ───────────────────────────────────


class TestPlannerSchemas:
    """Validate Test Planner data contracts."""

    def test_create_minimal_test_case(self):
        tc = TestCase(
            test_id="TC001",
            name="Valid Login",
        )
        assert tc.test_id == "TC001"
        assert tc.name == "Valid Login"
        assert tc.category == TestCategory.FUNCTIONAL
        assert tc.priority == TestPriority.MEDIUM
        assert tc.steps == []
        assert tc.assertions == []

    def test_create_full_test_case(self):
        """Match the contract from the requirements."""
        tc = TestCase(
            test_id="TC001",
            name="Valid Login",
            description="Verify that a user can log in with valid credentials.",
            category=TestCategory.FUNCTIONAL,
            priority=TestPriority.HIGH,
            steps=[
                TestStep(
                    step_number=1,
                    action=TestAction.NAVIGATE,
                    value="https://example.com/login",
                    description="Go to login page",
                ),
                TestStep(
                    step_number=2,
                    action=TestAction.FILL,
                    target="#username",
                    value="testuser",
                    description="Enter username",
                ),
                TestStep(
                    step_number=3,
                    action=TestAction.CLICK,
                    target="#login-button",
                    description="Click login",
                ),
            ],
            assertions=[
                Assertion(
                    type=AssertionType.URL_CONTAINS,
                    expected="/dashboard",
                    description="Should redirect to dashboard",
                ),
            ],
        )

        assert tc.test_id == "TC001"
        assert len(tc.steps) == 3
        assert len(tc.assertions) == 1
        assert tc.priority == TestPriority.HIGH

    def test_test_case_serialization_roundtrip(self):
        tc = TestCase(
            test_id="TC002",
            name="Search Feature",
            description="Test search functionality",
            steps=[
                TestStep(
                    step_number=1,
                    action=TestAction.FILL,
                    target="#search-input",
                    value="test query",
                ),
            ],
        )

        # Serialize to JSON
        json_str = tc.model_dump_json()
        data = json.loads(json_str)

        # Deserialize back
        tc2 = TestCase.model_validate(data)
        assert tc2.test_id == tc.test_id
        assert tc2.steps[0].value == "test query"

    def test_application_context(self):
        ctx = ApplicationContext(
            app_name="TestApp",
            app_url="https://testapp.example.com",
            description="A sample web application",
            pages=[
                PageInfo(url="/login", name="Login Page"),
                PageInfo(url="/dashboard", name="Dashboard"),
            ],
            technology_stack=["React", "Node.js"],
        )
        assert ctx.app_name == "TestApp"
        assert len(ctx.pages) == 2

    def test_backward_compatible_selector_alias(self):
        """TestStep.selector should return the same value as target."""
        step = TestStep(
            step_number=1,
            action=TestAction.CLICK,
            target="#my-button",
        )
        assert step.selector == "#my-button"
        assert step.target == "#my-button"


# ── Analyzer Schema Tests ──────────────────────────────────


class TestAnalyzerSchemas:
    """Validate Failure Analyzer data contracts."""

    def test_create_test_failure(self):
        """Match the failure contract from the requirements."""
        failure = TestFailure(
            test_id="TC001",
            failed_step=3,
            action="click",
            selector="#login-button",
            error="Element not found",
            url="/login",
            dom_snapshot="<html>...</html>",
            screenshot_path="/tmp/screenshot.png",
            expected="Element should be clickable",
            actual="Element not found in DOM",
        )
        assert failure.test_id == "TC001"
        assert failure.failed_step == 3
        assert failure.selector == "#login-button"

    def test_create_failure_analysis(self):
        """Match the analysis contract from the requirements."""
        analysis = FailureAnalysis(
            failure_type=FailureType.ELEMENT_NOT_FOUND,
            root_cause="The original selector no longer identifies the intended element.",
            healable=True,
            confidence=0.94,
        )
        assert analysis.failure_type == FailureType.ELEMENT_NOT_FOUND
        assert analysis.healable is True
        assert analysis.confidence == 0.94

    def test_confidence_bounds(self):
        """Confidence must be between 0.0 and 1.0."""
        with pytest.raises(Exception):
            FailureAnalysis(
                failure_type=FailureType.UNKNOWN,
                root_cause="test",
                healable=False,
                confidence=1.5,  # Invalid: > 1.0
            )

        with pytest.raises(Exception):
            FailureAnalysis(
                failure_type=FailureType.UNKNOWN,
                root_cause="test",
                healable=False,
                confidence=-0.1,  # Invalid: < 0.0
            )


# ── Healer Schema Tests ────────────────────────────────────


class TestHealerSchemas:
    """Validate Self-Healing Agent data contracts."""

    def test_create_healing_candidate(self):
        """Match the healing contract from the requirements."""
        candidate = HealingCandidate(
            test_id="TC001",
            failed_step=3,
            healing_attempted=True,
            old_selector="#login-button",
            new_selector="#signin-btn",
            confidence=0.94,
            reason="The candidate has matching semantic purpose and similar DOM context.",
            requires_validation=True,
        )
        assert candidate.healing_attempted is True
        assert candidate.new_selector == "#signin-btn"
        assert candidate.confidence == 0.94
        assert candidate.requires_validation is True
        assert candidate.status == HealingStatus.PROPOSED

    def test_no_safe_healing_found(self):
        candidate = HealingCandidate(
            test_id="TC001",
            failed_step=3,
            healing_attempted=True,
            old_selector="#login-button",
            new_selector="",
            confidence=0.0,
            reason="No suitable replacement found in DOM",
            status=HealingStatus.NO_SAFE_HEALING_FOUND,
        )
        assert candidate.status == HealingStatus.NO_SAFE_HEALING_FOUND
        assert candidate.new_selector == ""

    def test_healing_result(self):
        result = HealingResult(
            test_id="TC001",
            failed_step=3,
            old_selector="#login-button",
            new_selector="#signin-btn",
            status=HealingStatus.VALIDATED_SUCCESS,
            confidence=0.94,
            validated_by="execution_engine",
        )
        assert result.status == HealingStatus.VALIDATED_SUCCESS
        assert result.validated_by == "execution_engine"

    def test_healing_result_serialization(self):
        result = HealingResult(
            test_id="TC001",
            failed_step=3,
            old_selector="#x",
            new_selector="#y",
            status=HealingStatus.VALIDATED_FAILURE,
            confidence=0.5,
            validation_error="Element found but not interactable",
        )
        data = json.loads(result.model_dump_json())
        result2 = HealingResult.model_validate(data)
        assert result2.validation_error == "Element found but not interactable"
