"""
TestSphere-AI — Day 6: LLM Response Validation & Mock Scenario Tests

Regression and verification tests for the two issues identified
in the Day 6 code review:

1. Response normalization allowed whitespace-only responses through
   (and→or logic bug in _normalize_response).
2. Mock scenario registration used case-sensitive matching with a
   lowercase key that didn't match the real planner's capitalized prompt.

Tests cover:
  - Response normalization (valid, empty, whitespace, None, non-string,
    error finish_reason, missing provider/model backfill)
  - Mock scenario matching (case-insensitive, real prompt, unknown,
    registration count, individual scenarios)
  - Error distinction (LLMParsingError vs LLMSchemaValidationError)
  - Full pipeline verification via register_planner_scenarios()

All tests run offline, without API keys, models, or internet.
"""

from __future__ import annotations

import json

import pytest

from agents.llm.client import LLMClientSession
from agents.llm.config import LLMConfig
from agents.llm.exceptions import (
    LLMParsingError,
    LLMProviderError,
    LLMResponseError,
    LLMSchemaValidationError,
)
from agents.llm.parser import ResponseParser
from agents.llm.providers.mock import MockLLMProvider
from agents.llm.schemas import LLMRequest, LLMResponse, LLMUsage
from agents.planner.mock_scenarios import (
    VALID_TEST_PLAN_RESPONSE,
    INVALID_MALFORMED_RESPONSE,
    EMPTY_TEST_PLAN_RESPONSE,
    register_default_planner_scenario,
    register_planner_scenarios,
)
from agents.planner.planner import LLMTestPlanner
from agents.planner.schemas import (
    ApplicationContext,
    ElementContext,
    PageContext,
    TestPlan,
)
from agents.planner.validation import (
    TestPlanValidationError,
    detect_duplicate_test_cases,
    validate_element_references,
)
from agents.schemas.enums import (
    AssertionType,
    TestAction,
    TestCategory,
    TestPriority,
)
from tests.test_fixtures import (
    create_llm_session,
    create_mock_config,
    create_mock_provider,
    create_sample_login_context,
    create_test_planner,
)


# ── Fixtures ─────────────────────────────────────────────────


@pytest.fixture
def mock_config():
    return create_mock_config()


@pytest.fixture
def mock_provider(mock_config):
    return MockLLMProvider(mock_config)


@pytest.fixture
def llm_session(mock_provider, mock_config):
    return LLMClientSession(mock_provider, mock_config)


@pytest.fixture
def sample_context():
    return create_sample_login_context()


# ════════════════════════════════════════════════════════════════
#  RESPONSE NORMALIZATION TESTS — Day 6 Issue 1
# ════════════════════════════════════════════════════════════════


