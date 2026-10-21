"""
TestSphere-AI — Project Service.

Encapsulates storage and business operations for projects.
"""

from typing import List, Optional

from backend.database.store import Record, Store
from backend.models import APPLICATIONS, PROJECTS
from backend.services.exceptions import ProjectNotFoundError


class ProjectService:
    """Service layer for Project entities."""

    @staticmethod
    def create_project(db: Store, name: str, description: Optional[str] = None) -> Record:
        return db.insert(PROJECTS, name=name, description=description)

    @staticmethod
    def list_projects(db: Store) -> List[Record]:
        return db.find(PROJECTS)

    @staticmethod
    def get_project(db: Store, project_id: int) -> Record:
        project = db.get(PROJECTS, project_id)
        if not project:
            raise ProjectNotFoundError(f"Project with ID {project_id} not found")
        return project

    @staticmethod
    def update_project(
        db: Store, project_id: int, name: Optional[str] = None, description: Optional[str] = None,
    ) -> Record:
        ProjectService.get_project(db, project_id)
        changes = {k: v for k, v in {"name": name, "description": description}.items() if v is not None}
        return db.update(PROJECTS, project_id, **changes)

    @staticmethod
    def delete_project(db: Store, project_id: int) -> None:
        """Delete a project and, like the old foreign-key cascade, everything under it."""
        from backend.services.application_service import ApplicationService

        ProjectService.get_project(db, project_id)
        for app in db.find(APPLICATIONS, project_id=project_id):
            ApplicationService.delete_application(db, app["id"])
        db.delete(PROJECTS, project_id)
