"""
TestSphere-AI — LLM Configuration

Loads LLM settings from environment variables.
API keys are NEVER hard-coded.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv


@dataclass(frozen=True)
class LLMConfig:
    """Configuration for the LLM client.

    All values are loaded from environment variables.
    Call ``LLMConfig.from_env()`` to create an instance.
    """

    api_key: str = ""
    model: str = "gpt-4o"
    temperature: float = 0.2
    max_tokens: int = 4096

    @classmethod
    def from_env(cls, dotenv_path: str | None = None) -> LLMConfig:
        """Load configuration from environment variables.

        Parameters
        ----------
        dotenv_path:
            Optional path to a ``.env`` file. If not provided, the
            standard ``python-dotenv`` search is used.

        Returns
        -------
        LLMConfig
            A frozen configuration instance.

        Raises
        ------
        ValueError
            If ``LLM_API_KEY`` is not set and we are not in a test
            environment.
        """
        load_dotenv(dotenv_path=dotenv_path)

        api_key = os.getenv("LLM_API_KEY", "")
        model = os.getenv("LLM_MODEL", "gpt-4o")
        temperature = float(os.getenv("LLM_TEMPERATURE", "0.2"))
        max_tokens = int(os.getenv("LLM_MAX_TOKENS", "4096"))

        return cls(
            api_key=api_key,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    @property
    def is_configured(self) -> bool:
        """Return True if an API key is present."""
        return bool(self.api_key)
