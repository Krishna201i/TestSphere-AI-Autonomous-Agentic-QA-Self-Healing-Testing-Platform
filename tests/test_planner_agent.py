"""
TestSphere-AI — Day 4: Test Planner Agent Tests

Tests for the LLMTestPlanner skeleton:
  - Initialization with LLMClientSession
  - Input validation delegation
  - Output validation delegation
  - generate_tests raises NotImplementedError (Day 5)
  - Prompt building
  - Mock scenario registration
"""

import json

import pytest

from agents.llm.client import LLMClientSession
from agents.llm.config import LLMConfig
from agents.llm.providers.mock import MockLLMProvider
from agents.llm.factory import create_llm_client
from agents.planner.planner import LLMTestPlanner, TestPlannerAgent
from agents.planner.schemas import (
    ApplicationContext,
    Assertion,
    PageContext,
    ElementContext,
    TestCase,
    TestPlan,
    TestStep,
)
from agents.planner.validation import TestPlanValidationError
from agents.planner.prompts import (
    SYSTEM_PROMPT,
    ACTION_VOCABULARY,
    ASSERTION_VOCABULARY,
    CATEGORY_DEFINITIONS,
    PRIORITY_DEFINITIONS,
    OUTPUT_SCHEMA_INSTRUCTION,
    build_test_generation_prompt,
)
from agents.planner.mock_scenarios import (
    VALID_TEST_PLAN_RESPONSE,
    INVALID_MALFORMED_RESPONSE,
    EMPTY_TEST_PLAN_RESPONSE,
    UNSUPPORTED_ACTION_RESPONSE,
    MISSING_REQUIRED_FIELD_RESPONSE,
    INVALID_CATEGORY_RESPONSE,
    INVALID_PRIORITY_RESPONSE,
    SAMPLE_APPLICATION_CONTEXT,
    register_planner_scenarios,
)
from agents.schemas.enums import (
    AssertionType,
    TestAction,
    TestCategory,
    TestPriority,
)


# ── Fixtures ─────────────────────────────────────────────────


@pytest.fixture
def mock_config():
    """Return a mock LLM configuration."""
    return LLMConfig(provider="mock", model="mock-model")


@pytest.fixture
def mock_provider(mock_config):
    """Return a MockLLMProvider instance."""
    return MockLLMProvider(mock_config)


@pytest.fixture
def llm_session(mock_provider, mock_config):
    """Return an LLMClientSession wrapping the mock provider."""
    return LLMClientSession(mock_provider, mock_config)


@pytest.fixture
def planner(llm_session):
    """Return an LLMTestPlanner instance."""
    return LLMTestPlanner(llm_session)


@pytest.fixture
def sample_context():
    """Return a valid ApplicationContext for testing."""
    return ApplicationContext(
        app_name="Demo Application",
        app_url="http://localhost:3000",
        description="A demo app with login.",
        pages=[
            PageContext(
                url="/login",
                name="Login",
                title="Login Page",
                elements=[
                    ElementContext(tag="input", id="email", type="email"),
                    ElementContext(tag="input", id="password", type="password"),
                    ElementContext(tag="button", id="login-button", text="Login"),
                ],
            ),
        ],
    )


# ── Initialization Tests ─────────────────────────────────────


class TestLLMTestPlannerInit:
    """Validate LLMTestPlanner initialization."""

    def test_inherits_from_abstract(self, planner):
        assert isinstance(planner, TestPlannerAgent)

    def test_stores_llm_client(self, planner, llm_session):
        assert planner.llm_client is llm_session

    def test_provider_name(self, planner):
        assert planner.llm_client.provider_name == "mock"

    def test_create_via_factory(self, mock_config):
        """Can create planner using the factory function."""
        client = create_llm_client(mock_config)
        p = LLMTestPlanner(client)
        assert p.llm_client.provider_name == "mock"


# ── Input Validation Tests ───────────────────────────────────


