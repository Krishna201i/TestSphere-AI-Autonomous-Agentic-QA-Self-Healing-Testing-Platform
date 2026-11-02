"""
ClaudeProvider: the real anthropic SDK against a stubbed HTTP transport, so
these tests check what goes over the wire (headers, body) and how each API
answer maps onto the project's LLM errors.
"""

import asyncio
import json

import anthropic
import httpx2
import pytest

from agents.llm.config import LLMConfig
from agents.llm.exceptions import (
    LLMAuthenticationError,
    LLMConfigurationError,
    LLMProviderError,
    LLMRateLimitError,
    LLMRequestValidationError,
    LLMResponseError,
)
from agents.llm.factory import get_llm_provider
from agents.llm.providers.claude import ClaudeProvider
from agents.llm.schemas import LLMRequest


def message(text="hello", stop_reason="end_turn", **extra):
    return {"id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
            "content": [{"type": "text", "text": text}], "stop_reason": stop_reason, "stop_sequence": None,
            "usage": {"input_tokens": 12, "output_tokens": 34}, **extra}


def provider(handler, **config):
    config = {"provider": "anthropic", "api_key": "sk-ant-test", "model": "claude-opus-5-5",
              "max_tokens": 16000, "effort": "medium", **config}
    client = anthropic.AsyncAnthropic(api_key="sk-ant-test", max_retries=0, http_client=anthropic.DefaultAsyncHttpxClient(
        transport=httpx2.MockTransport(handler)))
    return ClaudeProvider(LLMConfig(**config), client=client)


def run(p, **request):
    return asyncio.run(p.generate(LLMRequest(prompt="Plan a test", **request)))


def test_the_request_is_a_messages_call_with_effort_and_fallbacks_and_no_temperature():
    seen = {}

    def handler(req):
        seen["path"], seen["beta"], seen["body"] = req.url.path, req.headers.get("anthropic-beta"), json.loads(req.content)
        return httpx2.Response(200, json=message('{"ok": true}'))

    result = run(provider(handler), system_instruction="You plan tests.", response_format="json")
    body = seen["body"]
    assert seen["path"] == "/v1/messages" and "server-side-fallback-2026-07-01" in seen["beta"]
    assert body["model"] == "claude-opus-5-5" and body["max_tokens"] == 16000
    assert body["fallbacks"] == "default" and body["output_config"] == {"effort": "medium"}
    assert "temperature" not in body and "thinking" not in body
    assert body["system"].startswith("You plan tests.") and "JSON" in body["system"]
    assert body["messages"] == [{"role": "user", "content": "Plan a test"}]
    assert result.content == '{"ok": true}' and result.provider == "anthropic"
    assert (result.usage.prompt_tokens, result.usage.completion_tokens) == (12, 34)


def test_no_fallbacks_when_turned_off_or_the_model_has_none():
    bodies = []

    def handler(req):
        bodies.append((req.headers.get("anthropic-beta"), json.loads(req.content)))
        return httpx2.Response(200, json=message())

    run(provider(handler, fallbacks=False))
    run(provider(handler, model="claude-haiku-5-5"))
    assert all(beta is None and "fallbacks" not in body for beta, body in bodies)


def test_a_cut_off_answer_is_reported_as_length():
    assert run(provider(lambda r: httpx2.Response(200, json=message(stop_reason="max_tokens")))).finish_reason == "length"


def test_a_declined_request_is_a_response_error_that_is_not_retried():
    def handler(req):
        return httpx2.Response(200, json=message("", stop_reason="refusal",
                                                 stop_details={"type": "refusal", "category": "cyber", "explanation": None}))

    with pytest.raises(LLMResponseError, match="declined the request \\(category: cyber\\)") as exc:
        run(provider(handler))
    assert not exc.value.is_retryable


@pytest.mark.parametrize(("status", "error", "retryable"), [
    (401, LLMAuthenticationError, False),
    (403, LLMAuthenticationError, False),
    (400, LLMRequestValidationError, False),
    (429, LLMRateLimitError, True),
    (500, LLMProviderError, True),
    (529, LLMProviderError, True),
])
def test_http_errors_map_onto_the_project_errors(status, error, retryable):
    def handler(req):
        return httpx2.Response(status, headers={"retry-after": "3"},
                               json={"type": "error", "error": {"type": "x", "message": "nope"}})

    with pytest.raises(error) as exc:
        run(provider(handler))
    assert exc.value.is_retryable is retryable
    assert "sk-ant-test" not in str(exc.value)
    if status == 429:
        assert exc.value.retry_after == 3.0


def test_config_defaults_for_claude(monkeypatch):
    for name in ("LLM_MODEL", "LLM_MAX_TOKENS", "LLM_EFFORT", "LLM_FALLBACKS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    config = LLMConfig.from_env(dotenv_path="nonexistent.env")
    assert (config.model, config.max_tokens, config.effort, config.fallbacks) == ("claude-opus-5-5", 16000, "medium", True)
    assert isinstance(get_llm_provider(config), ClaudeProvider)

    monkeypatch.setenv("LLM_EFFORT", "extreme")
    with pytest.raises(LLMConfigurationError, match="LLM_EFFORT must be one of"):
        LLMConfig.from_env(dotenv_path="nonexistent.env").validate()
