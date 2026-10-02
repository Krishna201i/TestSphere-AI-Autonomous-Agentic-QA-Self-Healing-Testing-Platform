"""
TestSphere-AI — Failure Analyzer Agent Interface

Abstract base class for the Failure Analysis Agent.
The analyzer receives test failures from Member 2 and produces
a structured analysis including root cause and healability.

Implementation will be added on Day 2+.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from agents.analyzer.schemas import FailureAnalysis, TestFailure


class FailureAnalyzerAgent(ABC):
    """Abstract Failure Analyzer Agent.

    Responsibilities:
    - Classify failure type
    - Determine root cause
    - Assess whether the failure is healable
    - Produce a confidence score for the analysis
    """

    @abstractmethod
    async def analyze(self, failure: TestFailure) -> FailureAnalysis:
        """Analyze a test failure.

        Parameters
        ----------
        failure:
            The test failure data from Member 2's execution engine.

        Returns
        -------
        FailureAnalysis
            Structured analysis including failure type, root cause,
            healability, and confidence score.
        """
        ...
