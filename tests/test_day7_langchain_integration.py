"""
TestSphere-AI — Day 7: LangChain Integration Tests

Comprehensive tests for the Day 7 LangChain integration:

  - LangChain prompt template creation and formatting
  - Application context insertion into prompts
  - LangChain planning adapter
  - Mock provider compatibility through the LangChain pipeline
  - Structured output processing (valid, cleanup, coercion, invalid)
  - Schema validation via StructuredOutputProcessor
  - Business-rule validation through the LangChain pipeline
  - LangChainTestPlanner full integration
  - Complete offline pipeline execution
  - Backward compatibility (original LLMTestPlanner unchanged)

No existing tests are modified or removed.
"""

import json

import pytest

from agents.llm.client import LLMClientSession
from agents.llm.config import LLMConfig
from agents.llm.exceptions import LLMResponseError
from agents.llm.providers.mock import MockLLMProvider
from agents.llm.factory import create_llm_client
from agents.planner.langchain_adapter import LangChainPlanningAdapter
from agents.planner.langchain_prompts import TestPlannerPromptTemplate
from agents.planner.mock_scenarios import (
    VALID_TEST_PLAN_RESPONSE,
    SAMPLE_APPLICATION_CONTEXT,
    register_default_planner_scenario,
    register_planner_scenarios,
)
from agents.planner.planner import (
    LangChainTestPlanner,
    LLMTestPlanner,
    TestPlannerAgent,
)
from agents.planner.prompts import (
    SYSTEM_PROMPT,
    ACTION_VOCABULARY,
    ASSERTION_VOCABULARY,
    CATEGORY_DEFINITIONS,
    PRIORITY_DEFINITIONS,
    OUTPUT_SCHEMA_INSTRUCTION,
    build_test_generation_prompt,
)
from agents.planner.schemas import (
    ApplicationContext,
    ElementContext,
    PageContext,
    TestCase,
    TestPlan,
    TestStep,
)
from agents.planner.structured_output import (
    StructuredOutputError,
    StructuredOutputProcessor,
)
from agents.planner.validation import TestPlanValidationError
from agents.schemas.enums import (
    AssertionType,
    TestAction,
    TestCategory,
    TestPriority,
)


# ── Shared Fixtures ──────────────────────────────────────────


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
def sample_context():
    """Return a valid ApplicationContext for testing."""
    return ApplicationContext(
        app_name="Demo Application",
        app_url="http://localhost:3000",
        description="A demo web application with login and dashboard.",
        pages=[
            PageContext(
                url="/login",
                name="Login",
                title="Login Page",
                description="User authentication page",
                elements=[
                    ElementContext(
                        tag="input", id="email", name="email",
                        type="email", placeholder="Enter email",
                    ),
                    ElementContext(
                        tag="input", id="password", name="password",
                        type="password", placeholder="Enter password",
                    ),
                    ElementContext(
                        tag="button", id="login-button", text="Login",
                    ),
                ],
            ),
            PageContext(
                url="/dashboard",
                name="Dashboard",
                title="Dashboard",
                description="Main application dashboard",
                elements=[
                    ElementContext(tag="h1", id="welcome-heading", text="Welcome"),
                    ElementContext(tag="button", id="logout-button", text="Logout"),
                ],
            ),
        ],
        technology_stack=["React", "Node.js"],
    )


@pytest.fixture
def minimal_context():
    """Return a minimal ApplicationContext."""
    return ApplicationContext(
        app_name="Minimal App",
        app_url="http://localhost",
    )


@pytest.fixture
def prompt_template():
    """Return a TestPlannerPromptTemplate instance."""
    return TestPlannerPromptTemplate()


@pytest.fixture
def output_processor():
    """Return a StructuredOutputProcessor instance."""
    return StructuredOutputProcessor()


@pytest.fixture
def adapter(llm_session):
    """Return a LangChainPlanningAdapter instance."""
    return LangChainPlanningAdapter(llm_session)


@pytest.fixture
def langchain_planner(llm_session):
    """Return a LangChainTestPlanner instance."""
    return LangChainTestPlanner(llm_session)


# ════════════════════════════════════════════════════════════════
#  TEST GROUP 1: LangChain Prompt Templates
# ════════════════════════════════════════════════════════════════


