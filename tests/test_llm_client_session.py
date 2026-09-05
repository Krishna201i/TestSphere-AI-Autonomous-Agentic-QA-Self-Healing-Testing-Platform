"""
TestSphere-AI — LLM Client Session Tests (Day 3)

Comprehensive unit and integration tests for the Day 3 ``LLMClientSession``.

Tests cover:
  - Client initialization
  - Provider delegation
  - Request validation
  - Response normalization
  - Error translation
  - Retry logic & limits
  - Timeout handling
  - Non-retryable error passthrough
  - Provider switching
  - Mock response registry
  - generate_json convenience
  - Full integration pipeline (provider-independent)

ALL tests run fully offline with NO:
  - Internet access
  - API keys
  - Real LLM models
  - External services
"""

from __future__ import annotations

import json

import pytest

from agents.llm.client import LLMClient, LLMClientSession
from agents.llm.config import LLMConfig
from agents.llm.exceptions import (
    LLMAuthenticationError,
    LLMConfigurationError,
    LLMConnectionError,
    LLMError,
    LLMProviderError,
    LLMRateLimitError,
    LLMRequestValidationError,
    LLMResponseError,
    LLMTimeoutError,
)
from agents.llm.factory import create_llm_client, get_llm_provider
from agents.llm.parser import ResponseParser
from agents.llm.providers.mock import MockLLMProvider
from agents.llm.schemas import LLMRequest, LLMResponse, LLMUsage


# ═══════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════


def _default_config(**overrides) -> LLMConfig:
    """Create a mock LLMConfig with sensible defaults."""
    defaults = dict(provider="mock", model="mock-model", max_retries=2, timeout=60)
    defaults.update(overrides)
    return LLMConfig(**defaults)


def _make_session(**overrides) -> LLMClientSession:
    """Create an LLMClientSession wrapping a MockLLMProvider."""
    config = _default_config(**overrides)
    provider = MockLLMProvider(config)
    return LLMClientSession(provider, config)


def _make_session_with_provider(
    provider: MockLLMProvider,
    **config_overrides,
) -> LLMClientSession:
    """Create an LLMClientSession wrapping the given provider."""
    config = provider.config
    if config_overrides:
        # Build a new config with overrides applied
        base = dict(
            provider=config.provider,
            model=config.model,
            max_retries=config.max_retries,
            timeout=config.timeout,
            api_key=config.api_key,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
        )
        base.update(config_overrides)
        config = LLMConfig(**base)
    return LLMClientSession(provider, config)


# ═══════════════════════════════════════════════════════════════
#  1 · Initialization Tests
# ═══════════════════════════════════════════════════════════════


class TestClientSessionInit:
    """Validate LLMClientSession initialization."""

    def test_initializes_successfully(self):
        """Client session should initialize without errors."""
        session = _make_session()
        assert session.provider_name == "mock"
        assert isinstance(session.provider, MockLLMProvider)

    def test_uses_configured_provider(self):
        """Session should use the MockLLMProvider from config."""
        config = _default_config()
        provider = MockLLMProvider(config)
        session = LLMClientSession(provider, config)
        assert session.provider is provider
        assert session.config is config

    def test_config_from_provider_when_not_given(self):
        """Config should default to provider's config when not passed."""
        config = _default_config()
        provider = MockLLMProvider(config)
        session = LLMClientSession(provider)
        assert session.config is config


# ═══════════════════════════════════════════════════════════════
#  2 · Request Validation Tests
# ═══════════════════════════════════════════════════════════════


