"""
TestSphere-AI — LLM Provider Factory

Returns the correct LLM provider based on configuration.

Usage::

    config = LLMConfig.from_env()
    provider = get_llm_provider(config)
    response = await provider.generate(request)

Provider selection is driven by ``LLM_PROVIDER`` env var::

    LLM_PROVIDER=mock   →  MockLLMProvider  (default, no deps)
    LLM_PROVIDER=local  →  LocalLLMProvider (future)
    LLM_PROVIDER=api    →  APIProvider      (future)
"""

from __future__ import annotations

import logging

from agents.llm.client import LLMClient
from agents.llm.config import LLMConfig
from agents.llm.exceptions import LLMConfigurationError

logger = logging.getLogger(__name__)


def get_llm_provider(config: LLMConfig | None = None) -> LLMClient:
    """Create and return an LLM provider based on configuration.

    Parameters
    ----------
    config:
        LLM configuration. If ``None``, loads from environment.

    Returns
    -------
    LLMClient
        A concrete LLM provider instance.

    Raises
    ------
    LLMConfigurationError
        If the provider is unknown or not yet implemented.
    """
    if config is None:
        config = LLMConfig.from_env()

    config.validate()

    provider = config.provider

    if provider == "mock":
        from agents.llm.providers.mock import MockLLMProvider

        logger.info("Creating MockLLMProvider (model=%s)", config.model)
        return MockLLMProvider(config)

    if provider == "local":
        raise LLMConfigurationError(
            "LLM_PROVIDER='local' is not yet implemented. "
            "It will be available in a future development day.",
            provider="local",
        )

    if provider == "api":
        raise LLMConfigurationError(
            "LLM_PROVIDER='api' is not yet implemented. "
            "It will be available in a future development day.",
            provider="api",
        )

    raise LLMConfigurationError(
        f"Unknown LLM_PROVIDER '{provider}'. "
        f"Valid providers: mock, local, api.",
        provider="config",
    )
