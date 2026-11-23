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
VALID_PROVIDERS = {"mock", "local", "api", "chain"}


# ---------------------------------------------------------------------------
# Fallback chain (LLM_PROVIDER=chain)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ChainLink:
    """One provider in the fallback chain.  ``api_key`` is never shown in repr."""

    name: str
    base_url: str
    model: str
    api_key: str = ""
    # Extra chat-completions fields this provider understands (e.g. NVIDIA's chat_template_kwargs)
    extra_body: tuple[tuple[str, object], ...] = ()

    def __repr__(self) -> str:
        return f"ChainLink(name={self.name!r}, model={self.model!r}, key={'****' if self.api_key else '<not set>'})"


NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
# Largest context window first (the providers' own figures): Gemini 3.8 Flash 1,048,576 tokens, Nemotron 3
# Ultra up to 1M, Gemma 4 31B 256K, Groq gpt-oss-120b 131,072
DEFAULT_CHAIN = "gemini,nvidia-nemotron,nvidia-gemma,groq"


def _env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return default


def chain_link(name: str) -> ChainLink:
    """The provider *name* as configured by its environment variables.

    Raises ``LLMConfigurationError`` for an unknown name.
    """
    nvidia = _env("NVIDIA_BASE_URL", default=NVIDIA_BASE_URL)
    if name == "nvidia-gemma":
        return ChainLink(name, nvidia, _env("NVIDIA_GEMMA_MODEL", default="google/gemma-4-31b-it"),
                         _env("NVIDIA_GEMMA_API_KEY", "NVIDIA_API_KEY"))
    if name == "nvidia-nemotron":
        thinking = _env("NVIDIA_NEMOTRON_THINKING", default="false").lower() in ("1", "true", "yes", "on")
        return ChainLink(name, nvidia, _env("NVIDIA_NEMOTRON_MODEL", default="nvidia/nemotron-3-ultra-550b-a55b"),
                         _env("NVIDIA_NEMOTRON_API_KEY", "NVIDIA_API_KEY"),
                         (("chat_template_kwargs", {"enable_thinking": thinking}),))
    if name == "groq":
        return ChainLink(name, _env("GROQ_BASE_URL", default="https://api.groq.com/openai/v1"),
                         _env("GROQ_MODEL", default="openai/gpt-oss-120b"), _env("GROQ_API_KEY"))
    if name == "gemini":
        return ChainLink(name, _env("GEMINI_BASE_URL", default="https://generativelanguage.googleapis.com/v1beta/openai"),
                         _env("GEMINI_MODEL", default="gemini-3.8-flash"), _env("GEMINI_API_KEY"))
    raise LLMConfigurationError(
        f"Unknown provider '{name}' in LLM_CHAIN (use nvidia-gemma, nvidia-nemotron, groq, gemini).",
        provider="config",
    )


def chain_links(*, configured_only: bool = True) -> list[ChainLink]:
    """The providers of ``LLM_CHAIN`` in order; by default only those with an API key."""
    names = [n.strip().lower() for n in _env("LLM_CHAIN", default=DEFAULT_CHAIN).split(",") if n.strip()]
    links = [chain_link(n) for n in dict.fromkeys(names)]
    return [link for link in links if link.api_key] if configured_only else links


@dataclass(frozen=True)
class LLMConfig:
    """Configuration for the LLM client.

    All values are loaded from environment variables.
    Call ``LLMConfig.from_env()`` to create an instance.

    The ``provider`` field controls which LLM backend is used:
      - ``"mock"``  — deterministic mock for development/testing (default)
      - ``"local"`` — OpenAI-compatible server on your machine (Ollama, vLLM, ...)
      - ``"api"``   — OpenAI-compatible cloud API (OpenAI, Gemini, Groq, …)
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
        if self.provider in ("mock", "local"):
            return True
        if self.provider == "chain":
            return bool(chain_links())
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
        if self.provider == "chain" and not chain_links():
            raise LLMConfigurationError(
                "LLM_PROVIDER=chain needs at least one provider key: NVIDIA_API_KEY (or NVIDIA_GEMMA_API_KEY / "
                "NVIDIA_NEMOTRON_API_KEY), GROQ_API_KEY or GEMINI_API_KEY.",
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
