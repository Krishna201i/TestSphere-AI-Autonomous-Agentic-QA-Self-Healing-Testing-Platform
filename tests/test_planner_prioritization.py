"""
TestSphere-AI — Unit Tests for Test Prioritization Module

Tests:
  - Priority level sorting (CRITICAL > HIGH > MEDIUM > LOW)
  - Category risk weighting (NEGATIVE, BOUNDARY, FUNCTIONAL, SMOKE)
  - Step complexity, page importance, and assertion bonuses
  - Prioritization with structured explanations
  - add_test_reasoning function
  - Empty list edge cases
  - Integration with TestPlanner prioritizing test plans
"""

from __future__ import annotations

from agents.planner.prioritization import (
    PrioritizationResult,
    RiskPrioritizationConfig,
    RiskPrioritizationContext,
    RiskPrioritizationResult,
    TestPrioritizer,
    add_test_reasoning,
)
from agents.planner.schemas import (
    Assertion,
    TestCase,
    TestStep,
)
from agents.schemas.enums import (
    AssertionType,
    TestAction,
    TestCategory,
    TestPriority,
)


def _make_case(
    test_id: str,
    priority: TestPriority = TestPriority.MEDIUM,
    category: TestCategory = TestCategory.FUNCTIONAL,
    page_url: str = "/dashboard",
    num_steps: int = 2,
    num_assertions: int = 1,
) -> TestCase:
    steps = [
        TestStep(
            step_number=i + 1,
            action=TestAction.CLICK,
            target="#btn",
        )
        for i in range(num_steps)
    ]
    assertions = [
        Assertion(
            type=AssertionType.ELEMENT_VISIBLE,
            target="#result",
        )
        for _ in range(num_assertions)
    ]
    return TestCase(
        test_id=test_id,
        name=f"Test {test_id}",
        description="A test case",
        priority=priority,
        category=category,
        page_url=page_url,
        steps=steps,
        assertions=assertions,
    )


class TestTestPrioritizer:
    """Tests for TestPrioritizer logic and scoring."""

    def test_priority_level_ordering(self):
        prioritizer = TestPrioritizer()
        cases = [
            _make_case("LOW", priority=TestPriority.LOW),
            _make_case("CRITICAL", priority=TestPriority.CRITICAL),
            _make_case("MEDIUM", priority=TestPriority.MEDIUM),
            _make_case("HIGH", priority=TestPriority.HIGH),
        ]
        sorted_cases = prioritizer.prioritize(cases)
        ordered_ids = [tc.test_id for tc in sorted_cases]
        assert ordered_ids == ["CRITICAL", "HIGH", "MEDIUM", "LOW"]

    def test_category_risk_weighting(self):
        prioritizer = TestPrioritizer()
        # Same priority, different categories
        cases = [
            _make_case("SMOKE", category=TestCategory.SMOKE),
            _make_case("NEGATIVE", category=TestCategory.NEGATIVE),
            _make_case("FUNCTIONAL", category=TestCategory.FUNCTIONAL),
            _make_case("BOUNDARY", category=TestCategory.BOUNDARY),
        ]
        sorted_cases = prioritizer.prioritize(cases)
        ordered_ids = [tc.test_id for tc in sorted_cases]
        # NEGATIVE (120) > BOUNDARY (110) > FUNCTIONAL (100) > SMOKE (80)
        assert ordered_ids == ["NEGATIVE", "BOUNDARY", "FUNCTIONAL", "SMOKE"]

    def test_page_importance_bonus(self):
        prioritizer = TestPrioritizer()
        cases = [
            _make_case("ABOUT", page_url="/about"),
            _make_case("LOGIN", page_url="https://app.com/login"),
            _make_case("CHECKOUT", page_url="/checkout"),
        ]
        results = prioritizer.prioritize_with_explanations(cases)
        # Login and checkout get high importance bonus (+80)
        login_res = next(r for r in results if r.test_case.test_id == "LOGIN")
        about_res = next(r for r in results if r.test_case.test_id == "ABOUT")
        assert login_res.score > about_res.score
        assert "Page importance" in login_res.explanation

    def test_step_and_assertion_complexity_bonus(self):
        prioritizer = TestPrioritizer()
        simple_case = _make_case("SIMPLE", num_steps=1, num_assertions=0)
        complex_case = _make_case("COMPLEX", num_steps=5, num_assertions=3)
        results = prioritizer.prioritize_with_explanations([simple_case, complex_case])
        comp_res = next(r for r in results if r.test_case.test_id == "COMPLEX")
        simp_res = next(r for r in results if r.test_case.test_id == "SIMPLE")
        assert comp_res.score > simp_res.score

    def test_empty_list_prioritization(self):
        prioritizer = TestPrioritizer()
        assert prioritizer.prioritize([]) == []
        assert prioritizer.prioritize_with_explanations([]) == []

    def test_structured_explanations(self):
        prioritizer = TestPrioritizer()
        case = _make_case("TC-1", priority=TestPriority.CRITICAL, category=TestCategory.NEGATIVE)
        results = prioritizer.prioritize_with_explanations([case])
        assert len(results) == 1
        res = results[0]
        assert isinstance(res, PrioritizationResult)
        assert res.score > 1000
        assert "Priority CRITICAL" in res.explanation
        assert "Category negative" in res.explanation


