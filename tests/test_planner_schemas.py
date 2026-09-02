"""
TestSphere-AI — Day 4: Test Planner Schema Tests

Comprehensive tests for the enhanced planner schemas:
  - ElementContext
  - PageContext / PageInfo
  - ApplicationContext
  - TestStep (with controlled actions)
  - Assertion (with controlled types)
  - TestCase (with optional fields)
  - TestPlan
"""

import json

import pytest

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
from agents.schemas.enums import (
    AssertionType,
    TestAction,
    TestCategory,
    TestPriority,
)


# ── ElementContext Tests ─────────────────────────────────────


class TestElementContextSchema:
    """Validate ElementContext schema."""

    def test_minimal_element(self):
        """Only tag is required."""
        el = ElementContext(tag="div")
        assert el.tag == "div"
        assert el.id is None
        assert el.name is None
        assert el.type is None
        assert el.role is None
        assert el.text is None
        assert el.placeholder is None
        assert el.classes == []
        assert el.attributes == {}
        assert el.selector is None
        assert el.visible is None
        assert el.interactable is None

    def test_full_element(self):
        el = ElementContext(
            tag="input",
            id="email",
            name="email",
            type="email",
            role="textbox",
            text="",
            placeholder="Enter email",
            classes=["form-control", "input-lg"],
            attributes={"data-testid": "email-input", "aria-label": "Email"},
            selector="#email",
            visible=True,
            interactable=True,
        )
        assert el.tag == "input"
        assert el.id == "email"
        assert el.type == "email"
        assert el.placeholder == "Enter email"
        assert "form-control" in el.classes
        assert el.attributes["data-testid"] == "email-input"
        assert el.visible is True
        assert el.interactable is True

    def test_element_serialization_roundtrip(self):
        el = ElementContext(
            tag="button",
            id="submit-btn",
            text="Submit",
            classes=["btn", "btn-primary"],
        )
        data = json.loads(el.model_dump_json())
        el2 = ElementContext.model_validate(data)
        assert el2.tag == "button"
        assert el2.id == "submit-btn"
        assert el2.text == "Submit"
        assert el2.classes == ["btn", "btn-primary"]

    def test_element_with_empty_tag_raises(self):
        """tag is required and cannot be omitted."""
        with pytest.raises(Exception):
            ElementContext()  # Missing required 'tag'


# ── PageContext Tests ────────────────────────────────────────


class TestPageContextSchema:
    """Validate PageContext schema."""

    def test_minimal_page(self):
        page = PageContext(url="/login")
        assert page.url == "/login"
        assert page.name == ""
        assert page.title == ""
        assert page.description == ""
        assert page.elements == []
        assert page.forms == []
        assert page.navigation_elements == []

    def test_page_with_elements(self):
        page = PageContext(
            url="/login",
            name="Login",
            title="Login Page",
            description="User authentication",
            elements=[
                ElementContext(tag="input", id="email", type="email"),
                ElementContext(tag="button", id="login-btn", text="Login"),
            ],
            forms=["login-form"],
            navigation_elements=["nav-home", "nav-about"],
        )
        assert len(page.elements) == 2
        assert page.elements[0].id == "email"
        assert page.forms == ["login-form"]

    def test_page_info_alias(self):
        """PageInfo should be the same class as PageContext."""
        assert PageInfo is PageContext
        page = PageInfo(url="/dashboard", name="Dashboard")
        assert isinstance(page, PageContext)

    def test_page_empty_elements_allowed(self):
        page = PageContext(url="/about", elements=[])
        assert page.elements == []

    def test_page_serialization_roundtrip(self):
        page = PageContext(
            url="/settings",
            name="Settings",
            elements=[
                ElementContext(tag="select", id="theme", name="theme"),
            ],
        )
        data = json.loads(page.model_dump_json())
        page2 = PageContext.model_validate(data)
        assert page2.url == "/settings"
        assert len(page2.elements) == 1
        assert page2.elements[0].id == "theme"


# ── ApplicationContext Tests ─────────────────────────────────


