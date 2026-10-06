"""
TestSphere-AI — TestCase Service Tests.

Validates:
- create test case
- list test cases
- filter by application_id
- get test case
- update test case
- delete test case
- missing application raises ApplicationNotFoundError
- missing test case raises TestCaseNotFoundError
- relationship integrity
"""

import unittest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database.session import Base
from backend.services.application_service import ApplicationService
from backend.services.exceptions import ApplicationNotFoundError, TestCaseNotFoundError
from backend.services.project_service import ProjectService
from backend.services.test_case_service import TestCaseService


class TestTestCaseService(unittest.TestCase):
    """Test suite for TestCaseService business operations."""

    def setUp(self) -> None:
        """Create an isolated in-memory database and seed Project & Application."""
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        self.session = self.Session()

        # Seed hierarchy
        self.project = ProjectService.create_project(self.session, name="Root Project")
        self.application = ApplicationService.create_application(
            self.session, self.project.id, name="Auth App", base_url="https://auth.test"
        )

    def tearDown(self) -> None:
        """Clean up session and drop all tables."""
        self.session.close()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_create_test_case_success(self) -> None:
        """Verify test case creation persists and sets default version."""
        tc = TestCaseService.create_test_case(
            db=self.session,
            application_id=self.application.id,
            external_id="tc-001",
            name="Login Flow",
            description="Verify login",
            category="AUTH",
            priority="HIGH",
            version=1,
        )
        self.assertIsNotNone(tc.id)
        self.assertEqual(tc.application_id, self.application.id)
        self.assertEqual(tc.external_id, "tc-001")
        self.assertEqual(tc.name, "Login Flow")
        self.assertEqual(tc.version, 1)

    def test_create_test_case_missing_application_raises_not_found(self) -> None:
        """Verify creating test case with nonexistent application_id raises ApplicationNotFoundError."""
        with self.assertRaises(ApplicationNotFoundError):
            TestCaseService.create_test_case(
                db=self.session,
                application_id=99999,
                external_id="tc-orphan",
                name="Orphan TC",
            )

    def test_list_test_cases_and_filter(self) -> None:
        """Verify listing test cases and filtering by application_id."""
        app2 = ApplicationService.create_application(
            self.session, self.project.id, name="Billing App", base_url="https://bill.test"
        )

        TestCaseService.create_test_case(self.session, self.application.id, "tc-1", "Test 1")
        TestCaseService.create_test_case(self.session, app2.id, "tc-2", "Test 2")

        all_tcs = TestCaseService.list_test_cases(self.session)
        self.assertEqual(len(all_tcs), 2)

        filtered = TestCaseService.list_test_cases(self.session, application_id=self.application.id)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0].external_id, "tc-1")

    def test_get_test_case_success(self) -> None:
        """Verify getting test case by ID."""
        created = TestCaseService.create_test_case(
            self.session, self.application.id, "tc-find", "Find TC"
        )
        fetched = TestCaseService.get_test_case(self.session, created.id)
        self.assertEqual(fetched.id, created.id)
        self.assertEqual(fetched.name, "Find TC")

    def test_get_test_case_missing_raises_not_found(self) -> None:
        """Verify get_test_case raises TestCaseNotFoundError when ID does not exist."""
        with self.assertRaises(TestCaseNotFoundError):
            TestCaseService.get_test_case(self.session, 99999)

    def test_update_test_case(self) -> None:
        """Verify updating test case fields."""
        created = TestCaseService.create_test_case(
            self.session, self.application.id, "tc-old", "Old Name"
        )
        updated = TestCaseService.update_test_case(
            db=self.session,
            test_case_id=created.id,
            name="New Name",
            priority="CRITICAL",
            version=2,
        )
        self.assertEqual(updated.name, "New Name")
        self.assertEqual(updated.priority, "CRITICAL")
        self.assertEqual(updated.version, 2)

    def test_delete_test_case(self) -> None:
        """Verify deleting test case removes it from database."""
        created = TestCaseService.create_test_case(
            self.session, self.application.id, "tc-del", "To Delete"
        )
        TestCaseService.delete_test_case(self.session, created.id)

        with self.assertRaises(TestCaseNotFoundError):
            TestCaseService.get_test_case(self.session, created.id)

    def test_relationship_integrity(self) -> None:
        """Verify relationship between Application and TestCase."""
        tc = TestCaseService.create_test_case(
            self.session, self.application.id, "tc-rel", "Rel TC"
        )
        fetched_app = ApplicationService.get_application(self.session, self.application.id)
        self.assertEqual(len(fetched_app.test_cases), 1)
        self.assertEqual(fetched_app.test_cases[0].id, tc.id)


if __name__ == "__main__":
    unittest.main()
