"""
TestSphere-AI — Applications API Tests.

Validates:
- create application
- project relationship works
- list applications
- filter by project_id
- retrieve application
- update application
- delete application
- nonexistent project_id is rejected
- nonexistent application returns 404
"""

import unittest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database.session import Base, get_db
from backend.main import app


class TestApplicationsAPI(unittest.TestCase):
    """Test suite for /applications CRUD API."""

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

        # Create a sample project to attach applications to
        proj_res = self.client.post("/projects", json={"name": "Parent Project"})
        self.project_id = proj_res.json()["id"]

    def tearDown(self) -> None:
        """Clean up database tables and reset dependency overrides."""
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_create_application_success(self) -> None:
        """Verify creating an application returns 201 and payload."""
        response = self.client.post(
            "/applications",
            json={
                "project_id": self.project_id,
                "name": "Web App",
                "base_url": "https://app.test",
                "description": "Main portal",
            },
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertIsNotNone(data.get("id"))
        self.assertEqual(data.get("project_id"), self.project_id)
        self.assertEqual(data.get("name"), "Web App")
        self.assertEqual(data.get("base_url"), "https://app.test")

    def test_create_application_nonexistent_project_rejected(self) -> None:
        """Verify creating an application with nonexistent project_id returns 404."""
        response = self.client.post(
            "/applications",
            json={
                "project_id": 99999,
                "name": "Orphan App",
                "base_url": "https://orphan.test",
            },
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json().get("detail"), "Project not found")

    def test_list_applications_and_filter_by_project_id(self) -> None:
        """Verify listing applications and filtering by project_id."""
        # Create second project
        proj_2_id = self.client.post("/projects", json={"name": "Second Project"}).json()["id"]

        # Create applications under different projects
        self.client.post(
            "/applications",
            json={"project_id": self.project_id, "name": "App 1", "base_url": "https://a1.test"},
        )
        self.client.post(
            "/applications",
            json={"project_id": proj_2_id, "name": "App 2", "base_url": "https://a2.test"},
        )

        # List all
        all_res = self.client.get("/applications")
        self.assertEqual(all_res.status_code, 200)
        self.assertEqual(len(all_res.json()), 2)

        # Filter by project 1
        filtered_res = self.client.get(f"/applications?project_id={self.project_id}")
        self.assertEqual(filtered_res.status_code, 200)
        filtered_data = filtered_res.json()
        self.assertEqual(len(filtered_data), 1)
        self.assertEqual(filtered_data[0]["name"], "App 1")

    def test_retrieve_application_success(self) -> None:
        """Verify retrieving an existing application."""
        created = self.client.post(
            "/applications",
            json={"project_id": self.project_id, "name": "App X", "base_url": "https://x.test"},
        ).json()
        app_id = created["id"]

        response = self.client.get(f"/applications/{app_id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["name"], "App X")

    def test_retrieve_nonexistent_application_returns_404(self) -> None:
        """Verify retrieving nonexistent application returns 404."""
        response = self.client.get("/applications/99999")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json().get("detail"), "Application not found")

    def test_update_application(self) -> None:
        """Verify updating application fields."""
        created = self.client.post(
            "/applications",
            json={"project_id": self.project_id, "name": "Initial", "base_url": "https://init.test"},
        ).json()
        app_id = created["id"]

        response = self.client.put(
            f"/applications/{app_id}",
            json={"name": "Updated Name", "base_url": "https://updated.test"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["name"], "Updated Name")
        self.assertEqual(data["base_url"], "https://updated.test")

    def test_delete_application(self) -> None:
        """Verify deleting an application returns 204 and subsequently 404."""
        created = self.client.post(
            "/applications",
            json={"project_id": self.project_id, "name": "To Delete", "base_url": "https://del.test"},
        ).json()
        app_id = created["id"]

        del_res = self.client.delete(f"/applications/{app_id}")
        self.assertEqual(del_res.status_code, 204)

        get_res = self.client.get(f"/applications/{app_id}")
        self.assertEqual(get_res.status_code, 404)


if __name__ == "__main__":
    unittest.main()
