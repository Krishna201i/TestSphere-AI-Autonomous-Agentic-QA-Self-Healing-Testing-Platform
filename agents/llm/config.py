"""
TestSphere-AI — LLM Configuration

Loads LLM settings from environment variables.
API keys are NEVER hard-coded.

The default provider is 'mock', which requires no API key,
no internet access, and no real model.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

from agents.llm.exceptions import LLMConfigurationError

# Valid provider identifiers
VALID_PROVIDERS = {"mock", "local", "api"}


@dataclass(frozen=True)
class LLMConfig:
    """Configuration for the LLM client.

    All values are loaded from environment variables.
    Call ``LLMConfig.from_env()`` to create an instance.

    The ``provider`` field controls which LLM backend is used:
      - ``"mock"``  — deterministic mock for development/testing (default)
      - ``"local"`` — local model (e.g. Ollama) — future
      - ``"api"``   — cloud API (e.g. OpenAI) — future
    """

    provider: str = "mock"
    api_key: str = ""
    model: str = "mock-model"
    temperature: float = 0.2
    max_tokens: int = 4096
    base_url: str | None = None
    timeout: int = 60
    max_retries: int = 2

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
        """
        load_dotenv(dotenv_path=dotenv_path)

        provider = os.getenv("LLM_PROVIDER", "mock")
        api_key = os.getenv("LLM_API_KEY", "")
        model = os.getenv("LLM_MODEL", "mock-model")
        temperature = float(os.getenv("LLM_TEMPERATURE", "0.2"))
        max_tokens = int(os.getenv("LLM_MAX_TOKENS", "4096"))
        base_url = os.getenv("LLM_BASE_URL") or None
        timeout = int(os.getenv("LLM_TIMEOUT", "60"))
        max_retries = int(os.getenv("LLM_MAX_RETRIES", "2"))

        return cls(
            provider=provider,
            api_key=api_key,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
        )

    @property
    def is_configured(self) -> bool:
        """Return True if the provider has sufficient configuration.

        For the mock provider, no API key is needed.
        For API providers, an API key is required.
        """
        if self.provider == "mock":
            return True
        return bool(self.api_key)

    def validate(self) -> None:
        """Validate that the configuration is sufficient for use.

        Raises
        ------
        LLMConfigurationError
            If the provider is unknown, required fields are missing,
            or values are out of range.
        """
        if self.provider not in VALID_PROVIDERS:
            raise LLMConfigurationError(
                f"Unknown LLM_PROVIDER '{self.provider}'. "
                f"Valid providers: {', '.join(sorted(VALID_PROVIDERS))}.",
                provider="config",
            )
        if not self.model:
            raise LLMConfigurationError(
                "LLM_MODEL is not set. Please set it in your .env file.",
                provider="config",
            )
        if self.provider == "api" and not self.api_key:
            raise LLMConfigurationError(
                "LLM_API_KEY is required when LLM_PROVIDER=api.",
                provider="config",
            )
        if self.timeout <= 0:
            raise LLMConfigurationError(
                f"LLM_TIMEOUT must be positive, got {self.timeout}.",
                provider="config",
            )
        if self.max_retries < 0:
            raise LLMConfigurationError(
                f"LLM_MAX_RETRIES must be non-negative, got {self.max_retries}.",
                provider="config",
            )

    def __repr__(self) -> str:
        """Safe repr that never exposes the API key."""
        masked_key = "****" if self.api_key else "<not set>"
        return (
            f"LLMConfig(provider='{self.provider}', api_key='{masked_key}', "
            f"model='{self.model}', temperature={self.temperature}, "
            f"max_tokens={self.max_tokens}, base_url='{self.base_url}', "
            f"timeout={self.timeout}, max_retries={self.max_retries})"
        )
