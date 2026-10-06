"""
TestSphere-AI — Day 4: Test Planner Validation Tests

Tests for the business-rule validation layer that goes beyond
Pydantic schema constraints.
"""

import pytest

from agents.planner.schemas import (
    ApplicationContext,
    Assertion,
    TestCase,
    TestPlan,
    TestStep,
)
from agents.planner.validation import (
    ACTION_REQUIREMENTS,
    ASSERTIONS_REQUIRING_EXPECTED,
    ASSERTIONS_REQUIRING_TARGET,
    TestPlanValidationError,
    validate_application_context,
    validate_assertion,
    validate_test_case,
    validate_test_plan,
    validate_test_step,
)
from agents.schemas.enums import (
    AssertionType,
    TestAction,
    TestCategory,
    TestPriority,
)


# ── Action Requirements Tests ────────────────────────────────


class TestActionRequirements:
    """Validate the ACTION_REQUIREMENTS mapping."""

    def test_all_actions_have_requirements(self):
        """Every TestAction must have a requirements entry."""
        for action in TestAction:
            assert action in ACTION_REQUIREMENTS, (
                f"Missing requirements for action: {action}"
            )

    def test_navigate_requires_value_not_target(self):
        target_req, value_req = ACTION_REQUIREMENTS[TestAction.NAVIGATE]
        assert target_req is False
        assert value_req is True

    def test_click_requires_target_not_value(self):
        target_req, value_req = ACTION_REQUIREMENTS[TestAction.CLICK]
        assert target_req is True
        assert value_req is False

    def test_fill_requires_both(self):
        target_req, value_req = ACTION_REQUIREMENTS[TestAction.FILL]
        assert target_req is True
        assert value_req is True

    def test_select_requires_both(self):
        target_req, value_req = ACTION_REQUIREMENTS[TestAction.SELECT]
        assert target_req is True
        assert value_req is True

    def test_check_requires_target_only(self):
        target_req, value_req = ACTION_REQUIREMENTS[TestAction.CHECK]
        assert target_req is True
        assert value_req is False

    def test_uncheck_requires_target_only(self):
        target_req, value_req = ACTION_REQUIREMENTS[TestAction.UNCHECK]
        assert target_req is True
        assert value_req is False

    def test_press_requires_value_only(self):
        target_req, value_req = ACTION_REQUIREMENTS[TestAction.PRESS]
        assert target_req is False
        assert value_req is True

    def test_wait_requires_nothing(self):
        target_req, value_req = ACTION_REQUIREMENTS[TestAction.WAIT]
        assert target_req is False
        assert value_req is False


# ── Assertion Validation Tests ───────────────────────────────


class TestAssertionValidation:
    """Validate assertion business rules."""

    def test_valid_element_visible(self):
        a = Assertion(
            type=AssertionType.ELEMENT_VISIBLE,
            target="#heading",
        )
        errors = validate_assertion(a)
        assert errors == []

    def test_element_visible_missing_target(self):
        a = Assertion(
            type=AssertionType.ELEMENT_VISIBLE,
            target="",
        )
        errors = validate_assertion(a)
        assert any("target" in e.lower() for e in errors)

    def test_url_contains_valid(self):
        a = Assertion(
            type=AssertionType.URL_CONTAINS,
            expected="/dashboard",
        )
        errors = validate_assertion(a)
        assert errors == []

    def test_url_contains_missing_expected(self):
        a = Assertion(
            type=AssertionType.URL_CONTAINS,
            expected="",
        )
        errors = validate_assertion(a)
        assert any("expected" in e.lower() for e in errors)

    def test_element_has_text_requires_both(self):
        a = Assertion(
            type=AssertionType.ELEMENT_HAS_TEXT,
            target="",
            expected="",
        )
        errors = validate_assertion(a)
        assert len(errors) == 2  # Missing target AND expected

    def test_element_not_visible_no_expected_needed(self):
        a = Assertion(
            type=AssertionType.ELEMENT_NOT_VISIBLE,
            target="#modal",
        )
        errors = validate_assertion(a)
        assert errors == []

    def test_value_equals_requires_both(self):
        a = Assertion(
            type=AssertionType.VALUE_EQUALS,
            target="#input",
            expected="hello",
        )
        errors = validate_assertion(a)
        assert errors == []