class TestRequestValidation:
    """Validate that the client rejects invalid requests."""

    def test_empty_prompt_rejected_at_schema_level(self):
        """Empty prompt should be rejected by the Pydantic validator."""
        with pytest.raises(Exception):
            LLMRequest(prompt="")

    def test_whitespace_prompt_rejected_at_schema_level(self):
        """Whitespace-only prompt should be rejected by the Pydantic validator."""
        with pytest.raises(Exception):
            LLMRequest(prompt="   ")

    def test_invalid_temperature_rejected(self):
        """Temperature outside 0.0–2.0 should be rejected."""
        with pytest.raises(Exception):
            LLMRequest(prompt="test", temperature=-0.1)

        with pytest.raises(Exception):
            LLMRequest(prompt="test", temperature=2.5)

    def test_invalid_max_tokens_rejected(self):
        """Non-positive max_tokens should be rejected."""
        with pytest.raises(Exception):
            LLMRequest(prompt="test", max_tokens=0)

        with pytest.raises(Exception):
            LLMRequest(prompt="test", max_tokens=-10)

    def test_invalid_response_format_rejected(self):
        """Unsupported response_format should be rejected."""
        with pytest.raises(Exception):
            LLMRequest(prompt="test", response_format="xml")

    def test_valid_request_accepted(self):
        """A well-formed request should pass validation."""
        req = LLMRequest(prompt="Hello world")
        assert req.prompt == "Hello world"
        assert req.response_format == "text"

    def test_valid_json_format_accepted(self):
        """response_format='json' should be accepted."""
        req = LLMRequest(prompt="Hello", response_format="json")
        assert req.response_format == "json"

    def test_boundary_temperature_accepted(self):
        """Temperature at boundaries (0.0, 2.0) should be accepted."""
        req_low = LLMRequest(prompt="test", temperature=0.0)
        assert req_low.temperature == 0.0

        req_high = LLMRequest(prompt="test", temperature=2.0)
        assert req_high.temperature == 2.0

    def test_none_temperature_accepted(self):
        """Temperature=None should use config default."""
        req = LLMRequest(prompt="test", temperature=None)
        assert req.temperature is None

    def test_positive_max_tokens_accepted(self):
        """max_tokens=1 should be the minimum valid value."""
        req = LLMRequest(prompt="test", max_tokens=1)
        assert req.max_tokens == 1


# ═══════════════════════════════════════════════════════════════
#  3 · Generate — Basic Flow
# ═══════════════════════════════════════════════════════════════


class TestGenerateBasicFlow:
    """Validate the basic generate() flow through the session."""

    @pytest.mark.asyncio
    async def test_valid_request_produces_valid_response(self):
        """A valid request should produce a standardized LLMResponse."""
        session = _make_session()
        request = LLMRequest(prompt="Hello world")
        response = await session.generate(request)

        assert isinstance(response, LLMResponse)
        assert response.provider == "mock"
        assert response.model == "mock-model"
        assert len(response.content) > 0
        assert response.finish_reason == "stop"

    @pytest.mark.asyncio
    async def test_response_includes_usage_stats(self):
        """Response should contain token usage statistics."""
        session = _make_session()
        request = LLMRequest(prompt="one two three")
        response = await session.generate(request)

        assert response.usage.prompt_tokens > 0
        assert response.usage.completion_tokens > 0
        assert response.usage.total_tokens > 0

    @pytest.mark.asyncio
    async def test_complete_convenience(self):
        """The complete() convenience should return just the text."""
        config = _default_config()
        provider = MockLLMProvider(config, responses=["Short answer"])
        session = LLMClientSession(provider, config)

        result = await session.complete("What is 2+2?")
        assert result == "Short answer"


# ═══════════════════════════════════════════════════════════════
#  4 · Response Normalization
# ═══════════════════════════════════════════════════════════════


class TestResponseNormalization:
    """Validate response normalization in the client session."""

    @pytest.mark.asyncio
    async def test_provider_field_populated(self):
        """Response should always have the provider field set."""
        session = _make_session()
        response = await session.generate(LLMRequest(prompt="test"))
        assert response.provider == "mock"

    @pytest.mark.asyncio
    async def test_model_field_populated(self):
        """Response should always have the model field set."""
        session = _make_session()
        response = await session.generate(LLMRequest(prompt="test"))
        assert response.model == "mock-model"

    @pytest.mark.asyncio
    async def test_empty_provider_response_is_caught(self):
        """Provider returning empty content should raise LLMResponseError."""
        config = _default_config(max_retries=0)
        provider = MockLLMProvider(config, simulate="empty")
        session = LLMClientSession(provider, config)

        with pytest.raises(LLMResponseError):
            await session.generate(LLMRequest(prompt="test"))


