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
"""

from __future__ import annotations

import logging
import time
from typing import Sequence

from agents.llm.client import LLMClient
from agents.llm.config import LLMConfig
from agents.llm.exceptions import (
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
        logger.info(
            "MockLLMProvider initialized — model=%s, simulate=%s",
            config.model,
            simulate or "none",
        )

    @property
    def call_count(self) -> int:
        """Number of generate() calls made to this provider."""
        return self._call_count

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
            When ``simulate="error"``.
        LLMTimeoutError
            When ``simulate="timeout"``.
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

        # ── Normal response ──────────────────────────────────
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