# ── Step Validation Tests ────────────────────────────────────


class TestStepValidation:
    """Validate test step business rules."""

    def test_valid_click_step(self):
        step = TestStep(
            step_number=1,
            action=TestAction.CLICK,
            target="#button",
        )
        errors = validate_test_step(step)
        assert errors == []

    def test_valid_fill_step(self):
        step = TestStep(
            step_number=1,
            action=TestAction.FILL,
            target="#email",
            value="test@test.com",
        )
        errors = validate_test_step(step)
        assert errors == []

    def test_click_missing_target(self):
        step = TestStep(
            step_number=1,
            action=TestAction.CLICK,
            target=None,
        )
        errors = validate_test_step(step)
        assert any("target" in e.lower() for e in errors)

    def test_fill_missing_value(self):
        step = TestStep(
            step_number=1,
            action=TestAction.FILL,
            target="#email",
            value=None,
        )
        errors = validate_test_step(step)
        assert any("value" in e.lower() for e in errors)

    def test_fill_missing_target(self):
        step = TestStep(
            step_number=1,
            action=TestAction.FILL,
            target=None,
            value="text",
        )
        errors = validate_test_step(step)
        assert any("target" in e.lower() for e in errors)

    def test_navigate_valid(self):
        step = TestStep(
            step_number=1,
            action=TestAction.NAVIGATE,
            value="http://localhost:3000",
        )
        errors = validate_test_step(step)
        assert errors == []

    def test_navigate_missing_value(self):
        step = TestStep(
            step_number=1,
            action=TestAction.NAVIGATE,
            value=None,
        )
        errors = validate_test_step(step)
        assert any("value" in e.lower() for e in errors)

    def test_press_valid(self):
        step = TestStep(
            step_number=1,
            action=TestAction.PRESS,
            value="Enter",
        )
        errors = validate_test_step(step)
        assert errors == []

    def test_wait_valid_no_requirements(self):
        step = TestStep(
            step_number=1,
            action=TestAction.WAIT,
        )
        errors = validate_test_step(step)
        assert errors == []


# ── TestCase Validation Tests ────────────────────────────────


class TestCaseValidation:
    """Validate test case business rules."""

    def _make_valid_step(self, order: int = 1) -> TestStep:
        return TestStep(
            step_number=order,
            action=TestAction.CLICK,
            target="#btn",
        )

    def test_valid_test_case(self):
        tc = TestCase(
            test_id="TC001",
            name="Valid Test",
            steps=[self._make_valid_step()],
        )
        errors = validate_test_case(tc)
        assert errors == []

    def test_empty_test_id(self):
        tc = TestCase(
            test_id="",
            name="No ID",
            steps=[self._make_valid_step()],
        )
        errors = validate_test_case(tc)
        assert any("test_id" in e for e in errors)

    def test_whitespace_test_id(self):
        tc = TestCase(
            test_id="   ",
            name="Whitespace ID",
            steps=[self._make_valid_step()],
        )
        errors = validate_test_case(tc)
        assert any("test_id" in e for e in errors)

    def test_empty_name(self):
        tc = TestCase(
            test_id="TC001",
            name="",
            steps=[self._make_valid_step()],
        )
        errors = validate_test_case(tc)
        assert any("name" in e for e in errors)

    def test_no_steps(self):
        tc = TestCase(
            test_id="TC001",
            name="No Steps",
            steps=[],
        )
        errors = validate_test_case(tc)
        assert any("at least one step" in e for e in errors)

    def test_duplicate_step_orders(self):
        tc = TestCase(
            test_id="TC001",
            name="Dup Steps",
            steps=[
                self._make_valid_step(1),
                TestStep(
                    step_number=1,
                    action=TestAction.WAIT,
                ),
            ],
        )
        errors = validate_test_case(tc)
        assert any("Duplicate step_number" in e for e in errors)

    def test_invalid_step_propagates(self):
        """A step with invalid requirements should propagate errors."""
        tc = TestCase(
            test_id="TC001",
            name="Bad Step",
            steps=[
                TestStep(
                    step_number=1,
                    action=TestAction.CLICK,
                    target=None,  # Missing required target
                ),
            ],
        )
        errors = validate_test_case(tc)
        assert any("target" in e.lower() for e in errors)

    def test_valid_with_assertions(self):
        tc = TestCase(
            test_id="TC001",
            name="With Assertions",
            steps=[self._make_valid_step()],
            assertions=[
                Assertion(
                    type=AssertionType.URL_CONTAINS,
                    expected="/dashboard",
                ),
            ],
        )
        errors = validate_test_case(tc)
        assert errors == []

    def test_invalid_assertion_propagates(self):
        tc = TestCase(
            test_id="TC001",
            name="Bad Assertion",
            steps=[self._make_valid_step()],
            assertions=[
                Assertion(
                    type=AssertionType.URL_CONTAINS,
                    expected="",  # Missing required expected
                ),
            ],
        )
        errors = validate_test_case(tc)
        assert any("expected" in e.lower() for e in errors)