class TestPromptTemplateCreation:
    """Validate TestPlannerPromptTemplate creation and properties."""

    def test_creates_successfully(self, prompt_template):
        assert isinstance(prompt_template, TestPlannerPromptTemplate)

    def test_has_system_prompt(self, prompt_template):
        assert prompt_template.system_prompt == SYSTEM_PROMPT

    def test_custom_system_prompt(self):
        custom = "You are a test generator."
        template = TestPlannerPromptTemplate(system_prompt_override=custom)
        assert template.system_prompt == custom

    def test_has_user_template(self, prompt_template):
        assert prompt_template.user_template is not None

    def test_has_chat_template(self, prompt_template):
        assert prompt_template.chat_template is not None

    def test_format_system_prompt_returns_string(self, prompt_template):
        result = prompt_template.format_system_prompt()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_format_system_prompt_matches_original(self, prompt_template):
        """LangChain system prompt should match the original SYSTEM_PROMPT."""
        assert prompt_template.format_system_prompt() == SYSTEM_PROMPT


class TestPromptTemplateFormatting:
    """Validate prompt formatting with application context."""

    def test_format_user_prompt_returns_string(
        self, prompt_template, sample_context
    ):
        result = prompt_template.format_user_prompt(sample_context)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_prompt_contains_app_name(self, prompt_template, sample_context):
        result = prompt_template.format_user_prompt(sample_context)
        assert "Demo Application" in result

    def test_prompt_contains_app_url(self, prompt_template, sample_context):
        result = prompt_template.format_user_prompt(sample_context)
        assert "http://localhost:3000" in result

    def test_prompt_contains_description(self, prompt_template, sample_context):
        result = prompt_template.format_user_prompt(sample_context)
        assert "demo web application" in result

    def test_prompt_contains_max_tests(self, prompt_template, sample_context):
        result = prompt_template.format_user_prompt(sample_context, max_tests=5)
        assert "5" in result

    def test_prompt_contains_action_vocabulary(
        self, prompt_template, sample_context
    ):
        result = prompt_template.format_user_prompt(sample_context)
        assert "navigate" in result
        assert "click" in result
        assert "fill" in result

    def test_prompt_contains_assertion_vocabulary(
        self, prompt_template, sample_context
    ):
        result = prompt_template.format_user_prompt(sample_context)
        assert "element_visible" in result
        assert "url_contains" in result

    def test_prompt_contains_category_definitions(
        self, prompt_template, sample_context
    ):
        result = prompt_template.format_user_prompt(sample_context)
        assert "functional" in result
        assert "negative" in result
        assert "boundary" in result

    def test_prompt_contains_priority_definitions(
        self, prompt_template, sample_context
    ):
        result = prompt_template.format_user_prompt(sample_context)
        assert "HIGH" in result
        assert "MEDIUM" in result
        assert "LOW" in result

    def test_prompt_contains_output_schema(
        self, prompt_template, sample_context
    ):
        result = prompt_template.format_user_prompt(sample_context)
        assert "JSON" in result

    def test_prompt_contains_pages_summary(
        self, prompt_template, sample_context
    ):
        result = prompt_template.format_user_prompt(sample_context)
        assert "Login" in result
        assert "Dashboard" in result
        assert "/login" in result

    def test_prompt_contains_elements_summary(
        self, prompt_template, sample_context
    ):
        result = prompt_template.format_user_prompt(sample_context)
        assert "email" in result
        assert "password" in result
        assert "login-button" in result

    def test_prompt_contains_context_json(
        self, prompt_template, sample_context
    ):
        result = prompt_template.format_user_prompt(sample_context)
        assert '"app_name"' in result
        assert '"pages"' in result


