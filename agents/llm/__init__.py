"""TestSphere-AI — LLM subpackage.

Provider-independent LLM abstraction layer.

Architecture::

    Agent
      ↓
    LLMClientSession (Day 3 — reusable client with retries & validation)
      ↓
    LLMClient (abstract provider interface)
      ↓
    get_llm_provider() → MockLLMProvider / LocalLLMProvider / APIProvider
      ↓
    LLMRequest → LLMResponse
      ↓
    ResponseParser → Structured Data
"""

from agents.llm.client import LLMClient, LLMClientSession
from agents.llm.config import LLMConfig
from agents.llm.exceptions import (
    LLMAuthenticationError,
    LLMConfigurationError,
    LLMConnectionError,
    LLMError,
    LLMParsingError,
    LLMProviderError,
    LLMRateLimitError,
    LLMRequestValidationError,
    LLMResponseError,
    LLMSchemaValidationError,
    LLMTimeoutError,
)
from agents.llm.factory import create_llm_client, get_llm_provider
from agents.llm.parser import ResponseParser
from agents.llm.providers.mock import MockLLMProvider
from agents.llm.schemas import LLMRequest, LLMResponse, LLMUsage

__all__ = [
    # Client interface
    "LLMClient",
    "LLMClientSession",
    # Provider factory
    "get_llm_provider",
    "create_llm_client",
    # Mock provider
    "MockLLMProvider",
    # Configuration
    "LLMConfig",
    # Schemas
    "LLMRequest",
    "LLMResponse",
    "LLMUsage",
    # Parser
    "ResponseParser",
    # Exceptions
    "LLMError",
    "LLMConfigurationError",
    "LLMAuthenticationError",
    "LLMRequestValidationError",
    "LLMTimeoutError",
    "LLMRateLimitError",
    "LLMConnectionError",
    "LLMProviderError",
    "LLMResponseError",
    "LLMParsingError",
    "LLMSchemaValidationError",
]
