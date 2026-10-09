"""
TestSphere-AI — Test Prioritization Module

Provides test case prioritization based on risk, importance,
and test category. Sorts generated test cases so that the most
critical tests run first.

Prioritization Criteria:
  1. Priority level (CRITICAL > HIGH > MEDIUM > LOW)
  2. Category risk weight (negative/boundary > functional > smoke)
  3. Action complexity (more steps = higher risk)
  4. Page importance (login, checkout > settings, about)

This module also adds structured explanations for why each test
was prioritized at its level.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from agents.planner.schemas import TestCase
from agents.schemas.enums import TestCategory, TestPriority

logger = logging.getLogger(__name__)


# ── Priority Weight Maps ─────────────────────────────────────

_PRIORITY_WEIGHTS: dict[TestPriority, int] = {
    TestPriority.CRITICAL: 1000,
    TestPriority.HIGH: 750,
    TestPriority.MEDIUM: 500,
    TestPriority.LOW: 250,
}

_CATEGORY_WEIGHTS: dict[TestCategory, int] = {
    TestCategory.FUNCTIONAL: 100,
    TestCategory.NEGATIVE: 120,   # Negative tests are high-risk
    TestCategory.BOUNDARY: 110,   # Boundary tests catch edge cases
    TestCategory.SMOKE: 80,       # Quick sanity checks
    TestCategory.REGRESSION: 90,
    TestCategory.EDGE_CASE: 95,
    TestCategory.ACCESSIBILITY: 70,
}

# Page URL patterns that indicate high-importance pages
_HIGH_IMPORTANCE_PATTERNS: list[str] = [
    "login", "signin", "sign-in", "auth",
    "checkout", "payment", "purchase",
    "register", "signup", "sign-up",
    "dashboard", "admin",
]

_MEDIUM_IMPORTANCE_PATTERNS: list[str] = [
    "profile", "account", "settings",
    "search", "cart", "order",
]


# ── Prioritization Result ────────────────────────────────────


@dataclass
class PrioritizationResult:
    """Result of prioritizing a test case.

    Attributes
    ----------
    test_case:
        The original test case.
    score:
        Computed priority score (higher = more important).
    explanation:
        Human-readable explanation of the prioritization.
    """

    test_case: TestCase
    score: int
    explanation: str


# ── Test Prioritizer ─────────────────────────────────────────


class TestPrioritizer:
    """Prioritizes test cases based on risk and importance.

    Sorts test cases by a computed priority score. The score
    combines priority level, test category risk, step complexity,
    and page importance.

    Usage
    -----
    >>> prioritizer = TestPrioritizer()
    >>> sorted_cases = prioritizer.prioritize(test_cases)
    """

    def prioritize(
        self, test_cases: list[TestCase],
    ) -> list[TestCase]:
        """Sort test cases by priority score (highest first).

        Parameters
        ----------
        test_cases:
            The test cases to prioritize.

        Returns
        -------
        list[TestCase]
            Test cases sorted by priority score (highest first).
        """
        if not test_cases:
            return []

        results = [self._score_test_case(tc) for tc in test_cases]
        results.sort(key=lambda r: r.score, reverse=True)

        logger.info(
            "Prioritized %d test cases. Top priority: %s (score=%d)",
            len(results),
            results[0].test_case.test_id if results else "none",
            results[0].score if results else 0,
        )

        return [r.test_case for r in results]

    def prioritize_with_explanations(
        self, test_cases: list[TestCase],
    ) -> list[PrioritizationResult]:
        """Sort test cases and return with explanations.

        Parameters
        ----------
        test_cases:
            The test cases to prioritize.

        Returns
        -------
        list[PrioritizationResult]
            Prioritized results with scores and explanations.
        """
        if not test_cases:
            return []

        results = [self._score_test_case(tc) for tc in test_cases]
        results.sort(key=lambda r: r.score, reverse=True)
        return results

    def _score_test_case(self, tc: TestCase) -> PrioritizationResult:
        """Compute the priority score for a single test case."""
        explanations: list[str] = []

        # 1. Priority level weight
        priority_weight = _PRIORITY_WEIGHTS.get(tc.priority, 500)
        explanations.append(
            f"Priority {tc.priority.value}: +{priority_weight}"
        )

        # 2. Category weight
        category_weight = _CATEGORY_WEIGHTS.get(tc.category, 80)
        explanations.append(
            f"Category {tc.category.value}: +{category_weight}"
        )

        # 3. Step complexity bonus
        step_bonus = min(len(tc.steps) * 10, 100)  # Cap at 100
        if step_bonus > 0:
            explanations.append(
                f"Step complexity ({len(tc.steps)} steps): +{step_bonus}"
            )

        # 4. Page importance
        page_bonus = self._page_importance(tc.page_url)
        if page_bonus > 0:
            explanations.append(
                f"Page importance ({tc.page_url}): +{page_bonus}"
            )

        # 5. Has assertions bonus
        total_assertions = len(tc.assertions) + sum(
            len(s.assertions) for s in tc.steps
        )
        assertion_bonus = min(total_assertions * 5, 50)  # Cap at 50
        if assertion_bonus > 0:
            explanations.append(
                f"Assertions ({total_assertions}): +{assertion_bonus}"
            )

        total_score = (
            priority_weight + category_weight + step_bonus
            + page_bonus + assertion_bonus
        )

        explanation = (
            f"Score: {total_score} = "
            + " + ".join(e.split(": +")[1] for e in explanations if ": +" in e)
            + f". Components: {'; '.join(explanations)}"
        )

        return PrioritizationResult(
            test_case=tc,
            score=total_score,
            explanation=explanation,
        )

    @staticmethod
    def _page_importance(page_url: Optional[str]) -> int:
        """Compute page importance bonus from URL patterns."""
        if not page_url:
            return 0

        url_lower = page_url.lower()

        for pattern in _HIGH_IMPORTANCE_PATTERNS:
            if pattern in url_lower:
                return 80

        for pattern in _MEDIUM_IMPORTANCE_PATTERNS:
            if pattern in url_lower:
                return 40

        return 0


def add_test_reasoning(test_cases: list[TestCase]) -> list[TestCase]:
    """Add structured reasoning to test cases that lack it.

    Generates explanations for why each test was created based on
    its category, priority, steps, and target page.

    Parameters
    ----------
    test_cases:
        The test cases to annotate.

    Returns
    -------
    list[TestCase]
        Test cases with ``generated_reasoning`` populated.
    """
    updated: list[TestCase] = []
    for tc in test_cases:
        if tc.generated_reasoning:
            updated.append(tc)
            continue

        reasoning_parts: list[str] = []

        # Category explanation
        category_reasons = {
            TestCategory.FUNCTIONAL: "Tests normal expected user workflow.",
            TestCategory.NEGATIVE: "Tests invalid or incorrect input handling.",
            TestCategory.BOUNDARY: "Tests edge-case or boundary values.",
            TestCategory.SMOKE: "Quick sanity check that core feature works.",
            TestCategory.REGRESSION: "Verifies previously working functionality.",
            TestCategory.EDGE_CASE: "Tests unusual or extreme conditions.",
            TestCategory.ACCESSIBILITY: "Verifies accessibility compliance.",
        }
        cat_reason = category_reasons.get(tc.category, "Tests application behavior.")
        reasoning_parts.append(cat_reason)

        # Priority explanation
        if tc.priority in (TestPriority.CRITICAL, TestPriority.HIGH):
            reasoning_parts.append(
                f"Prioritized as {tc.priority.value} due to business impact."
            )

        # Page explanation
        if tc.page_url:
            reasoning_parts.append(f"Targets page: {tc.page_url}.")

        # Step summary
        if tc.steps:
            actions = [s.action.value for s in tc.steps[:3]]
            reasoning_parts.append(
                f"Performs {len(tc.steps)} steps: {', '.join(actions)}{'...' if len(tc.steps) > 3 else ''}."
            )

        reasoning = " ".join(reasoning_parts)

        # Use model_copy to create updated test case
        updated_tc = tc.model_copy(
            update={"generated_reasoning": reasoning}
        )
        updated.append(updated_tc)

    return updated
