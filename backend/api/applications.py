"""
TestSphere-AI — Applications API Router.

Provides CRUD endpoints for web applications under test.
Delegates persistence and business logic to ApplicationService.
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.api.schemas import (
    ApplicationCreate,
    ApplicationResponse,
    ApplicationUpdate,
)
from backend.database.session import get_db
from backend.database.store import Record, Store
from backend.services.application_service import ApplicationService
from backend.services.security_service import record_audit
from backend.services.exceptions import (
    ApplicationNotFoundError,
    ProjectNotFoundError,
)

router = APIRouter(prefix="/applications", tags=["Applications"])


@router.post("", response_model=ApplicationResponse, status_code=status.HTTP_201_CREATED)
def create_application(
    payload: ApplicationCreate,
    db: Store = Depends(get_db),
) -> Record:
    """Create a new web application under an existing project."""
    try:
        app = ApplicationService.create_application(
            db=db,
            project_id=payload.project_id,
            name=payload.name,
            base_url=payload.base_url,
            description=payload.description,
        )
    except ProjectNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    record_audit(db, actor="dev_active", kind="target", level="success", ref=str(app.id),
                 message=f"Target registered: {app.name} ({app.base_url})")
    return app


@router.get("", response_model=List[ApplicationResponse])
def list_applications(
    project_id: Optional[int] = Query(None, description="Filter by parent Project ID"),
    db: Store = Depends(get_db),
) -> List[Record]:
    """Retrieve all applications, with optional project_id filtering."""
    return ApplicationService.list_applications(db=db, project_id=project_id)


@router.get("/{application_id}", response_model=ApplicationResponse)
def get_application(
    application_id: int,
    db: Store = Depends(get_db),
) -> Record:
    """Retrieve a single application by ID."""
    try:
        return ApplicationService.get_application(db=db, application_id=application_id)
    except ApplicationNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Application not found",
        )


@router.put("/{application_id}", response_model=ApplicationResponse)
def update_application(
    application_id: int,
    payload: ApplicationUpdate,
    db: Store = Depends(get_db),
) -> Record:
    """Update attributes of an application."""
    try:
        return ApplicationService.update_application(
            db=db,
            application_id=application_id,
            name=payload.name,
            base_url=payload.base_url,
            description=payload.description,
        )
    except ApplicationNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Application not found",
        )


@router.delete("/{application_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_application(
    application_id: int,
    db: Store = Depends(get_db),
) -> None:
    """Delete an application and its cascade children."""
    try:
        ApplicationService.delete_application(db=db, application_id=application_id)
    except ApplicationNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Application not found",
        )
    return None