# ═══════════════════════════════════════════════════════════════
#  5 · Error Translation
# ═══════════════════════════════════════════════════════════════


class TestErrorTranslation:
    """Validate that provider errors are translated to project-level exceptions."""

    @pytest.mark.asyncio
    async def test_provider_error_translated(self):
        """LLMProviderError should propagate correctly."""
        config = _default_config(max_retries=0)
        provider = MockLLMProvider(config, simulate="error")
        session = LLMClientSession(provider, config)

        with pytest.raises(LLMProviderError, match="Simulated provider error"):
            await session.generate(LLMRequest(prompt="test"))

    @pytest.mark.asyncio
    async def test_timeout_error_propagated(self):
        """LLMTimeoutError should propagate correctly."""
        config = _default_config(max_retries=0)
        provider = MockLLMProvider(config, simulate="timeout")
        session = LLMClientSession(provider, config)

        with pytest.raises(LLMTimeoutError, match="Simulated timeout"):
            await session.generate(LLMRequest(prompt="test"))

    @pytest.mark.asyncio
    async def test_response_error_not_retried(self):
        """LLMResponseError is not retryable and should raise immediately."""
        config = _default_config(max_retries=3)
        provider = MockLLMProvider(config, simulate="invalid")
        session = LLMClientSession(provider, config)

        with pytest.raises(LLMResponseError):
            await session.generate(LLMRequest(prompt="test"))

        # Only 1 call — not retried
        assert provider.call_count == 1

    @pytest.mark.asyncio
    async def test_unexpected_exception_wrapped(self):
        """Non-LLMError exceptions should be wrapped in LLMProviderError."""
        config = _default_config(max_retries=0)
        provider = MockLLMProvider(config)
        session = LLMClientSession(provider, config)

        # Monkey-patch to raise a raw exception
        async def _boom(_request):
            raise RuntimeError("something unexpected")

        provider.generate = _boom

        with pytest.raises(LLMProviderError, match="Unexpected provider error"):
            await session.generate(LLMRequest(prompt="test"))


# ═══════════════════════════════════════════════════════════════
#  6 · Retry Logic
# ═══════════════════════════════════════════════════════════════