class TestLLMTestPlannerInputValidation:
    """Validate input validation delegation."""

    def test_valid_context_passes(self, planner, sample_context):
        # Should not raise
        planner._validate_input(sample_context)

    def test_empty_app_name_raises(self, planner):
        ctx = ApplicationContext(app_name="", app_url="http://localhost")
        with pytest.raises(TestPlanValidationError) as exc_info:
            planner._validate_input(ctx)
        assert "app_name" in str(exc_info.value)

    def test_empty_app_url_raises(self, planner):
        ctx = ApplicationContext(app_name="App", app_url="")
        with pytest.raises(TestPlanValidationError) as exc_info:
            planner._validate_input(ctx)
        assert "app_url" in str(exc_info.value)


# ── Output Validation Tests ──────────────────────────────────


class TestLLMTestPlannerOutputValidation:
    """Validate output validation delegation."""

    def test_valid_cases_pass(self, planner):
        cases = [
            TestCase(
                test_id="TC001",
                name="Valid",
                steps=[
                    TestStep(
                        step_number=1,
                        action=TestAction.CLICK,
                        target="#btn",
                    ),
                ],
            ),
        ]
        result = planner._validate_output(cases)
        assert len(result) == 1

    def test_invalid_cases_filtered(self, planner):
        """Invalid test cases should be filtered out, not cause an error."""
        cases = [
            TestCase(
                test_id="TC001",
                name="Valid",
                steps=[
                    TestStep(
                        step_number=1,
                        action=TestAction.CLICK,
                        target="#btn",
                    ),
                ],
            ),
            TestCase(
                test_id="TC002",
                name="Invalid — no steps",
                steps=[],
            ),
        ]
        result = planner._validate_output(cases)
        assert len(result) == 1
        assert result[0].test_id == "TC001"

    def test_all_invalid_returns_empty(self, planner):
        cases = [
            TestCase(test_id="TC001", name="", steps=[]),
        ]
        result = planner._validate_output(cases)
        assert result == []


# ── Prompt Building Tests ────────────────────────────────────


class TestLLMTestPlannerPromptBuilding:
    """Validate prompt construction."""

    def test_build_prompt_returns_string(self, planner, sample_context):
        prompt = planner._build_prompt(sample_context)
        assert isinstance(prompt, str)
        assert len(prompt) > 0

    def test_prompt_contains_context(self, planner, sample_context):
        prompt = planner._build_prompt(sample_context)
        assert "Demo Application" in prompt
        assert "localhost:3000" in prompt

    def test_prompt_contains_action_vocabulary(self, planner, sample_context):
        prompt = planner._build_prompt(sample_context)
        assert "navigate" in prompt
        assert "click" in prompt
        assert "fill" in prompt

    def test_prompt_contains_assertion_vocabulary(self, planner, sample_context):
        prompt = planner._build_prompt(sample_context)
        assert "element_visible" in prompt
        assert "url_contains" in prompt

    def test_prompt_contains_max_tests(self, planner, sample_context):
        prompt = planner._build_prompt(sample_context, max_tests=5)
        assert "5" in prompt

    def test_system_prompt_not_empty(self, planner):
        system = planner._get_system_prompt()
        assert isinstance(system, str)
        assert len(system) > 0

    def test_system_prompt_contains_constraints(self, planner):
        system = planner._get_system_prompt()
        assert "ONLY" in system
        assert "NEVER" in system


# ── Generate Tests (Day 5 placeholder) ───────────────────────


class TestLLMTestPlannerGenerate:
    """Validate that generate_tests is a Day 4 skeleton."""

    @pytest.mark.asyncio
    async def test_generate_raises_not_implemented(self, planner, sample_context):
        with pytest.raises(NotImplementedError) as exc_info:
            await planner.generate_tests(sample_context)
        assert "Day 5" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_generate_validates_input_first(self, planner):
        """Invalid context should raise TestPlanValidationError, not NotImplementedError."""
        bad_ctx = ApplicationContext(app_name="", app_url="http://localhost")
        with pytest.raises(TestPlanValidationError):
            await planner.generate_tests(bad_ctx)


# ── Prompt Module Tests ──────────────────────────────────────