class TestPromptTemplateContextExtraction:
    """Validate context extraction helper methods."""

    def test_build_pages_summary_with_pages(
        self, prompt_template, sample_context
    ):
        summary = prompt_template._build_pages_summary(sample_context)
        assert "Login" in summary
        assert "Dashboard" in summary
        assert "/login" in summary

    def test_build_pages_summary_no_pages(self, prompt_template, minimal_context):
        summary = prompt_template._build_pages_summary(minimal_context)
        assert "No pages defined" in summary

    def test_build_elements_summary_with_elements(
        self, prompt_template, sample_context
    ):
        summary = prompt_template._build_elements_summary(sample_context)
        assert "email" in summary
        assert "password" in summary

    def test_build_elements_summary_no_pages(
        self, prompt_template, minimal_context
    ):
        summary = prompt_template._build_elements_summary(minimal_context)
        assert "No elements available" in summary

    def test_build_user_flows_with_pages(
        self, prompt_template, sample_context
    ):
        flows = prompt_template._build_user_flows(sample_context)
        assert "Login" in flows or "flow" in flows.lower()

    def test_build_user_flows_no_pages(
        self, prompt_template, minimal_context
    ):
        flows = prompt_template._build_user_flows(minimal_context)
        assert "No user flows" in flows

    def test_build_testing_requirements(
        self, prompt_template, sample_context
    ):
        reqs = prompt_template._build_testing_requirements(
            sample_context, max_tests=7,
        )
        assert "7" in reqs
        assert "React" in reqs


class TestChatPromptTemplate:
    """Validate chat prompt template (message-based output)."""

    def test_get_messages_returns_list(self, prompt_template, sample_context):
        messages = prompt_template.get_messages(sample_context)
        assert isinstance(messages, list)

    def test_get_messages_has_two_messages(self, prompt_template, sample_context):
        messages = prompt_template.get_messages(sample_context)
        assert len(messages) == 2

    def test_get_messages_first_is_system(self, prompt_template, sample_context):
        messages = prompt_template.get_messages(sample_context)
        assert messages[0].type == "system"

    def test_get_messages_second_is_human(self, prompt_template, sample_context):
        messages = prompt_template.get_messages(sample_context)
        assert messages[1].type == "human"

    def test_system_message_contains_qa_instructions(
        self, prompt_template, sample_context
    ):
        messages = prompt_template.get_messages(sample_context)
        assert "QA engineer" in messages[0].content

    def test_human_message_contains_context(
        self, prompt_template, sample_context
    ):
        messages = prompt_template.get_messages(sample_context)
        assert "Demo Application" in messages[1].content


# ════════════════════════════════════════════════════════════════
#  TEST GROUP 2: LangChain Planning Adapter
# ════════════════════════════════════════════════════════════════


class TestPlanningAdapterInit:
    """Validate LangChainPlanningAdapter initialization."""

    def test_creates_successfully(self, adapter):
        assert isinstance(adapter, LangChainPlanningAdapter)

    def test_stores_llm_client(self, adapter, llm_session):
        assert adapter.llm_client is llm_session

    def test_creates_default_prompt_template(self, adapter):
        assert isinstance(adapter.prompt_template, TestPlannerPromptTemplate)

    def test_custom_prompt_template(self, llm_session):
        custom_template = TestPlannerPromptTemplate(
            system_prompt_override="Custom system prompt.",
        )
        adapter = LangChainPlanningAdapter(
            llm_session, prompt_template=custom_template,
        )
        assert adapter.prompt_template is custom_template


class TestPlanningAdapterGeneration:
    """Validate the adapter's plan generation."""

    @pytest.mark.asyncio
    async def test_generates_raw_plan(
        self, adapter, mock_provider, sample_context
    ):
        """Adapter should produce a raw dict via mock provider."""
        register_default_planner_scenario(mock_provider)
        result = await adapter.generate_raw_plan(sample_context)
        assert isinstance(result, dict)
        assert "application_name" in result
        assert "test_cases" in result

    @pytest.mark.asyncio
    async def test_uses_langchain_prompt(
        self, adapter, mock_provider, sample_context
    ):
        """The adapter should use LangChain-formatted prompts that
        contain 'Generate up to' to match the mock scenario."""
        register_default_planner_scenario(mock_provider)
        result = await adapter.generate_raw_plan(sample_context, max_tests=5)
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_passes_max_tests(
        self, adapter, mock_provider, sample_context
    ):
        """max_tests parameter should be forwarded."""
        register_default_planner_scenario(mock_provider)
        # Should not raise — just verifying the parameter flows through
        result = await adapter.generate_raw_plan(
            sample_context, max_tests=3,
        )
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_adapter_with_factory_client(self, mock_config, sample_context):
        """Adapter should work with a factory-created client."""
        client = create_llm_client(mock_config)
        adapter = LangChainPlanningAdapter(client)
        # Register the mock response on the underlying provider
        provider = client.provider
        register_default_planner_scenario(provider)
        result = await adapter.generate_raw_plan(sample_context)
        assert isinstance(result, dict)