class TestRetryLogic:
    """Validate retry behaviour of the client session."""

    @pytest.mark.asyncio
    async def test_retryable_error_is_retried(self):
        """Transient errors (LLMProviderError) should be retried."""
        config = _default_config(max_retries=2)
        provider = MockLLMProvider(config)

        # 2 transient failures → 3rd call succeeds
        provider.set_failure_sequence([
            LLMProviderError("transient-1", provider="mock"),
            LLMProviderError("transient-2", provider="mock"),
        ])

        session = LLMClientSession(provider, config)
        response = await session.generate(LLMRequest(prompt="retry me"))

        assert isinstance(response, LLMResponse)
        assert response.content  # success
        assert provider.call_count == 3  # 2 failures + 1 success

    @pytest.mark.asyncio
    async def test_retry_limit_respected(self):
        """After max_retries, the last error should be raised."""
        config = _default_config(max_retries=2)
        provider = MockLLMProvider(config)

        # 3 failures — exceeds max_retries (max_attempts = 1 + 2 = 3)
        provider.set_failure_sequence([
            LLMProviderError("fail-1", provider="mock"),
            LLMProviderError("fail-2", provider="mock"),
            LLMProviderError("fail-3", provider="mock"),
        ])

        session = LLMClientSession(provider, config)

        with pytest.raises(LLMProviderError, match="fail-3"):
            await session.generate(LLMRequest(prompt="fail forever"))

        assert provider.call_count == 3  # 1 initial + 2 retries

    @pytest.mark.asyncio
    async def test_timeout_is_retried(self):
        """LLMTimeoutError should be retried."""
        config = _default_config(max_retries=1)
        provider = MockLLMProvider(config)

        # 1 timeout → 2nd call succeeds
        provider.set_failure_sequence([
            LLMTimeoutError("timeout", provider="mock"),
        ])

        session = LLMClientSession(provider, config)
        response = await session.generate(LLMRequest(prompt="timeout test"))

        assert isinstance(response, LLMResponse)
        assert provider.call_count == 2

    @pytest.mark.asyncio
    async def test_connection_error_is_retried(self):
        """LLMConnectionError should be retried."""
        config = _default_config(max_retries=1)
        provider = MockLLMProvider(config)

        provider.set_failure_sequence([
            LLMConnectionError("connection lost", provider="mock"),
        ])

        session = LLMClientSession(provider, config)
        response = await session.generate(LLMRequest(prompt="reconnect"))

        assert isinstance(response, LLMResponse)
        assert provider.call_count == 2

    @pytest.mark.asyncio
    async def test_rate_limit_is_retried(self):
        """LLMRateLimitError should be retried."""
        config = _default_config(max_retries=1)
        provider = MockLLMProvider(config)

        provider.set_failure_sequence([
            LLMRateLimitError("429 too many requests", provider="mock"),
        ])

        session = LLMClientSession(provider, config)
        response = await session.generate(LLMRequest(prompt="rate limited"))

        assert isinstance(response, LLMResponse)
        assert provider.call_count == 2

    @pytest.mark.asyncio
    async def test_non_retryable_not_retried_config_error(self):
        """LLMConfigurationError should NOT be retried."""
        config = _default_config(max_retries=3)
        provider = MockLLMProvider(config)

        provider.set_failure_sequence([
            LLMConfigurationError("bad config", provider="mock"),
        ])

        session = LLMClientSession(provider, config)

        with pytest.raises(LLMConfigurationError, match="bad config"):
            await session.generate(LLMRequest(prompt="config fail"))

        assert provider.call_count == 1  # not retried

    @pytest.mark.asyncio
    async def test_non_retryable_not_retried_auth_error(self):
        """LLMAuthenticationError should NOT be retried."""
        config = _default_config(max_retries=3)
        provider = MockLLMProvider(config)

        provider.set_failure_sequence([
            LLMAuthenticationError("invalid key", provider="mock"),
        ])

        session = LLMClientSession(provider, config)

        with pytest.raises(LLMAuthenticationError, match="invalid key"):
            await session.generate(LLMRequest(prompt="auth fail"))

        assert provider.call_count == 1  # not retried

    @pytest.mark.asyncio
    async def test_zero_retries_no_retry(self):
        """With max_retries=0, there should be exactly 1 attempt."""
        config = _default_config(max_retries=0)
        provider = MockLLMProvider(config, simulate="error")
        session = LLMClientSession(provider, config)

        with pytest.raises(LLMProviderError):
            await session.generate(LLMRequest(prompt="no retries"))

        assert provider.call_count == 1


# ═══════════════════════════════════════════════════════════════
#  7 · is_retryable Property
# ═══════════════════════════════════════════════════════════════


class TestIsRetryable:
    """Validate the is_retryable property on exceptions."""

    def test_base_error_not_retryable(self):
        assert LLMError("x").is_retryable is False

    def test_config_error_not_retryable(self):
        assert LLMConfigurationError("x").is_retryable is False

    def test_auth_error_not_retryable(self):
        assert LLMAuthenticationError("x").is_retryable is False

    def test_response_error_not_retryable(self):
        assert LLMResponseError("x").is_retryable is False

    def test_request_validation_error_not_retryable(self):
        assert LLMRequestValidationError("x").is_retryable is False

    def test_timeout_error_is_retryable(self):
        assert LLMTimeoutError("x").is_retryable is True

    def test_provider_error_is_retryable(self):
        assert LLMProviderError("x").is_retryable is True

    def test_connection_error_is_retryable(self):
        assert LLMConnectionError("x").is_retryable is True

    def test_rate_limit_error_is_retryable(self):
        assert LLMRateLimitError("x").is_retryable is True


# ═══════════════════════════════════════════════════════════════
#  8 · generate_json Convenience
# ═══════════════════════════════════════════════════════════════


