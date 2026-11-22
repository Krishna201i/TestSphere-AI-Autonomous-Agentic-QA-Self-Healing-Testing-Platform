"""
TestSphere-AI — Application Service.

Encapsulates storage and business operations for web applications under test.
"""

from typing import Any

from backend.database.store import Record, Store
from backend.models import APPLICATIONS, PROJECTS, TEST_CASES
from backend.services.exceptions import ApplicationNotFoundError, ProjectNotFoundError

DEFAULT_PROJECT = {"name": "TestSphere Auto QA", "description": "Autonomous agentic QA testing workspace"}


def default_project(db: Store, owner_uid: str | None = None) -> Record:
    """The user's first project (any user's when *owner_uid* is None), created on demand."""
    filters = {"owner_uid": owner_uid} if owner_uid else {}
    existing = db.find(PROJECTS, limit=1, **filters)
    if existing:
        return existing[0]
    from backend.services.project_service import ProjectService

    return ProjectService.create_project(db, owner_uid=owner_uid, **DEFAULT_PROJECT)


class ApplicationService:
    """Service layer for Application entities."""

    @staticmethod
    def create_application(
        db: Store, project_id: int | None, name: str, base_url: str, description: str | None = None,
        owner_uid: str | None = None,
    ) -> Record:
        if project_id is not None:
            if not db.get(PROJECTS, project_id):
                raise ProjectNotFoundError(f"Project with ID {project_id} not found")
        else:
            project_id = default_project(db, owner_uid)["id"]
        return db.insert(APPLICATIONS, project_id=project_id, name=name, base_url=base_url, description=description,
                         owner_uid=owner_uid)

    @staticmethod
    def list_applications(db: Store, project_id: int | None = None, **filters: Any) -> list[Record]:
        if project_id is not None:
            filters["project_id"] = project_id
        return db.find(APPLICATIONS, **filters)

    @staticmethod
    def get_application(db: Store, application_id: int) -> Record:
        application = db.get(APPLICATIONS, application_id)
        if not application:
            raise ApplicationNotFoundError(f"Application with ID {application_id} not found")
        return application

    @staticmethod
    def update_application(
        db: Store, application_id: int, name: str | None = None,
        base_url: str | None = None, description: str | None = None,
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