# ════════════════════════════════════════════════════════════════
#  TEST GROUP 3: Structured Output Processing
# ════════════════════════════════════════════════════════════════


class TestStructuredOutputValid:
    """Validate processing of valid structured output."""

    def test_process_valid_dict(self, output_processor):
        data = json.loads(VALID_TEST_PLAN_RESPONSE)
        plan = output_processor.process(data)
        assert isinstance(plan, TestPlan)
        assert plan.application_name == "Demo Application"
        assert len(plan.test_cases) >= 1

    def test_process_preserves_test_case_fields(self, output_processor):
        data = json.loads(VALID_TEST_PLAN_RESPONSE)
        plan = output_processor.process(data)
        tc = plan.test_cases[0]
        assert tc.test_id == "TC_LOGIN_001"
        assert tc.name == "Valid Login"
        assert len(tc.steps) > 0

    def test_process_preserves_assertions(self, output_processor):
        data = json.loads(VALID_TEST_PLAN_RESPONSE)
        plan = output_processor.process(data)
        tc = plan.test_cases[0]
        assert len(tc.assertions) > 0
        assert tc.assertions[0].type == AssertionType.URL_CONTAINS


class TestStructuredOutputCleanup:
    """Validate JSON cleanup functionality."""

    def test_clean_markdown_fences(self, output_processor):
        text = '```json\n{"application_name": "App", "test_cases": []}\n```'
        cleaned = output_processor.clean_json_string(text)
        data = json.loads(cleaned)
        assert data["application_name"] == "App"

    def test_clean_markdown_fences_no_lang(self, output_processor):
        text = '```\n{"application_name": "App", "test_cases": []}\n```'
        cleaned = output_processor.clean_json_string(text)
        data = json.loads(cleaned)
        assert data["application_name"] == "App"

    def test_clean_trailing_commas(self, output_processor):
        text = '{"application_name": "App", "test_cases": [],}'
        cleaned = output_processor.clean_json_string(text)
        data = json.loads(cleaned)
        assert data["application_name"] == "App"

    def test_clean_nested_trailing_commas(self, output_processor):
        text = '{"items": [1, 2, 3,]}'
        cleaned = output_processor.clean_json_string(text)
        data = json.loads(cleaned)
        assert data["items"] == [1, 2, 3]

    def test_clean_empty_raises(self, output_processor):
        with pytest.raises(StructuredOutputError) as exc_info:
            output_processor.clean_json_string("")
        assert exc_info.value.stage == "cleanup"

    def test_clean_whitespace_only_raises(self, output_processor):
        with pytest.raises(StructuredOutputError) as exc_info:
            output_processor.clean_json_string("   \n\t  ")
        assert exc_info.value.stage == "cleanup"


