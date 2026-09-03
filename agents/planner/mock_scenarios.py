"""
TestSphere-AI — Test Planner Mock Scenarios

Deterministic JSON fixtures for the ``MockLLMProvider`` response registry.
These mock responses represent the kinds of output the Test Planner Agent
will receive from the LLM on Day 5+.

Each scenario is a plain string (JSON or malformed text) suitable for
``MockLLMProvider.register_response()``.

Usage::

    from agents.llm.providers.mock import MockLLMProvider
    from agents.planner.mock_scenarios import register_planner_scenarios

    provider = MockLLMProvider(config)
    register_planner_scenarios(provider)
"""

from __future__ import annotations

import json


# ── Sample Application Context ───────────────────────────────

SAMPLE_APPLICATION_CONTEXT: dict = {
    "app_name": "Demo Application",
    "app_url": "http://localhost:3000",
    "description": "A demo web application with login and dashboard.",
    "pages": [
        {
            "url": "/login",
            "name": "Login",
            "title": "Login",
            "description": "User authentication page",
            "elements": [
                {
                    "tag": "input",
                    "id": "email",
                    "name": "email",
                    "type": "email",
                    "placeholder": "Enter email",
                },
                {
                    "tag": "input",
                    "id": "password",
                    "name": "password",
                    "type": "password",
                    "placeholder": "Enter password",
                },
                {
                    "tag": "button",
                    "id": "login-button",
                    "text": "Login",
                },
            ],
        },
        {
            "url": "/dashboard",
            "name": "Dashboard",
            "title": "Dashboard",
            "description": "Main application dashboard",
            "elements": [
                {
                    "tag": "h1",
                    "id": "welcome-heading",
                    "text": "Welcome",
                },
                {
                    "tag": "button",
                    "id": "logout-button",
                    "text": "Logout",
                },
            ],
        },
    ],
    "technology_stack": ["React", "Node.js"],
}


# ── Scenario 1: Valid Structured Test Plan ────────────────────

VALID_TEST_PLAN_RESPONSE: str = json.dumps(
    {
        "application_name": "Demo Application",
        "base_url": "http://localhost:3000",
        "test_cases": [
            {
                "test_id": "TC_LOGIN_001",
                "name": "Valid Login",
                "description": "Verify that a user can log in with valid credentials.",
                "category": "functional",
                "priority": "HIGH",
                "page_url": "/login",
                "tags": ["login", "authentication"],
                "steps": [
                    {
                        "step_number": 1,
                        "action": "navigate",
                        "target": None,
                        "value": "http://localhost:3000/login",
                        "description": "Navigate to login page",
                    },
                    {
                        "step_number": 2,
                        "action": "fill",
                        "target": "#email",
                        "value": "test@example.com",
                        "description": "Enter email address",
                    },
                    {
                        "step_number": 3,
                        "action": "fill",
                        "target": "#password",
                        "value": "password123",
                        "description": "Enter password",
                    },
                    {
                        "step_number": 4,
                        "action": "click",
                        "target": "#login-button",
                        "value": None,
                        "description": "Click the login button",
                    },
                ],
                "assertions": [
                    {
                        "type": "url_contains",
                        "target": "",
                        "expected": "/dashboard",
                        "description": "Should redirect to dashboard",
                    },
                ],
            },
            {
                "test_id": "TC_LOGIN_002",
                "name": "Empty Email Login",
                "description": "Verify that login fails with empty email.",
                "category": "negative",
                "priority": "MEDIUM",
                "page_url": "/login",
                "tags": ["login", "negative"],
                "steps": [
                    {
                        "step_number": 1,
                        "action": "navigate",
                        "target": None,
                        "value": "http://localhost:3000/login",
                        "description": "Navigate to login page",
                    },
                    {
                        "step_number": 2,
                        "action": "fill",
                        "target": "#password",
                        "value": "password123",
                        "description": "Enter password without email",
                    },
                    {
                        "step_number": 3,
                        "action": "click",
                        "target": "#login-button",
                        "value": None,
                        "description": "Click the login button",
                    },
                ],
                "assertions": [
                    {
                        "type": "url_contains",
                        "target": "",
                        "expected": "/login",
                        "description": "Should remain on login page",
                    },
                ],
            },
        ],
    },
    indent=2,
)


# ── Scenario 2: Invalid / Malformed Response ─────────────────

INVALID_MALFORMED_RESPONSE: str = (
    '{"application_name": "Demo", "test_cases": [INVALID JSON HERE]}'
)


# ── Scenario 3: Empty Test Plan ──────────────────────────────

EMPTY_TEST_PLAN_RESPONSE: str = json.dumps(
    {
        "application_name": "Demo Application",
        "base_url": "http://localhost:3000",
        "test_cases": [],
    },
    indent=2,
)


# ── Scenario 4: Unsupported Action ──────────────────────────

UNSUPPORTED_ACTION_RESPONSE: str = json.dumps(
    {
        "application_name": "Demo Application",
        "base_url": "http://localhost:3000",
        "test_cases": [
            {
                "test_id": "TC_BAD_001",
                "name": "Bad Action Test",
                "description": "Contains an unsupported action.",
                "category": "functional",
                "priority": "LOW",
                "steps": [
                    {
                        "step_number": 1,
                        "action": "drag_and_drop",
                        "target": "#element",
                        "value": None,
                        "description": "Unsupported action",
                    },
                ],
                "assertions": [],
            },
        ],
    },
    indent=2,
)


# ── Scenario 5: Missing Required Field ──────────────────────

