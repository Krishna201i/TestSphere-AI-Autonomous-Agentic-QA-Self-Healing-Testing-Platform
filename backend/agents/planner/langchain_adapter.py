"""
TestSphere-AI — LangChain Planning Adapter

Bridge layer between the Test Planner and the existing LLM
abstraction.  Uses LangChain prompt templates for prompt
construction while delegating LLM invocation to the existing
``LLMClientSession``.

Architecture::

    TestPlanner
        ↓
    LangChainPlanningAdapter     ← this module
        ↓
    TestPlannerPromptTemplate    (LangChain prompts)
        ↓
    LLMClientSession.generate_json()
        ↓
    MockLLMProvider / future provider

The adapter does NOT perform validation — that remains the
planner's responsibility.

Usage::

    from agents.planner.langchain_adapter import LangChainPlanningAdapter

    adapter = LangChainPlanningAdapter(llm_session)
    raw_data = await adapter.generate_raw_plan(context, max_tests=10)
"""

from __future__ import annotations

import logging

from agents.llm.client import LLMClientSession
from agents.llm.schemas import LLMRequest
from agents.planner.langchain_prompts import TestPlannerPromptTemplate
from agents.planner.schemas import ApplicationContext

logger = logging.getLogger(__name__)


class LangChainPlanningAdapter:
    """Adapter bridging LangChain prompt templates to the LLM abstraction.

    This adapter:

    1. Uses ``TestPlannerPromptTemplate`` (LangChain) to build prompts
    2. Sends them through the existing ``LLMClientSession``
    3. Returns the raw JSON response dict

    The adapter preserves provider independence — it works with any
    provider the ``LLMClientSession`` wraps (mock, local, API).

    Parameters
    ----------
    llm_client:
        An ``LLMClientSession`` instance.
    prompt_template:
        Optional custom prompt template.  If ``None``, a default
        ``TestPlannerPromptTemplate`` is created.
    """

    def __init__(
        self,
        llm_client: LLMClientSession,
        prompt_template: TestPlannerPromptTemplate | None = None,
    ) -> None:
        self._llm_client = llm_client
        self._prompt_template = prompt_template or TestPlannerPromptTemplate()
        logger.info(
            "LangChainPlanningAdapter initialized — provider=%s",
            llm_client.provider_name,
        )

    # ── Properties ────────────────────────────────────────────

    @property
    def llm_client(self) -> LLMClientSession:
        """The underlying LLM client session."""
        return self._llm_client

    @property
    def prompt_template(self) -> TestPlannerPromptTemplate:
        """The LangChain prompt template in use."""
        return self._prompt_template

    # ── Plan Generation ───────────────────────────────────────

    async def generate_raw_plan(
        self,
        context: ApplicationContext,
        *,
        max_tests: int = 10,
    ) -> dict:
        """Generate a raw test plan dict using LangChain prompts.

        Builds the prompt using LangChain templates, sends it
        through the existing ``LLMClientSession.generate_json()``,
        and returns the raw JSON dictionary.

        This method does NOT validate the response — that is the
        caller's responsibility.

        Parameters
        ----------
        context:
            The application context to generate tests for.
        max_tests:
            Maximum number of test cases to generate.

        Returns
        -------
        dict
            The raw JSON dictionary from the LLM response.

        Raises
        ------
        LLMProviderError
            If the LLM provider fails.
        LLMTimeoutError
            If the LLM request times out.
        LLMResponseError
            If the LLM response is empty or malformed.
        """
        # 1. Build prompts using LangChain templates
        system_prompt = self._prompt_template.format_system_prompt()
        user_prompt = self._prompt_template.format_user_prompt(
            context, max_tests=max_tests,
        )

        logger.info(
            "LangChainPlanningAdapter: built prompt via LangChain "
            "(%d chars system, %d chars user).",
            len(system_prompt),
            len(user_prompt),
        )

        # 2. Create the LLM request
        request = LLMRequest(
            prompt=user_prompt,
            system_instruction=system_prompt,
            response_format="json",
        )

        # 3. Send through existing LLM abstraction
        raw_data = await self._llm_client.generate_json(request)

        logger.info(
            "LangChainPlanningAdapter: received raw plan with %d keys.",
            len(raw_data),
        )

        return raw_data