class TestStructuredOutputCoercion:
    """Validate field coercion functionality."""

    def test_coerce_priority_to_upper(self, output_processor):
        data = {
            "application_name": "App",
            "test_cases": [
                {
                    "test_id": "TC001",
                    "name": "Test",
                    "priority": "high",
                    "category": "functional",
                    "steps": [
                        {"step_number": 1, "action": "click", "target": "#btn"},
                    ],
                    "assertions": [],
                },
            ],
        }
        coerced = output_processor.coerce_fields(data)
        assert coerced["test_cases"][0]["priority"] == "HIGH"

    def test_coerce_category_to_lower(self, output_processor):
        data = {
            "application_name": "App",
            "test_cases": [
                {
                    "test_id": "TC001",
                    "name": "Test",
                    "priority": "HIGH",
                    "category": "Functional",
                    "steps": [],
                    "assertions": [],
                },
            ],
        }
        coerced = output_processor.coerce_fields(data)
        assert coerced["test_cases"][0]["category"] == "functional"

    def test_coerce_action_to_lower(self, output_processor):
        data = {
            "test_cases": [
                {
                    "steps": [
                        {"step_number": 1, "action": "Click", "target": "#btn"},
                    ],
                },
            ],
        }
        coerced = output_processor.coerce_fields(data)
        assert coerced["test_cases"][0]["steps"][0]["action"] == "click"

    def test_coerce_assertion_type_to_lower(self, output_processor):
        data = {
            "test_cases": [
                {
                    "assertions": [
                        {"type": "URL_CONTAINS", "expected": "/dashboard"},
                    ],
                },
            ],
        }
        coerced = output_processor.coerce_fields(data)
        assert coerced["test_cases"][0]["assertions"][0]["type"] == "url_contains"

    def test_coerce_preserves_valid_values(self, output_processor):
        """Already valid values should remain unchanged."""
        data = {
            "test_cases": [
                {
                    "priority": "HIGH",
                    "category": "functional",
                    "steps": [
                        {"step_number": 1, "action": "click", "target": "#btn"},
                    ],
                    "assertions": [
                        {"type": "url_contains", "expected": "/test"},
                    ],
                },
            ],
        }
        coerced = output_processor.coerce_fields(data)
        tc = coerced["test_cases"][0]
        assert tc["priority"] == "HIGH"
        assert tc["category"] == "functional"
        assert tc["steps"][0]["action"] == "click"
        assert tc["assertions"][0]["type"] == "url_contains"

    def test_coerce_no_test_cases_key(self, output_processor):
        """Data without test_cases should be returned as-is."""
        data = {"application_name": "App"}
        coerced = output_processor.coerce_fields(data)
        assert coerced == data


class TestStructuredOutputInvalid:
    """Validate rejection of invalid output."""

    def test_process_non_dict_raises(self, output_processor):
        with pytest.raises(StructuredOutputError) as exc_info:
            output_processor.process([1, 2, 3])
        assert exc_info.value.stage == "validation"

    def test_process_missing_required_field_raises(self, output_processor):
        """Missing application_name should raise StructuredOutputError."""
        data = {"test_cases": []}
        with pytest.raises(StructuredOutputError) as exc_info:
            output_processor.process(data)
        assert exc_info.value.stage == "validation"

    def test_process_invalid_category_raises(self, output_processor):
        """Invalid test category should raise during schema validation."""
        data = {
            "application_name": "App",
            "test_cases": [
                {
                    "test_id": "TC001",
                    "name": "Test",
                    "category": "performance",
                    "priority": "HIGH",
                    "steps": [
                        {"step_number": 1, "action": "click", "target": "#btn"},
                    ],
                    "assertions": [],
                },
            ],
        }
        with pytest.raises(StructuredOutputError):
            output_processor.process(data)

    def test_process_invalid_action_raises(self, output_processor):
        """Invalid action should raise during schema validation."""
        data = {
            "application_name": "App",
            "test_cases": [
                {
                    "test_id": "TC001",
                    "name": "Test",
                    "category": "functional",
                    "priority": "HIGH",
                    "steps": [
                        {
                            "step_number": 1,
                            "action": "drag_and_drop",
                            "target": "#elem",
                        },
                    ],
                    "assertions": [],
                },
            ],
        }
        with pytest.raises(StructuredOutputError):
            output_processor.process(data)

    def test_process_text_invalid_json_raises(self, output_processor):
        with pytest.raises(StructuredOutputError) as exc_info:
            output_processor.process_text("not valid json at all")
        assert exc_info.value.stage == "cleanup"

    def test_process_text_valid(self, output_processor):
        plan = output_processor.process_text(VALID_TEST_PLAN_RESPONSE)
        assert isinstance(plan, TestPlan)
        assert len(plan.test_cases) >= 1

    def test_process_text_with_fences(self, output_processor):
        fenced = f"```json\n{VALID_TEST_PLAN_RESPONSE}\n```"
        plan = output_processor.process_text(fenced)
        assert isinstance(plan, TestPlan)


class TestStructuredOutputErrorException:
    """Validate StructuredOutputError properties."""

    def test_has_stage(self):
        err = StructuredOutputError("test", stage="cleanup")
        assert err.stage == "cleanup"

    def test_has_message(self):
        err = StructuredOutputError("test message", stage="validation")
        assert "test message" in str(err)

    def test_default_stage(self):
        err = StructuredOutputError("test")
        assert err.stage == ""


