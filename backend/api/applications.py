"""
TestSphere-AI — Applications API Router.

Provides CRUD endpoints for web applications under test (only the caller's own).
Delegates persistence and business logic to ApplicationService.
"""


from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.api.schemas import (
    ApplicationCreate,
    ApplicationResponse,
    ApplicationUpdate,
)
from backend.auth import User, actor_for, ensure_owned, get_current_user, scope
from backend.database.session import get_db
from backend.database.store import Record, Store
from backend.models import APPLICATIONS, PROJECTS
from backend.services.application_service import ApplicationService
from backend.services.exceptions import ProjectNotFoundError
from backend.services.security_service import record_audit

router = APIRouter(prefix="/applications", tags=["Applications"])


def owned_application(db: Store, user: User, application_id: int) -> Record:
    return ensure_owned(user, db.get(APPLICATIONS, application_id), "Application")


@router.post("", response_model=ApplicationResponse, status_code=status.HTTP_201_CREATED)
def create_application(
    payload: ApplicationCreate,
    db: Store = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Record:
    """Create a new web application under an existing project."""
    ensure_owned(user, db.get(PROJECTS, payload.project_id), "Project")
    try:
        app = ApplicationService.create_application(
            db=db,
            project_id=payload.project_id,
            name=payload.name,
            base_url=payload.base_url,
            description=payload.description,
            owner_uid=user.uid,
        )
    except ProjectNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        ) from None
    record_audit(db, actor=actor_for(user, None), kind="target", level="success", ref=str(app.id),
                 message=f"Target registered: {app.name} ({app.base_url})", owner_uid=user.uid)
    return app


@router.get("", response_model=list[ApplicationResponse])
def list_applications(
    project_id: int | None = Query(None, description="Filter by parent Project ID"),
    db: Store = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Record]:
    """Retrieve the caller's applications, with optional project_id filtering."""
    return ApplicationService.list_applications(db=db, project_id=project_id, **scope(user))


@router.get("/{application_id}", response_model=ApplicationResponse)
def get_application(
    application_id: int,
    db: Store = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Record:
    """Retrieve a single application by ID."""
    return owned_application(db, user, application_id)


@router.put("/{application_id}", response_model=ApplicationResponse)
def update_application(
    application_id: int,
    payload: ApplicationUpdate,
    db: Store = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Record:
    """Update attributes of an application."""
    owned_application(db, user, application_id)
    return ApplicationService.update_application(
        db=db,
        application_id=application_id,
        name=payload.name,
        base_url=payload.base_url,
        description=payload.description,
    )


@router.delete("/{application_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_application(
    application_id: int,
    db: Store = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    """Delete an application and its cascade children."""
    owned_application(db, user, application_id)
    ApplicationService.delete_application(db=db, application_id=application_id)
    return None
