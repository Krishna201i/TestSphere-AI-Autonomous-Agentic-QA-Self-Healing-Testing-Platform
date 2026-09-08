"""
TestSphere-AI — Structured Output Processor

Centralized processing layer between raw LLM responses and
schema validation.  Handles JSON cleanup, field coercion,
and Pydantic validation for test plan output.

Pipeline::

    Raw JSON dict (from LLM)
        ↓
    StructuredOutputProcessor.process()
        ↓
      - JSON string cleanup (if needed)
      - Field coercion (normalize common LLM variations)
      - Pydantic validation (TestPlan.model_validate)
        ↓
    TestPlan (or StructuredOutputError)

This module does NOT replace validation.py.  Business-rule
validation (action requirements, element references, duplicate
detection) is still performed by the planner after this stage.

Usage::

    from agents.planner.structured_output import StructuredOutputProcessor

    processor = StructuredOutputProcessor()
    test_plan = processor.process(raw_dict)
"""

from __future__ import annotations

import json
import logging
import re

from agents.planner.schemas import TestPlan

logger = logging.getLogger(__name__)


# ── Custom Exception ─────────────────────────────────────────


class StructuredOutputError(Exception):
    """Raised when structured output processing fails.

    This covers JSON cleanup failures, coercion errors, and
    Pydantic validation failures during output processing.

    Parameters
    ----------
    message:
        Human-readable description of the failure.
    stage:
        The processing stage where the failure occurred
        (e.g. 'cleanup', 'coercion', 'validation').
    """

    def __init__(self, message: str, *, stage: str = "") -> None:
        self.stage = stage
        super().__init__(message)


# ── Structured Output Processor ──────────────────────────────


