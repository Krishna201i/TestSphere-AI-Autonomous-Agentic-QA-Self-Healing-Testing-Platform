"""
TestSphere-AI — Test Planner Schemas

Data contracts for the Test Planner Agent's inputs and outputs.
These schemas define how application context flows in and how
generated test cases flow out to Member 2's execution engine.

Day 4 enhancements:
  - ElementContext — rich element description for DOM elements
  - PageContext — extended page info with elements, forms, nav
  - Enhanced TestStep — controlled actions, target alias, timeout
  - Enhanced Assertion — controlled assertion types
  - Enhanced TestCase — page_url, preconditions, tags, reasoning
  - TestPlan — top-level wrapper for generated test plans
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field

from agents.schemas.enums import (
    AssertionType,
    TestAction,
    TestCategory,
    TestPriority,
)


# ── Element Context ────────────────────────────────────────────


class ElementContext(BaseModel):
    """Describes a single DOM element on a page.

    This schema acts as a clean communication contract between
    Member 2's DOM extraction and Member 1's test generation.
    All fields except ``tag`` are optional — the available detail
    depends on what Member 2 can extract.
    """

    tag: str = Field(..., description="HTML tag name (e.g. 'input', 'button', 'a')")
    id: Optional[str] = Field(default=None, description="Element 'id' attribute")
    name: Optional[str] = Field(default=None, description="Element 'name' attribute")
    type: Optional[str] = Field(
        default=None, description="Element 'type' attribute (e.g. 'email', 'password')"
    )
    role: Optional[str] = Field(
        default=None, description="ARIA role attribute"
    )
    text: Optional[str] = Field(
        default=None, description="Visible text content of the element"
    )
    placeholder: Optional[str] = Field(
        default=None, description="Placeholder text for inputs"
    )
    classes: list[str] = Field(
        default_factory=list, description="CSS class names on the element"
    )
    attributes: dict[str, str] = Field(
        default_factory=dict,
        description="Additional HTML attributes (data-testid, aria-label, etc.)",
    )
    selector: Optional[str] = Field(
        default=None,
        description="CSS selector that uniquely identifies this element (when available)",
    )
    visible: Optional[bool] = Field(
        default=None, description="Whether the element is visible (when available)"
    )
    interactable: Optional[bool] = Field(
        default=None,
        description="Whether the element can be interacted with (when available)",
    )


# ── Page Context ───────────────────────────────────────────────


class PageContext(BaseModel):
    """Describes a single page or route in the application.

    Extends the Day 1 ``PageInfo`` with element-level detail,
    form groupings, and navigation elements.
    """

    url: str = Field(..., description="Relative URL path (e.g. '/login')")
    name: str = Field(default="", description="Human-readable page name")
    title: str = Field(default="", description="HTML page title")
    description: str = Field(default="", description="What this page does")
    elements: list[ElementContext] = Field(
        default_factory=list,
        description="DOM elements on this page",
    )
    forms: list[str] = Field(
        default_factory=list,
        description="Names or identifiers of forms on this page",
    )
    navigation_elements: list[str] = Field(
        default_factory=list,
        description="Navigation links/buttons on this page",
    )


# Backward-compatible alias — Day 1 code uses ``PageInfo``
PageInfo = PageContext


# ── Application Context (Input) ───────────────────────────────


class ApplicationContext(BaseModel):
    """Describes the application under test.

    Provided as input to the Test Planner Agent so it can reason
    about what tests to generate.
    """

    app_name: str = Field(..., description="Name of the application under test")
    app_url: str = Field(..., description="Base URL of the application")
    description: str = Field(
        default="", description="High-level description of app functionality"
    )
    pages: list[PageContext] = Field(
        default_factory=list, description="Known pages/routes in the application"
    )
    technology_stack: list[str] = Field(
        default_factory=list, description="Technologies the app is built with"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional application metadata",
    )


# ── Assertion (Output) ────────────────────────────────────────


class Assertion(BaseModel):
    """A single assertion within a test case.

    Defines what should be verified after steps execute.
    The ``type`` must be a value from the ``AssertionType`` enum.
    """

    type: AssertionType = Field(
        ...,
        description="Assertion type from the controlled vocabulary",
    )
    target: str = Field(
        default="", description="Selector or identifier to assert against"
    )
    expected: str = Field(default="", description="Expected value")
    description: str = Field(
        default="", description="Human-readable description of the assertion"
    )


# ── Test Step (Output) ────────────────────────────────────────


class TestStep(BaseModel):
    """A single step within a test case.

    Represents an atomic action (click, fill, navigate, etc.)
    that Member 2's execution engine will perform.
    The ``action`` must be a value from the ``TestAction`` enum.
    """

    step_number: int = Field(..., description="1-based step order", ge=1)
    action: TestAction = Field(
        ...,
        description="Action to perform from the controlled vocabulary",
    )
    target: Optional[str] = Field(
        default=None, description="CSS/XPath selector for the target element"
    )
    value: Optional[str] = Field(
        default=None, description="Value for input actions (e.g. text to type, URL)"
    )
    description: str = Field(
        default="", description="Human-readable description of this step"
    )
    assertions: list[Assertion] = Field(
        default_factory=list,
        description="Assertions to verify after this step completes",
    )
    timeout: Optional[int] = Field(
        default=None,
        description="Step-level timeout override in milliseconds",
        ge=0,
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional step metadata",
    )

    # Backward-compatible property — Day 1 tests use ``selector``
    @property
    def selector(self) -> Optional[str]:
        """Alias for ``target`` (backward compatibility)."""
        return self.target


# ── Test Case (Output) ────────────────────────────────────────


class TestCase(BaseModel):
    """A generated test case.

    Produced by the Test Planner Agent and consumed by
    Member 2's execution engine.

    This is a core inter-member contract.
    """

    test_id: str = Field(..., description="Unique test identifier, e.g. 'TC_LOGIN_001'")
    name: str = Field(..., description="Short descriptive test name")
    description: str = Field(
        default="", description="What this test verifies"
    )
    category: TestCategory = Field(
        default=TestCategory.FUNCTIONAL, description="Test category"
    )
    priority: TestPriority = Field(
        default=TestPriority.MEDIUM, description="Test priority"
    )
    steps: list[TestStep] = Field(
        default_factory=list, description="Ordered list of test steps"
    )
    assertions: list[Assertion] = Field(
        default_factory=list,
        description="Top-level assertions for the entire test case",
    )
    page_url: Optional[str] = Field(
        default=None, description="Primary page URL for this test"
    )
    preconditions: list[str] = Field(
        default_factory=list,
        description="Preconditions that must be met before running this test",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Tags for filtering and grouping (e.g. 'login', 'critical')",
    )
    generated_reasoning: Optional[str] = Field(
        default=None,
        description="Brief reasoning for why this test was generated (metadata only)",
    )


# ── Test Plan (Output) ────────────────────────────────────────


class TestPlan(BaseModel):
    """A complete test plan produced by the Test Planner Agent.

    Wraps a list of ``TestCase`` objects with application metadata
    and generation context.
    """

    application_name: str = Field(
        ..., description="Name of the application under test"
    )
    base_url: str = Field(
        default="", description="Base URL of the application"
    )
    generated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO 8601 timestamp of when the plan was generated",
    )
    test_cases: list[TestCase] = Field(
        default_factory=list, description="Generated test cases"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional generation metadata",
    )


# Pydantic v2: rebuild models that have forward references
ApplicationContext.model_rebuild()
