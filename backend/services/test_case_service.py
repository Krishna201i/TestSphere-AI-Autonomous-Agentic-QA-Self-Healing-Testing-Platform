"""
TestSphere-AI — Test Case Service.

Encapsulates storage operations for test cases.
Does not import or modify Member 1 TestCase AI logic.
"""

from typing import List, Optional

from backend.database.store import Record, Store
from backend.models import APPLICATIONS, TEST_CASES, TEST_EXECUTIONS
from backend.services.exceptions import ApplicationNotFoundError, TestCaseNotFoundError


class TestCaseService:
    """Service layer for TestCase entities."""

    @staticmethod
    def create_test_case(
        db: Store, application_id: int, external_id: Optional[str], name: str, description: Optional[str] = None,
        category: Optional[str] = None, priority: Optional[str] = None, version: int = 1,
    ) -> Record:
        if not db.get(APPLICATIONS, application_id):
            raise ApplicationNotFoundError(f"Application with ID {application_id} not found")
        return db.insert(
            TEST_CASES, application_id=application_id, external_id=external_id, name=name,
            description=description, category=category, priority=priority, version=version,
        )

    @staticmethod
    def list_test_cases(db: Store, application_id: Optional[int] = None) -> List[Record]:
        if application_id is not None:
            return db.find(TEST_CASES, application_id=application_id)
        return db.find(TEST_CASES)

    @staticmethod
    def get_test_case(db: Store, test_case_id: int) -> Record:
        test_case = db.get(TEST_CASES, test_case_id)
        if not test_case:
            raise TestCaseNotFoundError(f"Test case with ID {test_case_id} not found")
        return test_case

    @staticmethod
    def update_test_case(
        db: Store, test_case_id: int, external_id: Optional[str] = None, name: Optional[str] = None,
        description: Optional[str] = None, category: Optional[str] = None, priority: Optional[str] = None,
        version: Optional[int] = None,
    ) -> Record:
        TestCaseService.get_test_case(db, test_case_id)
        fields = {"external_id": external_id, "name": name, "description": description,
                  "category": category, "priority": priority, "version": version}
        return db.update(TEST_CASES, test_case_id, **{k: v for k, v in fields.items() if v is not None})

    @staticmethod
    def delete_test_case(db: Store, test_case_id: int) -> None:
        """Delete a test case and its executions."""
        TestCaseService.get_test_case(db, test_case_id)
        db.delete_where(TEST_EXECUTIONS, test_case_id=test_case_id)
        db.delete(TEST_CASES, test_case_id)
