"""
TestSphere-AI — LangChain Prompt Templates for the Test Planner

Centralized, reusable prompt-template system built on LangChain's
``PromptTemplate`` and ``ChatPromptTemplate``.

This module does NOT replace the original ``prompts.py``.  It provides
an alternative prompt layer that the ``LangChainPlanningAdapter`` uses.
The original ``build_test_generation_prompt()`` continues to work for
the existing ``LLMTestPlanner``.

All vocabulary constants (actions, assertions, categories, priorities,
output schema) are reused from ``prompts.py`` — no duplication.

Usage::

    from agents.planner.langchain_prompts import TestPlannerPromptTemplate

    template = TestPlannerPromptTemplate()
    system = template.format_system_prompt()
    user   = template.format_user_prompt(context, max_tests=10)
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.prompts import ChatPromptTemplate, PromptTemplate

from agents.planner.prompts import (
    ACTION_VOCABULARY,
    ASSERTION_VOCABULARY,
    CATEGORY_DEFINITIONS,
    OUTPUT_SCHEMA_INSTRUCTION,
    PRIORITY_DEFINITIONS,
    SYSTEM_PROMPT,
)
from agents.planner.schemas import ApplicationContext

logger = logging.getLogger(__name__)


# ── User Prompt Template ────────────────────────────────────────

_USER_PROMPT_TEMPLATE = """\
Generate up to {max_tests} test cases for the following application.

--- APPLICATION INFORMATION ---

Application Name: {app_name}
Application URL: {app_url}
Description: {app_description}

--- PAGES AND FEATURES ---

{pages_summary}

--- AVAILABLE ELEMENTS ---

{elements_summary}

--- USER FLOWS ---

{user_flows}

--- TESTING REQUIREMENTS ---

{testing_requirements}

--- FULL APPLICATION CONTEXT (JSON) ---

{context_json}

--- INSTRUCTIONS ---

