"""
TestSphere-AI — TestExecution Service Tests.

Validates:
- create execution
- default status is PENDING
- list executions
- filter by test_case_id
- get execution
- update execution
- delete execution
- missing test case raises TestCaseNotFoundError
- invalid status raises InvalidExecutionStatusError
- missing execution raises TestExecutionNotFoundError
- relationship integrity
"""

import unittest
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.database.session import Base
from backend.models.test_execution import TestExecutionStatus
from backend.services.application_service import ApplicationService
from backend.services.exceptions import (
    InvalidExecutionStatusError,
    TestCaseNotFoundError,
    TestExecutionNotFoundError,
)
from backend.services.project_service import ProjectService
from backend.services.test_case_service import TestCaseService
from backend.services.test_execution_service import TestExecutionService


class TestTestExecutionService(unittest.TestCase):
    """Test suite for TestExecutionService business operations."""

    def setUp(self) -> None:
        """Create an isolated in-memory database and seed hierarchy."""
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        self.session = self.Session()

        # Seed hierarchy: Project -> Application -> TestCase
        self.project = ProjectService.create_project(self.session, name="Exec Project")
        self.application = ApplicationService.create_application(
            self.session, self.project.id, name="App", base_url="https://app.test"
        )
        self.test_case = TestCaseService.create_test_case(
            self.session, self.application.id, external_id="tc-exec", name="Exec TC"
        )

    def tearDown(self) -> None:
        """Clean up session and drop all tables."""
        self.session.close()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_create_execution_default_status(self) -> None:
        """Verify execution creation defaults to PENDING."""
        exec_item = TestExecutionService.create_execution(
            db=self.session,
            test_case_id=self.test_case.id,
        )
        self.assertIsNotNone(exec_item.id)
        self.assertEqual(exec_item.test_case_id, self.test_case.id)
        self.assertEqual(exec_item.status, "PENDING")

    def test_create_execution_missing_test_case_raises_not_found(self) -> None:
        """Verify creating execution with nonexistent test_case_id raises TestCaseNotFoundError."""
        with self.assertRaises(TestCaseNotFoundError):
            TestExecutionService.create_execution(
                db=self.session,
                test_case_id=99999,
            )

    def test_create_execution_invalid_status_raises_error(self) -> None:
        """Verify invalid status string raises InvalidExecutionStatusError."""
        with self.assertRaises(InvalidExecutionStatusError):
            TestExecutionService.create_execution(
                db=self.session,
                test_case_id=self.test_case.id,
                status="BAD_STATUS",
            )

    def test_list_executions_and_filter(self) -> None:
        """Verify listing executions and filtering by test_case_id."""
        tc2 = TestCaseService.create_test_case(
            self.session, self.application.id, external_id="tc-2", name="TC 2"
        )

        TestExecutionService.create_execution(self.session, self.test_case.id)
        TestExecutionService.create_execution(self.session, tc2.id)

        all_execs = TestExecutionService.list_executions(self.session)
        self.assertEqual(len(all_execs), 2)

        filtered = TestExecutionService.list_executions(self.session, test_case_id=self.test_case.id)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0].test_case_id, self.test_case.id)

    def test_get_execution_success(self) -> None:
        """Verify getting execution by ID."""
        created = TestExecutionService.create_execution(self.session, self.test_case.id)
        fetched = TestExecutionService.get_execution(self.session, created.id)
        self.assertEqual(fetched.id, created.id)
        self.assertEqual(fetched.status, "PENDING")

    def test_get_execution_missing_raises_not_found(self) -> None:
        """Verify get_execution raises TestExecutionNotFoundError when ID does not exist."""
        with self.assertRaises(TestExecutionNotFoundError):
            TestExecutionService.get_execution(self.session, 99999)

    def test_update_execution(self) -> None:
        """Verify updating execution status and duration."""
        created = TestExecutionService.create_execution(self.session, self.test_case.id)
        now = datetime.now(timezone.utc)
        updated = TestExecutionService.update_execution(
            db=self.session,
            execution_id=created.id,
            status=TestExecutionStatus.PASSED,
            completed_at=now,
            duration_ms=500,
        )
        self.assertEqual(updated.status, "PASSED")
        self.assertEqual(updated.duration_ms, 500)
        self.assertIsNotNone(updated.completed_at)
        # SQLite stores datetimes without tzinfo, compare timestamps
        if updated.completed_at.tzinfo is None:
            self.assertEqual(updated.completed_at.replace(tzinfo=timezone.utc), now)
        else:
            self.assertEqual(updated.completed_at, now)

    def test_update_execution_invalid_status_raises_error(self) -> None:
        """Verify updating execution with invalid status raises InvalidExecutionStatusError."""
        created = TestExecutionService.create_execution(self.session, self.test_case.id)
        with self.assertRaises(InvalidExecutionStatusError):
            TestExecutionService.update_execution(
                db=self.session,
                execution_id=created.id,
                status="INVALID",
            )

    def test_delete_execution(self) -> None:
        """Verify deleting execution removes it from database."""
        created = TestExecutionService.create_execution(self.session, self.test_case.id)
        TestExecutionService.delete_execution(self.session, created.id)

        with self.assertRaises(TestExecutionNotFoundError):
            TestExecutionService.get_execution(self.session, created.id)

    def test_relationship_integrity(self) -> None:
        """Verify relationship between TestCase and TestExecution."""
        exec_item = TestExecutionService.create_execution(self.session, self.test_case.id)
        fetched_tc = TestCaseService.get_test_case(self.session, self.test_case.id)
        self.assertEqual(len(fetched_tc.test_executions), 1)
        self.assertEqual(fetched_tc.test_executions[0].id, exec_item.id)


if __name__ == "__main__":
    unittest.main()
