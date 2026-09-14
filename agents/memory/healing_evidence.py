"""
TestSphere-AI — Healing Evidence Retriever

Lightweight, deterministic retrieval layer for historical healing
evidence.  Queries the ``MemoryStore`` and provides structured
answers about past healing outcomes.

Day 12: Healing Result Feedback & Memory Learning.

This module does NOT implement machine learning.  It provides
pure aggregation over ``HealingRecord`` data for use by the
candidate scorer and decision engine.
"""

from __future__ import annotations

import logging
from typing import Optional

from pydantic import BaseModel, Field

from agents.memory.memory_interface import MemoryStore

logger = logging.getLogger(__name__)


# ── Data Models ──────────────────────────────────────────────


class ReplacementStats(BaseModel):
    """Statistics for a specific old → new selector replacement pair.

    Aggregated from historical ``HealingRecord`` data.
    """

    old_selector: str = Field(
        ..., description="The original selector that failed",
    )
    new_selector: str = Field(
        ..., description="The replacement selector that was attempted",
    )
    attempts: int = Field(
        default=0, ge=0,
        description="Total number of healing attempts with this pair",
    )
    successes: int = Field(
        default=0, ge=0,
        description="Number of successful validations",
    )
    failures: int = Field(
        default=0, ge=0,
        description="Number of failed validations",
    )
    inconclusive: int = Field(
        default=0, ge=0,
        description="Number of inconclusive validations (error/skipped)",
    )
    avg_confidence: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Average confidence score across attempts",
    )
    last_used: Optional[str] = Field(
        default=None,
        description="ISO 8601 timestamp of the most recent attempt",
    )

    @property
    def success_rate(self) -> float:
        """Compute the success rate (0.0–1.0).

        Returns 0.0 if no attempts have been made.
        """
        if self.attempts == 0:
            return 0.0
        return self.successes / self.attempts


class SelectorHistory(BaseModel):
    """Aggregated healing history for a specific original selector.

    Provides an overview of all healing attempts involving this
    selector, across all replacement selectors tried.
    """

    selector: str = Field(
        ..., description="The original selector",
    )
    total_healings: int = Field(
        default=0, ge=0,
        description="Total number of healing attempts for this selector",
    )
    total_successes: int = Field(
        default=0, ge=0,
        description="Total successful healings across all replacements",
    )
    total_failures: int = Field(
        default=0, ge=0,
        description="Total failed healings across all replacements",
    )
    distinct_replacements: int = Field(
        default=0, ge=0,
        description="Number of distinct replacement selectors tried",
    )
    replacement_stats: list[ReplacementStats] = Field(
        default_factory=list,
        description="Per-replacement statistics, ordered by success rate (best first)",
    )


# ── Healing Evidence Retriever ────────────────────────────────


