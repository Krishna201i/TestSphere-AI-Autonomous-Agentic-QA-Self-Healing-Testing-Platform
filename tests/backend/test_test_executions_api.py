"""
TestSphere-AI — Test Executions API Tests.

Validates:
- create execution
- default status is PENDING
- update execution status
- retrieve execution
- list executions
- filter by test_case_id
- invalid status is rejected
- nonexistent test_case_id is rejected
- nonexistent execution returns 404
"""

import unittest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database.session import Base, get_db
from backend.main import app


class TestTestExecutionsAPI(unittest.TestCase):
    """Test suite for /test-executions CRUD API."""

    def setUp(self) -> None:
        """Set up an isolated in-memory test database and client."""
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

        # Set up parent hierarchy: Project -> Application -> TestCase
        proj_res = self.client.post("/projects", json={"name": "Exec Project"})
        self.project_id = proj_res.json()["id"]

        app_res = self.client.post(
            "/applications",
            json={"project_id": self.project_id, "name": "Target App", "base_url": "https://target.test"},
        )
        self.application_id = app_res.json()["id"]

        tc_res = self.client.post(
            "/test-cases",
            json={
                "application_id": self.application_id,
                "external_id": "tc-exec-01",
                "name": "Checkout Flow Test",
            },
        )
        self.test_case_id = tc_res.json()["id"]

    def tearDown(self) -> None:
        """Clean up database tables and reset dependency overrides."""
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_create_execution_default_status_is_pending(self) -> None:
        """Verify creating execution without explicit status defaults to PENDING."""
        response = self.client.post(
            "/test-executions",
            json={"test_case_id": self.test_case_id},
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertIsNotNone(data.get("id"))
        self.assertEqual(data.get("test_case_id"), self.test_case_id)
        self.assertEqual(data.get("status"), "PENDING")

    def test_create_execution_nonexistent_test_case_rejected(self) -> None:
        """Verify creating execution with nonexistent test_case_id returns 404."""
        response = self.client.post(
            "/test-executions",
            json={"test_case_id": 99999},
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json().get("detail"), "Test case not found")

    def test_create_execution_invalid_status_rejected(self) -> None:
        """Verify invalid execution status is rejected with 422."""
        response = self.client.post(
            "/test-executions",
            json={"test_case_id": self.test_case_id, "status": "UNKNOWN_STATUS"},
        )
        self.assertEqual(response.status_code, 422)

    def test_update_execution_status(self) -> None:
        """Verify updating execution status and duration metrics."""
        created = self.client.post(
            "/test-executions",
            json={"test_case_id": self.test_case_id},
        ).json()
        exec_id = created["id"]

        # Update to RUNNING
        run_res = self.client.put(
            f"/test-executions/{exec_id}",
            json={"status": "RUNNING"},
        )
        self.assertEqual(run_res.status_code, 200)
        self.assertEqual(run_res.json()["status"], "RUNNING")

        # Update to PASSED with metrics
        pass_res = self.client.put(
            f"/test-executions/{exec_id}",
            json={"status": "PASSED", "duration_ms": 320},
        )
        self.assertEqual(pass_res.status_code, 200)
        self.assertEqual(pass_res.json()["status"], "PASSED")
        self.assertEqual(pass_res.json()["duration_ms"], 320)

    def test_retrieve_execution(self) -> None:
        """Verify retrieving an execution returns 200 and data."""
        created = self.client.post(
            "/test-executions",
            json={"test_case_id": self.test_case_id, "status": "FAILED", "error_message": "Timeout"},
        ).json()
        exec_id = created["id"]

        response = self.client.get(f"/test-executions/{exec_id}")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["id"], exec_id)
        self.assertEqual(data["status"], "FAILED")
        self.assertEqual(data["error_message"], "Timeout")

    def test_retrieve_nonexistent_execution_returns_404(self) -> None:
        """Verify retrieving nonexistent execution returns 404."""
        response = self.client.get("/test-executions/99999")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json().get("detail"), "Test execution not found")

    def test_list_executions_and_filter_by_test_case_id(self) -> None:
        """Verify listing executions with optional test_case_id filtering."""
        # Create second test case
        tc_2_id = self.client.post(
            "/test-cases",
            json={"application_id": self.application_id, "external_id": "tc-02", "name": "Second TC"},
        ).json()["id"]

        self.client.post("/test-executions", json={"test_case_id": self.test_case_id})
        self.client.post("/test-executions", json={"test_case_id": tc_2_id})

        all_res = self.client.get("/test-executions")
        self.assertEqual(all_res.status_code, 200)
        self.assertEqual(len(all_res.json()), 2)

        filter_res = self.client.get(f"/test-executions?test_case_id={self.test_case_id}")
        self.assertEqual(filter_res.status_code, 200)
        filtered = filter_res.json()
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["test_case_id"], self.test_case_id)


if __name__ == "__main__":
    unittest.main()
