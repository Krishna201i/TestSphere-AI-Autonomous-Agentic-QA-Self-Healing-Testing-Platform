"""
TestSphere-AI — Test Cases API Router.

Provides CRUD endpoints for persisted test cases (only the caller's own).
Delegates persistence and business logic to TestCaseService.
Does not import, modify, or duplicate Member 1 TestCase business logic.
"""


from fastapi import APIRouter, Depends, Query, status

from backend.api.schemas import (
    TestCaseCreate,
    TestCaseResponse,
    TestCaseUpdate,
)
from backend.auth import User, ensure_owned, get_current_user, scope
from backend.database.session import get_db
from backend.database.store import Record, Store
from backend.models import APPLICATIONS, TEST_CASES
from backend.services.test_case_service import TestCaseService

router = APIRouter(prefix="/test-cases", tags=["Test Cases"])


def owned_test_case(db: Store, user: User, test_case_id: int) -> Record:
    return ensure_owned(user, db.get(TEST_CASES, test_case_id), "Test case")


@router.post("", response_model=TestCaseResponse, status_code=status.HTTP_201_CREATED)
def create_test_case(
    payload: TestCaseCreate,
    db: Store = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Record:
    """Create a new test case linked to an existing application."""
    ensure_owned(user, db.get(APPLICATIONS, payload.application_id), "Application")
    return TestCaseService.create_test_case(
        db=db,
        application_id=payload.application_id,
        external_id=payload.external_id,
        name=payload.name,
        description=payload.description,
        category=payload.category,
        priority=payload.priority,
        version=payload.version,
        owner_uid=user.uid,
    )


@router.get("", response_model=list[TestCaseResponse])
def list_test_cases(
    application_id: int | None = Query(None, description="Filter by parent Application ID"),
    db: Store = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Record]:
    """Retrieve the caller's test cases, with optional application_id filtering."""
    return TestCaseService.list_test_cases(db=db, application_id=application_id, **scope(user))


@router.get("/{test_case_id}", response_model=TestCaseResponse)
def get_test_case(
    test_case_id: int,
    db: Store = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Record:
    """Retrieve a single test case by ID."""
    return owned_test_case(db, user, test_case_id)


@router.put("/{test_case_id}", response_model=TestCaseResponse)
def update_test_case(
    test_case_id: int,
    payload: TestCaseUpdate,
    db: Store = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Record:
    """Update attributes of an existing test case."""
    owned_test_case(db, user, test_case_id)
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


@router.delete("/{test_case_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_test_case(
    test_case_id: int,
    db: Store = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    """Delete a test case and cascade delete its associated test executions."""
    owned_test_case(db, user, test_case_id)
    TestCaseService.delete_test_case(db=db, test_case_id=test_case_id)
    return None
