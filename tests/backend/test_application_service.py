"""
TestSphere-AI — Application Service Tests.

Validates:
- create application
- list applications
- filter by project_id
- get application
- update application
- delete application
- missing project raises ProjectNotFoundError
- missing application raises ApplicationNotFoundError
- relationship integrity
"""

import unittest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database.session import Base
from backend.models.project import Project
from backend.services.application_service import ApplicationService
from backend.services.exceptions import ApplicationNotFoundError, ProjectNotFoundError
from backend.services.project_service import ProjectService


class TestApplicationService(unittest.TestCase):
    """Test suite for ApplicationService business operations."""

    def setUp(self) -> None:
        """Create an isolated in-memory database, session, and base Project."""
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        self.session = self.Session()

        # Seed initial project
        self.project = ProjectService.create_project(self.session, name="Root Project")

    def tearDown(self) -> None:
        """Clean up session and drop all tables."""
        self.session.close()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_create_application_success(self) -> None:
        """Verify application creation persists and links to project."""
        app = ApplicationService.create_application(
            db=self.session,
            project_id=self.project.id,
            name="Web App",
            base_url="https://app.test",
            description="Portal app",
        )
        self.assertIsNotNone(app.id)
        self.assertEqual(app.project_id, self.project.id)
        self.assertEqual(app.name, "Web App")
        self.assertEqual(app.base_url, "https://app.test")

    def test_create_application_missing_project_raises_not_found(self) -> None:
        """Verify creating application with nonexistent project_id raises ProjectNotFoundError."""
        with self.assertRaises(ProjectNotFoundError):
            ApplicationService.create_application(
                db=self.session,
                project_id=99999,
                name="Orphan",
                base_url="https://orphan.test",
            )

    def test_list_applications_and_filter(self) -> None:
        """Verify listing applications and filtering by project_id."""
        p2 = ProjectService.create_project(self.session, name="Project 2")

        ApplicationService.create_application(self.session, self.project.id, "App 1", "https://a1.test")
        ApplicationService.create_application(self.session, p2.id, "App 2", "https://a2.test")

        # List all
        all_apps = ApplicationService.list_applications(self.session)
        self.assertEqual(len(all_apps), 2)

        # Filter
        filtered = ApplicationService.list_applications(self.session, project_id=self.project.id)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0].name, "App 1")

    def test_get_application_success(self) -> None:
        """Verify getting application by ID."""
        created = ApplicationService.create_application(
            self.session, self.project.id, "App", "https://app.test"
        )
        fetched = ApplicationService.get_application(self.session, created.id)
        self.assertEqual(fetched.id, created.id)
        self.assertEqual(fetched.name, "App")

    def test_get_application_missing_raises_not_found(self) -> None:
        """Verify get_application raises ApplicationNotFoundError when ID does not exist."""
        with self.assertRaises(ApplicationNotFoundError):
            ApplicationService.get_application(self.session, 99999)

    def test_update_application(self) -> None:
        """Verify updating application fields."""
        created = ApplicationService.create_application(
            self.session, self.project.id, "Old App", "https://old.test"
        )
        updated = ApplicationService.update_application(
            db=self.session,
            application_id=created.id,
            name="New App",
            base_url="https://new.test",
            description="Updated desc",
        )
        self.assertEqual(updated.name, "New App")
        self.assertEqual(updated.base_url, "https://new.test")
        self.assertEqual(updated.description, "Updated desc")

    def test_delete_application(self) -> None:
        """Verify deleting application removes it from database."""
        created = ApplicationService.create_application(
            self.session, self.project.id, "To Delete", "https://del.test"
        )
        ApplicationService.delete_application(self.session, created.id)

        with self.assertRaises(ApplicationNotFoundError):
            ApplicationService.get_application(self.session, created.id)

    def test_relationship_integrity(self) -> None:
        """Verify relationship between Project and Application through services."""
        app = ApplicationService.create_application(
            self.session, self.project.id, "Child App", "https://child.test"
        )
        fetched_proj = ProjectService.get_project(self.session, self.project.id)
        self.assertEqual(len(fetched_proj.applications), 1)
        self.assertEqual(fetched_proj.applications[0].id, app.id)


if __name__ == "__main__":
    unittest.main()