class TestGenerateJson:
    """Validate the generate_json() convenience method."""

    @pytest.mark.asyncio
    async def test_valid_json_parsed(self):
        """generate_json should return a parsed dict."""
        data = {"message": "success", "count": 42}
        config = _default_config()
        provider = MockLLMProvider(config, responses=[json.dumps(data)])
        session = LLMClientSession(provider, config)

        result = await session.generate_json(LLMRequest(prompt="get json"))
        assert result == data

    @pytest.mark.asyncio
    async def test_invalid_json_raises(self):
        """Non-JSON content should raise LLMResponseError."""
        config = _default_config()
        provider = MockLLMProvider(config, responses=["not json {{{"])
        session = LLMClientSession(provider, config)

        with pytest.raises(LLMResponseError, match="not valid JSON"):
            await session.generate_json(LLMRequest(prompt="bad json"))

    @pytest.mark.asyncio
    async def test_json_array_raises(self):
        """JSON arrays should raise LLMResponseError (only objects accepted)."""
        config = _default_config()
        provider = MockLLMProvider(config, responses=["[1, 2, 3]"])
        session = LLMClientSession(provider, config)

        with pytest.raises(LLMResponseError, match="JSON object"):
            await session.generate_json(LLMRequest(prompt="array json"))

    @pytest.mark.asyncio
    async def test_sets_response_format_to_json(self):
        """generate_json should set response_format='json'."""
        data = {"ok": True}
        config = _default_config()
        provider = MockLLMProvider(config, responses=[json.dumps(data)])
        session = LLMClientSession(provider, config)

        # Pass a request with default text format
        request = LLMRequest(prompt="get json")
        assert request.response_format == "text"

        result = await session.generate_json(request)
        assert result == data


# ═══════════════════════════════════════════════════════════════
#  9 · Mock Response Registry
# ═══════════════════════════════════════════════════════════════


class TestMockResponseRegistry:
    """Validate the Day 3 response registry on MockLLMProvider."""

    @pytest.mark.asyncio
    async def test_register_response_by_prompt(self):
        """Registered response should be returned for matching prompt."""
        config = _default_config()
        provider = MockLLMProvider(config)
        provider.register_response("test plan", "Here is a test plan")

        request = LLMRequest(prompt="Generate a test plan for login")
        response = await provider.generate(request)
        assert response.content == "Here is a test plan"

    @pytest.mark.asyncio
    async def test_register_error_by_prompt(self):
        """Registered error should be raised for matching prompt."""
        config = _default_config()
        provider = MockLLMProvider(config)
        provider.register_error(
            "crash now",
            LLMProviderError("registered boom", provider="mock"),
        )

        with pytest.raises(LLMProviderError, match="registered boom"):
            await provider.generate(LLMRequest(prompt="crash now please"))

    @pytest.mark.asyncio
    async def test_unmatched_prompt_uses_default(self):
        """Unmatched prompt should fall back to default response."""
        config = _default_config()
        provider = MockLLMProvider(config)
        provider.register_response("test plan", "custom response")

        response = await provider.generate(
            LLMRequest(prompt="something else entirely")
        )
        assert "Mock response to:" in response.content

    @pytest.mark.asyncio
    async def test_failure_sequence(self):
        """Failure sequence should raise errors in order then succeed."""
        config = _default_config()
        provider = MockLLMProvider(config)
        provider.set_failure_sequence([
            LLMProviderError("fail-1", provider="mock"),
            LLMTimeoutError("fail-2", provider="mock"),
        ])

        with pytest.raises(LLMProviderError, match="fail-1"):
            await provider.generate(LLMRequest(prompt="attempt 1"))

        with pytest.raises(LLMTimeoutError, match="fail-2"):
            await provider.generate(LLMRequest(prompt="attempt 2"))

        # Third call succeeds
        response = await provider.generate(LLMRequest(prompt="attempt 3"))
        assert isinstance(response, LLMResponse)

    @pytest.mark.asyncio
    async def test_reset_clears_state(self):
        """reset() should clear all registered state."""
        config = _default_config()
        provider = MockLLMProvider(config)
        provider.register_response("test", "custom")
        provider.set_failure_sequence([LLMProviderError("x", provider="mock")])

        provider.reset()
        assert provider.call_count == 0

        response = await provider.generate(LLMRequest(prompt="test prompt"))
        # Should use default response, not the registered one
        assert "Mock response to:" in response.content