# ════════════════════════════════════════════════════════════════
#  TEST GROUP 4: LangChainTestPlanner Integration
# ════════════════════════════════════════════════════════════════


class TestLangChainTestPlannerInit:
    """Validate LangChainTestPlanner initialization."""

    def test_inherits_from_abstract(self, langchain_planner):
        assert isinstance(langchain_planner, TestPlannerAgent)

    def test_stores_llm_client(self, langchain_planner, llm_session):
        assert langchain_planner.llm_client is llm_session

    def test_has_adapter(self, langchain_planner):
        assert isinstance(
            langchain_planner.adapter, LangChainPlanningAdapter,
        )

    def test_has_output_processor(self, langchain_planner):
        assert isinstance(
            langchain_planner.output_processor, StructuredOutputProcessor,
        )

    def test_provider_name(self, langchain_planner):
        assert langchain_planner.llm_client.provider_name == "mock"

    def test_create_via_factory(self, mock_config):
        """Can create LangChain planner using the factory function."""
        client = create_llm_client(mock_config)
        planner = LangChainTestPlanner(client)
        assert planner.llm_client.provider_name == "mock"


class TestLangChainTestPlannerGenerate:
    """Validate LangChainTestPlanner test generation."""

    @pytest.mark.asyncio
    async def test_generate_produces_results(
        self, langchain_planner, mock_provider, sample_context
    ):
        """Valid context + valid mock response → test cases returned."""
        register_default_planner_scenario(mock_provider)
        result = await langchain_planner.generate_tests(sample_context)
        assert isinstance(result, list)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_generate_returns_test_cases(
        self, langchain_planner, mock_provider, sample_context
    ):
        """Each result should be a TestCase instance."""
        register_default_planner_scenario(mock_provider)
        result = await langchain_planner.generate_tests(sample_context)
        for tc in result:
            assert isinstance(tc, TestCase)

    @pytest.mark.asyncio
    async def test_generate_validates_input(self, langchain_planner):
        """Invalid context should raise TestPlanValidationError."""
        bad_ctx = ApplicationContext(app_name="", app_url="http://localhost")
        with pytest.raises(TestPlanValidationError):
            await langchain_planner.generate_tests(bad_ctx)

    @pytest.mark.asyncio
    async def test_generate_test_plan(
        self, langchain_planner, mock_provider, sample_context
    ):
        """generate_test_plan should return a full TestPlan."""
        register_default_planner_scenario(mock_provider)
        plan = await langchain_planner.generate_test_plan(sample_context)
        assert isinstance(plan, TestPlan)
        assert plan.application_name == "Demo Application"
        assert plan.metadata.get("pipeline") == "langchain"

    @pytest.mark.asyncio
    async def test_generate_respects_max_tests(
        self, langchain_planner, mock_provider, sample_context
    ):
        """max_tests should be forwarded through the pipeline."""
        register_default_planner_scenario(mock_provider)
        plan = await langchain_planner.generate_test_plan(
            sample_context, max_tests=5,
        )
        assert plan.metadata["max_tests_requested"] == 5


class TestLangChainTestPlannerValidation:
    """Validate that business-rule validation still works through LangChain pipeline."""

    @pytest.mark.asyncio
    async def test_validates_test_cases(
        self, langchain_planner, mock_provider, sample_context
    ):
        """Generated test cases should pass business-rule validation."""
        register_default_planner_scenario(mock_provider)
        result = await langchain_planner.generate_tests(sample_context)
        for tc in result:
            assert tc.test_id.strip()
            assert tc.name.strip()
            assert len(tc.steps) > 0

    @pytest.mark.asyncio
    async def test_removes_duplicates(
        self, langchain_planner, mock_provider, sample_context
    ):
        """The LangChain pipeline should still remove duplicates."""
        from agents.planner.mock_scenarios import DUPLICATE_TEST_RESPONSE

        mock_provider.register_response(
            "Generate up to", DUPLICATE_TEST_RESPONSE,
        )
        result = await langchain_planner.generate_tests(sample_context)
        # Should have fewer cases than the raw response (duplicates removed)
        raw_data = json.loads(DUPLICATE_TEST_RESPONSE)
        assert len(result) < len(raw_data["test_cases"])

    @pytest.mark.asyncio
    async def test_filters_hallucinated_elements(
        self, langchain_planner, mock_provider, sample_context
    ):
        """Test cases referencing non-existent elements should be filtered."""
        from agents.planner.mock_scenarios import HALLUCINATED_ELEMENT_RESPONSE

        mock_provider.register_response(
            "Generate up to", HALLUCINATED_ELEMENT_RESPONSE,
        )
        result = await langchain_planner.generate_tests(sample_context)
        # The hallucinated test case should be filtered out
        assert len(result) == 0