class TestResponseNormalizationDay6:
    """Regression tests for the _normalize_response and→or fix.

    Issue: Line 271 in client.py used 'and' instead of 'or', allowing
    whitespace-only responses to silently pass through as valid.
    """

    @pytest.mark.asyncio
    async def test_valid_response_passes(self, llm_session, mock_provider):
        """Normal text response should pass normalization."""
        mock_provider.register_response("test", "Valid response content")
        request = LLMRequest(prompt="test prompt")
        response = await llm_session.generate(request)
        assert response.content == "Valid response content"

    @pytest.mark.asyncio
    async def test_empty_string_response_raises(self, mock_config):
        """Empty string response should raise LLMResponseError."""
        provider = MockLLMProvider(mock_config, responses=[""])
        session = LLMClientSession(provider, mock_config)
        request = LLMRequest(prompt="test prompt")
        with pytest.raises(LLMResponseError, match="empty response"):
            await session.generate(request)

    @pytest.mark.asyncio
    async def test_whitespace_only_response_raises(self, mock_config):
        """Whitespace-only response should raise LLMResponseError.

        This is the REGRESSION TEST for the Day 6 and→or bug.
        Before the fix, '   ' would silently pass through.
        """
        provider = MockLLMProvider(mock_config, responses=["   "])
        session = LLMClientSession(provider, mock_config)
        request = LLMRequest(prompt="test prompt")
        with pytest.raises(LLMResponseError, match="empty response"):
            await session.generate(request)

    @pytest.mark.asyncio
    async def test_newline_only_response_raises(self, mock_config):
        """Newline-only response should raise LLMResponseError."""
        provider = MockLLMProvider(mock_config, responses=["\n\n\t\n"])
        session = LLMClientSession(provider, mock_config)
        request = LLMRequest(prompt="test prompt")
        with pytest.raises(LLMResponseError, match="empty response"):
            await session.generate(request)

    @pytest.mark.asyncio
    async def test_error_finish_reason_raises(self, mock_config):
        """Response with finish_reason='error' should raise."""
        provider = MockLLMProvider(mock_config)

        async def generate_error_finish(request):
            return LLMResponse(
                content="Some content",
                model="mock-model",
                provider="mock",
                usage=LLMUsage(prompt_tokens=5, completion_tokens=5),
                finish_reason="error",
            )

        provider.generate = generate_error_finish
        session = LLMClientSession(provider, mock_config)
        request = LLMRequest(prompt="test prompt")
        with pytest.raises(LLMResponseError, match="error finish reason"):
            await session.generate(request)

    @pytest.mark.asyncio
    async def test_provider_field_backfilled(self, mock_config):
        """Missing provider field should be backfilled from config."""
        provider = MockLLMProvider(mock_config)

        async def generate_no_provider(request):
            return LLMResponse(
                content="Hello",
                model="mock-model",
                provider="",
                usage=LLMUsage(prompt_tokens=1, completion_tokens=1),
            )

        provider.generate = generate_no_provider
        session = LLMClientSession(provider, mock_config)
        request = LLMRequest(prompt="test prompt")
        response = await session.generate(request)
        assert response.provider == "mock"

    @pytest.mark.asyncio
    async def test_model_field_backfilled(self, mock_config):
        """Missing model field should be backfilled from config."""
        provider = MockLLMProvider(mock_config)

        async def generate_no_model(request):
            return LLMResponse(
                content="Hello",
                model="",
                provider="mock",
                usage=LLMUsage(prompt_tokens=1, completion_tokens=1),
            )

        provider.generate = generate_no_model
        session = LLMClientSession(provider, mock_config)
        request = LLMRequest(prompt="test prompt")
        response = await session.generate(request)
        assert response.model == "mock-model"

    @pytest.mark.asyncio
    async def test_valid_json_response_passes(self, mock_config):
        """JSON content response should pass normalization."""
        json_content = json.dumps({"key": "value"})
        provider = MockLLMProvider(mock_config, responses=[json_content])
        session = LLMClientSession(provider, mock_config)
        request = LLMRequest(prompt="test prompt")
        response = await session.generate(request)
        assert response.content == json_content


# ════════════════════════════════════════════════════════════════
#  MOCK SCENARIO MATCHING TESTS — Day 6 Issue 2
# ════════════════════════════════════════════════════════════════


