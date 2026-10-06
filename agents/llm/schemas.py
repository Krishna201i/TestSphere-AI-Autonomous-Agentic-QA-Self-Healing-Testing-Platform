"""
TestSphere-AI — LLM Request / Response Schemas

Provider-independent data models for LLM interactions.
These schemas define the contract between agents and the
LLM abstraction layer, regardless of the underlying provider.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

# Supported response format identifiers
VALID_RESPONSE_FORMATS = {"text", "json"}


class LLMRequest(BaseModel):
    """A structured request to an LLM provider.

    Agents build an ``LLMRequest`` and pass it to the LLM interface.
    The provider translates this into whatever format the underlying
    model expects.
    """

    prompt: str = Field(
        ...,
        description="The user/task prompt to send to the model.",
    )
    system_instruction: str = Field(
        default="",
        description="Optional system-level instruction for the model.",
    )
    temperature: float | None = Field(
        default=None,
        description="Sampling temperature override (None = use config default).",
    )
    max_tokens: int | None = Field(
        default=None,
        description="Max output tokens override (None = use config default).",
    )
    response_format: str = Field(
        default="text",
        description=(
            "Expected response format: 'text' for free-form text, "
            "'json' when structured JSON output is expected."
        ),
    )

    @field_validator("prompt")
    @classmethod
    def prompt_must_not_be_empty(cls, v: str) -> str:
        """Reject empty or whitespace-only prompts."""
        if not v or not v.strip():
            raise ValueError("Prompt must not be empty or whitespace-only.")
        return v

    @field_validator("temperature")
    @classmethod
    def temperature_must_be_in_range(cls, v: float | None) -> float | None:
        """Temperature must be between 0.0 and 2.0 when specified."""
        if v is not None and (v < 0.0 or v > 2.0):
            raise ValueError(
                f"Temperature must be between 0.0 and 2.0, got {v}."
            )
        return v

    @field_validator("max_tokens")
    @classmethod
    def max_tokens_must_be_positive(cls, v: int | None) -> int | None:
        """Max tokens must be positive when specified."""
        if v is not None and v <= 0:
            raise ValueError(
                f"max_tokens must be a positive integer, got {v}."
            )
        return v

    @field_validator("response_format")
    @classmethod
    def response_format_must_be_valid(cls, v: str) -> str:
        """Response format must be a supported value."""
        if v not in VALID_RESPONSE_FORMATS:
            raise ValueError(
                f"Unsupported response_format '{v}'. "
                f"Valid formats: {', '.join(sorted(VALID_RESPONSE_FORMATS))}."
            )
        return v


class LLMUsage(BaseModel):
    """Token usage statistics from an LLM response."""

    prompt_tokens: int = Field(default=0, description="Tokens in the prompt.")
    completion_tokens: int = Field(default=0, description="Tokens in the completion.")

    @property
    def total_tokens(self) -> int:
        """Total tokens used (prompt + completion)."""
        return self.prompt_tokens + self.completion_tokens


class LLMResponse(BaseModel):
    """A structured response from an LLM provider.

    Returned by the LLM interface after a request is processed.
    Agents consume this model without knowing which provider
    generated the response.
    """

    content: str = Field(
        ...,
        description="The model's text response content.",
    )
    model: str = Field(
        default="",
        description="The model name that generated this response.",
    )
    provider: str = Field(
        default="",
        description="The provider that served this response (e.g. 'mock', 'local', 'openai').",
    )
    usage: LLMUsage = Field(
        default_factory=LLMUsage,
        description="Token usage statistics.",
    )
    finish_reason: str = Field(
        default="stop",
        description="Why the model stopped generating (e.g. 'stop', 'length', 'error').",
    )