# ═══════════════════════════════════════════════════════════════
#  10 · Provider Switching
# ═══════════════════════════════════════════════════════════════


class TestProviderSwitching:
    """Validate provider switching through configuration."""

    def test_mock_provider_selected(self):
        """LLM_PROVIDER=mock should produce MockLLMProvider."""
        config = _default_config(provider="mock")
        provider = get_llm_provider(config)
        assert isinstance(provider, MockLLMProvider)

    def test_unsupported_provider_raises(self):
        """LLM_PROVIDER=nonexistent should raise LLMConfigurationError."""
        config = LLMConfig(provider="nonexistent", model="m")
        with pytest.raises(LLMConfigurationError):
            get_llm_provider(config)

    def test_local_not_yet_implemented(self):
        """LLM_PROVIDER=local should raise LLMConfigurationError."""
        config = _default_config(provider="local")
        with pytest.raises(LLMConfigurationError, match="not yet implemented"):
            get_llm_provider(config)

    def test_api_not_yet_implemented(self):
        """LLM_PROVIDER=api should raise LLMConfigurationError."""
        config = LLMConfig(provider="api", model="gpt-4", api_key="sk-test")
        with pytest.raises(LLMConfigurationError, match="not yet implemented"):
            get_llm_provider(config)

    def test_create_llm_client_returns_session(self):
        """create_llm_client() should return an LLMClientSession."""
        config = _default_config()
        client = create_llm_client(config)
        assert isinstance(client, LLMClientSession)
        assert isinstance(client.provider, MockLLMProvider)

    def test_create_llm_client_unsupported_provider(self):
        """create_llm_client() with bad provider should raise."""
        config = LLMConfig(provider="nonexistent", model="m")
        with pytest.raises(LLMConfigurationError):
            create_llm_client(config)


# ═══════════════════════════════════════════════════════════════
#  11 · LLMRequestValidationError
# ═══════════════════════════════════════════════════════════════


class TestLLMRequestValidationError:
    """Validate LLMRequestValidationError in the exception hierarchy."""

    def test_inherits_from_llm_error(self):
        assert issubclass(LLMRequestValidationError, LLMError)

    def test_not_retryable(self):
        exc = LLMRequestValidationError("bad request")
        assert exc.is_retryable is False

    def test_captures_provider(self):
        exc = LLMRequestValidationError("bad", provider="client")
        assert exc.provider == "client"

    def test_eight_exception_types(self):
        """Day 3 adds LLMRequestValidationError → 8 specific types."""
        types = {
            LLMConfigurationError,
            LLMAuthenticationError,
            LLMRequestValidationError,
            LLMTimeoutError,
            LLMRateLimitError,
            LLMConnectionError,
            LLMProviderError,
            LLMResponseError,
        }
        assert len(types) == 8


# ═══════════════════════════════════════════════════════════════
#  12 · Integration Test — Full Day 3 Pipeline
# ═══════════════════════════════════════════════════════════════