class TestMockScenarioMatchingDay6:
    """Regression tests for the mock scenario matching fix.

    Issue: register_planner_scenarios() used 'generate test' (lowercase)
    as the key, but the real planner prompt starts with 'Generate up to'
    (capitalized). Case-sensitive matching caused a mismatch.
    """

    @pytest.mark.asyncio
    async def test_register_planner_scenarios_matches_real_prompt(
        self, sample_context
    ):
        """register_planner_scenarios() should match the real planner prompt.

        This is the REGRESSION TEST for the Day 6 scenario matching bug.
        Before the fix, register_planner_scenarios() would not match because
        the key 'generate test' didn't case-match 'Generate up to'.
        """
        planner, provider = create_test_planner()
        register_planner_scenarios(provider)

        # This call uses the REAL planner prompt — not a manually
        # registered substring. If scenario matching is broken,
        # this will either fail to return valid JSON or raise.
        result = await planner.generate_tests(sample_context)
        assert isinstance(result, list)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_register_default_scenario_matches_real_prompt(
        self, sample_context
    ):
        """register_default_planner_scenario() should also work."""
        planner, provider = create_test_planner()
        register_default_planner_scenario(provider)

        result = await planner.generate_tests(sample_context)
        assert isinstance(result, list)
        assert len(result) > 0

    def test_case_insensitive_response_matching(self, mock_config):
        """Response registry should match case-insensitively."""
        provider = MockLLMProvider(mock_config)
        provider.register_response("hello world", "matched!")

        # Verify the substring is registered
        assert len(provider._response_registry) == 1
        assert provider._response_registry[0] == ("hello world", "matched!")

    @pytest.mark.asyncio
    async def test_case_insensitive_matching_in_generate(self, mock_config):
        """Case-insensitive matching should work during generate()."""
        provider = MockLLMProvider(mock_config)
        provider.register_response("hello", "Matched!")
        session = LLMClientSession(provider, mock_config)

        # Prompt uses different casing
        request = LLMRequest(prompt="HELLO world")
        response = await session.generate(request)
        assert response.content == "Matched!"

    @pytest.mark.asyncio
    async def test_case_insensitive_error_matching(self, mock_config):
        """Error registry should also match case-insensitively."""
        provider = MockLLMProvider(mock_config)
        provider.register_error(
            "fail me",
            LLMProviderError("Test error", provider="mock"),
        )
        session = LLMClientSession(provider, mock_config)

        request = LLMRequest(prompt="Please FAIL ME now")
        with pytest.raises(LLMProviderError, match="Test error"):
            await session.generate(request)

    @pytest.mark.asyncio
    async def test_unknown_prompt_uses_default(self, mock_config):
        """Unmatched prompt should use the default mock response."""
        provider = MockLLMProvider(mock_config)
        provider.register_response("specific", "Specific response")
        session = LLMClientSession(provider, mock_config)

        request = LLMRequest(prompt="Completely unrelated prompt")
        response = await session.generate(request)
        # Default response starts with "Mock response to:"
        assert response.content.startswith("Mock response to:")

    def test_scenario_registration_count(self, mock_config):
        """register_planner_scenarios() should register 9 scenarios."""
        provider = MockLLMProvider(mock_config)
        register_planner_scenarios(provider)
        assert len(provider._response_registry) == 9

    def test_default_scenario_registration_count(self, mock_config):
        """register_default_planner_scenario() should register 1 scenario."""
        provider = MockLLMProvider(mock_config)
        register_default_planner_scenario(provider)
        assert len(provider._response_registry) == 1

    def test_register_scenarios_wrong_type_raises(self):
        """Passing wrong type should raise TypeError."""
        with pytest.raises(TypeError):
            register_planner_scenarios("not a provider")

    def test_register_default_wrong_type_raises(self):
        """Passing wrong type should raise TypeError."""
        with pytest.raises(TypeError):
            register_default_planner_scenario("not a provider")


# ════════════════════════════════════════════════════════════════
#  ERROR DISTINCTION TESTS — Day 6 New Exception Types
# ════════════════════════════════════════════════════════════════


