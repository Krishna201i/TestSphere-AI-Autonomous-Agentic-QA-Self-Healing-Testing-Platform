"""
TestSphere-AI — Test Planner Agent Interface

Abstract base class for the Test Planner Agent.
The planner receives application context and generates test cases
for Member 2's execution engine.

Implementation will be added on Day 2+.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from agents.planner.schemas import ApplicationContext, TestCase


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
