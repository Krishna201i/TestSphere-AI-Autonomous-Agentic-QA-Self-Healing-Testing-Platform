"""
TestSphere-AI — Test Execution Service.

Encapsulates database operations for test execution state and metrics.
Does NOT execute browser automation, invoke Playwright, or trigger AI agents.
"""

from datetime import datetime
from typing import List, Optional, Union
from sqlalchemy.orm import Session

from backend.models.test_case import TestCase
from backend.models.test_execution import TestExecution, TestExecutionStatus
from backend.services.exceptions import (
    InvalidExecutionStatusError,
    TestCaseNotFoundError,
    TestExecutionNotFoundError,
)


class TestExecutionService:
    """Service managing test execution records and statuses."""

    @staticmethod
    def _validate_status(status_val: Union[str, TestExecutionStatus]) -> str:
        """Validate that the status value belongs to TestExecutionStatus."""
        raw = status_val.value if hasattr(status_val, "value") else str(status_val)
        allowed = {s.value for s in TestExecutionStatus}
        if raw not in allowed:
            raise InvalidExecutionStatusError(
                f"Status '{raw}' is invalid. Allowed statuses: {sorted(allowed)}"
            )
        return raw

    @staticmethod
    def create_execution(
        db: Session,
        test_case_id: int,
        status: Union[str, TestExecutionStatus] = TestExecutionStatus.PENDING,
        started_at: Optional[datetime] = None,
        completed_at: Optional[datetime] = None,
        duration_ms: Optional[int] = None,
        error_message: Optional[str] = None,
    ) -> TestExecution:
        """Create and persist a new test execution record."""
        test_case = db.query(TestCase).filter(TestCase.id == test_case_id).first()
        if not test_case:
            raise TestCaseNotFoundError(f"Test case with ID {test_case_id} not found")

        status_str = TestExecutionService._validate_status(status)

        execution = TestExecution(
            test_case_id=test_case_id,
            status=status_str,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
            error_message=error_message,
        )
        db.add(execution)
        db.commit()
        db.refresh(execution)
        return execution

    @staticmethod
    def list_executions(
        db: Session,
        test_case_id: Optional[int] = None,
    ) -> List[TestExecution]:
        """Retrieve test executions, optionally filtered by test_case_id."""
        query = db.query(TestExecution)
        if test_case_id is not None:
            query = query.filter(TestExecution.test_case_id == test_case_id)
        return query.all()

    @staticmethod
    def get_execution(db: Session, execution_id: int) -> TestExecution:
        """Retrieve a test execution by primary key or raise TestExecutionNotFoundError."""
        execution = db.query(TestExecution).filter(TestExecution.id == execution_id).first()
        if not execution:
            raise TestExecutionNotFoundError(f"Test execution with ID {execution_id} not found")
        return execution

    @staticmethod
    def update_execution(
        db: Session,
        execution_id: int,
        status: Optional[Union[str, TestExecutionStatus]] = None,
        started_at: Optional[datetime] = None,
        completed_at: Optional[datetime] = None,
        duration_ms: Optional[int] = None,
        error_message: Optional[str] = None,
    ) -> TestExecution:
        """Update lifecycle status and execution metrics."""
        execution = TestExecutionService.get_execution(db, execution_id)
        if status is not None:
            execution.status = TestExecutionService._validate_status(status)
        if started_at is not None:
            execution.started_at = started_at
        if completed_at is not None:
            execution.completed_at = completed_at
        if duration_ms is not None:
            execution.duration_ms = duration_ms
        if error_message is not None:
            execution.error_message = error_message
        db.commit()
        db.refresh(execution)
        return execution

    @staticmethod
    def delete_execution(db: Session, execution_id: int) -> None:
        """Delete a test execution record."""
        execution = TestExecutionService.get_execution(db, execution_id)
        db.delete(execution)
        db.commit()