class TestErrorDistinctionDay6:
    """Tests for the new LLMParsingError and LLMSchemaValidationError types."""

    def test_parsing_error_inherits_from_response_error(self):
        """LLMParsingError should be a subclass of LLMResponseError."""
        assert issubclass(LLMParsingError, LLMResponseError)

    def test_schema_error_inherits_from_response_error(self):
        """LLMSchemaValidationError should be a subclass of LLMResponseError."""
        assert issubclass(LLMSchemaValidationError, LLMResponseError)

    def test_parsing_error_caught_by_response_error(self):
        """LLMParsingError should be caught by except LLMResponseError."""
        try:
            raise LLMParsingError("test", provider="mock")
        except LLMResponseError:
            pass  # Expected — backward compatible

    def test_schema_error_caught_by_response_error(self):
        """LLMSchemaValidationError should be caught by except LLMResponseError."""
        try:
            raise LLMSchemaValidationError("test", provider="mock")
        except LLMResponseError:
            pass  # Expected — backward compatible

    def test_parse_json_raises_parsing_error_on_malformed(self):
        """ResponseParser.parse_json should raise LLMParsingError for bad JSON."""
        response = LLMResponse(
            content="not valid json {[}",
            model="mock",
            provider="mock",
        )
        with pytest.raises(LLMParsingError, match="not valid JSON"):
            ResponseParser.parse_json(response)

    def test_parse_json_raises_parsing_error_on_array(self):
        """ResponseParser.parse_json should raise LLMParsingError for JSON arrays."""
        response = LLMResponse(
            content='[1, 2, 3]',
            model="mock",
            provider="mock",
        )
        with pytest.raises(LLMParsingError, match="JSON object"):
            ResponseParser.parse_json(response)

    def test_parse_json_raises_parsing_error_on_empty(self):
        """ResponseParser.parse_json should raise LLMParsingError for empty content."""
        response = LLMResponse(
            content="   ",
            model="mock",
            provider="mock",
        )
        with pytest.raises(LLMParsingError, match="empty response"):
            ResponseParser.parse_json(response)

    def test_parse_model_raises_schema_error(self):
        """ResponseParser.parse_model should raise LLMSchemaValidationError for wrong schema."""
        from pydantic import BaseModel, Field

        class StrictModel(BaseModel):
            required_field: str = Field(...)

        response = LLMResponse(
            content='{"wrong_field": "value"}',
            model="mock",
            provider="mock",
        )
        with pytest.raises(
            LLMSchemaValidationError, match="does not match schema"
        ):
            ResponseParser.parse_model(response, StrictModel)

    def test_parse_model_valid_schema(self):
        """ResponseParser.parse_model should return model instance for valid data."""
        from pydantic import BaseModel

        class SimpleModel(BaseModel):
            name: str
            value: int

        response = LLMResponse(
            content='{"name": "test", "value": 42}',
            model="mock",
            provider="mock",
        )
        result = ResponseParser.parse_model(response, SimpleModel)
        assert result.name == "test"
        assert result.value == 42

    def test_parse_json_valid(self):
        """ResponseParser.parse_json should return dict for valid JSON."""
        response = LLMResponse(
            content='{"key": "value"}',
            model="mock",
            provider="mock",
        )
        data = ResponseParser.parse_json(response)
        assert data == {"key": "value"}

    @pytest.mark.asyncio
    async def test_generate_json_malformed_raises_parsing_error(
        self, mock_config
    ):
        """LLMClientSession.generate_json should raise LLMResponseError
        for malformed JSON (the generate_json method catches and re-wraps).
        """
        provider = MockLLMProvider(mock_config, responses=["not json"])
        session = LLMClientSession(provider, mock_config)
        request = LLMRequest(prompt="test", response_format="json")
        with pytest.raises(LLMResponseError):
            await session.generate_json(request)

    @pytest.mark.asyncio
    async def test_generate_json_valid_returns_dict(self, mock_config):
        """LLMClientSession.generate_json should return dict for valid JSON."""
        json_str = json.dumps({"key": "value"})
        provider = MockLLMProvider(mock_config, responses=[json_str])
        session = LLMClientSession(provider, mock_config)
        request = LLMRequest(prompt="test")
        result = await session.generate_json(request)
        assert result == {"key": "value"}


# ════════════════════════════════════════════════════════════════
#  RESPONSE VALIDATION — MISSING FIELDS / TYPES
# ════════════════════════════════════════════════════════════════


class TestResponseFieldValidationDay6:
    """Tests for response field validation beyond the and→or fix."""

    def test_missing_fields_in_json_rejected(self):
        """JSON with missing required test plan fields should be rejected."""
        response = LLMResponse(
            content='{"random": "data"}',
            model="mock",
            provider="mock",
        )
        data = ResponseParser.parse_json(response)
        # Trying to parse as TestPlan should fail
        with pytest.raises(TestPlanValidationError):
            LLMTestPlanner._parse_response(data)

    def test_wrong_type_in_json_rejected(self):
        """JSON with wrong field types should be rejected."""
        bad_data = {
            "application_name": 12345,  # Should be string
            "test_cases": "not a list",  # Should be list
        }
        # TestPlan will reject wrong types at parse time
        with pytest.raises(TestPlanValidationError):
            LLMTestPlanner._parse_response(bad_data)

    def test_unexpected_structure_rejected(self):
        """Completely unexpected JSON structure should be rejected."""
        with pytest.raises(TestPlanValidationError):
            LLMTestPlanner._parse_response({"items": [1, 2, 3]})

    def test_empty_dict_rejected(self):
        """Empty dict should be rejected."""
        with pytest.raises(TestPlanValidationError):
            LLMTestPlanner._parse_response({})

    @pytest.mark.asyncio
    async def test_malformed_json_in_pipeline_raises(self, sample_context):
        """Malformed JSON response in the full pipeline should raise."""
        planner, provider = create_test_planner()
        provider.register_response(
            "Generate up to", INVALID_MALFORMED_RESPONSE
        )
        with pytest.raises(LLMResponseError):
            await planner.generate_tests(sample_context)


# ════════════════════════════════════════════════════════════════
#  FULL PIPELINE VERIFICATION — Day 6
# ════════════════════════════════════════════════════════════════


