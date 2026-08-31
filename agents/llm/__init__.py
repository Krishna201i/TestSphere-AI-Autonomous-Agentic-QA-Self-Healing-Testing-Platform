"""TestSphere-AI — LLM subpackage.

Provider-independent LLM abstraction layer.

Architecture::

    Agent
      ↓
    LLMClient (abstract interface)
      ↓
    get_llm_provider() → MockLLMProvider / LocalLLMProvider / APIProvider
      ↓
    LLMRequest → LLMResponse
      ↓
    ResponseParser → Structured Data
"""

from agents.llm.client import LLMClient
from agents.llm.config import LLMConfig
from agents.llm.exceptions import (
    LLMAuthenticationError,
    LLMConfigurationError,
    LLMConnectionError,
    LLMError,
    LLMProviderError,
    LLMRateLimitError,
    LLMResponseError,
    LLMTimeoutError,
)
from agents.llm.factory import get_llm_provider
from agents.llm.parser import ResponseParser
from agents.llm.providers.mock import MockLLMProvider
from agents.llm.schemas import LLMRequest, LLMResponse, LLMUsage

__all__ = [
    # Client interface
    "LLMClient",
    # Provider factory
    "get_llm_provider",
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
    "LLMTimeoutError",
    "LLMRateLimitError",
    "LLMConnectionError",
    "LLMProviderError",
    "LLMResponseError",
]
