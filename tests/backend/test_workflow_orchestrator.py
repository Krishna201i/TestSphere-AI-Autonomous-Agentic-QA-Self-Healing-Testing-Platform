"""
TestSphere-AI — Integration Tests for Workflow Orchestration & Converters.

Verifies:
1. Mapping of Member 1 actions & assertions to Member 2 engine steps.
2. TestCase to EngineTestPlan model translation.
3. EngineTestResult to Member 1 ExecutionResult & FailureContext translation.
4. Autonomous workflow orchestrator factory and execution lifecycles.
"""

import unittest
from unittest.mock import AsyncMock, patch
from datetime import datetime, timezone

from agents.planner.schemas import (
    Assertion,
    TestCase as Member1TestCase,
    TestStep as Member1TestStep,
)
from agents.schemas.enums import AssertionType, TestAction
from backend.database.session import get_store
from backend.models.test_execution import TestExecutionStatus
from backend.services.application_service import ApplicationService
from backend.services.project_service import ProjectService
from backend.services.test_case_service import TestCaseService
from backend.services.test_execution_service import TestExecutionService
from backend.orchestration.converters import (
    engine_result_to_execution_result,
    map_action_to_engine,
    map_assertion_to_engine,
    test_case_to_engine_plan as convert_test_case_to_engine_plan,
)
from backend.orchestration.orchestrator import (
    PlatformWorkflowOrchestrator,
    apply_healed_selector,
    create_default_orchestrator,
)
from engine.schemas import HealingReport
from engine.schemas import (
    ActionType,
    Step,
    StepResult,
    StepStatus,
    Target,
    TestPlan as EngineTestPlan,
    TestResult as EngineTestResult,
    TestStatus,
)


class TestWorkflowConverters(unittest.TestCase):
    """Test suite for data conversion between Member 1 and Member 2."""

    def test_map_action_to_engine(self) -> None:
        self.assertEqual(map_action_to_engine(TestAction.CLICK), ActionType.CLICK)
        self.assertEqual(map_action_to_engine(TestAction.FILL), ActionType.FILL)
        self.assertEqual(map_action_to_engine(TestAction.NAVIGATE), ActionType.GOTO)
        self.assertEqual(map_action_to_engine(TestAction.WAIT), ActionType.WAIT_FOR)

    def test_map_assertion_to_engine(self) -> None:
        text_assertion = Assertion(
            type=AssertionType.ELEMENT_CONTAINS_TEXT,
            target="#msg",
            expected="Welcome",
        )
        step = map_assertion_to_engine(text_assertion)
        self.assertEqual(step.action, ActionType.ASSERT_TEXT)
        self.assertIsNotNone(step.target)
        self.assertEqual(step.target.primary_locator, "#msg")
        self.assertEqual(step.expected, "Welcome")

        visible_assertion = Assertion(
            type=AssertionType.ELEMENT_VISIBLE,
            target="#login-btn",
        )
        step_vis = map_assertion_to_engine(visible_assertion)
        self.assertEqual(step_vis.action, ActionType.ASSERT_VISIBLE)
        self.assertIsNotNone(step_vis.target)
        self.assertEqual(step_vis.target.primary_locator, "#login-btn")

    def test_test_case_to_engine_plan(self) -> None:
        m1_case = Member1TestCase(
            test_id="TC-001",
            name="Login Test",
            steps=[
                Member1TestStep(
                    step_number=1,
                    action=TestAction.FILL,
                    target="#username",
                    value="admin",
                ),
                Member1TestStep(
                    step_number=2,
                    action=TestAction.CLICK,
                    target="#submit",
                    assertions=[
                        Assertion(
                            type=AssertionType.ELEMENT_VISIBLE,
                            target="#dashboard",
                        )
                    ],
                ),
            ],
            assertions=[
                Assertion(
                    type=AssertionType.ELEMENT_CONTAINS_TEXT,
                    target="#title",
                    expected="Dashboard",
                )
            ],
        )

        plan = convert_test_case_to_engine_plan(m1_case, base_url="https://app.local")
        self.assertEqual(plan.test_id, "TC-001")
        self.assertEqual(plan.base_url, "https://app.local")
        # 2 action steps + 1 inline assert + 1 case assert = 4 steps
        self.assertEqual(len(plan.steps), 4)
        self.assertEqual(plan.steps[0].action, ActionType.FILL)
        self.assertEqual(plan.steps[1].action, ActionType.CLICK)
        self.assertEqual(plan.steps[2].action, ActionType.ASSERT_VISIBLE)
        self.assertEqual(plan.steps[3].action, ActionType.ASSERT_TEXT)

    def test_engine_result_to_execution_result_success(self) -> None:
        engine_res = EngineTestResult(
            test_id="TC-001",
            status=TestStatus.PASSED,
            started_at=datetime.now(timezone.utc),
            duration_ms=120,
            steps=[
                StepResult(
                    step_id="step-1",
                    status=StepStatus.PASSED,
                    duration_ms=120,
                )
            ],
            artifacts_dir="artifacts",
        )
        m1_res = engine_result_to_execution_result(
            engine_result=engine_res,
            workflow_id="wf-1",
            test_case_id="TC-001",
        )
        self.assertEqual(m1_res.workflow_id, "wf-1")
        self.assertEqual(m1_res.status.value, "SUCCESS")
        self.assertIsNone(m1_res.failure_context)

    def test_engine_result_to_execution_result_failure(self) -> None:
        engine_res = EngineTestResult(
            test_id="TC-001",
            status=TestStatus.FAILED,
            started_at=datetime.now(timezone.utc),
            duration_ms=250,
            steps=[
                StepResult(
                    step_id="step-1",
                    status=StepStatus.FAILED,
                    duration_ms=250,
                    error="Timeout finding #submit",
                )
            ],
            artifacts_dir="artifacts",
        )
        plan = EngineTestPlan(
            test_id="TC-001",
            name="Login Plan",
            base_url="https://app.local",
            steps=[
                Step(
                    step_id="step-1",
                    action=ActionType.CLICK,
                    target=Target(description="Submit", primary_locator="#submit"),
                )
            ],
        )
        m1_res = engine_result_to_execution_result(
            engine_result=engine_res,
            workflow_id="wf-1",
            test_case_id="TC-001",
            engine_plan=plan,
        )
        self.assertEqual(m1_res.status.value, "FAILED")
        self.assertIsNotNone(m1_res.failure_context)
        self.assertEqual(m1_res.failure_context.failed_step, 1)
        self.assertEqual(m1_res.failure_context.action, "click")
        self.assertEqual(m1_res.failure_context.target_selector, "#submit")