class TestFullPipelineDay6:
    """End-to-end pipeline verification using register_planner_scenarios().

    This verifies the complete flow:
        ApplicationContext → TestPlanner → PromptBuilder → LLMClient
        → MockLLMProvider → Response Normalization → Response Validation
        → Structured TestPlan → Business Rule Validation
    """

    @pytest.mark.asyncio
    async def test_full_pipeline_via_register_planner_scenarios(self):
        """Complete pipeline using register_planner_scenarios().

        This is the critical integration test — it verifies that
        register_planner_scenarios() works with the real prompt
        generated by the planner, not with manually registered keys.
        """
        # 1. Create application context
        context = create_sample_login_context()

        # 2. Set up planner with mock provider
        planner, provider = create_test_planner()

        # 3. Use register_planner_scenarios() — NOT manual registration
        register_planner_scenarios(provider)

        # 4. Generate test plan
        plan = await planner.generate_test_plan(context)

        # 5. Verify the TestPlan structure
        assert isinstance(plan, TestPlan)
        assert plan.application_name == "Demo Application"
        assert plan.base_url == "http://localhost:3000"
        assert len(plan.test_cases) > 0

        # 6. Verify each test case has valid structure
        for tc in plan.test_cases:
            assert tc.test_id and tc.test_id.strip()
            assert tc.name and tc.name.strip()
            assert isinstance(tc.category, TestCategory)
            assert isinstance(tc.priority, TestPriority)
            assert len(tc.steps) > 0

            for step in tc.steps:
                assert isinstance(step.action, TestAction)

            for assertion in tc.assertions:
                assert isinstance(assertion.type, AssertionType)

        # 7. Verify element references are valid
        for tc in plan.test_cases:
            ref_errors = validate_element_references(tc, context)
            assert len(ref_errors) == 0, (
                f"Test case '{tc.test_id}' has unknown element "
                f"references: {ref_errors}"
            )

        # 8. Verify no duplicates
        dup_indices = detect_duplicate_test_cases(plan.test_cases)
        assert len(dup_indices) == 0

        # 9. Verify provider was called
        assert provider.call_count == 1

    @pytest.mark.asyncio
    async def test_pipeline_rejects_whitespace_response(self):
        """Pipeline should reject whitespace-only provider responses.

        Regression test: Before Day 6 fix, this would silently pass
        through _normalize_response and crash later in JSON parsing.
        """
        config = create_mock_config()
        provider = MockLLMProvider(config, responses=["   \n\t   "])
        session = LLMClientSession(provider, config)
        planner = LLMTestPlanner(session)
        context = create_sample_login_context()

        with pytest.raises(LLMResponseError, match="empty response"):
            await planner.generate_tests(context)

    @pytest.mark.asyncio
    async def test_pipeline_rejects_empty_response(self):
        """Pipeline should reject empty string provider responses."""
        config = create_mock_config()
        provider = MockLLMProvider(config, responses=[""])
        session = LLMClientSession(provider, config)
        planner = LLMTestPlanner(session)
        context = create_sample_login_context()

        with pytest.raises(LLMResponseError, match="empty response"):
            await planner.generate_tests(context)

    @pytest.mark.asyncio
    async def test_pipeline_valid_response_produces_valid_plan(self):
        """Valid response through full pipeline should produce valid plan."""
        planner, provider = create_test_planner()
        register_default_planner_scenario(provider)
        context = create_sample_login_context()

        test_cases = await planner.generate_tests(context)
        assert len(test_cases) > 0

        # Verify all returned cases are valid
        from agents.planner.validation import validate_test_case

        for tc in test_cases:
            errors = validate_test_case(tc)
            assert len(errors) == 0, (
                f"Test case '{tc.test_id}' failed validation: {errors}"
            )

    @pytest.mark.asyncio
    async def test_pipeline_error_responses_propagate(self):
        """Provider errors should propagate clearly through the pipeline."""
        config = create_mock_config()
        provider = MockLLMProvider(config, simulate="error")
        session = LLMClientSession(provider, config)
        planner = LLMTestPlanner(session)
        context = create_sample_login_context()

        with pytest.raises(LLMProviderError):
            await planner.generate_tests(context)

    @pytest.mark.asyncio
    async def test_pipeline_malformed_json_raises_clearly(self):
        """Malformed JSON should raise LLMResponseError, not crash."""
        planner, provider = create_test_planner()
        provider.register_response(
            "Generate up to",
            "This is not JSON at all",
        )
        context = create_sample_login_context()

        with pytest.raises(LLMResponseError):
            await planner.generate_tests(context)