# ════════════════════════════════════════════════════════════════
#  TEST GROUP 5: Offline Pipeline
# ════════════════════════════════════════════════════════════════


class TestOfflinePipeline:
    """Validate complete offline pipeline execution."""

    @pytest.mark.asyncio
    async def test_full_pipeline_offline(self, mock_config):
        """The entire LangChain pipeline should work offline
        with no API key and no internet access."""
        # Create everything from scratch — no external dependencies
        provider = MockLLMProvider(mock_config)
        register_default_planner_scenario(provider)
        session = LLMClientSession(provider, mock_config)
        planner = LangChainTestPlanner(session)

        context = ApplicationContext.model_validate(SAMPLE_APPLICATION_CONTEXT)
        plan = await planner.generate_test_plan(context)

        assert isinstance(plan, TestPlan)
        assert plan.application_name == "Demo Application"
        assert len(plan.test_cases) > 0
        assert plan.metadata["pipeline"] == "langchain"

    @pytest.mark.asyncio
    async def test_full_pipeline_with_factory(self, mock_config):
        """Offline pipeline should work with the factory function."""
        client = create_llm_client(mock_config)
        register_default_planner_scenario(client.provider)
        planner = LangChainTestPlanner(client)

        context = ApplicationContext.model_validate(SAMPLE_APPLICATION_CONTEXT)
        result = await planner.generate_tests(context)

        assert isinstance(result, list)
        assert len(result) > 0
        for tc in result:
            assert isinstance(tc, TestCase)
            assert tc.test_id.strip()

    @pytest.mark.asyncio
    async def test_no_api_key_required(self, mock_config):
        """The pipeline should work without any API key."""
        assert mock_config.api_key == ""
        provider = MockLLMProvider(mock_config)
        register_default_planner_scenario(provider)
        session = LLMClientSession(provider, mock_config)
        planner = LangChainTestPlanner(session)

        context = ApplicationContext.model_validate(SAMPLE_APPLICATION_CONTEXT)
        plan = await planner.generate_test_plan(context)
        assert isinstance(plan, TestPlan)

    @pytest.mark.asyncio
    async def test_mock_provider_call_count(self, mock_config):
        """Mock provider should track call count through the LangChain pipeline."""
        provider = MockLLMProvider(mock_config)
        register_default_planner_scenario(provider)
        session = LLMClientSession(provider, mock_config)
        planner = LangChainTestPlanner(session)

        assert provider.call_count == 0

        context = ApplicationContext.model_validate(SAMPLE_APPLICATION_CONTEXT)
        await planner.generate_tests(context)

        assert provider.call_count == 1


# ════════════════════════════════════════════════════════════════
#  TEST GROUP 6: Backward Compatibility
# ════════════════════════════════════════════════════════════════


