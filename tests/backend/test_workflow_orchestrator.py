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
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from agents.planner.schemas import (
    Assertion,
    TestCase as Member1TestCase,
    TestStep as Member1TestStep,
)
from agents.schemas.enums import AssertionType, TestAction
from backend.database.session import Base
from backend.models.application import Application
from backend.models.project import Project
from backend.models.test_case import TestCase
from backend.models.test_execution import TestExecution, TestExecutionStatus
from backend.orchestration.converters import (
    engine_result_to_execution_result,
    map_action_to_engine,
    map_assertion_to_engine,
    test_case_to_engine_plan as convert_test_case_to_engine_plan,
)
from backend.orchestration.orchestrator import (
    PlatformWorkflowOrchestrator,
    create_default_orchestrator,
)
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
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

        # Seed test data
        self.project = Project(name="Orchestration Test Project")
        self.db.add(self.project)
        self.db.commit()

        self.app = Application(
            project_id=self.project.id,
            name="Sample App",
            base_url="https://sample.local",
        )
        self.db.add(self.app)
        self.db.commit()

        self.tc = TestCase(
            application_id=self.app.id,
            external_id="TC-LOGIN-001",
            name="Verify Login Screen",
        )
        self.db.add(self.tc)
        self.db.commit()

        self.execution = TestExecution(
            test_case_id=self.tc.id,
            status=TestExecutionStatus.PENDING.value,
        )
        self.db.add(self.execution)
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)

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
        self.db.refresh(self.execution)
        self.assertEqual(self.execution.status, TestExecutionStatus.PASSED.value)
        self.assertEqual(self.execution.duration_ms, 150)
        self.assertIsNotNone(result["dashboard_summary"])


if __name__ == "__main__":
    unittest.main()