# ── TestPlan Validation Tests ────────────────────────────────


class TestPlanValidation:
    """Validate test plan business rules."""

    def _make_valid_case(self, test_id: str = "TC001") -> TestCase:
        return TestCase(
            test_id=test_id,
            name="Valid Test",
            steps=[
                TestStep(
                    step_number=1,
                    action=TestAction.CLICK,
                    target="#btn",
                ),
            ],
        )

    def test_valid_plan(self):
        plan = TestPlan(
            application_name="App",
            test_cases=[self._make_valid_case()],
        )
        errors = validate_test_plan(plan)
        assert errors == []

    def test_empty_application_name(self):
        plan = TestPlan(
            application_name="",
            test_cases=[self._make_valid_case()],
        )
        errors = validate_test_plan(plan)
        assert any("application_name" in e for e in errors)

    def test_duplicate_test_ids(self):
        plan = TestPlan(
            application_name="App",
            test_cases=[
                self._make_valid_case("TC001"),
                self._make_valid_case("TC001"),
            ],
        )
        errors = validate_test_plan(plan)
        assert any("Duplicate test_id" in e for e in errors)

    def test_empty_plan_valid(self):
        plan = TestPlan(
            application_name="App",
            test_cases=[],
        )
        errors = validate_test_plan(plan)
        assert errors == []

    def test_invalid_case_propagates(self):
        plan = TestPlan(
            application_name="App",
            test_cases=[
                TestCase(
                    test_id="TC001",
                    name="Bad",
                    steps=[],  # No steps
                ),
            ],
        )
        errors = validate_test_plan(plan)
        assert any("at least one step" in e for e in errors)


# ── ApplicationContext Validation Tests ──────────────────────


class TestApplicationContextValidation:
    """Validate application context business rules."""

    def test_valid_context(self):
        ctx = ApplicationContext(
            app_name="App",
            app_url="http://localhost:3000",
        )
        errors = validate_application_context(ctx)
        assert errors == []

    def test_empty_app_name(self):
        ctx = ApplicationContext(
            app_name="",
            app_url="http://localhost:3000",
        )
        errors = validate_application_context(ctx)
        assert any("app_name" in e for e in errors)

    def test_empty_app_url(self):
        ctx = ApplicationContext(
            app_name="App",
            app_url="",
        )
        errors = validate_application_context(ctx)
        assert any("app_url" in e for e in errors)

    def test_both_empty(self):
        ctx = ApplicationContext(
            app_name="",
            app_url="",
        )
        errors = validate_application_context(ctx)
        assert len(errors) == 2


# ── TestPlanValidationError Tests ────────────────────────────


class TestPlanValidationErrorClass:
    """Validate the custom exception class."""

    def test_error_message(self):
        err = TestPlanValidationError("Something went wrong")
        assert str(err) == "Something went wrong"

    def test_error_field(self):
        err = TestPlanValidationError("Bad value", field="test_id")
        assert err.field == "test_id"

    def test_error_default_field(self):
        err = TestPlanValidationError("No field")
        assert err.field == ""

    def test_error_is_exception(self):
        err = TestPlanValidationError("test")
        assert isinstance(err, Exception)
