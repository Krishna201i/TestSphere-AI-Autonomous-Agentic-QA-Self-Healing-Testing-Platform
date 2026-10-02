"""
TestSphere-AI — Self-Healing Agent Interface

Abstract base class for the Self-Healing Agent.
The healer takes a failure analysis and DOM context, then proposes
candidate selectors for healing. It NEVER declares healing
successful — that is Member 2's responsibility.

Implementation will be added on Day 2+.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from agents.analyzer.schemas import FailureAnalysis, TestFailure
from agents.healer.schemas import HealingCandidate


class SelfHealingAgent(ABC):
    """Abstract Self-Healing Agent.

    Responsibilities:
    - Generate candidate replacement selectors from DOM evidence
    - Rank candidates by likelihood of correctness
    - Assign confidence scores
    - Return NO_SAFE_HEALING_FOUND when appropriate
    - NEVER declare healing successful (validation is Member 2's job)

    Healing Principles:
    1. Never invent selectors without DOM evidence
    2. Never self-declare healing success
    3. Execution engine validates every candidate
    4. May return NO_SAFE_HEALING_FOUND
    5. Every decision carries a confidence score
    6. Low-confidence healing does not auto-modify tests
    7. Outputs must be structured and validated
    8. API keys are never committed
    """

    @abstractmethod
    async def propose_healing(
        self,
        failure: TestFailure,
        analysis: FailureAnalysis,
        dom_snapshot: str,
    ) -> HealingCandidate:
        """Propose a healing candidate for a failed test step.

        Parameters
        ----------
        failure:
            The original test failure data.
        analysis:
            The failure analysis from the Failure Analyzer Agent.
        dom_snapshot:
            The current DOM state (provided by Member 2).

        Returns
        -------
        HealingCandidate
            A proposed fix, or a candidate with status
            ``NO_SAFE_HEALING_FOUND`` if no safe fix is available.
        """
        ...
