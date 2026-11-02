"""
TestSphere-AI — Claude (Anthropic Messages API) LLM Provider

Calls Claude through the official ``anthropic`` SDK, so requests use the
Messages API directly instead of an OpenAI-compatible shim::

    LLM_PROVIDER=anthropic
    LLM_API_KEY=sk-ant-...          # or ANTHROPIC_API_KEY / an `ant auth login` profile
    LLM_MODEL=claude-opus-5-5       # the default
    LLM_EFFORT=medium               # low | medium | high | xhigh | max

Current Claude models think adaptively on every request; ``LLM_EFFORT``
is the depth (and spend) control, and thinking counts toward
``LLM_MAX_TOKENS``.  They take no ``temperature``, so the configured one is
not sent.  On models with server-side fallback, a request the model
declines is re-run on a fallback model inside the same call
(``LLM_FALLBACKS=off`` turns that off); a request the whole chain declines
raises ``LLMResponseError``, which is not retried.

SDK errors are translated into the project's exception hierarchy so
``LLMClientSession`` can decide what to retry:

    401 / 403      →  LLMAuthenticationError   (not retried)
    429            →  LLMRateLimitError        (retried)
    5xx / 529      →  LLMProviderError         (retried)
    other 4xx      →  LLMRequestValidationError (not retried)
    timeout        →  LLMTimeoutError          (retried)
    network error  →  LLMConnectionError       (retried)

The session owns retries, so the SDK's own are turned off.

SECURITY: the API key is handed to the SDK only; it is never logged or
included in exception messages.
"""

from __future__ import annotations

import contextlib
import logging
import time
from typing import Any

import anthropic

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

PROVIDER = "anthropic"
DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_MAX_TOKENS = 16000  # thinking shares this budget with the answer

# Models that accept the server-side refusal fallback in its "default" form
FALLBACK_MODELS = frozenset({"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"})
FALLBACK_BETA = "server-side-fallback-2026-07-01"

JSON_INSTRUCTION = "Respond with a single JSON value only: no prose and no Markdown code fences."

_STOP_REASONS = {"end_turn": "stop", "stop_sequence": "stop", "max_tokens": "length"}


class ClaudeProvider(LLMClient):
    """LLM provider for Claude through the Anthropic Messages API.

    Parameters
    ----------
    config:
        LLM configuration.  ``api_key`` is optional: without it the SDK
        resolves credentials itself (``ANTHROPIC_API_KEY``, an ``ant auth
        login`` profile, ...).
    client:
        Optional ``anthropic.AsyncAnthropic``, used by tests to stub the network.
    """

    def __init__(self, config: LLMConfig, *, client: Any = None) -> None:
        super().__init__(config)
        self._client = client or anthropic.AsyncAnthropic(
            api_key=config.api_key or None,
            base_url=config.base_url or None,
            timeout=float(config.timeout),
            max_retries=0,
        )
        logger.info("ClaudeProvider initialized — model=%s, effort=%s", config.model, config.effort or "default")

    # ── Request building ──────────────────────────────────────

    def _build_params(self, request: LLMRequest) -> dict[str, Any]:
        """Translate an ``LLMRequest`` into Messages API arguments."""
        system = request.system_instruction
        if request.response_format == "json":
            system = f"{system}\n\n{JSON_INSTRUCTION}" if system else JSON_INSTRUCTION

        params: dict[str, Any] = {
            "model": self._config.model,
            "max_tokens": request.max_tokens or self._config.max_tokens,
            "messages": [{"role": "user", "content": request.prompt}],
        }
        if system:
            params["system"] = system
        if self._config.effort:
            params["output_config"] = {"effort": self._config.effort}
        if self._config.fallbacks and self._config.model in FALLBACK_MODELS:
            params["betas"] = [FALLBACK_BETA]
            params["fallbacks"] = "default"
        return params

    # ── Error translation ─────────────────────────────────────

    @staticmethod
    def _retry_after(exc: anthropic.APIStatusError) -> float | None:
        with contextlib.suppress(TypeError, ValueError):
            return float(exc.response.headers.get("retry-after", ""))
        return None

    def _translate(self, exc: anthropic.APIError) -> Exception:
        """The ``LLMError`` subclass matching an SDK error."""
        if isinstance(exc, anthropic.APITimeoutError):  # a subclass of APIConnectionError: check it first
            return LLMTimeoutError(f"Claude API request timed out after {self._config.timeout}s.", provider=PROVIDER)
        if isinstance(exc, anthropic.APIConnectionError):
            return LLMConnectionError("Could not reach the Claude API.", provider=PROVIDER)
        if not isinstance(exc, anthropic.APIStatusError):
            return LLMProviderError(f"Claude API error: {type(exc).__name__}", provider=PROVIDER)

        message = f"Claude API returned HTTP {exc.status_code}: {str(exc.message)[:300]}"
        if isinstance(exc, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
            return LLMAuthenticationError(message, provider=PROVIDER)
        if isinstance(exc, anthropic.RateLimitError):
            return LLMRateLimitError(message, provider=PROVIDER, retry_after=self._retry_after(exc))
        if exc.status_code >= 500:  # includes 529 overloaded
            return LLMProviderError(message, provider=PROVIDER)
        return LLMRequestValidationError(message, provider=PROVIDER)

    # ── Response parsing ──────────────────────────────────────

    def _parse_response(self, message: Any) -> LLMResponse:
        """Convert a Messages API response into an ``LLMResponse``."""
        if message.stop_reason == "refusal":
            details = getattr(message, "stop_details", None)
            category = getattr(details, "category", None) or "unspecified"
            raise LLMResponseError(f"Claude declined the request (category: {category}).", provider=PROVIDER)

        text = "".join(block.text for block in message.content if block.type == "text")
        usage = message.usage
        return LLMResponse(
            content=text,
            model=message.model or self._config.model,
            provider=PROVIDER,
            usage=LLMUsage(prompt_tokens=usage.input_tokens or 0, completion_tokens=usage.output_tokens or 0),
            finish_reason=_STOP_REASONS.get(message.stop_reason or "end_turn", "stop"),
        )

    # ── Core Generate ─────────────────────────────────────────

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Send the request to the Messages API.

        Raises
        ------
        LLMAuthenticationError, LLMRateLimitError, LLMProviderError,
        LLMRequestValidationError, LLMTimeoutError, LLMConnectionError,
        LLMResponseError
            See the module docstring for the mapping.
        """
        start_time = time.monotonic()
        try:
            message = await self._client.beta.messages.create(**self._build_params(request))
        except anthropic.APIError as exc:
            raise self._translate(exc) from exc

        result = self._parse_response(message)
        logger.info(  # nosemgrep: python-logger-credential-disclosure - token *counts*, no secrets
            "ClaudeProvider response — duration=%.2fs, tokens=%d+%d, finish=%s, request_id=%s",
            time.monotonic() - start_time,
            result.usage.prompt_tokens,
            result.usage.completion_tokens,
            result.finish_reason,
            getattr(message, "_request_id", None),
        )
        return result
