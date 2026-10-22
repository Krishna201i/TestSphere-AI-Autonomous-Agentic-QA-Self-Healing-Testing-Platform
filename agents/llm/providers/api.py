"""
TestSphere-AI — Cloud API LLM Provider

Talks to any OpenAI-compatible ``/chat/completions`` endpoint, which
covers OpenAI, Groq, OpenRouter, Gemini (OpenAI-compat endpoint) and
Anthropic (OpenAI-compat endpoint) through a single code path::

    LLM_PROVIDER=api
    LLM_API_KEY=sk-...
    LLM_MODEL=gpt-4o-mini
    LLM_BASE_URL=https://api.openai.com/v1   # optional, this is the default

The same code path serves local OpenAI-compatible servers (Ollama, vLLM,
LM Studio, llama.cpp) as ``LLM_PROVIDER=local``: no API key needed, and
``LLM_BASE_URL`` defaults to Ollama's ``http://localhost:11434/v1``::

    LLM_PROVIDER=local
    LLM_MODEL=llama3.2

HTTP failures are translated into the project's exception hierarchy so
``LLMClientSession`` can decide what to retry:

    401 / 403      →  LLMAuthenticationError   (not retried)
    429            →  LLMRateLimitError        (retried)
    5xx            →  LLMProviderError         (retried)
    other 4xx      →  LLMRequestValidationError (not retried)
    timeout        →  LLMTimeoutError          (retried)
    network error  →  LLMConnectionError       (retried)

SECURITY: the API key is only ever placed in the Authorization header.
It is never logged or included in exception messages.
"""

from __future__ import annotations

import logging
import time

import httpx

from agents.llm.client import LLMClient
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
from agents.llm.schemas import LLMRequest, LLMResponse, LLMUsage

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_LOCAL_BASE_URL = "http://localhost:11434/v1"  # Ollama

# Map OpenAI-style finish reasons onto the values the session understands
_FINISH_REASONS = {
    "stop": "stop",
    "length": "length",
    "content_filter": "error",
    "tool_calls": "stop",
    "function_call": "stop",
}


class APIProvider(LLMClient):
    """LLM provider for OpenAI-compatible chat-completions APIs.

    Parameters
    ----------
    config:
        LLM configuration. For ``provider=self._config.provider`` an ``api_key`` is
        required and ``base_url`` defaults to the OpenAI API; for
        ``provider="local"`` the key is optional and ``base_url`` defaults
        to a local Ollama server.
    transport:
        Optional ``httpx`` transport, used by tests to stub the network.
    """

    def __init__(
        self,
        config: LLMConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(config)
        default = DEFAULT_LOCAL_BASE_URL if config.provider == "local" else DEFAULT_BASE_URL
        self._base_url = (config.base_url or default).rstrip("/")
        self._transport = transport

        logger.info(
            "APIProvider initialized — provider=%s, model=%s, base_url=%s",
            config.provider,
            config.model,
            self._base_url,
        )

    # ── Request building ──────────────────────────────────────

    def _build_payload(self, request: LLMRequest) -> dict:
        """Translate an ``LLMRequest`` into a chat-completions body."""
        messages: list[dict[str, str]] = []
        if request.system_instruction:
            messages.append({"role": "system", "content": request.system_instruction})
        messages.append({"role": "user", "content": request.prompt})

        payload: dict = {
            "model": self._config.model,
            "messages": messages,
            "temperature": (
                request.temperature
                if request.temperature is not None
                else self._config.temperature
            ),
            "max_tokens": request.max_tokens or self._config.max_tokens,
        }
        if request.response_format == "json":
            payload["response_format"] = {"type": "json_object"}
        return payload

    # ── Error translation ─────────────────────────────────────

    @staticmethod
    def _error_detail(response: httpx.Response) -> str:
        """Extract a short provider error message from a failed response."""
        try:
            body = response.json()
            error = body.get("error", body)
            if isinstance(error, dict):
                return str(error.get("message", error))[:300]
            return str(error)[:300]
        except ValueError:
            return response.text[:300]

    def _raise_for_status(self, response: httpx.Response) -> None:
        """Raise the matching ``LLMError`` subclass for a non-2xx response."""
        status = response.status_code
        if status < 400:
            return

        detail = self._error_detail(response)
        message = f"API returned HTTP {status}: {detail}"

        if status in (401, 403):
            raise LLMAuthenticationError(message, provider=self._config.provider)
        if status == 429:
            raise LLMRateLimitError(message, provider=self._config.provider)
        if status >= 500:
            raise LLMProviderError(message, provider=self._config.provider)
        raise LLMRequestValidationError(message, provider=self._config.provider)

    # ── Response parsing ──────────────────────────────────────

    def _parse_response(self, body: dict) -> LLMResponse:
        """Convert a chat-completions body into an ``LLMResponse``."""
        try:
            choice = body["choices"][0]
            content = choice["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMResponseError(
                "API response is missing choices[0].message.content.",
                provider=self._config.provider,
            ) from exc

        usage = body.get("usage") or {}
        finish_reason = _FINISH_REASONS.get(choice.get("finish_reason") or "stop", "stop")

        return LLMResponse(
            content=content if content is not None else "",
            model=body.get("model") or self._config.model,
            provider=self._config.provider,
            usage=LLMUsage(
                prompt_tokens=usage.get("prompt_tokens", 0) or 0,
                completion_tokens=usage.get("completion_tokens", 0) or 0,
            ),
            finish_reason=finish_reason,
        )

    # ── Core Generate ─────────────────────────────────────────

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Send the request to the chat-completions endpoint.

        Raises
        ------
        LLMAuthenticationError, LLMRateLimitError, LLMProviderError,
        LLMRequestValidationError, LLMTimeoutError, LLMConnectionError,
        LLMResponseError
            See the module docstring for the mapping.
        """
        start_time = time.monotonic()
        headers = {"Content-Type": "application/json"}
        if self._config.api_key:  # local servers usually need none
            headers["Authorization"] = f"Bearer {self._config.api_key}"

        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._config.timeout,
                transport=self._transport,
            ) as http:
                response = await http.post(
                    "/chat/completions",
                    json=self._build_payload(request),
                    headers=headers,
                )
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(
                f"API request timed out after {self._config.timeout}s.",
                provider=self._config.provider,
            ) from exc
        except httpx.RequestError as exc:
            raise LLMConnectionError(
                f"Could not reach LLM API at {self._base_url}: {type(exc).__name__}",
                provider=self._config.provider,
            ) from exc

        self._raise_for_status(response)

        try:
            body = response.json()
        except ValueError as exc:
            raise LLMResponseError(
                "API returned a non-JSON response body.",
                provider=self._config.provider,
            ) from exc

        result = self._parse_response(body)

        logger.info(
            "APIProvider response — duration=%.2fs, tokens=%d+%d, finish=%s",
            time.monotonic() - start_time,
            result.usage.prompt_tokens,
            result.usage.completion_tokens,
            result.finish_reason,
        )
        return result
