"""
TestSphere-AI — Projects API Tests.

Validates:
- create project
- list projects
- retrieve project
- update project
- delete project
- nonexistent project returns 404
- missing required name is rejected
"""

import unittest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database.session import Base, get_db
from backend.main import app


class TestProjectsAPI(unittest.TestCase):
    """Test suite for /projects CRUD API."""

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

    def tearDown(self) -> None:
        """Clean up database tables and reset dependency overrides."""
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_create_project_success(self) -> None:
        """Verify creating a project returns 201 and created project payload."""
        response = self.client.post(
            "/projects",
            json={"name": "Alpha Project", "description": "Test description"},
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertIsNotNone(data.get("id"))
        self.assertEqual(data.get("name"), "Alpha Project")
        self.assertEqual(data.get("description"), "Test description")
        self.assertIn("created_at", data)
        self.assertIn("updated_at", data)

    def test_create_project_missing_name_rejected(self) -> None:
        """Verify creating a project without required name is rejected with 422."""
        response = self.client.post("/projects", json={"description": "No name"})
        self.assertEqual(response.status_code, 422)

    def test_list_projects(self) -> None:
        """Verify listing projects returns all created projects."""
        self.client.post("/projects", json={"name": "Project 1"})
        self.client.post("/projects", json={"name": "Project 2"})

        response = self.client.get("/projects")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 2)
        names = [p["name"] for p in data]
        self.assertIn("Project 1", names)
        self.assertIn("Project 2", names)

    def test_retrieve_project_success(self) -> None:
        """Verify retrieving an existing project returns 200 and project details."""
        created = self.client.post("/projects", json={"name": "Beta Project"}).json()
        project_id = created["id"]

        response = self.client.get(f"/projects/{project_id}")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["id"], project_id)
        self.assertEqual(data["name"], "Beta Project")

    def test_retrieve_nonexistent_project_returns_404(self) -> None:
        """Verify retrieving nonexistent project returns 404."""
        response = self.client.get("/projects/99999")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json().get("detail"), "Project not found")

    def test_update_project(self) -> None:
        """Verify updating a project modifies attributes and persists."""
        created = self.client.post("/projects", json={"name": "Old Name"}).json()
        project_id = created["id"]

        response = self.client.put(
            f"/projects/{project_id}",
            json={"name": "New Name", "description": "Updated description"},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["name"], "New Name")
        self.assertEqual(data["description"], "Updated description")

    def test_update_nonexistent_project_returns_404(self) -> None:
        """Verify updating a nonexistent project returns 404."""
        response = self.client.put("/projects/99999", json={"name": "Ghost"})
        self.assertEqual(response.status_code, 404)

    def test_delete_project_success(self) -> None:
        """Verify deleting a project returns 204 and subsequent fetch returns 404."""
        created = self.client.post("/projects", json={"name": "To Delete"}).json()
        project_id = created["id"]

        delete_res = self.client.delete(f"/projects/{project_id}")
        self.assertEqual(delete_res.status_code, 204)

        get_res = self.client.get(f"/projects/{project_id}")
        self.assertEqual(get_res.status_code, 404)

    def test_delete_nonexistent_project_returns_404(self) -> None:
        """Verify deleting a nonexistent project returns 404."""
        response = self.client.delete("/projects/99999")
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()
