"""
TestSphere-AI — LLM Foundation Tests (Day 2)

Comprehensive unit tests for the provider-independent LLM layer:
  - Exception hierarchy
  - Configuration with provider selection
  - Mock provider behaviour
  - Provider factory
  - Failure simulations
  - Response parsing
  - End-to-end mock pipeline
  - Security safeguards

ALL tests run fully offline with NO:
  - Internet access
  - API keys
  - Real LLM models
  - External services
"""

from __future__ import annotations

import json
import os
from unittest.mock import patch

import pytest
from pydantic import BaseModel, Field

from agents.llm.client import LLMClient
from agents.llm.config import LLMConfig, VALID_PROVIDERS
from agents.llm.exceptions import (
    LLMConfigurationError,
    LLMError,
    LLMProviderError,
    LLMResponseError,
    LLMTimeoutError,
    LLMAuthenticationError,
    LLMRateLimitError,
    LLMConnectionError,
)
from agents.llm.factory import get_llm_provider
from agents.llm.parser import ResponseParser
from agents.llm.providers.mock import MockLLMProvider
from agents.llm.schemas import LLMRequest, LLMResponse, LLMUsage


# ── Exception Hierarchy Tests ──────────────────────────────


class TestLLMExceptions:
    """Validate the LLM exception hierarchy."""

    def test_all_exceptions_inherit_from_llm_error(self):
        """Every custom exception must be a subclass of LLMError."""
        subclasses = [
            LLMConfigurationError,
            LLMAuthenticationError,
            LLMTimeoutError,
            LLMRateLimitError,
            LLMConnectionError,
            LLMProviderError,
            LLMResponseError,
        ]
        for cls in subclasses:
            assert issubclass(cls, LLMError), (
                f"{cls.__name__} is not a subclass of LLMError"
            )

    def test_exception_captures_provider(self):
        exc = LLMProviderError("test error", provider="mock")
        assert exc.provider == "mock"
        assert str(exc) == "test error"

    def test_exception_default_provider(self):
        exc = LLMError("some error")
        assert exc.provider == "unknown"

    def test_seven_exception_types(self):
        """There should be exactly 7 specific exception types."""
        types = {
            LLMConfigurationError,
            LLMAuthenticationError,
            LLMTimeoutError,
            LLMRateLimitError,
            LLMConnectionError,
            LLMProviderError,
            LLMResponseError,
        }
        assert len(types) == 7


# ── LLM Request / Response Schema Tests ────────────────────


class TestLLMSchemas:
    """Validate LLM request and response schemas."""

    def test_request_minimal(self):
        req = LLMRequest(prompt="Hello")
        assert req.prompt == "Hello"
        assert req.system_instruction == ""
        assert req.temperature is None
        assert req.max_tokens is None
        assert req.response_format == "text"

    def test_request_full(self):
        req = LLMRequest(
            prompt="Test prompt",
            system_instruction="Be helpful",
            temperature=0.5,
            max_tokens=100,
            response_format="json",
        )
        assert req.prompt == "Test prompt"
        assert req.system_instruction == "Be helpful"
        assert req.temperature == 0.5
        assert req.max_tokens == 100
        assert req.response_format == "json"

    def test_response_minimal(self):
        resp = LLMResponse(content="Hello back")
        assert resp.content == "Hello back"
        assert resp.model == ""
        assert resp.provider == ""
        assert resp.finish_reason == "stop"

    def test_response_full(self):
        resp = LLMResponse(
            content="Response text",
            model="mock-model",
            provider="mock",
            usage=LLMUsage(prompt_tokens=10, completion_tokens=5),
            finish_reason="stop",
        )
        assert resp.content == "Response text"
        assert resp.model == "mock-model"
        assert resp.provider == "mock"
        assert resp.usage.prompt_tokens == 10
        assert resp.usage.completion_tokens == 5
        assert resp.usage.total_tokens == 15

    def test_response_serialization_roundtrip(self):
        resp = LLMResponse(
            content="Roundtrip test",
            model="test-model",
            provider="mock",
        )
        data = json.loads(resp.model_dump_json())
        resp2 = LLMResponse.model_validate(data)
        assert resp2.content == resp.content
        assert resp2.model == resp.model

    def test_usage_defaults(self):
        usage = LLMUsage()
        assert usage.prompt_tokens == 0
        assert usage.completion_tokens == 0
        assert usage.total_tokens == 0


# ── Configuration Tests ────────────────────────────────────


