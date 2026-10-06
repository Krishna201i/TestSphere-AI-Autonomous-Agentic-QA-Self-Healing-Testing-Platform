"""TestSphere-AI — Test Planner subpackage."""

from agents.planner.planner import (
    LangChainTestPlanner,
    LLMTestPlanner,
    TestPlannerAgent,
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
from agents.planner.validation import (
    TestPlanValidationError,
    detect_duplicate_test_cases,
    validate_application_context,
    validate_assertion,
    validate_element_references,
    validate_test_case,
    validate_test_plan,
    validate_test_step,
)

# Day 7 — LangChain integration components
from agents.planner.langchain_adapter import LangChainPlanningAdapter
from agents.planner.langchain_prompts import TestPlannerPromptTemplate
from agents.planner.structured_output import (
    StructuredOutputError,
    StructuredOutputProcessor,
)

__all__ = [
    # Agent classes
    "TestPlannerAgent",
    "LLMTestPlanner",
    "LangChainTestPlanner",
    # LangChain integration (Day 7)
    "LangChainPlanningAdapter",
    "TestPlannerPromptTemplate",
    "StructuredOutputProcessor",
    "StructuredOutputError",
    # Input schemas
    "ApplicationContext",
    "PageContext",
    "PageInfo",
    "ElementContext",
    # Output schemas
    "TestCase",
    "TestStep",
    "Assertion",
    "TestPlan",
    # Validation
    "TestPlanValidationError",
    "validate_test_step",
    "validate_test_case",
    "validate_test_plan",
    "validate_application_context",
    "validate_assertion",
    "validate_element_references",
    "detect_duplicate_test_cases",
]
