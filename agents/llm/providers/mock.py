"""
TestSphere-AI — Mock LLM Provider

A deterministic mock provider for development and testing.
No real model, no internet, no API key required.

The mock provider can operate in several modes to test
different scenarios::

    # Normal mode — returns predefined responses
    provider = MockLLMProvider(config)

    # Error simulation — raises LLMProviderError
    provider = MockLLMProvider(config, simulate="error")

    # Timeout simulation — raises LLMTimeoutError
    provider = MockLLMProvider(config, simulate="timeout")

    # Empty response simulation — raises LLMResponseError
    provider = MockLLMProvider(config, simulate="empty")

    # Invalid response simulation — raises LLMResponseError
    provider = MockLLMProvider(config, simulate="invalid")

    # Custom responses — returns user-defined content
    provider = MockLLMProvider(config, responses=["custom reply"])

Response Registry (Day 3)::

    # Register responses matched by prompt substring
    provider.register_response("test plan", "Here is a test plan…")

    # Register errors matched by prompt substring
    provider.register_error("fail me", LLMProviderError("boom"))

    # Simulate transient failures followed by success (retry testing)
    provider.set_failure_sequence([
        LLMProviderError("transient"),
        LLMProviderError("transient"),
    ])
    # The next call after the sequence exhausts returns normally.
"""

from __future__ import annotations

import logging
import time
from typing import Sequence

from agents.llm.client import LLMClient
from agents.llm.config import LLMConfig
from agents.llm.exceptions import (
    LLMError,
    LLMProviderError,
    LLMResponseError,
    LLMTimeoutError,
)
from agents.llm.schemas import LLMRequest, LLMResponse, LLMUsage

logger = logging.getLogger(__name__)

# Simulation modes that trigger error behaviour
SIMULATE_ERROR = "error"
SIMULATE_TIMEOUT = "timeout"
SIMULATE_EMPTY = "empty"
SIMULATE_INVALID = "invalid"