class TestPlatformWorkflowOrchestrator(unittest.IsolatedAsyncioTestCase):
    """Test suite for PlatformWorkflowOrchestrator execution workflow."""

    def setUp(self) -> None:
        self.db = get_store()  # fresh in-memory store per test (conftest)
        self.project = ProjectService.create_project(self.db, name="Orchestration Test Project")
        self.app = ApplicationService.create_application(
            self.db, self.project.id, name="Sample App", base_url="https://sample.local",
        )
        self.tc = TestCaseService.create_test_case(
            self.db, self.app.id, external_id="TC-LOGIN-001", name="Verify Login Screen",
        )
        self.execution = TestExecutionService.create_execution(
            self.db, self.tc.id, status=TestExecutionStatus.PENDING,
        )

    def _reload_execution(self):
        return TestExecutionService.get_execution(self.db, self.execution.id)

    def test_create_default_orchestrator(self) -> None:
        orch = create_default_orchestrator()
        self.assertIsNotNone(orch)

    @patch("backend.orchestration.orchestrator.run_test")
    async def test_execute_test_run_success(self, mock_run_test: AsyncMock) -> None:
        mock_run_test.return_value = EngineTestResult(
            test_id="TC-LOGIN-001",
            status=TestStatus.PASSED,
            started_at=datetime.now(timezone.utc),
            duration_ms=150,
            steps=[
                StepResult(
                    step_id="step-1",
                    status=StepStatus.PASSED,
                    duration_ms=150,
                )
            ],
            artifacts_dir="artifacts",
        )

        service = PlatformWorkflowOrchestrator()
        result = await service.execute_test_run(
            db=self.db,
            execution_id=self.execution.id,
        )

        self.assertEqual(result["status"], "PASSED")
        self.execution = self._reload_execution()
        self.assertEqual(self.execution.status, TestExecutionStatus.PASSED.value)
        self.assertEqual(self.execution.duration_ms, 150)
        self.assertIsNotNone(result["dashboard_summary"])

    @patch("backend.orchestration.orchestrator.run_test")
    async def test_engine_heal_is_recorded_as_healed(self, mock_run_test: AsyncMock) -> None:
        mock_run_test.return_value = EngineTestResult(
            test_id="TC-LOGIN-001",
            status=TestStatus.HEALED,
            started_at=datetime.now(timezone.utc),
            duration_ms=200,
            steps=[
                StepResult(
                    step_id="click-login",
                    status=StepStatus.HEALED,
                    duration_ms=200,
                    locator_used="#login-btn",
                    healing=HealingReport(
                        original_locator='[data-testid="login-button"]',
                        selected_locator="#login-btn",
                        confidence=0.87,
                        strategy_used="fallback[0]",
                    ),
                )
            ],
            artifacts_dir="artifacts",
        )

        result = await PlatformWorkflowOrchestrator().execute_test_run(db=self.db, execution_id=self.execution.id)

        self.assertEqual(result["status"], "HEALED")
        self.assertIn('[data-testid="login-button"] -> #login-btn', result["error_message"])
        self.assertIn("confidence 0.87", result["error_message"])
        self.assertEqual(result["engine_steps"][0]["healing"]["selected_locator"], "#login-btn")
        self.execution = self._reload_execution()
        self.assertEqual(self.execution.status, TestExecutionStatus.HEALED.value)

    @patch("backend.orchestration.orchestrator.run_test")
    async def test_browser_failure_is_never_reported_as_passed(self, mock_run_test: AsyncMock) -> None:
        # Even when the stored plain-HTTP page analysis succeeded
        TestCaseService.update_test_case(
            self.db, self.tc.id, description='{"steps": [], "analysis": {"success": true, "latency_ms": 120}}',
        )
        mock_run_test.return_value = EngineTestResult(
            test_id="TC-LOGIN-001",
            status=TestStatus.FAILED,
            started_at=datetime.now(timezone.utc),
            duration_ms=5,
            steps=[
                StepResult(
                    step_id="browser",
                    status=StepStatus.FAILED,
                    duration_ms=5,
                    error="Browser execution error: Executable doesn't exist",
                )
            ],
            artifacts_dir="artifacts",
        )

        result = await PlatformWorkflowOrchestrator().execute_test_run(db=self.db, execution_id=self.execution.id)

        self.assertEqual(result["status"], "FAILED")
        self.assertTrue(result["error_message"].startswith("Not executed: the browser could not start"))
        self.execution = self._reload_execution()
        self.assertEqual(self.execution.status, TestExecutionStatus.FAILED.value)