class TestApplicationContextSchema:
    """Validate ApplicationContext schema."""

    def test_minimal_context(self):
        ctx = ApplicationContext(
            app_name="TestApp",
            app_url="http://localhost:3000",
        )
        assert ctx.app_name == "TestApp"
        assert ctx.app_url == "http://localhost:3000"
        assert ctx.description == ""
        assert ctx.pages == []
        assert ctx.technology_stack == []
        assert ctx.metadata == {}

    def test_full_context(self):
        ctx = ApplicationContext(
            app_name="Demo App",
            app_url="http://localhost:3000",
            description="A demo application",
            pages=[
                PageContext(
                    url="/login",
                    name="Login",
                    elements=[ElementContext(tag="input", id="email")],
                ),
            ],
            technology_stack=["React", "Node.js"],
            metadata={"version": "1.0", "environment": "staging"},
        )
        assert len(ctx.pages) == 1
        assert ctx.metadata["version"] == "1.0"

    def test_empty_pages_allowed(self):
        ctx = ApplicationContext(
            app_name="App",
            app_url="http://localhost",
            pages=[],
        )
        assert ctx.pages == []

    def test_context_serialization_roundtrip(self):
        ctx = ApplicationContext(
            app_name="RoundtripApp",
            app_url="http://example.com",
            pages=[
                PageContext(
                    url="/home",
                    elements=[
                        ElementContext(tag="h1", text="Welcome"),
                    ],
                ),
            ],
        )
        data = json.loads(ctx.model_dump_json())
        ctx2 = ApplicationContext.model_validate(data)
        assert ctx2.app_name == "RoundtripApp"
        assert ctx2.pages[0].elements[0].text == "Welcome"


# ── TestStep Tests ───────────────────────────────────────────


class TestStepSchema:
    """Validate TestStep schema with controlled actions."""

    def test_valid_click(self):
        step = TestStep(
            step_number=1,
            action=TestAction.CLICK,
            target="#login-button",
        )
        assert step.step_number == 1
        assert step.action == TestAction.CLICK
        assert step.target == "#login-button"
        assert step.value is None

    def test_valid_fill(self):
        step = TestStep(
            step_number=2,
            action=TestAction.FILL,
            target="#email",
            value="test@example.com",
        )
        assert step.action == TestAction.FILL
        assert step.target == "#email"
        assert step.value == "test@example.com"

    def test_valid_navigate(self):
        step = TestStep(
            step_number=1,
            action=TestAction.NAVIGATE,
            value="http://localhost:3000/login",
        )
        assert step.action == TestAction.NAVIGATE
        assert step.target is None
        assert step.value == "http://localhost:3000/login"

    def test_valid_select(self):
        step = TestStep(
            step_number=1,
            action=TestAction.SELECT,
            target="#country",
            value="US",
        )
        assert step.action == TestAction.SELECT

    def test_valid_check(self):
        step = TestStep(
            step_number=1,
            action=TestAction.CHECK,
            target="#terms-checkbox",
        )
        assert step.action == TestAction.CHECK

    def test_valid_uncheck(self):
        step = TestStep(
            step_number=1,
            action=TestAction.UNCHECK,
            target="#newsletter",
        )
        assert step.action == TestAction.UNCHECK

    def test_valid_press(self):
        step = TestStep(
            step_number=1,
            action=TestAction.PRESS,
            value="Enter",
        )
        assert step.action == TestAction.PRESS

    def test_valid_wait(self):
        step = TestStep(
            step_number=1,
            action=TestAction.WAIT,
            description="Wait for page load",
        )
        assert step.action == TestAction.WAIT

    def test_unsupported_action_raises(self):
        """An action not in TestAction should raise a validation error."""
        with pytest.raises(Exception):
            TestStep(
                step_number=1,
                action="drag_and_drop",
                target="#element",
            )

    def test_step_with_timeout(self):
        step = TestStep(
            step_number=1,
            action=TestAction.CLICK,
            target="#btn",
            timeout=5000,
        )
        assert step.timeout == 5000

    def test_step_with_metadata(self):
        step = TestStep(
            step_number=1,
            action=TestAction.CLICK,
            target="#btn",
            metadata={"screenshot": True},
        )
        assert step.metadata["screenshot"] is True

    def test_step_number_must_be_positive(self):
        with pytest.raises(Exception):
            TestStep(
                step_number=0,
                action=TestAction.CLICK,
                target="#btn",
            )

    def test_backward_compatible_selector(self):
        step = TestStep(
            step_number=1,
            action=TestAction.CLICK,
            target="#my-btn",
        )
        assert step.selector == step.target

    def test_step_serialization_roundtrip(self):
        step = TestStep(
            step_number=1,
            action=TestAction.FILL,
            target="#email",
            value="user@test.com",
            description="Enter email",
        )
        data = json.loads(step.model_dump_json())
        step2 = TestStep.model_validate(data)
        assert step2.action == TestAction.FILL
        assert step2.value == "user@test.com"


