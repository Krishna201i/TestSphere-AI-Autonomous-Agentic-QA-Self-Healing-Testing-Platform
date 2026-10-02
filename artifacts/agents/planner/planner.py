"""
TestSphere-AI — Test Planner Agent

Abstract base class and concrete LLM-powered implementation.

Architecture::

    ApplicationContext
          ↓
    Input Validation
          ↓
    LLMTestPlanner
          ↓  (prompt construction)
    LLMClientSession.generate_json()
          ↓
    MockLLMProvider (Day 4) / real provider (future)
          ↓
    Raw JSON Response
          ↓
    Response Parsing → TestPlan
          ↓
    Validation Layer
          ↓
    Duplicate Detection
          ↓
    Element Reference Validation
          ↓
    Valid TestPlan

The Test Planner's ONLY responsibility is to convert structured
application information into meaningful, executable test plans.

It does NOT:
  - Execute tests
  - Open a browser
  - Use Playwright directly
  - Modify the application
  - Validate healed selectors
  - Perform self-healing
  - Interact directly with the frontend

Day 4: Skeleton with input/output validation.
Day 5: Full LLM-based generation logic.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod

from agents.llm.client import LLMClientSession
from agents.llm.exceptions import LLMError, LLMResponseError
from agents.llm.schemas import LLMRequest
from agents.planner.prompts import SYSTEM_PROMPT, build_test_generation_prompt
from agents.planner.schemas import ApplicationContext, TestCase, TestPlan
from agents.planner.validation import (
    TestPlanValidationError,
    detect_duplicate_test_cases,
    validate_application_context,
    validate_element_references,
    validate_test_case,
    validate_test_plan,
)

logger = logging.getLogger(__name__)


class TestPlannerAgent(ABC):
    """Abstract Test Planner Agent.

    Responsibilities:
    - Analyze application context
    - Generate meaningful test cases
    - Produce structured, executable test plans
    - Prioritize tests by risk and importance
    """

    @abstractmethod
    async def generate_tests(
        self,
        context: ApplicationContext,
        *,
        max_tests: int = 10,
    ) -> list[TestCase]:
        """Generate test cases from application context.

        Parameters
        ----------
        context:
            Information about the application under test.
        max_tests:
            Maximum number of test cases to generate.

        Returns
        -------
        list[TestCase]
            A list of generated test cases ready for execution.
        """
        ...


class LLMTestPlanner(TestPlannerAgent):
    """Concrete Test Planner Agent powered by an LLM.

    Uses the ``LLMClientSession`` for provider-independent LLM access.
    The client is injected at construction time, enabling easy testing
    with the ``MockLLMProvider``.

    The generation pipeline is:

    1. Validate ApplicationContext
    2. Build the prompt (system + user)
    3. Send via ``LLMClientSession.generate_json()``
    4. Parse the JSON response into a ``TestPlan``
    5. Validate each ``TestCase`` against business rules
    6. Remove duplicate test cases
    7. Validate element references against the ApplicationContext
    8. Return a valid ``TestPlan``

    Parameters
    ----------
    llm_client:
        An ``LLMClientSession`` instance (wraps any LLM provider).

    Example::

        from agents.llm.factory import create_llm_client

        client = create_llm_client()
        planner = LLMTestPlanner(client)
        plan = await planner.generate_test_plan(app_context)
    """

    def __init__(self, llm_client: LLMClientSession) -> None:
        self._llm_client = llm_client
        logger.info(
            "LLMTestPlanner initialized — provider=%s",
            llm_client.provider_name,
        )

    # ── Properties ────────────────────────────────────────────

    @property
    def llm_client(self) -> LLMClientSession:
        """The underlying LLM client session."""
        return self._llm_client

    # ── Input Validation ──────────────────────────────────────

    @staticmethod
    def _validate_input(context: ApplicationContext) -> None:
        """Validate the application context before generation.

        Raises
        ------
        TestPlanValidationError
            If the input context fails business-rule validation.
        """
        errors = validate_application_context(context)
        if errors:
            raise TestPlanValidationError(
                f"Invalid application context: {'; '.join(errors)}",
                field="application_context",
            )

    # ── Output Validation ─────────────────────────────────────

    @staticmethod
    def _validate_output(test_cases: list[TestCase]) -> list[TestCase]:
        """Validate generated test cases against business rules.

        Invalid test cases are logged and filtered out rather than
        causing total failure.

        Parameters
        ----------
        test_cases:
            The raw generated test cases.

        Returns
        -------
        list[TestCase]
            Only the test cases that pass validation.
        """
        valid_cases: list[TestCase] = []
        for tc in test_cases:
            errors = validate_test_case(tc)
            if errors:
                logger.warning(
                    "LLMTestPlanner: dropping invalid test case '%s': %s",
                    tc.test_id,
                    "; ".join(errors),
                )
            else:
                valid_cases.append(tc)
        return valid_cases

    # ── Prompt Building ───────────────────────────────────────

    @staticmethod
    def _build_prompt(
        context: ApplicationContext,
        *,
        max_tests: int = 10,
    ) -> str:
        """Build the user prompt for test generation.

        Returns
        -------
        str
            The assembled prompt string.
        """
        return build_test_generation_prompt(context, max_tests=max_tests)

    @staticmethod
    def _get_system_prompt() -> str:
        """Return the system prompt for the LLM.

        Returns
        -------
        str
            The system-level instruction for the model.
        """
        return SYSTEM_PROMPT

    # ── Response Parsing ──────────────────────────────────────

    @staticmethod
    def _parse_response(data: dict) -> TestPlan:
        """Parse a raw JSON dict into a TestPlan.

        Handles the conversion from the LLM's raw JSON output
        to a validated ``TestPlan`` Pydantic model.

        Parameters
        ----------
        data:
            The raw JSON dictionary from the LLM response.

        Returns
        -------
        TestPlan
            A parsed (but not yet business-rule validated) TestPlan.

        Raises
        ------
        TestPlanValidationError
            If the response cannot be parsed into a valid TestPlan.
        """
        try:
            plan = TestPlan.model_validate(data)
        except Exception as exc:
            raise TestPlanValidationError(
                f"Failed to parse LLM response into TestPlan: {exc}",
                field="response",
            ) from exc
        return plan

    # ── Duplicate Detection ───────────────────────────────────

    @staticmethod
    def _remove_duplicates(test_cases: list[TestCase]) -> list[TestCase]:
        """Remove duplicate test cases.

        Uses the signature-based detection from the validation layer.
        The first occurrence is kept; duplicates are dropped with a
        warning.

        Parameters
        ----------
        test_cases:
            The list of test cases to deduplicate.

        Returns
        -------
        list[TestCase]
            Test cases with duplicates removed.
        """
        dup_indices = detect_duplicate_test_cases(test_cases)
        if not dup_indices:
            return test_cases

        dup_set = set(dup_indices)
        deduplicated: list[TestCase] = []
        for idx, tc in enumerate(test_cases):
            if idx in dup_set:
                logger.warning(
                    "LLMTestPlanner: removing duplicate test case '%s' "
                    "(index %d)",
                    tc.test_id,
                    idx,
                )
            else:
                deduplicated.append(tc)

        return deduplicated

    # ── Element Reference Validation ──────────────────────────

    @staticmethod
    def _validate_element_refs(
        test_cases: list[TestCase],
        context: ApplicationContext,
    ) -> list[TestCase]:
        """Filter out test cases that reference unknown elements.

        Uses the element reference validation from the validation
        layer.  Test cases with hallucinated element targets are
        dropped with a warning.

        Parameters
        ----------
        test_cases:
            The test cases to validate.
        context:
            The ApplicationContext used for generation.

        Returns
        -------
        list[TestCase]
            Test cases that only reference known elements.
        """
        valid: list[TestCase] = []
        for tc in test_cases:
            ref_errors = validate_element_references(tc, context)
            if ref_errors:
                logger.warning(
                    "LLMTestPlanner: dropping test case '%s' — "
                    "unknown element references: %s",
                    tc.test_id,
                    "; ".join(ref_errors),
                )
            else:
                valid.append(tc)
        return valid

    # ── Generate ──────────────────────────────────────────────

    async def generate_tests(
        self,
        context: ApplicationContext,
        *,
        max_tests: int = 10,
    ) -> list[TestCase]:
        """Generate test cases from application context.

        Full generation pipeline (Day 5):

        1. Validate input ApplicationContext
        2. Build the prompt
        3. Send to LLM via LLMClientSession
        4. Parse the structured JSON response
        5. Validate each test case
        6. Remove duplicates
        7. Validate element references
        8. Return valid test cases

        Parameters
        ----------
        context:
            Information about the application under test.
        max_tests:
            Maximum number of test cases to generate.

        Returns
        -------
        list[TestCase]
            A list of generated, validated test cases.

        Raises
        ------
        TestPlanValidationError
            If the application context is invalid or the response
            cannot be parsed.
        LLMProviderError
            If the LLM provider fails.
        LLMTimeoutError
            If the LLM request times out.
        LLMResponseError
            If the LLM response is empty or malformed.
        """
        # 1. Validate input
        self._validate_input(context)

        # 2. Build prompts
        user_prompt = self._build_prompt(context, max_tests=max_tests)
        system_prompt = self._get_system_prompt()

        logger.info(
            "LLMTestPlanner.generate_tests() — context validated, "
            "prompt built (%d chars).",
            len(user_prompt),
        )

        # 3. Send to LLM — uses generate_json() for automatic JSON parsing
        request = LLMRequest(
            prompt=user_prompt,
            system_instruction=system_prompt,
            response_format="json",
        )

        try:
            raw_data = await self._llm_client.generate_json(request)
        except LLMResponseError:
            # Re-raise LLMResponseError (malformed/empty response)
            raise
        except LLMError:
            # Re-raise other LLM errors (provider, timeout, etc.)
            raise

        # 4. Parse response into TestPlan
        plan = self._parse_response(raw_data)

        logger.info(
            "LLMTestPlanner: parsed %d test cases from LLM response.",
            len(plan.test_cases),
        )

        # 5. Validate each test case
        valid_cases = self._validate_output(plan.test_cases)

        # 6. Remove duplicates
        valid_cases = self._remove_duplicates(valid_cases)

        # 7. Validate element references
        valid_cases = self._validate_element_refs(valid_cases, context)

        logger.info(
            "LLMTestPlanner: returning %d valid test cases "
            "(from %d generated).",
            len(valid_cases),
            len(plan.test_cases),
        )

        return valid_cases

    async def generate_test_plan(
        self,
        context: ApplicationContext,
        *,
        max_tests: int = 10,
    ) -> TestPlan:
        """Generate a complete TestPlan from application context.

        Convenience method that wraps ``generate_tests()`` and
        returns a full ``TestPlan`` object with metadata.

        Parameters
        ----------
        context:
            Information about the application under test.
        max_tests:
            Maximum number of test cases to generate.

        Returns
        -------
        TestPlan
            A validated test plan with metadata.
        """
        test_cases = await self.generate_tests(
            context, max_tests=max_tests,
        )
        return TestPlan(
            application_name=context.app_name,
            base_url=context.app_url,
            test_cases=test_cases,
            metadata={
                "max_tests_requested": max_tests,
                "provider": self._llm_client.provider_name,
            },
        )
