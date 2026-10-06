"""
TestSphere-AI — Project Service.

Encapsulates database and business operations for projects.
"""

from typing import List, Optional
from sqlalchemy.orm import Session

from backend.models.project import Project
from backend.services.exceptions import ProjectNotFoundError


class ProjectService:
    """Service handling project persistence and lifecycle operations."""

    @staticmethod
    def create_project(
        db: Session,
        name: str,
        description: Optional[str] = None,
    ) -> Project:
        """Create and persist a new testing project."""
        project = Project(
            name=name,
            description=description,
        )
        db.add(project)
        db.commit()
        db.refresh(project)
        return project

    @staticmethod
    def list_projects(db: Session) -> List[Project]:
        """Retrieve all testing projects."""
        return db.query(Project).all()

    @staticmethod
    def get_project(db: Session, project_id: int) -> Project:
        """Retrieve a project by its primary key or raise ProjectNotFoundError."""
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise ProjectNotFoundError(f"Project with ID {project_id} not found")
        return project

    @staticmethod
    def update_project(
        db: Session,
        project_id: int,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Project:
        """Update attributes of an existing project."""
        project = ProjectService.get_project(db, project_id)
        if name is not None:
            project.name = name
        if description is not None:
            project.description = description
        db.commit()
        db.refresh(project)
        return project

    @staticmethod
    def delete_project(db: Session, project_id: int) -> None:
        """Delete a project and cascade-delete associated applications."""
        project = ProjectService.get_project(db, project_id)
        db.delete(project)
        db.commit()