# ── Assertion Tests ──────────────────────────────────────────


class TestAssertionSchema:
    """Validate Assertion schema with controlled types."""

    def test_valid_element_visible(self):
        a = Assertion(
            type=AssertionType.ELEMENT_VISIBLE,
            target="#welcome",
            description="Welcome heading should be visible",
        )
        assert a.type == AssertionType.ELEMENT_VISIBLE
        assert a.target == "#welcome"

    def test_valid_url_contains(self):
        a = Assertion(
            type=AssertionType.URL_CONTAINS,
            expected="/dashboard",
        )
        assert a.type == AssertionType.URL_CONTAINS
        assert a.expected == "/dashboard"

    def test_valid_element_has_text(self):
        a = Assertion(
            type=AssertionType.ELEMENT_HAS_TEXT,
            target="#title",
            expected="Welcome",
        )
        assert a.type == AssertionType.ELEMENT_HAS_TEXT

    def test_valid_value_equals(self):
        a = Assertion(
            type=AssertionType.VALUE_EQUALS,
            target="#email",
            expected="test@example.com",
        )
        assert a.type == AssertionType.VALUE_EQUALS

    def test_unsupported_assertion_type_raises(self):
        """A type not in AssertionType should raise."""
        with pytest.raises(Exception):
            Assertion(
                type="element_clickable",
                target="#btn",
            )

    def test_assertion_serialization_roundtrip(self):
        a = Assertion(
            type=AssertionType.URL_EQUALS,
            expected="http://localhost:3000/dashboard",
            description="Should be on dashboard",
        )
        data = json.loads(a.model_dump_json())
        a2 = Assertion.model_validate(data)
        assert a2.type == AssertionType.URL_EQUALS
        assert a2.expected == "http://localhost:3000/dashboard"


# ── TestCase Tests ───────────────────────────────────────────


