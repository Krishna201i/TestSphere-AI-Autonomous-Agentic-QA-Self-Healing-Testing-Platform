"""
TestSphere-AI — Test Cases API Router.

Provides CRUD endpoints for persisted test cases.
Delegates persistence and business logic to TestCaseService.
Does not import, modify, or duplicate Member 1 TestCase business logic.
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.api.schemas import (
    TestCaseCreate,
    TestCaseResponse,
    TestCaseUpdate,
)
from backend.database.session import get_db
from backend.models.test_case import TestCase
from backend.services.exceptions import (
    ApplicationNotFoundError,
    TestCaseNotFoundError,
)
from backend.services.test_case_service import TestCaseService

router = APIRouter(prefix="/test-cases", tags=["Test Cases"])


@router.post("", response_model=TestCaseResponse, status_code=status.HTTP_201_CREATED)
def create_test_case(
    payload: TestCaseCreate,
    db: Session = Depends(get_db),
) -> TestCase:
    """Create a new test case linked to an existing application."""
    try:
        return TestCaseService.create_test_case(
            db=db,
            application_id=payload.application_id,
            external_id=payload.external_id,
            name=payload.name,
            description=payload.description,
            category=payload.category,
            priority=payload.priority,
            version=payload.version,
        )
    except ApplicationNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Application not found",
        )


@router.get("", response_model=List[TestCaseResponse])
def list_test_cases(
    application_id: Optional[int] = Query(None, description="Filter by parent Application ID"),
    db: Session = Depends(get_db),
) -> List[TestCase]:
    """Retrieve all test cases, with optional application_id filtering."""
    return TestCaseService.list_test_cases(db=db, application_id=application_id)


@router.get("/{test_case_id}", response_model=TestCaseResponse)
def get_test_case(
    test_case_id: int,
    db: Session = Depends(get_db),
) -> TestCase:
    """Retrieve a single test case by ID."""
    try:
        return TestCaseService.get_test_case(db=db, test_case_id=test_case_id)
    except TestCaseNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Test case not found",
        )


@router.put("/{test_case_id}", response_model=TestCaseResponse)
def update_test_case(
    test_case_id: int,
    payload: TestCaseUpdate,
    db: Session = Depends(get_db),
) -> TestCase:
    """Update attributes of an existing test case."""
    try:
        return TestCaseService.update_test_case(
            db=db,
            test_case_id=test_case_id,
            external_id=payload.external_id,
            name=payload.name,
            description=payload.description,
            category=payload.category,
            priority=payload.priority,
            version=payload.version,
        )
    except TestCaseNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Test case not found",
        )


@router.delete("/{test_case_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_test_case(
    test_case_id: int,
    db: Session = Depends(get_db),
) -> None:
    """Delete a test case and cascade delete its associated test executions."""
    try:
        TestCaseService.delete_test_case(db=db, test_case_id=test_case_id)
    except TestCaseNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Test case not found",
        )
    return None
