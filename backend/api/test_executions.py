"""
TestSphere-AI — Test Executions API Router.

Provides endpoints to record and inspect test execution state (only the caller's own).
Delegates persistence and business logic to TestExecutionService.
Does not launch Playwright, execute browser tests, or invoke AI agents.
"""


from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.api.schemas import (
    TestExecutionCreate,
    TestExecutionResponse,
    TestExecutionUpdate,
)
from backend.auth import User, ensure_owned, get_current_user, scope
from backend.database.session import get_db
from backend.database.store import Record, Store
from backend.models import TEST_CASES, TEST_EXECUTIONS
from backend.services.exceptions import InvalidExecutionStatusError
from backend.services.test_execution_service import TestExecutionService

router = APIRouter(prefix="/test-executions", tags=["Test Executions"])


def owned_execution(db: Store, user: User, execution_id: int) -> Record:
    return ensure_owned(user, db.get(TEST_EXECUTIONS, execution_id), "Test execution")


@router.post("", response_model=TestExecutionResponse, status_code=status.HTTP_201_CREATED)
def create_test_execution(
    payload: TestExecutionCreate,
    db: Store = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Record:
    """Record a new test execution instance."""
    ensure_owned(user, db.get(TEST_CASES, payload.test_case_id), "Test case")
    try:
        return TestExecutionService.create_execution(
            db=db,
            test_case_id=payload.test_case_id,
            status=payload.status,
            started_at=payload.started_at,
            completed_at=payload.completed_at,
            duration_ms=payload.duration_ms,
            error_message=payload.error_message,
            owner_uid=user.uid,
        )
    except InvalidExecutionStatusError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.get("", response_model=list[TestExecutionResponse])
def list_test_executions(
    test_case_id: int | None = Query(None, description="Filter by parent TestCase ID"),
    db: Store = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Record]:
    """Retrieve the caller's test executions, with optional test_case_id filtering."""
    return TestExecutionService.list_executions(db=db, test_case_id=test_case_id, **scope(user))


@router.get("/{execution_id}", response_model=TestExecutionResponse)
def get_test_execution(
    execution_id: int,
    db: Store = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Record:
    """Retrieve a single test execution record by ID."""
    return owned_execution(db, user, execution_id)


@router.put("/{execution_id}", response_model=TestExecutionResponse)
def update_test_execution(
    execution_id: int,
    payload: TestExecutionUpdate,
    db: Store = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Record:
    """Update execution lifecycle state and metrics."""
    owned_execution(db, user, execution_id)
    try:
        return TestExecutionService.update_execution(
            db=db,
            execution_id=execution_id,
            status=payload.status,
            started_at=payload.started_at,
            completed_at=payload.completed_at,
            duration_ms=payload.duration_ms,
            error_message=payload.error_message,
        )
    except InvalidExecutionStatusError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.delete("/{execution_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_test_execution(
    execution_id: int,
    db: Store = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    """Delete a test execution record."""
    owned_execution(db, user, execution_id)
    TestExecutionService.delete_execution(db=db, execution_id=execution_id)
    return None
