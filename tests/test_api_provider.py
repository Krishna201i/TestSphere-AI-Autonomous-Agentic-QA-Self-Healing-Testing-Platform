"""
Tests for the OpenAI-compatible APIProvider.

All HTTP traffic is stubbed with ``httpx.MockTransport`` — no network,
no real API key.
"""

from __future__ import annotations

import json

import httpx
import pytest

from agents.llm.client import LLMClientSession
from agents.llm.config import LLMConfig
from agents.llm.exceptions import (
    LLMAuthenticationError,
    LLMConnectionError,
    LLMProviderError,
    LLMRateLimitError,
    LLMRequestValidationError,
    LLMResponseError,
    LLMTimeoutError,
)
from agents.llm.providers.api import DEFAULT_BASE_URL, APIProvider
from agents.llm.schemas import LLMRequest

API_KEY = "sk-test-secret-key"


def _config(**overrides) -> LLMConfig:
    values = dict(provider="api", api_key=API_KEY, model="gpt-test", max_retries=0)
    values.update(overrides)
    return LLMConfig(**values)


def _completion(content="hello", finish_reason="stop", usage=None) -> dict:
    return {
        "model": "gpt-test-2026",
        "choices": [{"message": {"role": "assistant", "content": content},
                     "finish_reason": finish_reason}],
        "usage": usage if usage is not None else {"prompt_tokens": 7, "completion_tokens": 3},
    }


def _provider(handler, **config_overrides) -> APIProvider:
    return APIProvider(_config(**config_overrides), transport=httpx.MockTransport(handler))