class TestAddTestReasoning:
    """Tests for add_test_reasoning utility."""

    def test_add_test_reasoning_populates_missing_reasoning(self):
        cases = [
            _make_case("TC-1", category=TestCategory.NEGATIVE, priority=TestPriority.CRITICAL),
            _make_case("TC-2", category=TestCategory.FUNCTIONAL, priority=TestPriority.LOW),
        ]
        annotated = add_test_reasoning(cases)
        assert annotated[0].generated_reasoning is not None
        assert "invalid or incorrect input" in annotated[0].generated_reasoning
        assert "CRITICAL" in annotated[0].generated_reasoning
        assert annotated[1].generated_reasoning is not None
        assert "normal expected user workflow" in annotated[1].generated_reasoning

    def test_add_test_reasoning_preserves_existing_reasoning(self):
        case = _make_case("TC-1").model_copy(
            update={"generated_reasoning": "Custom pre-existing reasoning."}
        )
        annotated = add_test_reasoning([case])
        assert annotated[0].generated_reasoning == "Custom pre-existing reasoning."


class TestRiskBasedPrioritization:
    """Tests for opt-in risk-based test scheduling."""

    def test_disabled_by_default_preserves_original_order(self):
        prioritizer = TestPrioritizer()
        cases = [
            _make_case("TC-1", priority=TestPriority.LOW),
            _make_case("TC-2", priority=TestPriority.CRITICAL),
            _make_case("TC-3", priority=TestPriority.MEDIUM),
        ]
        # When config is None or disabled, return original order without reordering or exclusion
        res_default = prioritizer.prioritize_by_risk(cases)
        assert [c.test_id for c in res_default] == ["TC-1", "TC-2", "TC-3"]

        cfg_disabled = RiskPrioritizationConfig(enabled=False)
        res_disabled = prioritizer.prioritize_by_risk(cases, config=cfg_disabled)
        assert [c.test_id for c in res_disabled] == ["TC-1", "TC-2", "TC-3"]

    def test_risk_prioritization_orders_by_combined_risk(self):
        prioritizer = TestPrioritizer()
        # TC-LOGIN: high change relevance and high failure history
        tc_login = _make_case("TC-LOGIN", priority=TestPriority.HIGH, page_url="/login")
        # TC-CHECKOUT: critical, but no change and low failure
        tc_checkout = _make_case("TC-CHECKOUT", priority=TestPriority.CRITICAL, page_url="/checkout")
        # TC-ABOUT: low priority, low failure, no change
        tc_about = _make_case("TC-ABOUT", priority=TestPriority.LOW, page_url="/about")

        context = RiskPrioritizationContext(
            changed_files=["src/auth/login_service.py"],
            failure_history={"TC-LOGIN": 0.80, "TC-CHECKOUT": 0.10, "TC-ABOUT": 0.0},
            flaky_risk_scores={"TC-LOGIN": 0.20, "TC-CHECKOUT": 0.05, "TC-ABOUT": 0.0},
            test_file_mappings={"TC-LOGIN": ["src/auth/login_service.py"]},
        )
        cfg = RiskPrioritizationConfig(enabled=True)

        results = prioritizer.prioritize_by_risk_with_explanations(
            [tc_about, tc_checkout, tc_login], context=context, config=cfg
        )

        assert len(results) == 3
        # TC-LOGIN should be first because of change relevance (1.0) and failure history (0.8)
        assert results[0].test_case.test_id == "TC-LOGIN"
        assert results[0].change_relevance == 1.0
        assert results[0].failure_history == 0.8
        assert results[0].risk_score > results[1].risk_score
        assert results[2].test_case.test_id == "TC-ABOUT"

        # Verify all tests preserved
        sorted_cases = prioritizer.prioritize_by_risk(
            [tc_about, tc_checkout, tc_login], context=context, config=cfg
        )
        assert [c.test_id for c in sorted_cases] == ["TC-LOGIN", "TC-CHECKOUT", "TC-ABOUT"]

    def test_graceful_handling_without_git_history(self):
        prioritizer = TestPrioritizer()
        cases = [
            _make_case("TC-A", priority=TestPriority.CRITICAL),
            _make_case("TC-B", priority=TestPriority.LOW),
        ]
        # Empty context simulates repository without git history
        context = RiskPrioritizationContext(changed_files=[])
        cfg = RiskPrioritizationConfig(enabled=True)

        results = prioritizer.prioritize_by_risk_with_explanations(cases, context=context, config=cfg)
        assert len(results) == 2
        assert results[0].change_relevance == 0.0
        assert results[1].change_relevance == 0.0
        # Criticality still distinguishes them
        assert results[0].test_case.test_id == "TC-A"
        assert results[0].risk_score > results[1].risk_score

    def test_risk_explanation_contains_breakdown(self):
        prioritizer = TestPrioritizer()
        tc = _make_case("TC-1", priority=TestPriority.CRITICAL, page_url="/auth/login")
        context = RiskPrioritizationContext(
            changed_files=["src/auth/login.py"],
            failure_history={"TC-1": 0.50},
            flaky_risk_scores={"TC-1": 0.25},
        )
        cfg = RiskPrioritizationConfig(enabled=True)
        results = prioritizer.prioritize_by_risk_with_explanations([tc], context=context, config=cfg)
        exp = results[0].explanation
        assert "Risk:" in exp
        assert "ChangeRelevance" in exp
        assert "FailureHistory" in exp
        assert "Criticality" in exp
        assert "FlakyRisk" in exp

    def test_invalid_weights_raise_value_error(self):
        import pytest
        with pytest.raises(ValueError, match="Total risk factor weight"):
            RiskPrioritizationConfig(
                enabled=True,
                weight_change_relevance=0.0,
                weight_failure_history=0.0,
                weight_criticality=0.0,
                weight_flaky_risk=0.0,
            )