class StructuredOutputProcessor:
    """Processes raw LLM output into validated TestPlan objects.

    Sits between the raw LLM response and business-rule validation.
    Handles common LLM output issues:

    - Markdown code fences around JSON
    - Trailing commas in JSON
    - Case-insensitive field values (priority, category)
    - Missing optional fields

    The processor does NOT perform business-rule validation
    (action requirements, element references, etc.).  That remains
    the responsibility of the validation layer.
    """

    # ── JSON String Cleanup ──────────────────────────────────

    @staticmethod
    def clean_json_string(text: str) -> str:
        """Clean a raw text response into parseable JSON.

        Handles common LLM output quirks:

        - Strips markdown code fences (```json ... ```)
        - Removes trailing commas before closing brackets
        - Strips leading/trailing whitespace

        Parameters
        ----------
        text:
            The raw text from the LLM response.

        Returns
        -------
        str
            Cleaned JSON string ready for ``json.loads()``.

        Raises
        ------
        StructuredOutputError
            If the text is empty after cleanup.
        """
        if not text or not text.strip():
            raise StructuredOutputError(
                "Cannot clean empty text.", stage="cleanup",
            )

        cleaned = text.strip()

        # Strip markdown code fences: ```json ... ```  or  ``` ... ```
        fence_pattern = r"^```(?:json)?\s*\n?(.*?)\n?\s*```$"
        match = re.match(fence_pattern, cleaned, re.DOTALL)
        if match:
            cleaned = match.group(1).strip()

        # Remove trailing commas before closing brackets/braces
        # e.g., {"a": 1,} → {"a": 1}
        cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)

        if not cleaned:
            raise StructuredOutputError(
                "Text is empty after cleanup.", stage="cleanup",
            )

        return cleaned

    # ── Field Coercion ───────────────────────────────────────

    @staticmethod
    def coerce_fields(data: dict) -> dict:
        """Normalize common LLM output variations in field values.

        Handles:

        - Priority case normalization (``"high"`` → ``"HIGH"``)
        - Category case normalization (``"Functional"`` → ``"functional"``)
        - Action case normalization (``"Click"`` → ``"click"``)
        - Assertion type normalization

        The coercion is applied recursively to all test cases,
        steps, and assertions in the data.

        Parameters
        ----------
        data:
            The parsed JSON dictionary from the LLM response.

        Returns
        -------
        dict
            The dictionary with normalized field values.
        """
        # Valid priority values (uppercase)
        valid_priorities = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
        # Valid categories (lowercase)
        valid_categories = {
            "functional", "negative", "boundary", "smoke",
            "regression", "edge_case", "accessibility",
        }
        # Valid actions (lowercase)
        valid_actions = {
            "navigate", "click", "fill", "select",
            "check", "uncheck", "press", "wait",
        }
        # Valid assertion types (lowercase with underscores)
        valid_assertion_types = {
            "element_visible", "element_not_visible",
            "element_contains_text", "element_has_text",
            "url_contains", "url_equals", "value_equals",
        }

        coerced = dict(data)

        if "test_cases" not in coerced:
            return coerced

        for tc in coerced.get("test_cases", []):
            if not isinstance(tc, dict):
                continue

            # Coerce priority → UPPER
            if "priority" in tc and isinstance(tc["priority"], str):
                upper = tc["priority"].upper()
                if upper in valid_priorities:
                    tc["priority"] = upper

            # Coerce category → lower
            if "category" in tc and isinstance(tc["category"], str):
                lower = tc["category"].lower()
                if lower in valid_categories:
                    tc["category"] = lower

            # Coerce steps
            for step in tc.get("steps", []):
                if not isinstance(step, dict):
                    continue
                if "action" in step and isinstance(step["action"], str):
                    lower = step["action"].lower()
                    if lower in valid_actions:
                        step["action"] = lower

                # Coerce inline assertions on steps
                for assertion in step.get("assertions", []):
                    if not isinstance(assertion, dict):
                        continue
                    if "type" in assertion and isinstance(assertion["type"], str):
                        lower = assertion["type"].lower()
                        if lower in valid_assertion_types:
                            assertion["type"] = lower

            # Coerce top-level assertions
            for assertion in tc.get("assertions", []):
                if not isinstance(assertion, dict):
                    continue
                if "type" in assertion and isinstance(assertion["type"], str):
                    lower = assertion["type"].lower()
                    if lower in valid_assertion_types:
                        assertion["type"] = lower

        return coerced

    # ── Core Processing ──────────────────────────────────────

    def process(self, raw_data: dict) -> TestPlan:
        """Process raw LLM output into a validated TestPlan.

        Pipeline:

        1. Coerce field values (normalize case, fix common issues)
        2. Validate against the TestPlan Pydantic schema

        Parameters
        ----------
        raw_data:
            The raw JSON dictionary from the LLM response.

        Returns
        -------
        TestPlan
            A validated (schema-level) TestPlan.
            Business-rule validation is done separately.

        Raises
        ------
        StructuredOutputError
            If coercion or schema validation fails.
        """
        if not isinstance(raw_data, dict):
            raise StructuredOutputError(
                f"Expected a dict, got {type(raw_data).__name__}.",
                stage="validation",
            )

        # 1. Coerce fields
        try:
            coerced = self.coerce_fields(raw_data)
        except Exception as exc:
            raise StructuredOutputError(
                f"Field coercion failed: {exc}",
                stage="coercion",
            ) from exc

        # 2. Pydantic validation
        try:
            plan = TestPlan.model_validate(coerced)
        except Exception as exc:
            raise StructuredOutputError(
                f"Schema validation failed: {exc}",
                stage="validation",
            ) from exc

        logger.info(
            "StructuredOutputProcessor: validated TestPlan with %d test cases.",
            len(plan.test_cases),
        )

        return plan

    def process_text(self, text: str) -> TestPlan:
        """Process a raw text response into a validated TestPlan.

        Combines JSON cleanup and processing in a single call.
        Useful when the raw LLM response is a text string rather
        than a pre-parsed dict.

        Parameters
        ----------
        text:
            The raw text response from the LLM.

        Returns
        -------
        TestPlan
            A validated TestPlan.

        Raises
        ------
        StructuredOutputError
            If cleanup, parsing, or validation fails.
        """
        # 1. Clean the JSON string
        cleaned = self.clean_json_string(text)

        # 2. Parse JSON
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise StructuredOutputError(
                f"JSON parsing failed: {exc}",
                stage="cleanup",
            ) from exc

        if not isinstance(data, dict):
            raise StructuredOutputError(
                f"Expected a JSON object, got {type(data).__name__}.",
                stage="cleanup",
            )

        # 3. Process the parsed dict
        return self.process(data)