class TestBackwardCompatibility:
    """Ensure existing LLMTestPlanner is completely unaffected."""

    @pytest.mark.asyncio
    async def test_original_planner_still_works(
        self, mock_provider, mock_config
    ):
        """The original LLMTestPlanner should work exactly as before."""
        register_default_planner_scenario(mock_provider)
        session = LLMClientSession(mock_provider, mock_config)
        planner = LLMTestPlanner(session)

        context = ApplicationContext.model_validate(SAMPLE_APPLICATION_CONTEXT)
        result = await planner.generate_tests(context)

        assert isinstance(result, list)
        assert len(result) > 0

    def test_original_prompt_builder_works(self):
        """The original build_test_generation_prompt should still work."""
        ctx = ApplicationContext(
            app_name="TestApp",
            app_url="http://test.com",
        )
        prompt = build_test_generation_prompt(ctx, max_tests=3)
        assert "TestApp" in prompt
        assert "3" in prompt

    def test_original_planner_is_abstract_subclass(self):
        """LLMTestPlanner should still be a TestPlannerAgent."""
        from agents.planner.planner import LLMTestPlanner as LTP
        assert issubclass(LTP, TestPlannerAgent)

    def test_langchain_planner_is_abstract_subclass(self):
        """LangChainTestPlanner should also be a TestPlannerAgent."""
        assert issubclass(LangChainTestPlanner, TestPlannerAgent)

    def test_both_planners_coexist(self, llm_session):
        """Both planner types can be instantiated simultaneously."""
        original = LLMTestPlanner(llm_session)
        langchain = LangChainTestPlanner(llm_session)
        assert isinstance(original, TestPlannerAgent)
        assert isinstance(langchain, TestPlannerAgent)
        assert type(original) is not type(langchain)

    @pytest.mark.asyncio
    async def test_both_planners_produce_equivalent_results(
        self, mock_provider, mock_config
    ):
        """Both planners should produce valid test cases from the same input."""
        register_default_planner_scenario(mock_provider)
        session = LLMClientSession(mock_provider, mock_config)

        original = LLMTestPlanner(session)
        langchain = LangChainTestPlanner(session)

        context = ApplicationContext.model_validate(SAMPLE_APPLICATION_CONTEXT)

        result_original = await original.generate_tests(context)
        result_langchain = await langchain.generate_tests(context)

        # Both should return valid test cases
        assert len(result_original) > 0
        assert len(result_langchain) > 0

        # Both should produce TestCase objects
        for tc in result_original:
            assert isinstance(tc, TestCase)
        for tc in result_langchain:
            assert isinstance(tc, TestCase)

    def test_existing_imports_work(self):
        """Existing import patterns should still work."""
        from agents.planner import LLMTestPlanner
        from agents.planner import TestPlannerAgent
        from agents.planner import validate_test_case
        from agents.planner import TestPlanValidationError
        assert LLMTestPlanner is not None
        assert TestPlannerAgent is not None

    def test_new_imports_work(self):
        """New Day 7 imports should work."""
        from agents.planner import LangChainTestPlanner
        from agents.planner import LangChainPlanningAdapter
        from agents.planner import TestPlannerPromptTemplate
        from agents.planner import StructuredOutputProcessor
        from agents.planner import StructuredOutputError
        assert LangChainTestPlanner is not None
        assert StructuredOutputProcessor is not None


# ════════════════════════════════════════════════════════════════
#  TEST GROUP 7: Schema Validation Through Pipeline
# ════════════════════════════════════════════════════════════════


class TestSchemaValidationThroughPipeline:
    """Validate that schema validation works correctly in the LangChain pipeline."""

    def test_valid_plan_passes_schema(self, output_processor):
        data = json.loads(VALID_TEST_PLAN_RESPONSE)
        plan = output_processor.process(data)
        assert isinstance(plan, TestPlan)
        for tc in plan.test_cases:
            assert isinstance(tc.category, TestCategory)
            assert isinstance(tc.priority, TestPriority)
            for step in tc.steps:
                assert isinstance(step.action, TestAction)

    def test_coerced_values_pass_schema(self, output_processor):
        """Values that need coercion should still produce valid schema objects."""
        data = {
            "application_name": "App",
            "test_cases": [
                {
                    "test_id": "TC001",
                    "name": "Test",
                    "priority": "high",
                    "category": "Functional",
                    "steps": [
                        {
                            "step_number": 1,
                            "action": "Click",
                            "target": "#btn",
                        },
                    ],
                    "assertions": [
                        {
                            "type": "Element_Visible",
                            "target": "#btn",
                        },
                    ],
                },
            ],
        }
        plan = output_processor.process(data)
        tc = plan.test_cases[0]
        assert tc.priority == TestPriority.HIGH
        assert tc.category == TestCategory.FUNCTIONAL
        assert tc.steps[0].action == TestAction.CLICK
        assert tc.assertions[0].type == AssertionType.ELEMENT_VISIBLE

    def test_empty_test_cases_passes_schema(self, output_processor):
        data = {
            "application_name": "App",
            "test_cases": [],
        }
        plan = output_processor.process(data)
        assert isinstance(plan, TestPlan)
        assert len(plan.test_cases) == 0
