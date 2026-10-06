"""
TestSphere-AI — Project Service Tests.

Validates:
- create project
- list projects
- get project
- update project
- delete project
- missing project raises ProjectNotFoundError
"""

import unittest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database.session import Base
from backend.services.exceptions import ProjectNotFoundError
from backend.services.project_service import ProjectService


class TestProjectService(unittest.TestCase):
    """Test suite for ProjectService business operations."""

    def setUp(self) -> None:
        """Create an isolated in-memory database and session."""
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        self.session = self.Session()

    def tearDown(self) -> None:
        """Clean up session and drop all tables."""
        self.session.close()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_create_project(self) -> None:
        """Verify project creation persists and returns the instance."""
        project = ProjectService.create_project(
            db=self.session,
            name="Service Project",
            description="Testing service logic",
        )
        self.assertIsNotNone(project.id)
        self.assertEqual(project.name, "Service Project")
        self.assertEqual(project.description, "Testing service logic")

    def test_list_projects(self) -> None:
        """Verify listing all projects."""
        ProjectService.create_project(self.session, "P1")
        ProjectService.create_project(self.session, "P2")

        projects = ProjectService.list_projects(self.session)
        self.assertEqual(len(projects), 2)
        names = [p.name for p in projects]
        self.assertIn("P1", names)
        self.assertIn("P2", names)

    def test_get_project_success(self) -> None:
        """Verify getting project by ID."""
        created = ProjectService.create_project(self.session, "Target P")
        fetched = ProjectService.get_project(self.session, created.id)
        self.assertEqual(fetched.id, created.id)
        self.assertEqual(fetched.name, "Target P")

    def test_get_project_missing_raises_not_found(self) -> None:
        """Verify get_project raises ProjectNotFoundError when ID does not exist."""
        with self.assertRaises(ProjectNotFoundError):
            ProjectService.get_project(self.session, 99999)

    def test_update_project(self) -> None:
        """Verify updating project fields."""
        created = ProjectService.create_project(self.session, "Original Name")
        updated = ProjectService.update_project(
            db=self.session,
            project_id=created.id,
            name="Renamed Project",
            description="New description",
        )
        self.assertEqual(updated.name, "Renamed Project")
        self.assertEqual(updated.description, "New description")

    def test_delete_project(self) -> None:
        """Verify deleting project removes it from database."""
        created = ProjectService.create_project(self.session, "To Delete")
        ProjectService.delete_project(self.session, created.id)

        with self.assertRaises(ProjectNotFoundError):
            ProjectService.get_project(self.session, created.id)


if __name__ == "__main__":
    unittest.main()
