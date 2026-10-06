"""
TestSphere-AI — Healing Pattern Detector

Identifies recurring patterns in healing history that can serve
as structured signals for future healing decisions.

Day 12: Healing Result Feedback & Memory Learning.

Pattern Types
-------------
1. SELECTOR_CHAIN:  A → B → C (repeated selector changes)
2. RELIABLE_REPLACEMENT: Same replacement succeeded N times
3. UNRELIABLE_REPLACEMENT: A replacement repeatedly fails

This module does NOT implement predictive ML.  It produces
structured historical signals that can be consumed by the
decision engine or presented to human operators.
"""

from __future__ import annotations

import logging
from typing import Optional

from pydantic import BaseModel, Field

from agents.memory.memory_interface import MemoryStore
from agents.schemas.enums import HealingPatternType

logger = logging.getLogger(__name__)

# ── Minimum occurrences to declare a pattern ──────────────────
# These thresholds prevent noise from one-off events.

SELECTOR_CHAIN_MIN_LENGTH = 2
RELIABLE_REPLACEMENT_MIN_SUCCESSES = 2
UNRELIABLE_REPLACEMENT_MIN_FAILURES = 2


# ── Pattern Model ────────────────────────────────────────────


class HealingPattern(BaseModel):
    """A detected healing pattern from historical data.

    Represents a recurring behavior observed in the healing
    history that may inform future decisions.
    """

    pattern_type: HealingPatternType = Field(
        ..., description="Type of pattern detected",
    )
    selectors: list[str] = Field(
        default_factory=list,
        description=(
            "Selectors involved in the pattern. "
            "For SELECTOR_CHAIN: the chain of selectors. "
            "For RELIABLE/UNRELIABLE: [old_selector, new_selector]."
        ),
    )
    occurrences: int = Field(
        default=0, ge=0,
        description="Number of times this pattern has been observed",
    )
    confidence_signal: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description=(
            "Signal strength (0.0–1.0). Higher values indicate "
            "stronger evidence for the pattern."
        ),
    )
    description: str = Field(
        default="",
        description="Human-readable description of the pattern",
    )


# ── Pattern Detector ─────────────────────────────────────────


class HealingPatternDetector:
    """Detects recurring patterns in healing history.

    Analyzes ``HealingRecord`` data from the ``MemoryStore``
    to identify structured signals about selector behavior.

    Parameters
    ----------
    memory_store:
        The memory store to query for healing records.
    """

    def __init__(self, memory_store: MemoryStore) -> None:
        self._memory = memory_store

    def detect_all_patterns(
        self,
        selector: str,
    ) -> list[HealingPattern]:
        """Detect all patterns for a given selector.

        Parameters
        ----------
        selector:
            The original selector to analyze.

        Returns
        -------
        list[HealingPattern]
            All detected patterns, may be empty.
        """
        patterns: list[HealingPattern] = []

        chain = self.detect_selector_chain(selector)
        if chain is not None:
            patterns.append(chain)

        reliable = self.detect_reliable_replacements(selector)
        patterns.extend(reliable)

        unreliable = self.detect_unreliable_replacements(selector)
        patterns.extend(unreliable)

        return patterns

    def detect_selector_chain(
        self,
        selector: str,
    ) -> Optional[HealingPattern]:
        """Detect if a selector has been replaced in a chain.

        A chain exists when: A was replaced by B, and B was later
        replaced by C (i.e., B appears as both a new_selector and
        an old_selector in different records).

        Parameters
        ----------
        selector:
            The starting selector to trace.

        Returns
        -------
        Optional[HealingPattern]
            The detected chain pattern, or None if no chain exists.
        """
        chain: list[str] = [selector]
        current = selector
        visited: set[str] = {selector}

        while True:
            # Find successful healings from this selector
            records = self._memory.get_healing_history(current, limit=100)
            successful = [
                r for r in records if r.validation_result is True
            ]

            if not successful:
                break

            # Take the most recent successful replacement
            latest = max(successful, key=lambda r: r.timestamp)
            next_selector = latest.new_selector

            # Prevent cycles
            if next_selector in visited:
                break

            chain.append(next_selector)
            visited.add(next_selector)
            current = next_selector

        if len(chain) < SELECTOR_CHAIN_MIN_LENGTH + 1:
            return None

        # Compute confidence signal based on chain length
        # Longer chains → stronger signal (capped at 1.0)
        signal = min((len(chain) - 1) / 5.0, 1.0)

        return HealingPattern(
            pattern_type=HealingPatternType.SELECTOR_CHAIN,
            selectors=chain,
            occurrences=len(chain) - 1,
            confidence_signal=round(signal, 4),
            description=(
                f"Selector chain detected: "
                f"{' → '.join(chain)} "
                f"({len(chain) - 1} replacements)"
            ),
        )

    def detect_reliable_replacements(
        self,
        selector: str,
    ) -> list[HealingPattern]:
        """Detect replacements that have succeeded multiple times.

        Parameters
        ----------
        selector:
            The original selector.

        Returns
        -------
        list[HealingPattern]
            One pattern per reliable replacement found.
        """
        records = self._memory.get_healing_history(selector, limit=100)
        if not records:
            return []

        # Group by new_selector
        by_replacement: dict[str, list] = {}
        for r in records:
            if r.new_selector not in by_replacement:
                by_replacement[r.new_selector] = []
            by_replacement[r.new_selector].append(r)

        patterns: list[HealingPattern] = []

        for new_sel, recs in by_replacement.items():
            successes = sum(
                1 for r in recs if r.validation_result is True
            )
            if successes >= RELIABLE_REPLACEMENT_MIN_SUCCESSES:
                total = len(recs)
                success_rate = successes / total if total > 0 else 0.0

                patterns.append(HealingPattern(
                    pattern_type=HealingPatternType.RELIABLE_REPLACEMENT,
                    selectors=[selector, new_sel],
                    occurrences=successes,
                    confidence_signal=round(success_rate, 4),
                    description=(
                        f"Reliable replacement: '{selector}' → '{new_sel}' "
                        f"succeeded {successes}/{total} times "
                        f"(rate: {success_rate:.0%})"
                    ),
                ))

        return patterns

    def detect_unreliable_replacements(
        self,
        selector: str,
    ) -> list[HealingPattern]:
        """Detect replacements that have failed repeatedly.

        Parameters
        ----------
        selector:
            The original selector.

        Returns
        -------
        list[HealingPattern]
            One pattern per unreliable replacement found.
        """
        records = self._memory.get_healing_history(selector, limit=100)
        if not records:
            return []

        # Group by new_selector
        by_replacement: dict[str, list] = {}
        for r in records:
            if r.new_selector not in by_replacement:
                by_replacement[r.new_selector] = []
            by_replacement[r.new_selector].append(r)

        patterns: list[HealingPattern] = []

        for new_sel, recs in by_replacement.items():
            failures = sum(
                1 for r in recs if r.validation_result is False
            )
            if failures >= UNRELIABLE_REPLACEMENT_MIN_FAILURES:
                total = len(recs)
                failure_rate = failures / total if total > 0 else 0.0

                patterns.append(HealingPattern(
                    pattern_type=HealingPatternType.UNRELIABLE_REPLACEMENT,
                    selectors=[selector, new_sel],
                    occurrences=failures,
                    confidence_signal=round(1.0 - failure_rate, 4),
                    description=(
                        f"Unreliable replacement: '{selector}' → '{new_sel}' "
                        f"failed {failures}/{total} times "
                        f"(failure rate: {failure_rate:.0%})"
                    ),
                ))

        return patterns
