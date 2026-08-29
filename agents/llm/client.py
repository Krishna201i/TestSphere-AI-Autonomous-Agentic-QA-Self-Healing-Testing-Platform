"""
TestSphere-AI — LLM Client Interface

Abstract base class for LLM interactions.
Concrete implementations (OpenAI, Anthropic, etc.) will be
added on future development days.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from agents.llm.config import LLMConfig


class LLMClient(ABC):
    """Abstract LLM client.

    All LLM interactions in the system go through this interface.
    This ensures the AI layer is decoupled from any specific LLM
    provider and can be swapped or mocked during testing.

    Concrete implementations will be added on Day 2+.
    """

    def __init__(self, config: LLMConfig) -> None:
        self._config = config

    @property
    def config(self) -> LLMConfig:
        """Return the LLM configuration."""
        return self._config

    @abstractmethod
    async def complete(
        self,
        prompt: str,
        *,
        system_prompt: str = "",
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Send a completion request to the LLM.

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
            The LLM's text response.
        """
        ...

    @abstractmethod
    async def complete_structured(
        self,
        prompt: str,
        response_schema: type,
        *,
        system_prompt: str = "",
        temperature: float | None = None,
    ) -> Any:
        """Send a completion request expecting structured output.

        The response will be parsed and validated against the
        provided Pydantic model / response_schema.

        Parameters
        ----------
        prompt:
            The user/task prompt.
        response_schema:
            A Pydantic model class to validate the response against.
        system_prompt:
            Optional system-level instruction.
        temperature:
            Override the default temperature for this call.

        Returns
        -------
        Any
            An instance of ``response_schema`` populated from the
            LLM's response.
        """
        ...
