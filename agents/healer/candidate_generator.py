"""
TestSphere-AI — Candidate Generator

Generates candidate replacement selectors for failed test steps
by comparing current UI elements against historical element records.

The generator produces raw ``ScoredCandidate`` instances with
individual similarity scores filled in.  The ``CandidateScorer``
then computes the final weighted confidence.

Day 10: Foundation implementation.

IMPORTANT: This module does NOT execute browser actions or modify
selectors.  It only produces candidate data structures.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from agents.healer.healing_schemas import HealingContext, ScoredCandidate
from agents.memory.context_comparator import ContextComparator
from agents.memory.memory_interface import MemoryStore
from agents.memory.memory_schemas import ElementRecord
from agents.schemas.enums import CandidateSource

if TYPE_CHECKING:
    from agents.analyzer.schemas import FailureAnalysis

logger = logging.getLogger(__name__)

# Stable attributes that are designed to be resilient across UI changes
_STABLE_ATTRIBUTES: frozenset[str] = frozenset({
    "data-testid", "data-test-id", "data-qa", "data-cy",
    "aria-label", "aria-labelledby", "class",
})


class CandidateGenerator:
    """Generates candidate replacement selectors.

    Uses two sources of candidates:

    1. **Current UI elements** — Elements provided in the healing
       context (from the execution engine or failure context).
    2. **Historical memory** — Previous healing records that
       successfully replaced the same selector.

    Each candidate is annotated with individual similarity scores
    but NOT yet weighted into a final confidence — that is the
    ``CandidateScorer``'s responsibility.

    Parameters
    ----------
    memory_store:
        Memory store for retrieving historical element and healing data.
    comparator:
        Context comparator for element-level comparison.
    """

    def __init__(
        self,
        memory_store: MemoryStore,
        comparator: Optional[ContextComparator] = None,
    ) -> None:
        self._memory = memory_store
        self._comparator = comparator or ContextComparator()

    # ── Public API ────────────────────────────────────────────

    def generate_candidates(
        self, context: HealingContext,
    ) -> list[ScoredCandidate]:
        """Generate candidate replacement selectors.

        Parameters
        ----------
        context:
            The healing context containing the failure analysis
            and current UI elements.

        Returns
        -------
        list[ScoredCandidate]
            Unscored candidates (individual similarity fields set,
            but ``confidence`` is 0.0 — scoring is done separately).
        """
        analysis = context.failure_analysis
        candidates: list[ScoredCandidate] = []

        # Retrieve previous element from memory
        previous_element = self._get_previous_element(analysis)

        # Source 1: Current UI elements
        if context.current_elements and previous_element is not None:
            current_candidates = self._generate_from_current_elements(
                previous_element=previous_element,
                current_elements=context.current_elements,
                page_url=context.page_url,
            )
            candidates.extend(current_candidates)

        # Source 2: Historical healing records
        if analysis.failed_target:
            historical_candidates = self._generate_from_historical_memory(
                original_selector=analysis.failed_target,
                previous_element=previous_element,
            )
            # Avoid duplicates: only add historical candidates whose
            # selectors are not already present from current elements
            existing_selectors = {c.selector for c in candidates}
            for hc in historical_candidates:
                if hc.selector not in existing_selectors:
                    candidates.append(hc)

        logger.info(
            "Generated %d candidate(s) for test_id=%s, selector=%s",
            len(candidates),
            analysis.test_id,
            analysis.failed_target,
        )

        return candidates

    # ── Private: Current Elements ─────────────────────────────

    def _generate_from_current_elements(
        self,
        previous_element: ElementRecord,
        current_elements: list[ElementRecord],
        page_url: Optional[str] = None,
    ) -> list[ScoredCandidate]:
        """Generate candidates by comparing current elements to the previous."""
        candidates: list[ScoredCandidate] = []

        for current in current_elements:
            # Skip the exact same selector — that's the one that failed
            if current.selector == previous_element.selector:
                continue

            similarities = self._compute_similarity(
                previous_element, current, page_url,
            )
            evidence = self._build_evidence(
                previous_element, current, similarities,
            )

            # Determine selector type heuristic
            selector_type = self._infer_selector_type(current.selector)

            candidate = ScoredCandidate(
                selector=current.selector,
                selector_type=selector_type,
                source=CandidateSource.CURRENT_DOM,
                confidence=0.0,  # Scored later by CandidateScorer
                evidence=evidence,
                text_similarity=similarities["text"],
                role_similarity=similarities["role"],
                type_similarity=similarities["type"],
                page_similarity=similarities["page"],
                historical_similarity=0.0,  # Set below if applicable
                name_similarity=similarities["name"],
                stable_attribute_similarity=similarities["stable_attribute"],
            )
            candidates.append(candidate)

        return candidates

    # ── Private: Historical Memory ────────────────────────────

    def _generate_from_historical_memory(
        self,
        original_selector: str,
        previous_element: Optional[ElementRecord],
    ) -> list[ScoredCandidate]:
        """Generate candidates from historical healing records."""
        candidates: list[ScoredCandidate] = []

        healing_history = self._memory.get_healing_history(
            original_selector, limit=10,
        )

        for record in healing_history:
            # Only consider previously successful healings
            if record.validation_result is not True:
                continue

            evidence = [
                f"Previously healed: '{original_selector}' → '{record.new_selector}'",
                f"Previous confidence: {record.confidence:.2f}",
            ]
            if record.healing_reason:
                evidence.append(f"Previous reason: {record.healing_reason}")

            selector_type = self._infer_selector_type(record.new_selector)

            candidate = ScoredCandidate(
                selector=record.new_selector,
                selector_type=selector_type,
                source=CandidateSource.HISTORICAL_MEMORY,
                confidence=0.0,  # Scored later
                evidence=evidence,
                text_similarity=0.0,
                role_similarity=0.0,
                type_similarity=0.0,
                page_similarity=0.0,
                historical_similarity=1.0,  # Strong: validated in the past
                name_similarity=0.0,
            )
            candidates.append(candidate)

        return candidates

    # ── Private: Similarity Computation ───────────────────────

    def _compute_similarity(
        self,
        previous: ElementRecord,
        current: ElementRecord,
        page_url: Optional[str] = None,
    ) -> dict[str, float]:
        """Compute individual similarity scores between two elements.

        Returns a dict with keys: text, role, type, page, name, stable_attribute.
        Each value is 0.0 (no match) or 1.0 (match), except stable_attribute
        which is the fraction of matching stable attributes.
        """
        scores: dict[str, float] = {}

        # Text similarity
        scores["text"] = self._text_match(previous.text, current.text)

        # Role similarity
        scores["role"] = self._exact_match(previous.role, current.role)

        # Element type — inferred from attributes if available
        prev_type = previous.attributes.get("type", "")
        curr_type = current.attributes.get("type", "")
        scores["type"] = self._exact_match(prev_type, curr_type)

        # Page similarity
        prev_page = previous.page_url or ""
        curr_page = current.page_url or page_url or ""
        scores["page"] = self._page_match(prev_page, curr_page)

        # Name similarity
        prev_name = previous.attributes.get("name", "")
        curr_name = current.attributes.get("name", "")
        scores["name"] = self._exact_match(prev_name, curr_name)

        # Stable attribute similarity
        scores["stable_attribute"] = self._stable_attribute_match(
            previous.attributes, current.attributes,
        )

        return scores

    def _build_evidence(
        self,
        previous: ElementRecord,
        current: ElementRecord,
        similarities: dict[str, float],
    ) -> list[str]:
        """Build concise evidence strings from similarity scores."""
        evidence: list[str] = []

        if similarities["text"] > 0.0 and previous.text:
            evidence.append(f"Same visible text: {previous.text}")

        if similarities["role"] > 0.0 and previous.role:
            evidence.append(f"Same role: {previous.role}")

        if similarities["type"] > 0.0:
            type_val = previous.attributes.get("type", "")
            if type_val:
                evidence.append(f"Same element type: {type_val}")

        if similarities["page"] > 0.0:
            evidence.append("Same page context")

        if similarities["name"] > 0.0:
            name_val = previous.attributes.get("name", "")
            if name_val:
                evidence.append(f"Same name attribute: {name_val}")

        if similarities.get("stable_attribute", 0.0) > 0.0:
            matching_attrs = self._get_matching_stable_attributes(
                previous.attributes, current.attributes,
            )
            if matching_attrs:
                evidence.append(
                    f"Matching stable attributes: {', '.join(matching_attrs)}"
                )

        # Note selector difference
        if previous.selector != current.selector:
            evidence.append(
                f"Selector changed: '{previous.selector}' → '{current.selector}'"
            )

        return evidence

    # ── Private: Helpers ──────────────────────────────────────

    def _get_previous_element(
        self, analysis: FailureAnalysis,
    ) -> Optional[ElementRecord]:
        """Retrieve the previous element from memory or analysis context."""
        # First try from the analysis's historical context
        if (
            analysis.historical_context is not None
            and analysis.historical_context.previous_element is not None
        ):
            return analysis.historical_context.previous_element

        # Fall back to memory store lookup by selector
        if analysis.failed_target:
            return self._memory.get_element_by_selector(
                analysis.failed_target,
            )

        return None

    @staticmethod
    def _text_match(
        text_a: Optional[str], text_b: Optional[str],
    ) -> float:
        """Compare two text values, case-insensitive."""
        if text_a is None or text_b is None:
            return 0.0
        if not text_a.strip() or not text_b.strip():
            return 0.0
        return 1.0 if text_a.strip().lower() == text_b.strip().lower() else 0.0

    @staticmethod
    def _exact_match(
        val_a: Optional[str], val_b: Optional[str],
    ) -> float:
        """Compare two string values for exact equality."""
        if val_a is None or val_b is None:
            return 0.0
        if not val_a.strip() or not val_b.strip():
            return 0.0
        return 1.0 if val_a.strip().lower() == val_b.strip().lower() else 0.0

    @staticmethod
    def _page_match(url_a: str, url_b: str) -> float:
        """Compare two page URLs."""
        if not url_a or not url_b:
            return 0.0
        return 1.0 if url_a.strip().rstrip("/") == url_b.strip().rstrip("/") else 0.0

    @staticmethod
    def _infer_selector_type(selector: str) -> str:
        """Infer the selector type from the selector string."""
        s = selector.strip()
        if s.startswith("#"):
            return "id"
        if s.startswith("//") or s.startswith("(//"):
            return "xpath"
        if s.startswith("[name=") or s.startswith("[name=\""):
            return "name"
        if s.startswith("."):
            return "class"
        return "css"

    @staticmethod
    def _stable_attribute_match(
        attrs_a: dict[str, str],
        attrs_b: dict[str, str],
    ) -> float:
        """Compute similarity based on matching stable attributes.

        Compares stable HTML attributes (data-testid, aria-label, etc.)
        between two elements.  Returns the fraction of overlapping
        stable attributes that have matching values.

        Returns 0.0 if no stable attributes exist in either element.
        """
        # Collect stable attributes present in either element
        relevant_keys = set()
        for key in _STABLE_ATTRIBUTES:
            if key in attrs_a or key in attrs_b:
                relevant_keys.add(key)

        if not relevant_keys:
            return 0.0

        matches = 0
        for key in relevant_keys:
            val_a = attrs_a.get(key, "").strip().lower()
            val_b = attrs_b.get(key, "").strip().lower()
            if val_a and val_b and val_a == val_b:
                matches += 1

        return matches / len(relevant_keys)

    @staticmethod
    def _get_matching_stable_attributes(
        attrs_a: dict[str, str],
        attrs_b: dict[str, str],
    ) -> list[str]:
        """Return list of stable attribute names that match between elements."""
        matching: list[str] = []
        for key in _STABLE_ATTRIBUTES:
            val_a = attrs_a.get(key, "").strip().lower()
            val_b = attrs_b.get(key, "").strip().lower()
            if val_a and val_b and val_a == val_b:
                matching.append(key)
        return sorted(matching)
