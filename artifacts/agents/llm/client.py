"""
TestSphere-AI — LLM Client Interface & Session

Abstract base class for LLM providers, plus the concrete
``LLMClientSession`` that wraps any provider with:

- Request validation
- Response normalization
- Retry logic (configurable, transient-only)
- Timeout handling
- Error translation

Architecture::

    Agent
      ↓
    LLMClientSession   (this module — Day 3)
      ↓
    LLMClient          (abstract provider interface)
      ↓
    MockLLMProvider / LocalLLMProvider / APIProvider
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from agents.llm.config import LLMConfig
from agents.llm.exceptions import (
    LLMError,
    LLMProviderError,
    LLMRequestValidationError,
    LLMResponseError,
)
from agents.llm.schemas import LLMRequest, LLMResponse

logger = logging.getLogger(__name__)


class LLMClient(ABC):
    """Abstract LLM client.

    All LLM interactions in the system go through this interface.
    This ensures the AI layer is decoupled from any specific LLM
    provider and can be swapped or mocked during testing.

    Concrete implementations:
      - ``MockLLMProvider`` — deterministic mock (Day 2)
      - ``LocalLLMProvider`` — local model via Ollama etc. (future)
      - ``APIProvider`` — cloud API like OpenAI (future)
    """

    def __init__(self, config: LLMConfig) -> None:
        self._config = config

    @property
    def config(self) -> LLMConfig:
        """Return the LLM configuration."""
        return self._config

    @property
    def provider_name(self) -> str:
        """Return the name of this provider."""
        return self._config.provider

    @abstractmethod
    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Send a request to the LLM and return a structured response.

        This is the primary entry point that all agents use.

        Parameters
        ----------
        request:
            A structured LLM request containing the prompt,
            system instruction, and generation parameters.

        Returns
        -------
        LLMResponse
            A structured response containing the model's output,
            usage statistics, and metadata.

        Raises
        ------
        LLMProviderError
            If the provider encounters an internal error.
        LLMTimeoutError
            If the request exceeds the configured timeout.
        LLMResponseError
            If the response cannot be parsed or is invalid.
        """
        ...

    async def complete(
        self,
        prompt: str,
        *,
        system_prompt: str = "",
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Convenience method: send a text prompt and return just the content.

        Builds an ``LLMRequest`` internally and extracts the text
        content from the ``LLMResponse``.

        Parameters
        ----------
        prompt:
            The user/task prompt.
        system_prompt:
            Optional system-level instruction.
        temperature:
            Override the default temperature for this call.
        max_tokens:
            Override the default max tokens for this call.

        Returns
        -------
        str
            The model's text response content.
        """
        request = LLMRequest(
            prompt=prompt,
            system_instruction=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        response = await self.generate(request)
        return response.content


# ════════════════════════════════════════════════════════════════
#  LLMClientSession — Day 3 reusable client wrapper
# ════════════════════════════════════════════════════════════════


class LLMClientSession:
    """Reusable LLM client session that wraps a provider.

    ``LLMClientSession`` is the primary interface that future AI agents
    should use.  It sits between the agent and the underlying provider,
    adding cross-cutting concerns:

    - **Request validation** — rejects malformed requests before they
      reach the provider.
    - **Response normalization** — ensures ``provider`` and ``model``
      fields are always populated, and empty content is caught.
    - **Retry logic** — retries transient provider errors up to
      ``config.max_retries`` times.
    - **Error translation** — catches raw/unexpected exceptions and
      wraps them in ``LLMProviderError``.
    - **Logging** — safe logging of request attempts, retries, and
      errors (never logs secrets or full prompts).

    Architecture::

        Future AI Agent
              ↓
        LLMClientSession     ← you are here
              ↓
        LLMClient (provider)
              ↓
        MockLLMProvider  /  future providers

    Usage::

        from agents.llm.factory import create_llm_client

        client = create_llm_client()
        response = await client.generate(LLMRequest(prompt="…"))

    Parameters
    ----------
    provider:
        A concrete ``LLMClient`` implementation (e.g. ``MockLLMProvider``).
    config:
        Optional explicit config.  If ``None``, the provider's config
        is used.
    """

    def __init__(
        self,
        provider: LLMClient,
        config: LLMConfig | None = None,
    ) -> None:
        self._provider = provider
        self._config = config or provider.config
        logger.info(
            "LLMClientSession initialized — provider=%s, model=%s, "
            "max_retries=%d, timeout=%ds",
            self._config.provider,
            self._config.model,
            self._config.max_retries,
            self._config.timeout,
        )

    # ── Properties ────────────────────────────────────────────

    @property
    def provider(self) -> LLMClient:
        """The underlying LLM provider."""
        return self._provider

    @property
    def config(self) -> LLMConfig:
        """The active LLM configuration."""
        return self._config

    @property
    def provider_name(self) -> str:
        """Name of the configured provider."""
        return self._config.provider

    # ── Request Validation ────────────────────────────────────

    @staticmethod
    def _validate_request(request: LLMRequest) -> None:
        """Validate an LLM request before sending to the provider.

        The Pydantic model already enforces structural constraints
        (non-empty prompt, valid temperature, etc.) at construction
        time.  This method performs additional semantic checks.

        Raises
        ------
        LLMRequestValidationError
            If the request is semantically invalid.
        """
        # Pydantic validators already enforce non-empty prompt,
        # temperature range, max_tokens > 0, and valid response_format.
        # This method exists as the single point for any future
        # semantic validation that goes beyond schema constraints.
        if not request.prompt.strip():
            raise LLMRequestValidationError(
                "Request prompt must not be empty or whitespace-only.",
                provider="client",
            )

    # ── Response Normalization ────────────────────────────────

    def _normalize_response(self, response: LLMResponse) -> LLMResponse:
        """Normalize a provider response into the standard schema.

        Ensures that ``provider`` and ``model`` fields are populated
        even if the provider didn't set them, and that content is
        not empty.

        Parameters
        ----------
        response:
            The raw response from the provider.

        Returns
        -------
        LLMResponse
            The normalized response.

        Raises
        ------
        LLMResponseError
            If the response has empty or missing content.
        """
        # Ensure provider field is populated
        provider = response.provider or self._config.provider
        model = response.model or self._config.model

        # Check for empty content
        if not response.content and not response.content.strip():
            raise LLMResponseError(
                "Provider returned an empty response.",
                provider=provider,
            )

        return LLMResponse(
            content=response.content,
            model=model,
            provider=provider,
            usage=response.usage,
            finish_reason=response.finish_reason,
        )

    # ── Generate ──────────────────────────────────────────────

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Send a request to the LLM provider and return a normalized response.

        This is the main entry point for AI agents.  The method:

        1. Validates the request.
        2. Delegates to the configured provider (with retry logic).
        3. Normalizes the response.
        4. Translates provider errors into project-level exceptions.

        Parameters
        ----------
        request:
            A valid ``LLMRequest``.

        Returns
        -------
        LLMResponse
            A standardized, normalized response.

        Raises
        ------
        LLMRequestValidationError
            If the request is invalid.
        LLMProviderError
            If the provider fails after all retries.
        LLMTimeoutError
            If the provider times out after all retries.
        LLMResponseError
            If the response cannot be parsed or is empty.
        """
        # 1. Validate
        self._validate_request(request)

        max_attempts = 1 + self._config.max_retries
        last_error: LLMError | None = None

        for attempt in range(1, max_attempts + 1):
            try:
                logger.info(
                    "LLMClientSession.generate() — attempt %d/%d, "
                    "provider=%s",
                    attempt,
                    max_attempts,
                    self._config.provider,
                )

                # 2. Delegate to provider
                raw_response = await self._provider.generate(request)

                # 3. Normalize
                response = self._normalize_response(raw_response)

                logger.info(
                    "LLMClientSession.generate() — success on attempt "
                    "%d/%d, tokens=%d",
                    attempt,
                    max_attempts,
                    response.usage.total_tokens,
                )

                return response

            except LLMError as exc:
                last_error = exc

                if not exc.is_retryable:
                    # Permanent error — do not retry
                    logger.warning(
                        "LLMClientSession.generate() — non-retryable "
                        "error on attempt %d/%d: %s: %s",
                        attempt,
                        max_attempts,
                        type(exc).__name__,
                        exc,
                    )
                    raise

                if attempt < max_attempts:
                    logger.warning(
                        "LLMClientSession.generate() — retryable error "
                        "on attempt %d/%d: %s: %s — retrying…",
                        attempt,
                        max_attempts,
                        type(exc).__name__,
                        exc,
                    )
                else:
                    logger.error(
                        "LLMClientSession.generate() — retryable error "
                        "on final attempt %d/%d: %s: %s — giving up",
                        attempt,
                        max_attempts,
                        type(exc).__name__,
                        exc,
                    )

            except Exception as exc:
                # Unexpected error — wrap in LLMProviderError
                logger.error(
                    "LLMClientSession.generate() — unexpected error "
                    "on attempt %d/%d: %s: %s",
                    attempt,
                    max_attempts,
                    type(exc).__name__,
                    exc,
                )
                raise LLMProviderError(
                    f"Unexpected provider error: {exc}",
                    provider=self._config.provider,
                ) from exc

        # All retries exhausted
        assert last_error is not None
        raise last_error

    async def generate_json(self, request: LLMRequest) -> dict:
        """Convenience: generate a response and parse it as JSON.

        Builds on ``generate()`` with automatic JSON parsing.
        Sets ``response_format="json"`` on the request if not already set.

        Parameters
        ----------
        request:
            A valid ``LLMRequest``.  ``response_format`` will be set
            to ``"json"`` automatically.

        Returns
        -------
        dict
            The parsed JSON object from the response.

        Raises
        ------
        LLMResponseError
            If the response content is not valid JSON.
        """
        import json

        # Ensure response_format is json
        if request.response_format != "json":
            request = request.model_copy(update={"response_format": "json"})

        response = await self.generate(request)

        text = response.content.strip()
        if not text:
            raise LLMResponseError(
                "Cannot parse JSON from empty response.",
                provider=response.provider,
            )

        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMResponseError(
                f"Response is not valid JSON: {exc}",
                provider=response.provider,
            ) from exc

        if not isinstance(data, dict):
            raise LLMResponseError(
                f"Expected a JSON object, got {type(data).__name__}.",
                provider=response.provider,
            )

        return data

    async def complete(
        self,
        prompt: str,
        *,
        system_prompt: str = "",
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Convenience: send a text prompt and return just the content.

        Parameters
        ----------
        prompt:
            The user/task prompt.
        system_prompt:
            Optional system-level instruction.
        temperature:
            Override the default temperature for this call.
        max_tokens:
            Override the default max tokens for this call.

        Returns
        -------
        str
            The model's text response content.
        """
        request = LLMRequest(
            prompt=prompt,
            system_instruction=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        response = await self.generate(request)
        return response.content
