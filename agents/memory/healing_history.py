"""
TestSphere-AI — Healing Memory Interface

Abstract base class for the Healing Memory store.
Tracks past healing attempts so the AI can learn from previous
successes and failures, and avoid repeating failed strategies.

.. deprecated:: Day 8
    Superseded by :class:`~agents.memory.store.MemoryStore` and
    :class:`~agents.memory.store.BaseMemoryStore`. Retained for
    backward compatibility with Day 1 prototypes.
"""

from __future__ import annotations

import warnings
from abc import ABC, abstractmethod

from agents.healer.schemas import HealingResult


class HealingMemory(ABC):
    """Abstract Healing Memory store.

    .. deprecated:: Day 8
        Use :class:`~agents.memory.store.MemoryStore` instead.

    Responsibilities:
    - Record healing outcomes (success and failure)
    - Retrieve past healing history for a given selector
    - Enable the AI to learn from previous healing attempts
    - Support confidence calibration over time
    """

    @abstractmethod
    async def record(self, result: HealingResult) -> None:
        """Record a healing outcome.

        Parameters
        ----------
        result:
            The validated healing result to store.
        """
        ...

    @abstractmethod
    async def get_history(
        self,
        selector: str,
        *,
        limit: int = 10,
    ) -> list[HealingResult]:
        """Retrieve past healing attempts for a selector.

        Parameters
        ----------
        selector:
            The original selector to look up history for.
        limit:
            Maximum number of records to return.

        Returns
        -------
        list[HealingResult]
            Past healing results, most recent first.
        """
        ...
