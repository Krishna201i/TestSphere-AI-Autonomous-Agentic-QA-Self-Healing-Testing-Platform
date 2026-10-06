"""
TestSphere-AI — Test Planner Prompt Architecture

Reusable prompt components for the Test Planner Agent.
These templates instruct the LLM to generate structured,
schema-compliant test plans from application context.

The actual prompt assembly and LLM invocation belongs to Day 5.
Day 4 defines the building blocks.

Usage::

    from agents.planner.prompts import build_test_generation_prompt

    prompt = build_test_generation_prompt(application_context)
"""

from __future__ import annotations

import json

from agents.planner.schemas import ApplicationContext
from agents.schemas.enums import AssertionType, TestAction, TestCategory, TestPriority


# ── System Prompt ────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are a senior QA engineer and test planner for a web application.
Your task is to analyze the provided application context and generate
a structured, executable test plan.

RULES — you MUST follow every rule below:

1. ONLY use information from the provided application context.
2. NEVER invent application elements, pages, or selectors that are
   not present in the context.
3. NEVER invent selectors without evidence from the provided elements.
4. Generate structured test cases that match the required JSON schema.
5. Use ONLY supported actions from the action vocabulary.
6. Use ONLY supported assertion types from the assertion vocabulary.
7. Use ONLY supported test categories and priority levels.
8. Avoid generating duplicate or redundant tests.
9. Focus on meaningful user workflows — not trivial or contrived tests.
10. Return output as a single valid JSON object matching the TestPlan schema.
11. Do NOT generate arbitrary executable code.
12. Do NOT include internal chain-of-thought or private reasoning in output.
"""

# ── Action Vocabulary ────────────────────────────────────────

ACTION_VOCABULARY = """\
SUPPORTED ACTIONS (use only these):

| Action   | Description                           | Target Required | Value Required |
|----------|---------------------------------------|-----------------|----------------|
| navigate | Navigate to a URL                     | No              | Yes (URL)      |
| click    | Click an element                      | Yes             | No             |
| fill     | Type text into an input field         | Yes             | Yes (text)     |
| select   | Select an option from a dropdown      | Yes             | Yes (option)   |
| check    | Check a checkbox                      | Yes             | No             |
| uncheck  | Uncheck a checkbox                    | Yes             | No             |
| press    | Press a keyboard key                  | No              | Yes (key name) |
| wait     | Wait for a condition or fixed time    | No              | No             |
"""

# ── Assertion Vocabulary ─────────────────────────────────────

ASSERTION_VOCABULARY = """\
SUPPORTED ASSERTION TYPES (use only these):

| Type                 | Description                                      | Target Required | Expected Required |
|----------------------|--------------------------------------------------|-----------------|-------------------|
| element_visible      | Verify an element is visible on the page         | Yes             | No                |
| element_not_visible  | Verify an element is NOT visible on the page     | Yes             | No                |
| element_contains_text| Verify an element contains the expected text     | Yes             | Yes               |
| element_has_text     | Verify an element has exactly the expected text  | Yes             | Yes               |
| url_contains         | Verify the current URL contains a substring      | No              | Yes               |
| url_equals           | Verify the current URL matches exactly            | No              | Yes               |
| value_equals         | Verify an input element's value matches           | Yes             | Yes               |
"""

# ── Category Definitions ────────────────────────────────────

CATEGORY_DEFINITIONS = """\
TEST CATEGORIES (assign the most appropriate category):

| Category    | Meaning                                                  |
|-------------|----------------------------------------------------------|
| functional  | Tests expected normal user workflows                     |
| negative    | Tests invalid or incorrect input/workflows               |
| boundary    | Tests minimum, maximum, empty, or edge-case values       |
| smoke       | Quick sanity checks that core features work              |
| regression  | Tests verifying previously working functionality         |
| edge_case   | Tests for unusual or extreme conditions                  |
| accessibility | Tests verifying accessibility compliance               |
"""

# ── Priority Definitions ────────────────────────────────────

PRIORITY_DEFINITIONS = """\
PRIORITY LEVELS (assign the most appropriate priority):

| Priority | Meaning                                                         |
|----------|-----------------------------------------------------------------|
| CRITICAL | System-critical functionality whose failure blocks all usage    |
| HIGH     | Critical user workflows — login, signup, payment, checkout      |
| MEDIUM   | Important but not immediately business-critical functionality   |
| LOW      | Minor or low-impact functionality                               |
"""

# ── Output Schema Instruction ───────────────────────────────

OUTPUT_SCHEMA_INSTRUCTION = """\
OUTPUT FORMAT — respond with a single JSON object:

{
    "application_name": "<name from context>",
    "base_url": "<url from context>",
    "test_cases": [
        {
            "test_id": "TC_<PAGE>_<NNN>",
            "name": "<short descriptive name>",
            "description": "<what this test verifies>",
            "category": "<category from vocabulary>",
            "priority": "<priority from vocabulary>",
            "page_url": "<page URL if applicable>",
            "preconditions": ["<precondition>"],
            "tags": ["<tag>"],
            "steps": [
                {
                    "step_number": 1,
                    "action": "<action from vocabulary>",
                    "target": "<CSS selector or null>",
                    "value": "<value or null>",
                    "description": "<what this step does>"
                }
            ],
            "assertions": [
                {
                    "type": "<assertion type from vocabulary>",
                    "target": "<selector or empty>",
                    "expected": "<expected value or empty>",
                    "description": "<what is being verified>"
                }
            ]
        }
    ]
}

IMPORTANT: Return ONLY the JSON object.  No markdown, no code fences, no explanation.
"""


# ── Prompt Builder ───────────────────────────────────────────


def _serialize_context(context: ApplicationContext) -> str:
    """Serialize an ApplicationContext to a readable JSON string for the prompt."""
    return json.dumps(context.model_dump(mode="json"), indent=2)


def build_test_generation_prompt(
    context: ApplicationContext,
    *,
    max_tests: int = 10,
) -> str:
    """Assemble the complete test generation prompt from components.

    This function combines the action vocabulary, assertion vocabulary,
    category definitions, priority definitions, output schema, and the
    serialized application context into a single user prompt.

    The system prompt (``SYSTEM_PROMPT``) should be sent separately
    via the ``system_instruction`` field on ``LLMRequest``.

    Parameters
    ----------
    context:
        The application context to generate tests for.
    max_tests:
        Maximum number of test cases to generate.

    Returns
    -------
    str
        The assembled user prompt string.
    """
    context_json = _serialize_context(context)

    prompt_parts = [
        f"Generate up to {max_tests} test cases for the following application.\n",
        "--- APPLICATION CONTEXT ---\n",
        context_json,
        "\n--- INSTRUCTIONS ---\n",
        ACTION_VOCABULARY,
        ASSERTION_VOCABULARY,
        CATEGORY_DEFINITIONS,
        PRIORITY_DEFINITIONS,
        OUTPUT_SCHEMA_INSTRUCTION,
    ]

    return "\n".join(prompt_parts)