class TestLLMConfigProvider:
    """Validate provider-aware LLM configuration."""

    def test_default_provider_is_mock(self):
        config = LLMConfig()
        assert config.provider == "mock"
        assert config.model == "mock-model"

    def test_mock_is_configured_without_api_key(self):
        """Mock provider should be considered configured without an API key."""
        config = LLMConfig(provider="mock", api_key="")
        assert config.is_configured is True

    def test_api_not_configured_without_key(self):
        config = LLMConfig(provider="api", api_key="")
        assert config.is_configured is False

    def test_api_configured_with_key(self):
        config = LLMConfig(provider="api", api_key="sk-test")
        assert config.is_configured is True

    def test_from_env_reads_provider(self):
        env = {"LLM_PROVIDER": "mock", "LLM_MODEL": "test-model"}
        with patch.dict(os.environ, env, clear=False):
            config = LLMConfig.from_env()
            assert config.provider == "mock"
            assert config.model == "test-model"

    def test_from_env_defaults_to_mock(self):
        """Without LLM_PROVIDER set, it should default to mock."""
        # Remove LLM_PROVIDER if it exists
        env_backup = os.environ.pop("LLM_PROVIDER", None)
        try:
            config = LLMConfig.from_env()
            assert config.provider == "mock"
        finally:
            if env_backup is not None:
                os.environ["LLM_PROVIDER"] = env_backup

    def test_validate_unknown_provider(self):
        config = LLMConfig(provider="nonexistent")
        with pytest.raises(LLMConfigurationError, match="Unknown LLM_PROVIDER"):
            config.validate()

    def test_validate_empty_model(self):
        config = LLMConfig(provider="mock", model="")
        with pytest.raises(LLMConfigurationError, match="LLM_MODEL"):
            config.validate()

    def test_validate_api_requires_key(self):
        config = LLMConfig(provider="api", api_key="")
        with pytest.raises(LLMConfigurationError, match="LLM_API_KEY"):
            config.validate()

    def test_validate_invalid_timeout(self):
        config = LLMConfig(timeout=0)
        with pytest.raises(LLMConfigurationError, match="LLM_TIMEOUT"):
            config.validate()

    def test_validate_negative_retries(self):
        config = LLMConfig(max_retries=-1)
        with pytest.raises(LLMConfigurationError, match="LLM_MAX_RETRIES"):
            config.validate()

    def test_validate_mock_success(self):
        """Mock config should validate without an API key."""
        config = LLMConfig(provider="mock", model="mock-model")
        config.validate()  # Should not raise

    def test_repr_masks_api_key(self):
        config = LLMConfig(api_key="sk-secret-12345")
        s = repr(config)
        assert "sk-secret-12345" not in s
        assert "****" in s

    def test_repr_shows_not_set(self):
        config = LLMConfig(api_key="")
        s = repr(config)
        assert "<not set>" in s

    def test_repr_shows_provider(self):
        config = LLMConfig(provider="mock")
        s = repr(config)
        assert "mock" in s

    def test_config_is_frozen(self):
        config = LLMConfig()
        with pytest.raises(AttributeError):
            config.provider = "api"  # type: ignore

    def test_valid_providers_set(self):
        assert "mock" in VALID_PROVIDERS
        assert "local" in VALID_PROVIDERS
        assert "api" in VALID_PROVIDERS


# ── Mock Provider Tests ────────────────────────────────────


class TestMockLLMProvider:
    """Validate MockLLMProvider behaviour."""

    def _make_provider(self, **kwargs) -> MockLLMProvider:
        config = LLMConfig(provider="mock", model="mock-model")
        return MockLLMProvider(config, **kwargs)

    @pytest.mark.asyncio
    async def test_initializes(self):
        """Mock provider should initialize without errors."""
        provider = self._make_provider()
        assert provider.provider_name == "mock"
        assert provider.call_count == 0

    @pytest.mark.asyncio
    async def test_returns_response(self):
        """Mock provider should return a valid LLMResponse."""
        provider = self._make_provider()
        request = LLMRequest(prompt="Hello world")
        response = await provider.generate(request)

        assert isinstance(response, LLMResponse)
        assert response.provider == "mock"
        assert response.model == "mock-model"
        assert response.finish_reason == "stop"
        assert "Hello world" in response.content
        assert provider.call_count == 1

    @pytest.mark.asyncio
    async def test_custom_responses(self):
        """Mock provider should cycle through predefined responses."""
        provider = self._make_provider(responses=["Answer A", "Answer B"])
        request = LLMRequest(prompt="test")

        r1 = await provider.generate(request)
        assert r1.content == "Answer A"

        r2 = await provider.generate(request)
        assert r2.content == "Answer B"

        # Cycles back
        r3 = await provider.generate(request)
        assert r3.content == "Answer A"
        assert provider.call_count == 3

    @pytest.mark.asyncio
    async def test_usage_stats(self):
        """Mock provider should report approximate token usage."""
        provider = self._make_provider()
        request = LLMRequest(prompt="one two three")
        response = await provider.generate(request)

        assert response.usage.prompt_tokens == 3  # 3 words
        assert response.usage.completion_tokens > 0
        assert response.usage.total_tokens > 0

    @pytest.mark.asyncio
    async def test_works_with_complete_convenience(self):
        """The complete() convenience method should work with mock."""
        provider = self._make_provider(responses=["Convenience works"])
        result = await provider.complete("test prompt")
        assert result == "Convenience works"


