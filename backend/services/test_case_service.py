"""
TestSphere-AI — Test Case Service.

Encapsulates database and persistence operations for test cases.
Does not import or modify Member 1 TestCase AI logic.
"""

from typing import List, Optional
from sqlalchemy.orm import Session

from backend.models.application import Application
from backend.models.test_case import TestCase
from backend.services.exceptions import ApplicationNotFoundError, TestCaseNotFoundError


class TestCaseService:
    """Service handling test case persistence and querying."""

    @staticmethod
    def create_test_case(
        db: Session,
        application_id: int,
        external_id: str,
        name: str,
        description: Optional[str] = None,
        category: Optional[str] = None,
        priority: Optional[str] = None,
        version: int = 1,
    ) -> TestCase:
        """Create and persist a new test case after validating parent application existence."""
        application = db.query(Application).filter(Application.id == application_id).first()
        if not application:
            raise ApplicationNotFoundError(f"Application with ID {application_id} not found")

        test_case = TestCase(
            application_id=application_id,
            external_id=external_id,
            name=name,
            description=description,
            category=category,
            priority=priority,
            version=version,
        )
        db.add(test_case)
        db.commit()
        db.refresh(test_case)
        return test_case

    @staticmethod
    def list_test_cases(
        db: Session,
        application_id: Optional[int] = None,
    ) -> List[TestCase]:
        """Retrieve test cases, optionally filtered by application_id."""
        query = db.query(TestCase)
        if application_id is not None:
            query = query.filter(TestCase.application_id == application_id)
        return query.all()

    @staticmethod
    def get_test_case(db: Session, test_case_id: int) -> TestCase:
        """Retrieve a test case by primary key or raise TestCaseNotFoundError."""
        test_case = db.query(TestCase).filter(TestCase.id == test_case_id).first()
        if not test_case:
            raise TestCaseNotFoundError(f"Test case with ID {test_case_id} not found")
        return test_case

    @staticmethod
    def update_test_case(
        db: Session,
        test_case_id: int,
        external_id: Optional[str] = None,
        name: Optional[str] = None,
        description: Optional[str] = None,
        category: Optional[str] = None,
        priority: Optional[str] = None,
        version: Optional[int] = None,
    ) -> TestCase:
        """Update attributes of an existing test case."""
        test_case = TestCaseService.get_test_case(db, test_case_id)
        if external_id is not None:
            test_case.external_id = external_id
        if name is not None:
            test_case.name = name
        if description is not None:
            test_case.description = description
        if category is not None:
            test_case.category = category
        if priority is not None:
            test_case.priority = priority
        if version is not None:
            test_case.version = version
        db.commit()
        db.refresh(test_case)
        return test_case

    @staticmethod
    def delete_test_case(db: Session, test_case_id: int) -> None:
        """Delete a test case and cascade-delete associated test executions."""
        test_case = TestCaseService.get_test_case(db, test_case_id)
        db.delete(test_case)
        db.commit()