class TestCaseSchema:
    """Validate TestCase schema with all Day 4 enhancements."""

    def test_valid_full_test_case(self):
        tc = TestCase(
            test_id="TC_LOGIN_001",
            name="Valid Login",
            description="Verify that a user can log in.",
            category=TestCategory.FUNCTIONAL,
            priority=TestPriority.HIGH,
            page_url="/login",
            preconditions=["User account exists"],
            tags=["login", "authentication"],
            steps=[
                TestStep(
                    step_number=1,
                    action=TestAction.NAVIGATE,
                    value="http://localhost:3000/login",
                ),
                TestStep(
                    step_number=2,
                    action=TestAction.FILL,
                    target="#email",
                    value="test@example.com",
                ),
                TestStep(
                    step_number=3,
                    action=TestAction.CLICK,
                    target="#login-button",
                ),
            ],
            assertions=[
                Assertion(
                    type=AssertionType.URL_CONTAINS,
                    expected="/dashboard",
                ),
            ],
        )
        assert tc.test_id == "TC_LOGIN_001"
        assert tc.page_url == "/login"
        assert tc.preconditions == ["User account exists"]
        assert tc.tags == ["login", "authentication"]
        assert len(tc.steps) == 3
        assert len(tc.assertions) == 1

    def test_minimal_test_case(self):
        tc = TestCase(test_id="TC001", name="Minimal")
        assert tc.description == ""
        assert tc.category == TestCategory.FUNCTIONAL
        assert tc.priority == TestPriority.MEDIUM
        assert tc.page_url is None
        assert tc.preconditions == []
        assert tc.tags == []
        assert tc.generated_reasoning is None

    def test_missing_test_id_raises(self):
        with pytest.raises(Exception):
            TestCase(name="No ID")

    def test_missing_name_raises(self):
        with pytest.raises(Exception):
            TestCase(test_id="TC001")

    def test_invalid_category_raises(self):
        with pytest.raises(Exception):
            TestCase(
                test_id="TC001",
                name="Bad Category",
                category="performance",
            )

    def test_invalid_priority_raises(self):
        with pytest.raises(Exception):
            TestCase(
                test_id="TC001",
                name="Bad Priority",
                priority="URGENT",
            )

    def test_negative_category(self):
        tc = TestCase(
            test_id="TC001",
            name="Negative Test",
            category=TestCategory.NEGATIVE,
        )
        assert tc.category == TestCategory.NEGATIVE

    def test_boundary_category(self):
        tc = TestCase(
            test_id="TC001",
            name="Boundary Test",
            category=TestCategory.BOUNDARY,
        )
        assert tc.category == TestCategory.BOUNDARY

    def test_generated_reasoning_optional(self):
        tc = TestCase(
            test_id="TC001",
            name="With Reasoning",
            generated_reasoning="Login is critical user workflow.",
        )
        assert tc.generated_reasoning == "Login is critical user workflow."

    def test_test_case_serialization_roundtrip(self):
        tc = TestCase(
            test_id="TC_ROUND_001",
            name="Roundtrip Test",
            category=TestCategory.NEGATIVE,
            priority=TestPriority.LOW,
            tags=["test"],
            steps=[
                TestStep(
                    step_number=1,
                    action=TestAction.CLICK,
                    target="#btn",
                ),
            ],
            assertions=[
                Assertion(
                    type=AssertionType.ELEMENT_VISIBLE,
                    target="#result",
                ),
            ],
        )
        data = json.loads(tc.model_dump_json())
        tc2 = TestCase.model_validate(data)
        assert tc2.test_id == "TC_ROUND_001"
        assert tc2.category == TestCategory.NEGATIVE
        assert tc2.tags == ["test"]


# ── TestPlan Tests ───────────────────────────────────────────


class TestPlanSchema:
    """Validate TestPlan schema."""

    def test_valid_plan(self):
        plan = TestPlan(
            application_name="Demo App",
            base_url="http://localhost:3000",
            test_cases=[
                TestCase(
                    test_id="TC001",
                    name="Login Test",
                    steps=[
                        TestStep(
                            step_number=1,
                            action=TestAction.CLICK,
                            target="#btn",
                        ),
                    ],
                ),
            ],
        )
        assert plan.application_name == "Demo App"
        assert len(plan.test_cases) == 1
        assert plan.generated_at  # Should be auto-populated

    def test_empty_plan(self):
        plan = TestPlan(
            application_name="Empty App",
            test_cases=[],
        )
        assert plan.test_cases == []

    def test_plan_with_metadata(self):
        plan = TestPlan(
            application_name="App",
            metadata={"generator": "LLMTestPlanner", "version": "0.1"},
        )
        assert plan.metadata["generator"] == "LLMTestPlanner"

    def test_plan_serialization_roundtrip(self):
        plan = TestPlan(
            application_name="Roundtrip App",
            base_url="http://example.com",
            test_cases=[
                TestCase(
                    test_id="TC001",
                    name="Test",
                    steps=[
                        TestStep(
                            step_number=1,
                            action=TestAction.WAIT,
                        ),
                    ],
                ),
            ],
        )
        data = json.loads(plan.model_dump_json())
        plan2 = TestPlan.model_validate(data)
        assert plan2.application_name == "Roundtrip App"
        assert len(plan2.test_cases) == 1
