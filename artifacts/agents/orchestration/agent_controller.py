"""
TestSphere-AI — Agent Controller Interface

Orchestrates the AI agent pipeline:
  ApplicationContext → Planner → TestCases → Execution → Results
  Failure → Analyzer → FailureAnalysis → Healer → HealingCandidate → Validation

The controller is the main entry point for Member 3's backend to
invoke the AI intelligence layer.

Implementation will be added on Day 2+.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from agents.analyzer.analyzer import FailureAnalyzerAgent
from agents.analyzer.schemas import FailureAnalysis, TestFailure
from agents.healer.healer import SelfHealingAgent
from agents.healer.schemas import HealingCandidate
from agents.memory.healing_history import HealingMemory
from agents.planner.planner import TestPlannerAgent
from agents.planner.schemas import ApplicationContext, TestCase


class AgentController(ABC):
    """Abstract orchestration controller for the AI agent pipeline.

    This is the primary interface between the AI layer (Member 1)
    and the rest of the system (Members 2 and 3).

    The controller coordinates:
    1. Test generation via the Test Planner Agent
    2. Failure analysis via the Failure Analyzer Agent
    3. Self-healing via the Self-Healing Agent
    4. Healing memory recording

    Data Flow:
    ─────────
    ApplicationContext
        → TestPlannerAgent.generate_tests()
        → list[TestCase]
        → Member 2 executes
        → TestFailure (if failure)
        → FailureAnalyzerAgent.analyze()
        → FailureAnalysis
        → SelfHealingAgent.propose_healing()
        → HealingCandidate
        → Member 2 validates
        → HealingResult
        → HealingMemory.record()
    """

    @abstractmethod
    async def generate_test_plan(
        self,
        context: ApplicationContext,
    ) -> list[TestCase]:
        """Generate test cases for an application.

        Parameters
        ----------
        context:
            Application context describing what to test.

        Returns
        -------
        list[TestCase]
            Generated test cases for Member 2 to execute.
        """
        ...

    @abstractmethod
    async def handle_failure(
        self,
        failure: TestFailure,
    ) -> HealingCandidate | FailureAnalysis:
        """Handle a test failure: analyze and optionally propose healing.

        Parameters
        ----------
        failure:
            Test failure data from Member 2's execution engine.

        Returns
        -------
        HealingCandidate | FailureAnalysis
            A healing candidate if the failure is healable,
            or just the analysis if it is not.
        """
        ...
