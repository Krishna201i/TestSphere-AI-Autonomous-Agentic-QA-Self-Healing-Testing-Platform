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
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database.session import Base, get_db
from backend.main import app
from backend.models.application import Application
from backend.models.project import Project
from backend.models.test_case import TestCase
from backend.models.test_execution import TestExecution, TestExecutionStatus
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
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.TestingSessionLocal = sessionmaker(
            autocommit=False, autoflush=False, bind=self.engine
        )

        def override_get_db():
            db = self.TestingSessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

        # Seed data
        db = self.TestingSessionLocal()
        self.project = Project(name="API Workflow Project")
        db.add(self.project)
        db.commit()

        self.application = Application(
            project_id=self.project.id,
            name="Workflow App",
            base_url="https://workflow.local",
        )
        db.add(self.application)
        db.commit()

        self.test_case = TestCase(
            application_id=self.application.id,
            external_id="TC-FLOW-1",
            name="Flow Test",
        )
        db.add(self.test_case)
        db.commit()

        self.execution = TestExecution(
            test_case_id=self.test_case.id,
            status=TestExecutionStatus.PENDING.value,
        )
        db.add(self.execution)
        db.commit()
        self.execution_id = self.execution.id
        db.close()

    def tearDown(self) -> None:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=self.engine)

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