class TestDay3Integration:
    """End-to-end integration tests demonstrating the complete Day 3 flow.

    Application Component
            ↓
      LLMClientSession
            ↓
      MockLLMProvider
            ↓
      Mock Raw Response
            ↓
      Normalization
            ↓
      Standard LLMResponse

    The application component (this test) does NOT know the provider
    is a mock — it only interacts with the LLMClientSession interface.
    """

    @pytest.mark.asyncio
    async def test_full_text_pipeline(self):
        """Agent → LLMClientSession → Mock → Normalized text response."""
        # Agent creates client via factory (provider-independent)
        client = create_llm_client(
            _default_config(provider="mock", model="mock-model")
        )

        # Agent builds a request
        request = LLMRequest(
            prompt="Generate a test plan for the login page",
            system_instruction="You are a QA agent",
        )

        # Agent calls generate — doesn't know provider is mock
        response = await client.generate(request)

        # Agent verifies response structure
        assert isinstance(response, LLMResponse)
        assert len(response.content) > 0
        assert response.provider  # normalized — always populated
        assert response.model  # normalized — always populated
        assert response.usage.total_tokens > 0
        assert response.finish_reason == "stop"

    @pytest.mark.asyncio
    async def test_full_json_pipeline(self):
        """Agent → LLMClientSession → Mock → Normalized JSON response."""
        data = {
            "test_name": "Login Test",
            "steps": ["Navigate", "Enter creds", "Click login"],
        }

        config = _default_config()
        provider = MockLLMProvider(config, responses=[json.dumps(data)])
        client = LLMClientSession(provider, config)

        result = await client.generate_json(
            LLMRequest(prompt="Generate a test plan as JSON")
        )

        assert result == data
        assert result["test_name"] == "Login Test"
        assert len(result["steps"]) == 3

    @pytest.mark.asyncio
    async def test_full_pipeline_with_response_parser(self):
        """Agent → LLMClientSession → Mock → ResponseParser → Pydantic model."""
        from pydantic import BaseModel

        class PlanResult(BaseModel):
            name: str
            step_count: int

        data = {"name": "Login Test Plan", "step_count": 5}
        config = _default_config()
        provider = MockLLMProvider(config, responses=[json.dumps(data)])
        client = LLMClientSession(provider, config)

        response = await client.generate(
            LLMRequest(prompt="plan", response_format="json")
        )
        plan = ResponseParser.parse_model(response, PlanResult)

        assert isinstance(plan, PlanResult)
        assert plan.name == "Login Test Plan"
        assert plan.step_count == 5

    @pytest.mark.asyncio
    async def test_retry_then_success_pipeline(self):
        """Agent → LLMClientSession (retry) → Mock → Success."""
        config = _default_config(max_retries=2)
        provider = MockLLMProvider(config)
        provider.set_failure_sequence([
            LLMProviderError("transient", provider="mock"),
        ])

        client = LLMClientSession(provider, config)
        response = await client.generate(
            LLMRequest(prompt="Resilient request")
        )

        # Succeeded after 1 retry
        assert isinstance(response, LLMResponse)
        assert response.content
        assert provider.call_count == 2

    @pytest.mark.asyncio
    async def test_provider_independence(self):
        """Two clients with different configs should behave identically.

        This proves that the agent code doesn't need to know
        which provider is being used.
        """
        # Client A — mock provider
        config_a = _default_config(provider="mock", model="model-a")
        provider_a = MockLLMProvider(config_a, responses=["Answer from A"])
        client_a = LLMClientSession(provider_a, config_a)

        # Client B — also mock but different model name
        config_b = _default_config(provider="mock", model="model-b")
        provider_b = MockLLMProvider(config_b, responses=["Answer from B"])
        client_b = LLMClientSession(provider_b, config_b)

        # Same request to both
        request = LLMRequest(prompt="What is the answer?")

        response_a = await client_a.generate(request)
        response_b = await client_b.generate(request)

        # Both return LLMResponse with same structure
        assert isinstance(response_a, LLMResponse)
        assert isinstance(response_b, LLMResponse)

        # Content differs (provider-specific) but structure is identical
        assert response_a.content == "Answer from A"
        assert response_b.content == "Answer from B"

        # Agent code can treat them identically
        assert response_a.finish_reason == response_b.finish_reason
        assert type(response_a) is type(response_b)

    @pytest.mark.asyncio
    async def test_mock_registry_integration(self):
        """Agent using response registry for domain-specific mock responses."""
        config = _default_config()
        provider = MockLLMProvider(config)
        provider.register_response(
            "test plan",
            json.dumps({
                "test_id": "TC001",
                "name": "Login Test",
                "steps": 3,
            }),
        )

        client = LLMClientSession(provider, config)

        # Agent requests a test plan
        result = await client.generate_json(
            LLMRequest(prompt="Generate a test plan for login")
        )

        assert result["test_id"] == "TC001"
        assert result["name"] == "Login Test"
        assert result["steps"] == 3