class TestStoredSteps(unittest.IsolatedAsyncioTestCase):
    """How a test case's stored description turns into steps."""

    def setUp(self) -> None:
        self.db = get_store()
        project = ProjectService.create_project(self.db, name="Steps Project")
        self.app = ApplicationService.create_application(self.db, project.id, name="App", base_url="https://sample.local")

    def _run_for(self, description):
        tc = TestCaseService.create_test_case(self.db, self.app.id, external_id=None, name="T", description=description)
        execution = TestExecutionService.create_execution(self.db, tc.id, status=TestExecutionStatus.PENDING)
        return execution, PlatformWorkflowOrchestrator().execute_test_run(db=self.db, execution_id=execution.id)

    @patch("backend.orchestration.orchestrator.run_test")
    async def test_unreadable_stored_steps_fail_the_run_instead_of_passing_a_page_load(self, mock_run_test) -> None:
        """Regression: a parse error used to be swallowed and a bare 'open the page' run could pass."""
        execution, run = self._run_for('{"steps": [{"action": "fill", "target": "#q", "step_number": "not-a-number"}]}')
        result = await run
        mock_run_test.assert_not_called()  # nothing ran, so nothing can pass
        self.assertEqual(result["status"], TestExecutionStatus.FAILED.value)
        self.assertIn("could not be read", result["error_message"])
        stored = TestExecutionService.get_execution(self.db, execution.id)
        self.assertEqual(stored.status, TestExecutionStatus.FAILED.value)

    @patch("backend.orchestration.orchestrator.run_test")
    async def test_a_plain_text_description_still_runs_the_page_check(self, mock_run_test) -> None:
        mock_run_test.return_value = EngineTestResult(
            test_id="t", status=TestStatus.PASSED, started_at=datetime.now(timezone.utc), duration_ms=1,
            steps=[StepResult(step_id="step-1", status=StepStatus.PASSED, duration_ms=1)], artifacts_dir="artifacts",
        )
        _, run = self._run_for("Checks that the home page opens")
        result = await run
        mock_run_test.assert_called_once()
        self.assertEqual(result["status"], TestExecutionStatus.PASSED.value)


class TestApplyHealedSelector(unittest.TestCase):
    """The healed selector must only replace the broken step's locator."""

    def _plan(self) -> EngineTestPlan:
        return EngineTestPlan(
            test_id="t",
            name="t",
            base_url="https://app.local",
            steps=[
                Step(step_id="goto", action=ActionType.GOTO, value="https://app.local"),
                Step(step_id="user", action=ActionType.FILL, value="a", target=Target(description="u", primary_locator="#username")),
                Step(step_id="pass", action=ActionType.FILL, value="b", target=Target(description="p", primary_locator="#password")),
                Step(step_id="submit", action=ActionType.CLICK, target=Target(description="s", primary_locator="#submit")),
            ],
        )

    def test_replaces_only_steps_using_the_broken_selector(self) -> None:
        healed = apply_healed_selector(self._plan(), "#submit", failed_step=4, healed_selector="#login-btn")
        locators = [s.target.primary_locator if s.target else None for s in healed.steps]
        self.assertEqual(locators, [None, "#username", "#password", "#login-btn"])

    def test_falls_back_to_failed_step_when_selector_unknown(self) -> None:
        healed = apply_healed_selector(self._plan(), "", failed_step=2, healed_selector="#user-field")
        locators = [s.target.primary_locator if s.target else None for s in healed.steps]
        self.assertEqual(locators, [None, "#user-field", "#password", "#submit"])

    def test_original_plan_is_untouched(self) -> None:
        plan = self._plan()
        apply_healed_selector(plan, "#submit", failed_step=4, healed_selector="#x")
        self.assertEqual(plan.steps[3].target.primary_locator, "#submit")


if __name__ == "__main__":
    unittest.main()