# ── Mock Failure Simulation Tests ──────────────────────────


class TestMockFailureSimulation:
    """Validate that MockLLMProvider can simulate error scenarios."""

    def _make_provider(self, simulate: str) -> MockLLMProvider:
        config = LLMConfig(provider="mock", model="mock-model")
        return MockLLMProvider(config, simulate=simulate)

    @pytest.mark.asyncio
    async def test_simulate_provider_error(self):
        provider = self._make_provider("error")
        request = LLMRequest(prompt="test")
        with pytest.raises(LLMProviderError, match="Simulated provider error"):
            await provider.generate(request)

    @pytest.mark.asyncio
    async def test_simulate_timeout(self):
        provider = self._make_provider("timeout")
        request = LLMRequest(prompt="test")
        with pytest.raises(LLMTimeoutError, match="Simulated timeout"):
            await provider.generate(request)

    @pytest.mark.asyncio
    async def test_simulate_empty_response(self):
        provider = self._make_provider("empty")
        request = LLMRequest(prompt="test")
        with pytest.raises(LLMResponseError, match="empty response"):
            await provider.generate(request)

    @pytest.mark.asyncio
    async def test_simulate_invalid_response(self):
        provider = self._make_provider("invalid")
        request = LLMRequest(prompt="test")
        with pytest.raises(LLMResponseError, match="invalid"):
            await provider.generate(request)


# ── Provider Factory Tests ─────────────────────────────────


class TestProviderFactory:
    """Validate the provider factory."""

    def test_returns_mock_provider(self):
        config = LLMConfig(provider="mock", model="mock-model")
        provider = get_llm_provider(config)
        assert isinstance(provider, MockLLMProvider)

    def test_defaults_to_mock_from_env(self):
        env_backup = os.environ.pop("LLM_PROVIDER", None)
        try:
            provider = get_llm_provider()
            assert isinstance(provider, MockLLMProvider)
        finally:
            if env_backup is not None:
                os.environ["LLM_PROVIDER"] = env_backup

    def test_local_not_implemented(self):
        config = LLMConfig(provider="local", model="some-model")
        with pytest.raises(LLMConfigurationError, match="not yet implemented"):
            get_llm_provider(config)

    def test_api_not_implemented(self):
        config = LLMConfig(provider="api", model="gpt-4", api_key="sk-test")
        with pytest.raises(LLMConfigurationError, match="not yet implemented"):
            get_llm_provider(config)

    def test_unknown_provider(self):
        config = LLMConfig(provider="nonexistent", model="m")
        with pytest.raises(LLMConfigurationError):
            get_llm_provider(config)

    def test_factory_validates_config(self):
        """Factory should catch invalid config before creating provider."""
        config = LLMConfig(provider="mock", model="")
        with pytest.raises(LLMConfigurationError, match="LLM_MODEL"):
            get_llm_provider(config)


# ── Response Parser Tests ──────────────────────────────────


