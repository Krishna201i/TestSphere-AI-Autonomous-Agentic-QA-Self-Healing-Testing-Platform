"""
TestSphere-AI — Test Planner Schemas

Data contracts for the Test Planner Agent's inputs and outputs.
These schemas define how application context flows in and how
generated test cases flow out to Member 2's execution engine.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from agents.schemas.enums import TestCategory, TestPriority


# ── Inputs ──────────────────────────────────────────────────


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
    pages: list[PageInfo] = Field(
        default_factory=list, description="Known pages/routes in the application"
    )
    technology_stack: list[str] = Field(
        default_factory=list, description="Technologies the app is built with"
    )


class PageInfo(BaseModel):
    """Describes a single page or route in the application."""

    url: str = Field(..., description="Relative URL path")
    name: str = Field(default="", description="Human-readable page name")
    description: str = Field(default="", description="What this page does")


# ── Outputs ─────────────────────────────────────────────────


class Assertion(BaseModel):
    """A single assertion within a test step.

    Defines what should be verified after a step executes.
    """

    type: str = Field(
        ...,
        description="Assertion type, e.g. 'visible', 'text_equals', 'url_contains'",
    )
    target: str = Field(
        default="", description="Selector or value to assert against"
    )
    expected: str = Field(default="", description="Expected value")
    description: str = Field(
        default="", description="Human-readable description of the assertion"
    )


class TestStep(BaseModel):
    """A single step within a test case.

    Represents an atomic action (click, type, navigate, etc.)
    that Member 2's execution engine will perform.
    """

    step_number: int = Field(..., description="1-based step order")
    action: str = Field(
        ...,
        description="Action to perform: 'navigate', 'click', 'type', 'select', 'wait', 'assert'",
    )
    selector: Optional[str] = Field(
        default=None, description="CSS/XPath selector for the target element"
    )
    value: Optional[str] = Field(
        default=None, description="Value for input actions (e.g. text to type)"
    )
    description: str = Field(
        default="", description="Human-readable description of this step"
    )
    assertions: list[Assertion] = Field(
        default_factory=list,
        description="Assertions to verify after this step completes",
    )


class TestCase(BaseModel):
    """A generated test case.

    Produced by the Test Planner Agent and consumed by
    Member 2's execution engine.

    This is a core inter-member contract.
    """

    test_id: str = Field(..., description="Unique test identifier, e.g. 'TC001'")
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


# Pydantic v2: rebuild models that have forward references
ApplicationContext.model_rebuild()
