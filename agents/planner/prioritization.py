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
import re
from dataclasses import dataclass, field

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


@dataclass(frozen=True)
class RiskPrioritizationConfig:
    """Configuration for opt-in risk-based test scheduling.

    Weights are explainable configuration values normalized between 0.0 and 1.0.
    """

    enabled: bool = False
    weight_change_relevance: float = 0.35
    weight_failure_history: float = 0.30
    weight_criticality: float = 0.20
    weight_flaky_risk: float = 0.15

    def __post_init__(self) -> None:
        total = (
            self.weight_change_relevance
            + self.weight_failure_history
            + self.weight_criticality
            + self.weight_flaky_risk
        )
        if total <= 0:
            raise ValueError("Total risk factor weight must be greater than zero")


@dataclass
class RiskPrioritizationContext:
    """Runtime context providing risk signals for test scheduling."""

    changed_files: list[str] = field(default_factory=list)
    failure_history: dict[str, float] = field(default_factory=dict)
    criticality_scores: dict[str, float] = field(default_factory=dict)
    flaky_risk_scores: dict[str, float] = field(default_factory=dict)
    test_file_mappings: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class RiskPrioritizationResult:
    """Result of risk-based prioritization for a single test case."""

    test_case: TestCase
    risk_score: float
    change_relevance: float
    failure_history: float
    criticality: float
    flaky_risk: float
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
    def _page_importance(page_url: str | None) -> int:
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

    def prioritize_by_risk(
        self,
        test_cases: list[TestCase],
        context: RiskPrioritizationContext | None = None,
        config: RiskPrioritizationConfig | None = None,
    ) -> list[TestCase]:
        """Prioritize test cases using risk-based scheduling when enabled.

        Falls back to existing order when disabled or when no context is provided.
        Never excludes any test cases.
        """
        if not test_cases:
            return []
        if config is None or not config.enabled:
            return list(test_cases)
        results = self.prioritize_by_risk_with_explanations(test_cases, context, config)
        return [r.test_case for r in results]

    def prioritize_by_risk_with_explanations(
        self,
        test_cases: list[TestCase],
        context: RiskPrioritizationContext | None = None,
        config: RiskPrioritizationConfig | None = None,
    ) -> list[RiskPrioritizationResult]:
        """Compute risk scores and return test cases with factor explanations.

        Risk = 0.35 * ChangeRelevance + 0.30 * FailureHistory + 0.20 * Criticality + 0.15 * FlakyRisk
        All factors and weights are normalized between 0.0 and 1.0.
        """
        if not test_cases:
            return []
        cfg = config or RiskPrioritizationConfig(enabled=True)
        ctx = context or RiskPrioritizationContext()

        results = [self._score_risk_case(tc, ctx, cfg) for tc in test_cases]
        # Sort stably by risk_score descending
        results.sort(key=lambda r: r.risk_score, reverse=True)
        return results

    def _score_risk_case(
        self,
        tc: TestCase,
        context: RiskPrioritizationContext,
        config: RiskPrioritizationConfig,
    ) -> RiskPrioritizationResult:
        """Compute normalized risk score and explanation for a test case."""
        # 1. Change relevance (0.0 - 1.0)
        change_rel, matched_files = self._compute_change_relevance(tc, context)

        # 2. Failure history (0.0 - 1.0)
        raw_fail = context.failure_history.get(tc.test_id, 0.0)
        fail_hist = min(max(float(raw_fail), 0.0), 1.0)

        # 3. Criticality (0.0 - 1.0)
        if tc.test_id in context.criticality_scores:
            crit = min(max(float(context.criticality_scores[tc.test_id]), 0.0), 1.0)
        else:
            _crit_map = {
                TestPriority.CRITICAL: 1.0,
                TestPriority.HIGH: 0.75,
                TestPriority.MEDIUM: 0.50,
                TestPriority.LOW: 0.25,
            }
            crit = _crit_map.get(tc.priority, 0.50)

        # 4. Flaky risk (0.0 - 1.0)
        raw_flaky = context.flaky_risk_scores.get(tc.test_id, 0.0)
        flaky_risk = min(max(float(raw_flaky), 0.0), 1.0)

        # Normalized weights
        total_weight = (
            config.weight_change_relevance
            + config.weight_failure_history
            + config.weight_criticality
            + config.weight_flaky_risk
        )
        w_change = config.weight_change_relevance / total_weight
        w_fail = config.weight_failure_history / total_weight
        w_crit = config.weight_criticality / total_weight
        w_flaky = config.weight_flaky_risk / total_weight

        risk_score = (
            w_change * change_rel
            + w_fail * fail_hist
            + w_crit * crit
            + w_flaky * flaky_risk
        )
        risk_score = round(min(max(risk_score, 0.0), 1.0), 4)

        match_desc = (
            f"matched {len(matched_files)} changed file(s)"
            if matched_files
            else "no changed file match"
        )
        explanation = (
            f"Risk: {risk_score:.4f} = {w_change:.2f}*ChangeRelevance({change_rel:.2f}) + "
            f"{w_fail:.2f}*FailureHistory({fail_hist:.2f}) + "
            f"{w_crit:.2f}*Criticality({crit:.2f}) + "
            f"{w_flaky:.2f}*FlakyRisk({flaky_risk:.2f}). "
            f"Signals: [Change: {match_desc}, FailHistory: {fail_hist:.2%}, "
            f"Priority: {tc.priority.value}, FlakyRisk: {flaky_risk:.2%}]"
        )

        return RiskPrioritizationResult(
            test_case=tc,
            risk_score=risk_score,
            change_relevance=change_rel,
            failure_history=fail_hist,
            criticality=crit,
            flaky_risk=flaky_risk,
            explanation=explanation,
        )

    def _compute_change_relevance(
        self,
        tc: TestCase,
        context: RiskPrioritizationContext,
    ) -> tuple[float, list[str]]:
        """Determine whether the test case is relevant to recently changed files."""
        if not context.changed_files:
            return 0.0, []

        changed_set = {f.lower() for f in context.changed_files}
        matched: list[str] = []

        # Check explicit test-file mappings
        if tc.test_id in context.test_file_mappings:
            for mapped in context.test_file_mappings[tc.test_id]:
                mapped_lower = mapped.lower()
                for ch in changed_set:
                    if mapped_lower in ch or ch in mapped_lower:
                        matched.append(ch)
            if matched:
                return 1.0, sorted(set(matched))

        # Check keyword matches from page_url and name
        tokens: set[str] = set()
        if tc.page_url:
            clean_url = re.sub(r"[^a-zA-Z0-9]", " ", tc.page_url.lower())
            tokens.update(
                t for t in clean_url.split() if len(t) >= 4 and t not in ("http", "https")
            )
        for word in tc.name.lower().split():
            clean = re.sub(r"[^a-zA-Z0-9]", "", word)
            if len(clean) >= 4:
                tokens.add(clean)

        for token in tokens:
            for ch in changed_set:
                if token in ch:
                    matched.append(ch)

        if matched:
            return 0.8, sorted(set(matched))

        return 0.0, []


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