MISSING_REQUIRED_FIELD_RESPONSE: str = json.dumps(
    {
        "application_name": "Demo Application",
        "base_url": "http://localhost:3000",
        "test_cases": [
            {
                # Missing test_id and name
                "description": "A test case with missing required fields.",
                "category": "functional",
                "priority": "HIGH",
                "steps": [
                    {
                        "step_number": 1,
                        "action": "click",
                        "target": "#btn",
                        "description": "Click a button",
                    },
                ],
                "assertions": [],
            },
        ],
    },
    indent=2,
)


# ── Scenario 6: Invalid Category ────────────────────────────

INVALID_CATEGORY_RESPONSE: str = json.dumps(
    {
        "application_name": "Demo Application",
        "base_url": "http://localhost:3000",
        "test_cases": [
            {
                "test_id": "TC_CAT_001",
                "name": "Bad Category Test",
                "description": "Contains an invalid category.",
                "category": "performance",
                "priority": "HIGH",
                "steps": [
                    {
                        "step_number": 1,
                        "action": "click",
                        "target": "#btn",
                        "description": "Click a button",
                    },
                ],
                "assertions": [],
            },
        ],
    },
    indent=2,
)


# ── Scenario 7: Invalid Priority ────────────────────────────

INVALID_PRIORITY_RESPONSE: str = json.dumps(
    {
        "application_name": "Demo Application",
        "base_url": "http://localhost:3000",
        "test_cases": [
            {
                "test_id": "TC_PRI_001",
                "name": "Bad Priority Test",
                "description": "Contains an invalid priority.",
                "category": "functional",
                "priority": "URGENT",
                "steps": [
                    {
                        "step_number": 1,
                        "action": "click",
                        "target": "#btn",
                        "description": "Click a button",
                    },
                ],
                "assertions": [],
            },
        ],
    },
    indent=2,
)


# ── Scenario 8: Hallucinated Element References ─────────────

HALLUCINATED_ELEMENT_RESPONSE: str = json.dumps(
    {
        "application_name": "Demo Application",
        "base_url": "http://localhost:3000",
        "test_cases": [
            {
                "test_id": "TC_HALL_001",
                "name": "Hallucinated Element Test",
                "description": "References elements that do not exist in the context.",
                "category": "functional",
                "priority": "HIGH",
                "page_url": "/login",
                "steps": [
                    {
                        "step_number": 1,
                        "action": "navigate",
                        "target": None,
                        "value": "http://localhost:3000/login",
                        "description": "Navigate to login page",
                    },
                    {
                        "step_number": 2,
                        "action": "fill",
                        "target": "#username",
                        "value": "admin",
                        "description": "Enter username into non-existent field",
                    },
                    {
                        "step_number": 3,
                        "action": "click",
                        "target": "#submit-form",
                        "value": None,
                        "description": "Click a non-existent submit button",
                    },
                ],
                "assertions": [
                    {
                        "type": "url_contains",
                        "target": "",
                        "expected": "/dashboard",
                        "description": "Should redirect to dashboard",
                    },
                ],
            },
        ],
    },
    indent=2,
)


# ── Scenario 9: Duplicate Test Cases ────────────────────────

DUPLICATE_TEST_RESPONSE: str = json.dumps(
    {
        "application_name": "Demo Application",
        "base_url": "http://localhost:3000",
        "test_cases": [
            {
                "test_id": "TC_DUP_001",
                "name": "Valid Login",
                "description": "Verify valid login works.",
                "category": "functional",
                "priority": "HIGH",
                "page_url": "/login",
                "steps": [
                    {
                        "step_number": 1,
                        "action": "fill",
                        "target": "#email",
                        "value": "test@example.com",
                        "description": "Enter email",
                    },
                    {
                        "step_number": 2,
                        "action": "click",
                        "target": "#login-button",
                        "value": None,
                        "description": "Click login",
                    },
                ],
                "assertions": [],
            },
            {
                "test_id": "TC_DUP_002",
                "name": "Valid Login",
                "description": "Duplicate — same name, category, and action sequence.",
                "category": "functional",
                "priority": "HIGH",
                "page_url": "/login",
                "steps": [
                    {
                        "step_number": 1,
                        "action": "fill",
                        "target": "#email",
                        "value": "test@example.com",
                        "description": "Enter email",
                    },
                    {
                        "step_number": 2,
                        "action": "click",
                        "target": "#login-button",
                        "value": None,
                        "description": "Click login",
                    },
                ],
                "assertions": [],
            },
        ],
    },
    indent=2,
)


# ── Registration Helper ─────────────────────────────────────


def register_planner_scenarios(provider: object) -> None:
    """Register all planner mock scenarios on a ``MockLLMProvider``.

    Parameters
    ----------
    provider:
        A ``MockLLMProvider`` instance (typed as object to avoid
        circular imports).
    """
    # Import at call time to avoid circular dependency
    from agents.llm.providers.mock import MockLLMProvider

    if not isinstance(provider, MockLLMProvider):
        raise TypeError(
            f"Expected MockLLMProvider, got {type(provider).__name__}"
        )

    provider.register_response("generate test", VALID_TEST_PLAN_RESPONSE)
    provider.register_response("malformed", INVALID_MALFORMED_RESPONSE)
    provider.register_response("empty plan", EMPTY_TEST_PLAN_RESPONSE)
    provider.register_response("unsupported action", UNSUPPORTED_ACTION_RESPONSE)
    provider.register_response("missing field", MISSING_REQUIRED_FIELD_RESPONSE)
    provider.register_response("invalid category", INVALID_CATEGORY_RESPONSE)
    provider.register_response("invalid priority", INVALID_PRIORITY_RESPONSE)
    provider.register_response("hallucinated element", HALLUCINATED_ELEMENT_RESPONSE)
    provider.register_response("duplicate test", DUPLICATE_TEST_RESPONSE)
