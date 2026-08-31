"""
TestSphere-AI — LLM Client Interface

Abstract base class for LLM providers.
Concrete implementations (Mock, Local, API) inherit from this
interface. Agents interact ONLY with this abstraction.

Architecture::

    Agent
      ↓
    LLMClient (this interface)
      ↓
    MockLLMProvider / LocalLLMProvider / APIProvider
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from agents.llm.config import LLMConfig
from agents.llm.schemas import LLMRequest, LLMResponse


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
