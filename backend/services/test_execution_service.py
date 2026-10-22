"""
TestSphere-AI — Test Execution Service.

Encapsulates storage operations for test execution state and metrics.
Does NOT execute browser automation, invoke Playwright, or trigger AI agents.
"""

from datetime import datetime
from typing import Any

from backend.database.store import Record, Store
from backend.models import TEST_CASES, TEST_EXECUTIONS
from backend.models.test_execution import TestExecutionStatus
from backend.services.exceptions import (
    InvalidExecutionStatusError,
    TestCaseNotFoundError,
    TestExecutionNotFoundError,
)


class TestExecutionService:
    """Service layer for TestExecution entities."""

    @staticmethod
    def _validate_status(status_val: str | TestExecutionStatus) -> str:
        raw = status_val.value if hasattr(status_val, "value") else str(status_val)
        allowed = {s.value for s in TestExecutionStatus}
        if raw not in allowed:
            raise InvalidExecutionStatusError(f"Status '{raw}' is invalid. Allowed statuses: {sorted(allowed)}")
        return raw

    @staticmethod
    def create_execution(
        db: Store, test_case_id: int, status: str | TestExecutionStatus = TestExecutionStatus.PENDING,
        started_at: datetime | None = None, completed_at: datetime | None = None,
        duration_ms: int | None = None, error_message: str | None = None,
        owner_uid: str | None = None,
    ) -> Record:
        test_case = db.get(TEST_CASES, test_case_id)
        if not test_case:
            raise TestCaseNotFoundError(f"Test case with ID {test_case_id} not found")
        return db.insert(
            TEST_EXECUTIONS, test_case_id=test_case_id, status=TestExecutionService._validate_status(status),
            started_at=started_at, completed_at=completed_at, duration_ms=duration_ms, error_message=error_message,
            owner_uid=owner_uid or test_case.get("owner_uid"),
        )

    @staticmethod
    def list_executions(db: Store, test_case_id: int | None = None, **filters: Any) -> list[Record]:
        if test_case_id is not None:
            filters["test_case_id"] = test_case_id
        return db.find(TEST_EXECUTIONS, **filters)

    @staticmethod
    def get_execution(db: Store, execution_id: int) -> Record:
        execution = db.get(TEST_EXECUTIONS, execution_id)
        if not execution:
            raise TestExecutionNotFoundError(f"Test execution with ID {execution_id} not found")
        return execution

    @staticmethod
    def update_execution(
        db: Store, execution_id: int, status: str | TestExecutionStatus | None = None,
        started_at: datetime | None = None, completed_at: datetime | None = None,
        duration_ms: int | None = None, error_message: str | None = None,
    ) -> Record:
        TestExecutionService.get_execution(db, execution_id)
        changes = {"started_at": started_at, "completed_at": completed_at,
                   "duration_ms": duration_ms, "error_message": error_message}
        changes = {k: v for k, v in changes.items() if v is not None}
        if status is not None:
            changes["status"] = TestExecutionService._validate_status(status)
        return db.update(TEST_EXECUTIONS, execution_id, **changes)

    @staticmethod
    def delete_execution(db: Store, execution_id: int) -> None:
        TestExecutionService.get_execution(db, execution_id)
        db.delete(TEST_EXECUTIONS, execution_id)
