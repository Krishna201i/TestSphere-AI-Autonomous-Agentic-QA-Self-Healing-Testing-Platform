"""
TestSphere-AI — Test Executions API Router.

Provides endpoints to record and inspect test execution state.
Delegates persistence and business logic to TestExecutionService.
Does not launch Playwright, execute browser tests, or invoke AI agents.
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.api.schemas import (
    TestExecutionCreate,
    TestExecutionResponse,
    TestExecutionUpdate,
)
from backend.database.session import get_db
from backend.models.test_execution import TestExecution
from backend.services.exceptions import (
    InvalidExecutionStatusError,
    TestCaseNotFoundError,
    TestExecutionNotFoundError,
)
from backend.services.test_execution_service import TestExecutionService

router = APIRouter(prefix="/test-executions", tags=["Test Executions"])


@router.post("", response_model=TestExecutionResponse, status_code=status.HTTP_201_CREATED)
def create_test_execution(
    payload: TestExecutionCreate,
    db: Session = Depends(get_db),
) -> TestExecution:
    """Record a new test execution instance."""
    try:
        return TestExecutionService.create_execution(
            db=db,
            test_case_id=payload.test_case_id,
            status=payload.status,
            started_at=payload.started_at,
            completed_at=payload.completed_at,
            duration_ms=payload.duration_ms,
            error_message=payload.error_message,
        )
    except TestCaseNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Test case not found",
        )
    except InvalidExecutionStatusError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )


@router.get("", response_model=List[TestExecutionResponse])
def list_test_executions(
    test_case_id: Optional[int] = Query(None, description="Filter by parent TestCase ID"),
    db: Session = Depends(get_db),
) -> List[TestExecution]:
    """Retrieve all test executions, with optional test_case_id filtering."""
    return TestExecutionService.list_executions(db=db, test_case_id=test_case_id)


@router.get("/{execution_id}", response_model=TestExecutionResponse)
def get_test_execution(
    execution_id: int,
    db: Session = Depends(get_db),
) -> TestExecution:
    """Retrieve a single test execution record by ID."""
    try:
        return TestExecutionService.get_execution(db=db, execution_id=execution_id)
    except TestExecutionNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Test execution not found",
        )


@router.put("/{execution_id}", response_model=TestExecutionResponse)
def update_test_execution(
    execution_id: int,
    payload: TestExecutionUpdate,
    db: Session = Depends(get_db),
) -> TestExecution:
    """Update execution lifecycle state and metrics."""
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
    except TestExecutionNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Test execution not found",
        )
    except InvalidExecutionStatusError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )


@router.delete("/{execution_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_test_execution(
    execution_id: int,
    db: Session = Depends(get_db),
) -> None:
    """Delete a test execution record."""
    try:
        TestExecutionService.delete_execution(db=db, execution_id=execution_id)
    except TestExecutionNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Test execution not found",
        )
    return None