class MockLLMProvider(LLMClient):
    """Deterministic mock LLM provider for testing.

    This provider does NOT perform any real AI inference.
    It returns predefined responses so that the entire AI pipeline
    (interfaces, data flow, parsing, validation, error handling)
    can be tested without a real model.

    Parameters
    ----------
    config:
        LLM configuration. For the mock provider, no API key is needed.
    simulate:
        Optional failure simulation mode. One of:
        ``"error"`` — raise ``LLMProviderError``
        ``"timeout"`` — raise ``LLMTimeoutError``
        ``"empty"`` — raise ``LLMResponseError`` (empty content)
        ``"invalid"`` — raise ``LLMResponseError`` (invalid/malformed)
        ``None`` — normal operation (default)
    responses:
        Optional list of predefined response strings. The provider
        cycles through them on successive calls. If not provided,
        a sensible default response is used.
    """

    def __init__(
        self,
        config: LLMConfig,
        *,
        simulate: str | None = None,
        responses: Sequence[str] | None = None,
    ) -> None:
        super().__init__(config)
        self._simulate = simulate
        self._responses = list(responses) if responses else None
        self._call_count = 0

        # Day 3 — Response registry
        self._response_registry: list[tuple[str, str]] = []
        self._error_registry: list[tuple[str, LLMError]] = []
        self._failure_sequence: list[LLMError] = []
        self._failure_sequence_index: int = 0

        logger.info(
            "MockLLMProvider initialized — model=%s, simulate=%s",
            config.model,
            simulate or "none",
        )

    # ── Properties ────────────────────────────────────────────

    @property
    def call_count(self) -> int:
        """Number of generate() calls made to this provider."""
        return self._call_count

    # ── Response Registry (Day 3) ─────────────────────────────

    def register_response(self, prompt_contains: str, response: str) -> None:
        """Register a response to return when the prompt contains a substring.

        Parameters
        ----------
        prompt_contains:
            A substring to match against the request prompt.
        response:
            The response content to return on match.
        """
        self._response_registry.append((prompt_contains, response))
        logger.info(
            "MockLLMProvider: registered response for prompt containing '%s'",
            prompt_contains,
        )

    def register_error(self, prompt_contains: str, error: LLMError) -> None:
        """Register an error to raise when the prompt contains a substring.

        Parameters
        ----------
        prompt_contains:
            A substring to match against the request prompt.
        error:
            The LLMError instance to raise on match.
        """
        self._error_registry.append((prompt_contains, error))
        logger.info(
            "MockLLMProvider: registered error %s for prompt containing '%s'",
            type(error).__name__,
            prompt_contains,
        )

    def set_failure_sequence(self, errors: Sequence[LLMError]) -> None:
        """Set a sequence of errors to raise before returning normally.

        This is useful for testing retry logic. The provider will raise
        each error in order on successive calls. Once the sequence is
        exhausted, subsequent calls return normally.

        Parameters
        ----------
        errors:
            An ordered sequence of errors to raise.
        """
        self._failure_sequence = list(errors)
        self._failure_sequence_index = 0
        logger.info(
            "MockLLMProvider: set failure sequence with %d errors",
            len(errors),
        )

    def reset(self) -> None:
        """Clear all registered responses, errors, and failure sequences.

        Also resets the call counter.
        """
        self._response_registry.clear()
        self._error_registry.clear()
        self._failure_sequence.clear()
        self._failure_sequence_index = 0
        self._call_count = 0
        logger.info("MockLLMProvider: reset all state")

    # ── Core Generate ─────────────────────────────────────────

    def _get_default_response(self, request: LLMRequest) -> str:
        """Generate a deterministic default response.

        The response includes a summary of the request so tests can
        verify the data flow without needing real AI reasoning.
        """
        return (
            f"Mock response to: {request.prompt[:80]}"
            if request.prompt
            else "Mock response (empty prompt)"
        )

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Return a mock LLM response.

        Parameters
        ----------
        request:
            The structured LLM request.

        Returns
        -------
        LLMResponse
            A deterministic mock response.

        Raises
        ------
        LLMProviderError
            When ``simulate="error"`` or via failure sequence/error registry.
        LLMTimeoutError
            When ``simulate="timeout"`` or via failure sequence/error registry.
        LLMResponseError
            When ``simulate="empty"`` or ``simulate="invalid"``.
        """
        self._call_count += 1
        start_time = time.monotonic()

        logger.info(
            "MockLLMProvider.generate() — call #%d, simulate=%s",
            self._call_count,
            self._simulate or "none",
        )

        # ── Failure simulations ──────────────────────────────
        if self._simulate == SIMULATE_ERROR:
            raise LLMProviderError(
                "Simulated provider error.",
                provider="mock",
            )

        if self._simulate == SIMULATE_TIMEOUT:
            raise LLMTimeoutError(
                f"Simulated timeout after {self._config.timeout}s.",
                provider="mock",
            )

        if self._simulate == SIMULATE_EMPTY:
            raise LLMResponseError(
                "Simulated empty response from provider.",
                provider="mock",
            )

        if self._simulate == SIMULATE_INVALID:
            raise LLMResponseError(
                "Simulated invalid/malformed response from provider.",
                provider="mock",
            )

        # ── Failure sequence (Day 3) ─────────────────────────
        if self._failure_sequence_index < len(self._failure_sequence):
            error = self._failure_sequence[self._failure_sequence_index]
            self._failure_sequence_index += 1
            raise error

        # ── Error registry (Day 3) ───────────────────────────
        for substring, error in self._error_registry:
            if substring in request.prompt:
                raise error

        # ── Response registry (Day 3) ────────────────────────
        for substring, response_content in self._response_registry:
            if substring in request.prompt:
                content = response_content
                break
        else:
            # ── Normal response ──────────────────────────────
            if self._responses:
                # Cycle through predefined responses
                idx = (self._call_count - 1) % len(self._responses)
                content = self._responses[idx]
            else:
                content = self._get_default_response(request)

        duration = time.monotonic() - start_time

        # Simulate token counts based on rough word-counting
        prompt_tokens = len(request.prompt.split())
        completion_tokens = len(content.split())

        logger.info(
            "MockLLMProvider response — duration=%.4fs, tokens=%d+%d",
            duration,
            prompt_tokens,
            completion_tokens,
        )

        return LLMResponse(
            content=content,
            model=self._config.model,
            provider="mock",
            usage=LLMUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            ),
            finish_reason="stop",
        )
