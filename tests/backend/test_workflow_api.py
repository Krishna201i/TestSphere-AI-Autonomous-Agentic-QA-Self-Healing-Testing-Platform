"""
TestSphere-AI — Integration Tests for Workflow API Endpoints.

Tests:
1. POST /workflow/execute/{execution_id}
2. GET /workflow/stream/{workflow_id}
"""

import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient

from backend.database.session import get_store
from backend.main import app
from backend.models.test_execution import TestExecutionStatus
from backend.services.application_service import ApplicationService
from backend.services.project_service import ProjectService
from backend.services.test_case_service import TestCaseService
from backend.services.test_execution_service import TestExecutionService
from engine.schemas import (
    ActionType,
    StepResult,
    StepStatus,
    TestResult as EngineTestResult,
    TestStatus,
)


class TestWorkflowAPI(unittest.TestCase):
    """Test suite for /workflow API endpoints."""

    def setUp(self) -> None:
        self.client = TestClient(app)
        db = get_store()  # fresh in-memory store per test (conftest)
        self.project = ProjectService.create_project(db, name="API Workflow Project")
        self.application = ApplicationService.create_application(
            db, self.project.id, name="Workflow App", base_url="https://workflow.local",
        )
        self.test_case = TestCaseService.create_test_case(
            db, self.application.id, external_id="TC-FLOW-1", name="Flow Test",
        )
        self.execution = TestExecutionService.create_execution(
            db, self.test_case.id, status=TestExecutionStatus.PENDING,
        )
        self.execution_id = self.execution.id

    @patch("backend.orchestration.orchestrator.run_test")
    def test_execute_workflow_endpoint_success(self, mock_run_test: AsyncMock) -> None:
        mock_run_test.return_value = EngineTestResult(
            test_id="TC-FLOW-1",
            status=TestStatus.PASSED,
            started_at=datetime.now(timezone.utc),
            duration_ms=100,
            steps=[
                StepResult(
                    step_id="step-1",
                    status=StepStatus.PASSED,
                    duration_ms=100,
                )
            ],
            artifacts_dir="artifacts",
        )

        response = self.client.post(f"/workflow/execute/{self.execution_id}")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "PASSED")
        self.assertIn("dashboard_summary", data)

    def test_execute_workflow_not_found(self) -> None:
        response = self.client.post("/workflow/execute/999999")
        self.assertEqual(response.status_code, 404)

    @patch("backend.orchestration.orchestrator.run_test")
    def test_plan_and_execute_endpoint(self, mock_run_test: AsyncMock) -> None:
        mock_run_test.return_value = EngineTestResult(
            test_id="TC-AUTO-1",
            status=TestStatus.PASSED,
            started_at=datetime.now(timezone.utc),
            duration_ms=80,
            steps=[
                StepResult(step_id="step-1", status=StepStatus.PASSED, duration_ms=80)
            ],
            artifacts_dir="artifacts",
        )

        # Test both /api/workflow/plan-and-execute and /workflow/plan-and-execute
        payload = {
            "app_name": "API Plan App",
            "app_url": "https://example.com",
            "test_case_name": "Dynamic Case",
            "steps": [{"step_number": 1, "action": "NAVIGATE", "value": "https://example.com"}],
        }
        res_api = self.client.post("/api/workflow/plan-and-execute", json=payload)
        self.assertEqual(res_api.status_code, 200)
        data_api = res_api.json()
        self.assertEqual(data_api["status"], "PASSED")
        self.assertIn("execution_id", data_api)
        self.assertGreaterEqual(len(data_api.get("events", [])), 1)

        res_root = self.client.post("/workflow/plan-and-execute", json=payload)
        self.assertEqual(res_root.status_code, 200)

    @patch("backend.orchestration.orchestrator.run_test")
    def test_stream_workflow_events(self, mock_run_test: AsyncMock) -> None:
        mock_run_test.return_value = EngineTestResult(
            test_id="TC-FLOW-1",
            status=TestStatus.PASSED,
            started_at=datetime.now(timezone.utc),
            duration_ms=100,
            steps=[
                StepResult(step_id="step-1", status=StepStatus.PASSED, duration_ms=100)
            ],
            artifacts_dir="artifacts",
        )
        self.client.post(f"/api/workflow/execute/{self.execution_id}")

        # Stream via /api and direct endpoint, and via numeric id
        stream_resp = self.client.get(f"/api/workflow/stream/wf-exec-{self.execution_id}")
        self.assertEqual(stream_resp.status_code, 200)
        self.assertIn("text/event-stream", stream_resp.headers.get("content-type", ""))
        self.assertIn("event: ", stream_resp.text)

        num_stream = self.client.get(f"/api/workflow/stream/{self.execution_id}")
        self.assertEqual(num_stream.status_code, 200)
        self.assertIn("event: ", num_stream.text)


if __name__ == "__main__":
    unittest.main()



class TestPlanFromErrorPage(unittest.TestCase):
    """A target that fails to load must not produce a synthesized (passing) test."""

    def setUp(self) -> None:
        self.client = TestClient(app)

    @patch("backend.api.workflow.URLAnalyzerService.analyze_live_website", new_callable=AsyncMock)
    def test_404_target_is_refused(self, mock_analyze: AsyncMock) -> None:
        mock_analyze.return_value = {"success": False, "status_code": 404, "page_title": "Error response"}
        res = self.client.post("/api/workflow/plan-and-execute", json={"app_url": "http://127.0.0.1:1/missing"})
        self.assertEqual(res.status_code, 422)
        self.assertIn("HTTP 404", res.json()["detail"])
        self.assertEqual(self.client.get("/api/test-cases").json(), [])

    @patch("backend.api.workflow.URLAnalyzerService.analyze_live_website", new_callable=AsyncMock)
    def test_unreachable_target_is_refused(self, mock_analyze: AsyncMock) -> None:
        mock_analyze.side_effect = RuntimeError("connection refused")
        res = self.client.post("/api/workflow/plan-and-execute", json={"app_url": "http://127.0.0.1:1/"})
        self.assertEqual(res.status_code, 422)
        self.assertIn("unreachable", res.json()["detail"])