def _json_handler(status=200, body=None, captured=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if captured is not None:
            captured.append(request)
        return httpx.Response(status, json=body if body is not None else _completion())
    return handler


# ── Request building ──────────────────────────────────────────


class TestRequestBuilding:

    @pytest.mark.asyncio
    async def test_posts_to_default_openai_endpoint(self):
        captured: list[httpx.Request] = []
        await _provider(_json_handler(captured=captured)).generate(LLMRequest(prompt="hi"))
        assert str(captured[0].url) == f"{DEFAULT_BASE_URL}/chat/completions"

    @pytest.mark.asyncio
    async def test_custom_base_url_trailing_slash(self):
        captured: list[httpx.Request] = []
        provider = _provider(_json_handler(captured=captured),
                             base_url="https://api.groq.com/openai/v1/")
        await provider.generate(LLMRequest(prompt="hi"))
        assert str(captured[0].url) == "https://api.groq.com/openai/v1/chat/completions"

    @pytest.mark.asyncio
    async def test_sends_bearer_key_and_messages(self):
        captured: list[httpx.Request] = []
        await _provider(_json_handler(captured=captured)).generate(
            LLMRequest(prompt="plan tests", system_instruction="you are QA")
        )
        req = captured[0]
        body = json.loads(req.content)
        assert req.headers["Authorization"] == f"Bearer {API_KEY}"
        assert body["model"] == "gpt-test"
        assert body["messages"] == [
            {"role": "system", "content": "you are QA"},
            {"role": "user", "content": "plan tests"},
        ]
        assert "response_format" not in body

    @pytest.mark.asyncio
    async def test_local_provider_posts_to_ollama_without_a_key(self):
        from agents.llm.providers.api import DEFAULT_LOCAL_BASE_URL

        captured: list[httpx.Request] = []
        response = await _provider(_json_handler(captured=captured), provider="local", api_key="").generate(
            LLMRequest(prompt="hi"))
        assert str(captured[0].url) == f"{DEFAULT_LOCAL_BASE_URL}/chat/completions"
        assert "Authorization" not in captured[0].headers
        assert response.provider == "local"

    @pytest.mark.asyncio
    async def test_omits_empty_system_message(self):
        captured: list[httpx.Request] = []
        await _provider(_json_handler(captured=captured)).generate(LLMRequest(prompt="hi"))
        assert json.loads(captured[0].content)["messages"] == [{"role": "user", "content": "hi"}]

    @pytest.mark.asyncio
    async def test_uses_config_defaults_and_request_overrides(self):
        captured: list[httpx.Request] = []
        provider = _provider(_json_handler(captured=captured), temperature=0.3, max_tokens=500)
        await provider.generate(LLMRequest(prompt="a"))
        await provider.generate(LLMRequest(prompt="b", temperature=0.0, max_tokens=50))
        first, second = (json.loads(r.content) for r in captured)
        assert (first["temperature"], first["max_tokens"]) == (0.3, 500)
        assert (second["temperature"], second["max_tokens"]) == (0.0, 50)

    @pytest.mark.asyncio
    async def test_json_format_requests_json_object(self):
        captured: list[httpx.Request] = []
        await _provider(_json_handler(captured=captured)).generate(
            LLMRequest(prompt="give json", response_format="json")
        )
        assert json.loads(captured[0].content)["response_format"] == {"type": "json_object"}


# ── Response parsing ──────────────────────────────────────────


class TestResponseParsing:

    @pytest.mark.asyncio
    async def test_parses_content_usage_and_model(self):
        response = await _provider(_json_handler()).generate(LLMRequest(prompt="hi"))
        assert response.content == "hello"
        assert response.provider == "api"
        assert response.model == "gpt-test-2026"
        assert (response.usage.prompt_tokens, response.usage.completion_tokens) == (7, 3)
        assert response.finish_reason == "stop"

    @pytest.mark.asyncio
    async def test_missing_usage_defaults_to_zero(self):
        body = _completion()
        del body["usage"]
        response = await _provider(_json_handler(body=body)).generate(LLMRequest(prompt="hi"))
        assert response.usage.total_tokens == 0

    @pytest.mark.asyncio
    async def test_length_finish_reason_preserved(self):
        body = _completion(finish_reason="length")
        response = await _provider(_json_handler(body=body)).generate(LLMRequest(prompt="hi"))
        assert response.finish_reason == "length"

    @pytest.mark.asyncio
    async def test_content_filter_maps_to_error(self):
        body = _completion(finish_reason="content_filter")
        response = await _provider(_json_handler(body=body)).generate(LLMRequest(prompt="hi"))
        assert response.finish_reason == "error"

    @pytest.mark.asyncio
    async def test_missing_choices_raises_response_error(self):
        with pytest.raises(LLMResponseError, match="choices"):
            await _provider(_json_handler(body={"choices": []})).generate(LLMRequest(prompt="hi"))

    @pytest.mark.asyncio
    async def test_non_json_body_raises_response_error(self):
        provider = _provider(lambda r: httpx.Response(200, text="<html>oops</html>"))
        with pytest.raises(LLMResponseError, match="non-JSON"):
            await provider.generate(LLMRequest(prompt="hi"))


# ── Error translation ─────────────────────────────────────────


class TestErrorTranslation:

    @pytest.mark.parametrize(
        ("status", "error_type"),
        [
            (401, LLMAuthenticationError),
            (403, LLMAuthenticationError),
            (429, LLMRateLimitError),
            (500, LLMProviderError),
            (503, LLMProviderError),
            (400, LLMRequestValidationError),
            (404, LLMRequestValidationError),
        ],
    )
    @pytest.mark.asyncio
    async def test_http_status_mapping(self, status, error_type):
        body = {"error": {"message": f"status {status}"}}
        with pytest.raises(error_type, match=f"HTTP {status}: status {status}"):
            await _provider(_json_handler(status=status, body=body)).generate(LLMRequest(prompt="hi"))

    @pytest.mark.asyncio
    async def test_timeout_maps_to_timeout_error(self):
        def handler(request):
            raise httpx.ReadTimeout("slow", request=request)
        with pytest.raises(LLMTimeoutError):
            await _provider(handler).generate(LLMRequest(prompt="hi"))

    @pytest.mark.asyncio
    async def test_network_failure_maps_to_connection_error(self):
        def handler(request):
            raise httpx.ConnectError("refused", request=request)
        with pytest.raises(LLMConnectionError):
            await _provider(handler).generate(LLMRequest(prompt="hi"))

    @pytest.mark.asyncio
    async def test_api_key_never_in_error_message(self):
        body = {"error": {"message": "bad key"}}
        with pytest.raises(LLMAuthenticationError) as exc_info:
            await _provider(_json_handler(status=401, body=body)).generate(LLMRequest(prompt="hi"))
        assert API_KEY not in str(exc_info.value)


# ── Integration with LLMClientSession ─────────────────────────


class TestSessionIntegration:

    @pytest.mark.asyncio
    async def test_session_retries_rate_limit_then_succeeds(self):
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(429, json={"error": {"message": "slow down"}})
            return httpx.Response(200, json=_completion("recovered"))

        config = _config(max_retries=2)
        session = LLMClientSession(
            APIProvider(config, transport=httpx.MockTransport(handler)), config
        )
        response = await session.generate(LLMRequest(prompt="hi"))
        assert response.content == "recovered"
        assert calls["n"] == 2

    @pytest.mark.asyncio
    async def test_session_does_not_retry_auth_error(self):
        calls = {"n": 0}

        def handler(request):
            calls["n"] += 1
            return httpx.Response(401, json={"error": {"message": "nope"}})

        config = _config(max_retries=3)
        session = LLMClientSession(
            APIProvider(config, transport=httpx.MockTransport(handler)), config
        )
        with pytest.raises(LLMAuthenticationError):
            await session.generate(LLMRequest(prompt="hi"))
        assert calls["n"] == 1

    @pytest.mark.asyncio
    async def test_session_generate_json(self):
        body = _completion(content='{"tests": ["login"]}')
        config = _config()
        session = LLMClientSession(
            APIProvider(config, transport=httpx.MockTransport(_json_handler(body=body))), config
        )
        assert await session.generate_json(LLMRequest(prompt="plan")) == {"tests": ["login"]}
