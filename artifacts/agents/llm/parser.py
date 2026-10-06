"""
TestSphere-AI — LLM Response Parser

Foundation for parsing and validating LLM responses.
Converts raw LLM output into structured, validated data.

Architecture::

    LLM Provider
        ↓
    Raw LLMResponse
        ↓
    ResponseParser
        ↓
    Validated / Structured Data
        ↓
    Agent

For Day 2, the parser handles:
  - Text extraction
  - JSON parsing from text responses
  - Pydantic schema validation

Full agent-specific parsing (e.g. test plan parsing) belongs to
future development days.
"""

from __future__ import annotations

import json
import logging
from typing import TypeVar

from pydantic import BaseModel

from agents.llm.exceptions import LLMResponseError
from agents.llm.schemas import LLMResponse

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class ResponseParser:
    """Parses and validates LLM responses.

    Methods
    -------
    extract_text(response)
        Return the raw text content from a response.
    parse_json(response)
        Parse the response content as JSON.
    parse_model(response, schema)
        Parse and validate the response against a Pydantic model.
    """

    @staticmethod
    def extract_text(response: LLMResponse) -> str:
        """Extract the text content from an LLM response.

        Parameters
        ----------
        response:
            The LLM response to extract text from.

        Returns
        -------
        str
            The text content.

        Raises
        ------
        LLMResponseError
            If the response content is empty.
        """
        if not response.content or not response.content.strip():
            raise LLMResponseError(
                "LLM response contains no text content.",
                provider=response.provider,
            )
        return response.content.strip()

    @staticmethod
    def parse_json(response: LLMResponse) -> dict:
        """Parse the response content as a JSON object.

        Parameters
        ----------
        response:
            The LLM response whose content should be valid JSON.

        Returns
        -------
        dict
            The parsed JSON data.

        Raises
        ------
        LLMResponseError
            If the content is not valid JSON.
        """
        text = response.content.strip()
        if not text:
            raise LLMResponseError(
                "Cannot parse JSON from empty response.",
                provider=response.provider,
            )
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LLMResponseError(
                f"LLM response is not valid JSON: {exc}",
                provider=response.provider,
            ) from exc

        if not isinstance(data, dict):
            raise LLMResponseError(
                f"Expected a JSON object, got {type(data).__name__}.",
                provider=response.provider,
            )

        return data

    @staticmethod
    def parse_model(response: LLMResponse, schema: type[T]) -> T:
        """Parse and validate the response against a Pydantic model.

        Parameters
        ----------
        response:
            The LLM response whose content should be valid JSON
            matching the schema.
        schema:
            A Pydantic model class to validate against.

        Returns
        -------
        T
            An instance of ``schema`` populated from the response.

        Raises
        ------
        LLMResponseError
            If the content is not valid JSON or does not match the schema.
        """
        data = ResponseParser.parse_json(response)

        try:
            return schema.model_validate(data)
        except Exception as exc:
            raise LLMResponseError(
                f"LLM response does not match schema "
                f"{schema.__name__}: {exc}",
                provider=response.provider,
            ) from exc
