"""
TestSphere-AI — Test Cases API Tests.

Validates:
- create test case
- application relationship works
- list test cases
- filter by application_id
- retrieve test case
- update test case
- delete test case
- nonexistent application_id is rejected
- nonexistent test case returns 404
"""

import unittest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database.session import Base, get_db
from backend.main import app


class TestTestCasesAPI(unittest.TestCase):
    """Test suite for /test-cases CRUD API."""

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

        # Set up parent Project & Application
        proj_res = self.client.post("/projects", json={"name": "QA Project"})
        self.project_id = proj_res.json()["id"]

        app_res = self.client.post(
            "/applications",
            json={"project_id": self.project_id, "name": "Auth App", "base_url": "https://auth.test"},
        )
        self.application_id = app_res.json()["id"]

    def tearDown(self) -> None:
        """Clean up database tables and reset dependency overrides."""
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_create_test_case_success(self) -> None:
        """Verify creating a test case returns 201 and valid payload."""
        response = self.client.post(
            "/test-cases",
            json={
                "application_id": self.application_id,
                "external_id": "tc-login-01",
                "name": "User Login Test",
                "description": "Standard login flow",
                "category": "AUTH",
                "priority": "HIGH",
                "version": 1,
            },
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertIsNotNone(data.get("id"))
        self.assertEqual(data.get("application_id"), self.application_id)
        self.assertEqual(data.get("external_id"), "tc-login-01")
        self.assertEqual(data.get("name"), "User Login Test")
        self.assertEqual(data.get("version"), 1)

    def test_create_test_case_nonexistent_application_rejected(self) -> None:
        """Verify creating a test case with nonexistent application_id returns 404."""
        response = self.client.post(
            "/test-cases",
            json={
                "application_id": 99999,
                "external_id": "tc-orphan",
                "name": "Orphan Test",
            },
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json().get("detail"), "Application not found")

    def test_list_test_cases_and_filter_by_application_id(self) -> None:
        """Verify listing test cases and filtering by application_id."""
        # Create second application
        app_2_id = self.client.post(
            "/applications",
            json={"project_id": self.project_id, "name": "App 2", "base_url": "https://app2.test"},
        ).json()["id"]

        self.client.post(
            "/test-cases",
            json={"application_id": self.application_id, "external_id": "tc-1", "name": "Test 1"},
        )
        self.client.post(
            "/test-cases",
            json={"application_id": app_2_id, "external_id": "tc-2", "name": "Test 2"},
        )

        all_res = self.client.get("/test-cases")
        self.assertEqual(all_res.status_code, 200)
        self.assertEqual(len(all_res.json()), 2)

        filtered_res = self.client.get(f"/test-cases?application_id={self.application_id}")
        self.assertEqual(filtered_res.status_code, 200)
        filtered_data = filtered_res.json()
        self.assertEqual(len(filtered_data), 1)
        self.assertEqual(filtered_data[0]["external_id"], "tc-1")

    def test_retrieve_test_case_success(self) -> None:
        """Verify retrieving an existing test case."""
        created = self.client.post(
            "/test-cases",
            json={"application_id": self.application_id, "external_id": "tc-fetch", "name": "Fetch Test"},
        ).json()
        tc_id = created["id"]

        response = self.client.get(f"/test-cases/{tc_id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["name"], "Fetch Test")

    def test_retrieve_nonexistent_test_case_returns_404(self) -> None:
        """Verify retrieving nonexistent test case returns 404."""
        response = self.client.get("/test-cases/99999")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json().get("detail"), "Test case not found")

    def test_update_test_case(self) -> None:
        """Verify updating test case attributes."""
        created = self.client.post(
            "/test-cases",
            json={"application_id": self.application_id, "external_id": "tc-upd", "name": "Before Update"},
        ).json()
        tc_id = created["id"]

        response = self.client.put(
            f"/test-cases/{tc_id}",
            json={"name": "After Update", "priority": "CRITICAL", "version": 2},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["name"], "After Update")
        self.assertEqual(data["priority"], "CRITICAL")
        self.assertEqual(data["version"], 2)

    def test_delete_test_case(self) -> None:
        """Verify deleting a test case returns 204 and subsequently 404."""
        created = self.client.post(
            "/test-cases",
            json={"application_id": self.application_id, "external_id": "tc-del", "name": "Delete Me"},
        ).json()
        tc_id = created["id"]

        del_res = self.client.delete(f"/test-cases/{tc_id}")
        self.assertEqual(del_res.status_code, 204)

        get_res = self.client.get(f"/test-cases/{tc_id}")
        self.assertEqual(get_res.status_code, 404)


if __name__ == "__main__":
    unittest.main()
