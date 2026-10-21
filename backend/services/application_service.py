"""
TestSphere-AI — Application Service.

Encapsulates storage and business operations for web applications under test.
"""

from typing import List, Optional

from backend.database.store import Record, Store
from backend.models import APPLICATIONS, PROJECTS, TEST_CASES
from backend.services.exceptions import ApplicationNotFoundError, ProjectNotFoundError

DEFAULT_PROJECT = {"name": "TestSphere Auto QA", "description": "Autonomous agentic QA testing workspace"}


def default_project(db: Store) -> Record:
    """The first project, created on demand."""
    existing = db.find(PROJECTS, limit=1)
    return existing[0] if existing else db.insert(PROJECTS, **DEFAULT_PROJECT)


class ApplicationService:
    """Service layer for Application entities."""

    @staticmethod
    def create_application(
        db: Store, project_id: Optional[int], name: str, base_url: str, description: Optional[str] = None,
    ) -> Record:
        if project_id is not None:
            if not db.get(PROJECTS, project_id):
                raise ProjectNotFoundError(f"Project with ID {project_id} not found")
        else:
            project_id = default_project(db)["id"]
        return db.insert(APPLICATIONS, project_id=project_id, name=name, base_url=base_url, description=description)

    @staticmethod
    def list_applications(db: Store, project_id: Optional[int] = None) -> List[Record]:
        if project_id is not None:
            return db.find(APPLICATIONS, project_id=project_id)
        return db.find(APPLICATIONS)

    @staticmethod
    def get_application(db: Store, application_id: int) -> Record:
        application = db.get(APPLICATIONS, application_id)
        if not application:
            raise ApplicationNotFoundError(f"Application with ID {application_id} not found")
        return application

    @staticmethod
    def update_application(
        db: Store, application_id: int, name: Optional[str] = None,
        base_url: Optional[str] = None, description: Optional[str] = None,
    ) -> Record:
        ApplicationService.get_application(db, application_id)
        fields = {"name": name, "base_url": base_url, "description": description}
        return db.update(APPLICATIONS, application_id, **{k: v for k, v in fields.items() if v is not None})

    @staticmethod
    def delete_application(db: Store, application_id: int) -> None:
        """Delete an application and its test cases and executions."""
        from backend.services.test_case_service import TestCaseService

        ApplicationService.get_application(db, application_id)
        for tc in db.find(TEST_CASES, application_id=application_id):
            TestCaseService.delete_test_case(db, tc["id"])
        db.delete(APPLICATIONS, application_id)