{action_vocabulary}
{assertion_vocabulary}
{category_definitions}
{priority_definitions}
{output_schema_instruction}"""


class TestPlannerPromptTemplate:
    """LangChain-based prompt template system for test plan generation.

    Wraps LangChain's ``PromptTemplate`` and ``ChatPromptTemplate``
    to provide structured, maintainable prompt generation.

    The templates accept structured inputs and produce formatted
    prompts that instruct the LLM to generate schema-compliant
    test plans.

    All vocabulary and instruction constants are reused from the
    original ``prompts.py`` module — no content duplication.

    Parameters
    ----------
    system_prompt_override:
        Optional custom system prompt.  If ``None``, the standard
        ``SYSTEM_PROMPT`` from ``prompts.py`` is used.
    """

    def __init__(self, system_prompt_override: str | None = None) -> None:
        self._system_prompt = system_prompt_override or SYSTEM_PROMPT

        # Build the LangChain PromptTemplate for the user prompt
        self._user_template = PromptTemplate(
            input_variables=[
                "max_tests",
                "app_name",
                "app_url",
                "app_description",
                "pages_summary",
                "elements_summary",
                "user_flows",
                "context_json",
                "user_flows",
                "testing_requirements",
            ],
            partial_variables={
                "action_vocabulary": ACTION_VOCABULARY,
                "assertion_vocabulary": ASSERTION_VOCABULARY,
                "category_definitions": CATEGORY_DEFINITIONS,
                "priority_definitions": PRIORITY_DEFINITIONS,
                "output_schema_instruction": OUTPUT_SCHEMA_INSTRUCTION,
            },
            template=_USER_PROMPT_TEMPLATE,
        )

        # Build the ChatPromptTemplate (system + user)
        self._chat_template = ChatPromptTemplate.from_messages([
            ("system", self._system_prompt),
            ("human", _USER_PROMPT_TEMPLATE),
        ]).partial(
            action_vocabulary=ACTION_VOCABULARY,
            assertion_vocabulary=ASSERTION_VOCABULARY,
            category_definitions=CATEGORY_DEFINITIONS,
            priority_definitions=PRIORITY_DEFINITIONS,
            output_schema_instruction=OUTPUT_SCHEMA_INSTRUCTION,
        )

        logger.info("TestPlannerPromptTemplate initialized.")

    # ── Properties ────────────────────────────────────────────

    @property
    def system_prompt(self) -> str:
        """The system prompt string."""
        return self._system_prompt

    @property
    def user_template(self) -> PromptTemplate:
        """The LangChain user prompt template."""
        return self._user_template

    @property
    def chat_template(self) -> ChatPromptTemplate:
        """The LangChain chat prompt template (system + user)."""
        return self._chat_template

    # ── Context Extraction ────────────────────────────────────

    @staticmethod
    def _build_pages_summary(context: ApplicationContext) -> str:
        """Build a human-readable summary of application pages.

        Parameters
        ----------
        context:
            The application context.

        Returns
        -------
        str
            A formatted summary of all pages.
        """
        if not context.pages:
            return "No pages defined."

        parts: list[str] = []
        for page in context.pages:
            desc = page.description or "No description"
            parts.append(
                f"- {page.name or page.url} ({page.url}): {desc}"
            )
        return "\n".join(parts)

    @staticmethod
    def _build_elements_summary(context: ApplicationContext) -> str:
        """Build a summary of interactive elements across all pages.

        Parameters
        ----------
        context:
            The application context.

        Returns
        -------
        str
            A formatted summary of elements grouped by page.
        """
        if not context.pages:
            return "No elements available."

        parts: list[str] = []
        for page in context.pages:
            if not page.elements:
                continue
            parts.append(f"Page: {page.name or page.url}")
            for elem in page.elements:
                ident = elem.id or elem.name or elem.selector or elem.tag
                elem_type = elem.type or elem.tag
                text = elem.text or elem.placeholder or ""
                parts.append(
                    f"  - {elem_type} (#{ident})"
                    + (f' "{text}"' if text else "")
                )
        return "\n".join(parts) if parts else "No elements available."

    @staticmethod
    def _build_user_flows(context: ApplicationContext) -> str:
        """Infer user flows from the application structure.

        For Day 7, this is a simple inference from page names and
        elements.  Future versions may accept explicit user flows.

        Parameters
        ----------
        context:
            The application context.

        Returns
        -------
        str
            A description of potential user flows.
        """
        if not context.pages:
            return "No user flows identified."

        flows: list[str] = []
        page_names = [p.name or p.url for p in context.pages]
        if len(page_names) > 1:
            flows.append(
                f"Navigation flow: {' → '.join(page_names)}"
            )

        for page in context.pages:
            form_elements = [
                e for e in page.elements
                if e.tag in ("input", "textarea", "select")
            ]
            buttons = [
                e for e in page.elements if e.tag == "button"
            ]
            if form_elements and buttons:
                flows.append(
                    f"Form submission on {page.name or page.url}: "
                    f"{len(form_elements)} input(s), "
                    f"{len(buttons)} button(s)"
                )

        return "\n".join(flows) if flows else "No user flows identified."

    @staticmethod
    def _build_testing_requirements(
        context: ApplicationContext,
        *,
        max_tests: int = 10,
    ) -> str:
        """Build testing requirements from context and parameters.

        Parameters
        ----------
        context:
            The application context.
        max_tests:
            Maximum number of test cases to generate.

        Returns
        -------
        str
            A formatted set of testing requirements.
        """
        reqs = [
            f"- Generate up to {max_tests} test cases.",
            "- Cover functional, negative, and boundary scenarios.",
            "- Prioritize by risk and user impact.",
            "- Only reference elements present in the application context.",
        ]
        if context.technology_stack:
            reqs.append(
                f"- Technology stack: {', '.join(context.technology_stack)}."
            )
        return "\n".join(reqs)

    # ── Prompt Formatting ─────────────────────────────────────

    def _build_template_variables(
        self,
        context: ApplicationContext,
        *,
        max_tests: int = 10,
    ) -> dict[str, Any]:
        """Build the template variable dictionary from an ApplicationContext.

        Parameters
        ----------
        context:
            The application context.
        max_tests:
            Maximum number of test cases.

        Returns
        -------
        dict[str, Any]
            Variables ready to pass to LangChain templates.
        """
        return {
            "max_tests": str(max_tests),
            "app_name": context.app_name,
            "app_url": context.app_url,
            "app_description": context.description or "No description provided.",
            "pages_summary": self._build_pages_summary(context),
            "elements_summary": self._build_elements_summary(context),
            "user_flows": self._build_user_flows(context),
            "testing_requirements": self._build_testing_requirements(
                context, max_tests=max_tests,
            ),
            "context_json": json.dumps(
                context.model_dump(mode="json"), indent=2,
            ),
        }

    def format_system_prompt(self) -> str:
        """Return the formatted system prompt.

        Returns
        -------
        str
            The system prompt string.
        """
        return self._system_prompt

    def format_user_prompt(
        self,
        context: ApplicationContext,
        *,
        max_tests: int = 10,
    ) -> str:
        """Format the user prompt with application context.

        Uses the LangChain ``PromptTemplate`` to perform structured
        variable substitution.

        Parameters
        ----------
        context:
            The application context.
        max_tests:
            Maximum number of test cases.

        Returns
        -------
        str
            The fully formatted user prompt.
        """
        variables = self._build_template_variables(
            context, max_tests=max_tests,
        )
        formatted = self._user_template.format(**variables)
        logger.debug(
            "TestPlannerPromptTemplate: formatted user prompt (%d chars).",
            len(formatted),
        )
        return formatted

    def get_messages(
        self,
        context: ApplicationContext,
        *,
        max_tests: int = 10,
    ) -> list:
        """Get formatted chat messages (system + user).

        Uses the LangChain ``ChatPromptTemplate`` for message-based
        prompt construction.

        Parameters
        ----------
        context:
            The application context.
        max_tests:
            Maximum number of test cases.

        Returns
        -------
        list
            A list of LangChain message objects (SystemMessage, HumanMessage).
        """
        variables = self._build_template_variables(
            context, max_tests=max_tests,
        )
        messages = self._chat_template.format_messages(**variables)
        logger.debug(
            "TestPlannerPromptTemplate: generated %d chat messages.",
            len(messages),
        )
        return messages