class HealingEvidenceRetriever:
    """Deterministic retrieval of historical healing evidence.

    Queries the ``MemoryStore`` and aggregates ``HealingRecord``
    data to answer questions about past healing outcomes.

    Parameters
    ----------
    memory_store:
        The memory store to query for healing records.
    """

    def __init__(self, memory_store: MemoryStore) -> None:
        self._memory = memory_store

    def has_selector_failed(self, selector: str) -> bool:
        """Check whether this selector has been involved in past failures.

        Parameters
        ----------
        selector:
            The selector to check.

        Returns
        -------
        bool
            True if there are healing records for this selector.
        """
        records = self._memory.get_healing_history(selector, limit=1)
        return len(records) > 0

    def has_replacement_succeeded(
        self,
        old_selector: str,
        new_selector: str,
    ) -> bool:
        """Check if a specific replacement has succeeded before.

        Parameters
        ----------
        old_selector:
            The original selector.
        new_selector:
            The replacement selector.

        Returns
        -------
        bool
            True if at least one validated success exists.
        """
        records = self._memory.get_healing_history_for_replacement(
            old_selector, new_selector,
        )
        return any(r.validation_result is True for r in records)

    def get_replacement_stats(
        self,
        old_selector: str,
        new_selector: str,
    ) -> ReplacementStats:
        """Get aggregated statistics for a specific replacement pair.

        Parameters
        ----------
        old_selector:
            The original selector.
        new_selector:
            The replacement selector.

        Returns
        -------
        ReplacementStats
            Aggregated statistics for this replacement pair.
        """
        records = self._memory.get_healing_history_for_replacement(
            old_selector, new_selector,
        )

        if not records:
            return ReplacementStats(
                old_selector=old_selector,
                new_selector=new_selector,
            )

        successes = sum(1 for r in records if r.validation_result is True)
        failures = sum(1 for r in records if r.validation_result is False)
        inconclusive = sum(
            1 for r in records if r.validation_result is None
        )

        confidences = [r.confidence for r in records]
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0

        # Most recent timestamp
        sorted_records = sorted(
            records, key=lambda r: r.timestamp, reverse=True,
        )
        last_used = sorted_records[0].timestamp if sorted_records else None

        return ReplacementStats(
            old_selector=old_selector,
            new_selector=new_selector,
            attempts=len(records),
            successes=successes,
            failures=failures,
            inconclusive=inconclusive,
            avg_confidence=round(min(avg_confidence, 1.0), 4),
            last_used=last_used,
        )

    def get_selector_history(
        self, selector: str,
    ) -> SelectorHistory:
        """Get complete healing history for a selector.

        Parameters
        ----------
        selector:
            The original selector to look up.

        Returns
        -------
        SelectorHistory
            Aggregated history across all replacement selectors.
        """
        all_records = self._memory.get_healing_history(
            selector, limit=100,
        )

        if not all_records:
            return SelectorHistory(selector=selector)

        # Group by new_selector
        by_replacement: dict[str, list] = {}
        for record in all_records:
            key = record.new_selector
            if key not in by_replacement:
                by_replacement[key] = []
            by_replacement[key].append(record)

        # Build per-replacement stats
        replacement_stats: list[ReplacementStats] = []
        total_successes = 0
        total_failures = 0

        for new_sel, records in by_replacement.items():
            stats = self.get_replacement_stats(selector, new_sel)
            replacement_stats.append(stats)
            total_successes += stats.successes
            total_failures += stats.failures

        # Sort by success rate (best first)
        replacement_stats.sort(
            key=lambda s: s.success_rate, reverse=True,
        )

        return SelectorHistory(
            selector=selector,
            total_healings=len(all_records),
            total_successes=total_successes,
            total_failures=total_failures,
            distinct_replacements=len(by_replacement),
            replacement_stats=replacement_stats,
        )

    def get_last_successful_replacement(
        self, selector: str,
    ) -> Optional[str]:
        """Get the most recent successful replacement for a selector.

        Parameters
        ----------
        selector:
            The original selector.

        Returns
        -------
        Optional[str]
            The replacement selector, or None if no success exists.
        """
        records = self._memory.get_healing_history(selector, limit=100)

        # Filter to successful validations, sort by timestamp
        successes = [r for r in records if r.validation_result is True]
        if not successes:
            return None

        latest = max(successes, key=lambda r: r.timestamp)
        return latest.new_selector

    def compute_history_score(
        self,
        old_selector: str,
        new_selector: str,
    ) -> float:
        """Compute a historical evidence score for a replacement.

        Returns a value in [0.0, 1.0] based on historical success rate.
        Returns 0.0 for candidates with no history (neutral — not penalized).

        Parameters
        ----------
        old_selector:
            The original selector that failed.
        new_selector:
            The candidate replacement selector.

        Returns
        -------
        float
            Historical evidence score (0.0 to 1.0).
        """
        stats = self.get_replacement_stats(old_selector, new_selector)

        if stats.attempts == 0:
            # No history — neutral score (not penalized)
            return 0.0

        return stats.success_rate
