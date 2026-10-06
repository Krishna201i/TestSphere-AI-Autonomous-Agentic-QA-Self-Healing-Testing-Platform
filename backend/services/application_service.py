"""
TestSphere-AI — Application Service.

Encapsulates database and business operations for web applications under test.
"""

from typing import List, Optional
from sqlalchemy.orm import Session

from backend.models.application import Application
from backend.models.project import Project
from backend.services.exceptions import ApplicationNotFoundError, ProjectNotFoundError


class ApplicationService:
    """Service handling application persistence and querying."""

    @staticmethod
    def create_application(
        db: Session,
        project_id: int,
        name: str,
        base_url: str,
        description: Optional[str] = None,
    ) -> Application:
        """Create and persist a new application after validating parent project existence."""
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise ProjectNotFoundError(f"Project with ID {project_id} not found")

        application = Application(
            project_id=project_id,
            name=name,
            base_url=base_url,
            description=description,
        )
        db.add(application)
        db.commit()
        db.refresh(application)
        return application

    @staticmethod
    def list_applications(
        db: Session,
        project_id: Optional[int] = None,
    ) -> List[Application]:
        """Retrieve applications, optionally filtered by project_id."""
        query = db.query(Application)
        if project_id is not None:
            query = query.filter(Application.project_id == project_id)
        return query.all()

    @staticmethod
    def get_application(db: Session, application_id: int) -> Application:
        """Retrieve an application by its primary key or raise ApplicationNotFoundError."""
        application = db.query(Application).filter(Application.id == application_id).first()
        if not application:
            raise ApplicationNotFoundError(f"Application with ID {application_id} not found")
        return application

    @staticmethod
    def update_application(
        db: Session,
        application_id: int,
        name: Optional[str] = None,
        base_url: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Application:
        """Update attributes of an existing application."""
        application = ApplicationService.get_application(db, application_id)
        if name is not None:
            application.name = name
        if base_url is not None:
            application.base_url = base_url
        if description is not None:
            application.description = description
        db.commit()
        db.refresh(application)
        return application

    @staticmethod
    def delete_application(db: Session, application_id: int) -> None:
        """Delete an application and cascade-delete associated test cases."""
        application = ApplicationService.get_application(db, application_id)
        db.delete(application)
        db.commit()