class TestPromptModule:
    """Validate standalone prompt utilities."""

    def test_system_prompt_defined(self):
        assert isinstance(SYSTEM_PROMPT, str)
        assert "QA engineer" in SYSTEM_PROMPT

    def test_action_vocabulary_defined(self):
        assert isinstance(ACTION_VOCABULARY, str)
        for action in TestAction:
            assert action.value in ACTION_VOCABULARY

    def test_assertion_vocabulary_defined(self):
        assert isinstance(ASSERTION_VOCABULARY, str)
        for at in AssertionType:
            assert at.value in ASSERTION_VOCABULARY

    def test_category_definitions_defined(self):
        assert isinstance(CATEGORY_DEFINITIONS, str)
        assert "functional" in CATEGORY_DEFINITIONS
        assert "negative" in CATEGORY_DEFINITIONS
        assert "boundary" in CATEGORY_DEFINITIONS

    def test_priority_definitions_defined(self):
        assert isinstance(PRIORITY_DEFINITIONS, str)
        assert "HIGH" in PRIORITY_DEFINITIONS
        assert "MEDIUM" in PRIORITY_DEFINITIONS
        assert "LOW" in PRIORITY_DEFINITIONS

    def test_output_schema_instruction_defined(self):
        assert isinstance(OUTPUT_SCHEMA_INSTRUCTION, str)
        assert "JSON" in OUTPUT_SCHEMA_INSTRUCTION

    def test_build_prompt_function(self):
        ctx = ApplicationContext(
            app_name="TestApp",
            app_url="http://test.com",
        )
        prompt = build_test_generation_prompt(ctx, max_tests=3)
        assert "TestApp" in prompt
        assert "3" in prompt


# ── Mock Scenario Tests ──────────────────────────────────────


class TestMockScenarios:
    """Validate mock scenario fixtures."""

    def test_valid_plan_is_valid_json(self):
        data = json.loads(VALID_TEST_PLAN_RESPONSE)
        assert "application_name" in data
        assert "test_cases" in data
        assert len(data["test_cases"]) >= 1

    def test_valid_plan_test_cases_have_required_fields(self):
        data = json.loads(VALID_TEST_PLAN_RESPONSE)
        for tc in data["test_cases"]:
            assert "test_id" in tc
            assert "name" in tc
            assert "steps" in tc

    def test_invalid_malformed_is_not_valid_json(self):
        with pytest.raises(json.JSONDecodeError):
            json.loads(INVALID_MALFORMED_RESPONSE)

    def test_empty_plan_has_no_cases(self):
        data = json.loads(EMPTY_TEST_PLAN_RESPONSE)
        assert data["test_cases"] == []

    def test_unsupported_action_contains_bad_action(self):
        data = json.loads(UNSUPPORTED_ACTION_RESPONSE)
        actions = {
            step["action"]
            for tc in data["test_cases"]
            for step in tc["steps"]
        }
        valid_actions = {a.value for a in TestAction}
        assert not actions.issubset(valid_actions), (
            "Expected at least one unsupported action"
        )

    def test_invalid_category_contains_bad_category(self):
        data = json.loads(INVALID_CATEGORY_RESPONSE)
        categories = {tc["category"] for tc in data["test_cases"]}
        valid_categories = {c.value for c in TestCategory}
        assert not categories.issubset(valid_categories)

    def test_invalid_priority_contains_bad_priority(self):
        data = json.loads(INVALID_PRIORITY_RESPONSE)
        priorities = {tc["priority"] for tc in data["test_cases"]}
        valid_priorities = {p.value for p in TestPriority}
        assert not priorities.issubset(valid_priorities)

    def test_sample_context_is_valid(self):
        ctx = ApplicationContext.model_validate(SAMPLE_APPLICATION_CONTEXT)
        assert ctx.app_name == "Demo Application"
        assert len(ctx.pages) == 2

    def test_register_planner_scenarios(self, mock_config):
        provider = MockLLMProvider(mock_config)
        register_planner_scenarios(provider)
        # Should have registered 7 scenarios
        assert len(provider._response_registry) == 7

    def test_register_scenarios_wrong_type(self):
        with pytest.raises(TypeError):
            register_planner_scenarios("not a provider")