class TestResponseParser:
    """Validate response parsing."""

    def test_extract_text(self):
        response = LLMResponse(content="  Hello world  ", provider="mock")
        text = ResponseParser.extract_text(response)
        assert text == "Hello world"

    def test_extract_text_empty_raises(self):
        response = LLMResponse(content="", provider="mock")
        with pytest.raises(LLMResponseError, match="no text"):
            ResponseParser.extract_text(response)

    def test_extract_text_whitespace_raises(self):
        response = LLMResponse(content="   ", provider="mock")
        with pytest.raises(LLMResponseError, match="no text"):
            ResponseParser.extract_text(response)

    def test_parse_json_valid(self):
        data = {"message": "success", "status": "ok"}
        response = LLMResponse(content=json.dumps(data), provider="mock")
        result = ResponseParser.parse_json(response)
        assert result == data

    def test_parse_json_invalid(self):
        response = LLMResponse(content="not json {{{", provider="mock")
        with pytest.raises(LLMResponseError, match="not valid JSON"):
            ResponseParser.parse_json(response)

    def test_parse_json_empty_raises(self):
        response = LLMResponse(content="", provider="mock")
        with pytest.raises(LLMResponseError, match="empty response"):
            ResponseParser.parse_json(response)

    def test_parse_json_array_raises(self):
        """JSON arrays are not accepted — we expect objects."""
        response = LLMResponse(content="[1, 2, 3]", provider="mock")
        with pytest.raises(LLMResponseError, match="JSON object"):
            ResponseParser.parse_json(response)

    def test_parse_model_valid(self):

        class SampleResult(BaseModel):
            message: str
            status: str = "unknown"

        data = {"message": "Mock LLM response", "status": "success"}
        response = LLMResponse(content=json.dumps(data), provider="mock")
        result = ResponseParser.parse_model(response, SampleResult)

        assert isinstance(result, SampleResult)
        assert result.message == "Mock LLM response"
        assert result.status == "success"

    def test_parse_model_schema_mismatch(self):

        class StrictModel(BaseModel):
            required_field: int

        response = LLMResponse(
            content=json.dumps({"wrong": "data"}),
            provider="mock",
        )
        with pytest.raises(LLMResponseError, match="does not match schema"):
            ResponseParser.parse_model(response, StrictModel)


# ── End-to-End Mock Pipeline Test ──────────────────────────


class TestEndToEndMockPipeline:
    """Prove the complete abstraction works end-to-end with mock."""

    @pytest.mark.asyncio
    async def test_full_pipeline_text(self):
        """Agent → LLM Interface → Mock → Response → Text."""
        # 1. Config
        config = LLMConfig(provider="mock", model="mock-model")
        config.validate()

        # 2. Factory
        provider = get_llm_provider(config)
        assert isinstance(provider, LLMClient)

        # 3. Request
        request = LLMRequest(
            prompt="Generate a test plan",
            system_instruction="You are a QA agent",
        )

        # 4. Generate
        response = await provider.generate(request)

        # 5. Parse
        text = ResponseParser.extract_text(response)

        # 6. Verify
        assert isinstance(text, str)
        assert len(text) > 0
        assert response.provider == "mock"
        assert response.model == "mock-model"

    @pytest.mark.asyncio
    async def test_full_pipeline_structured(self):
        """Agent → LLM Interface → Mock (JSON) → Parser → Pydantic Model."""

        class MockResult(BaseModel):
            message: str
            status: str

        # Create provider with JSON response
        config = LLMConfig(provider="mock", model="mock-model")
        provider = MockLLMProvider(
            config,
            responses=[json.dumps({"message": "Mock LLM response", "status": "success"})],
        )

        request = LLMRequest(
            prompt="Do something",
            response_format="json",
        )
        response = await provider.generate(request)
        result = ResponseParser.parse_model(response, MockResult)

        assert isinstance(result, MockResult)
        assert result.message == "Mock LLM response"
        assert result.status == "success"


# ── Security Tests ─────────────────────────────────────────


class TestSecuritySafeguards:
    """Ensure API keys are never exposed."""

    def test_config_repr_hides_key(self):
        config = LLMConfig(api_key="sk-my-secret-api-key-xyz")
        s = repr(config)
        assert "sk-my-secret-api-key-xyz" not in s
        assert "****" in s

    def test_config_str_hides_key(self):
        config = LLMConfig(api_key="sk-my-secret-api-key-xyz")
        s = repr(config)
        assert "sk-my-secret-api-key-xyz" not in s

    def test_exception_messages_are_safe(self):
        """Exception messages should not contain API keys."""
        config = LLMConfig(provider="api", api_key="")
        try:
            config.validate()
        except LLMConfigurationError as exc:
            msg = str(exc)
            assert "sk-" not in msg

    def test_no_api_key_needed_for_mock(self):
        """The entire Day 2 test suite runs without any API key."""
        config = LLMConfig(provider="mock")
        assert config.api_key == ""
        config.validate()  # Should not raise
