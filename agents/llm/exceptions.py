"""
TestSphere-AI — LLM Exception Hierarchy

Custom exceptions for the LLM client layer.
These allow agents to distinguish between configuration problems,
transient API failures, and permanent errors.

SECURITY: Exception messages MUST NOT contain API keys or tokens.
"""

from __future__ import annotations


class LLMError(Exception):
    """Base exception for all LLM client errors.

    All LLM-related exceptions inherit from this class so that
    callers can catch broad or specific error categories.
    """

    def __init__(self, message: str, *, provider: str = "unknown") -> None:
        self.provider = provider
        super().__init__(message)


class LLMConfigurationError(LLMError):
    """Raised when LLM configuration is missing or invalid.

    Examples:
        - Unknown provider name
        - Invalid model name
        - Missing required configuration

    This error should NOT be retried — it requires a config fix.
    """


class LLMAuthenticationError(LLMError):
    """Raised when the LLM provider rejects the credentials.

    Typically maps to HTTP 401 or 403 responses from API providers.
    This error should NOT be retried — it requires a credential fix.

    Note: Not raised by the mock provider.
    """


class LLMTimeoutError(LLMError):
    """Raised when an LLM request exceeds the configured timeout.

    The request took longer than ``LLMConfig.timeout`` seconds.
    May be retried if retries are configured.
    """


class LLMRateLimitError(LLMError):
    """Raised when the LLM provider returns a rate-limit response.

    Typically maps to HTTP 429 from API providers.
    May be retried with backoff.

    Note: Can be simulated by the mock provider for testing.
    """


class LLMConnectionError(LLMError):
    """Raised when the client cannot reach the LLM provider.

    Covers DNS failures, TCP connection refused, TLS errors, etc.
    May be retried if retries are configured.

    Note: Not raised by the mock provider under normal use.
    """


class LLMProviderError(LLMError):
    """Raised for unexpected provider-side errors.

    Typically maps to HTTP 5xx responses or internal provider errors.
    May be retried if retries are configured.

    The mock provider can simulate this for testing error-handling paths.
    """


class LLMResponseError(LLMError):
    """Raised when the LLM response cannot be parsed or validated.

    Examples:
        - Empty response body
        - Malformed JSON when structured output was expected
        - Response does not match the expected Pydantic schema
    """
