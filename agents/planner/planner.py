"""
TestSphere-AI — Test Planner Agent

Abstract base class and concrete LLM-powered implementation skeleton.

Architecture::

    ApplicationContext
          ↓
    LLMTestPlanner
          ↓  (uses)
    LLMClientSession
          ↓
    MockLLMProvider (Day 4) / real provider (future)
          ↓
    Structured Test Plan
          ↓
    Validation Layer
          ↓
    Valid list[TestCase]

The Test Planner's ONLY responsibility is to convert structured
application information into meaningful, executable test plans.

It does NOT:
  - Execute browser actions
  - Use Playwright directly
  - Modify the application
  - Validate healed selectors
  - Perform self-healing
  - Interact directly with the frontend

Day 4: Skeleton with input/output validation.
Day 5: Full LLM-based generation logic.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from agents.llm.client import LLMClientSession
from agents.planner.prompts import SYSTEM_PROMPT, build_test_generation_prompt
from agents.planner.schemas import ApplicationContext, TestCase, TestPlan
from agents.planner.validation import (
    TestPlanValidationError,
    validate_application_context,
    validate_test_case,
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

    Parameters
    ----------
    llm_client:
        An ``LLMClientSession`` instance (wraps any LLM provider).

    Example::

        from agents.llm.factory import create_llm_client

        client = create_llm_client()
        planner = LLMTestPlanner(client)
        tests = await planner.generate_tests(app_context)
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

    # ── Generate ──────────────────────────────────────────────

    async def generate_tests(
        self,
        context: ApplicationContext,
        *,
        max_tests: int = 10,
    ) -> list[TestCase]:
        """Generate test cases from application context.

        Day 4: Skeleton implementation.  Validates input and raises
        ``NotImplementedError`` — the actual LLM generation logic
        will be implemented on Day 5.

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

        Raises
        ------
        TestPlanValidationError
            If the application context is invalid.
        NotImplementedError
            Always — full generation is a Day 5 deliverable.
        """
        # 1. Validate input
        self._validate_input(context)

        # 2. Build prompt (validates prompt construction works)
        _prompt = self._build_prompt(context, max_tests=max_tests)
        _system = self._get_system_prompt()

        logger.info(
            "LLMTestPlanner.generate_tests() — context validated, "
            "prompt built (%d chars).  Generation not yet implemented.",
            len(_prompt),
        )

        # 3. Actual LLM invocation → Day 5
        raise NotImplementedError(
            "LLMTestPlanner.generate_tests() is a Day 4 skeleton. "
            "Full LLM-based generation will be implemented on Day 5."
        )
