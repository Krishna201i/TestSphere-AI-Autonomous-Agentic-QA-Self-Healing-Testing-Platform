"""
TestSphere-AI — Projects API Router.

Provides CRUD endpoints for testing projects (only the caller's own).
Delegates persistence and business logic to ProjectService.
"""


from fastapi import APIRouter, Depends, status

from backend.api.schemas import ProjectCreate, ProjectResponse, ProjectUpdate
from backend.auth import User, ensure_owned, get_current_user, scope
from backend.database.session import get_db
from backend.database.store import Record, Store
from backend.models import PROJECTS
from backend.services.project_service import PIPELINE_FIELDS, ProjectService

router = APIRouter(prefix="/projects", tags=["Projects"])


def owned_project(db: Store, user: User, project_id: int) -> Record:
    return ensure_owned(user, db.get(PROJECTS, project_id), "Project")


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectCreate, db: Store = Depends(get_db), user: User = Depends(get_current_user),
) -> Record:
    """Create a new testing project."""
    return ProjectService.create_project(
        db=db,
        name=payload.name,
        description=payload.description,
        owner_uid=user.uid,
        **payload.model_dump(include=set(PIPELINE_FIELDS)),
    )


@router.get("", response_model=list[ProjectResponse])
def list_projects(db: Store = Depends(get_db), user: User = Depends(get_current_user)) -> list[Record]:
    """Retrieve the caller's testing projects."""
    return ProjectService.list_projects(db, **scope(user))


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(project_id: int, db: Store = Depends(get_db), user: User = Depends(get_current_user)) -> Record:
    """Retrieve a project by its primary key."""
    return owned_project(db, user, project_id)


@router.put("/{project_id}", response_model=ProjectResponse)
def update_project(
    project_id: int,
    payload: ProjectUpdate,
    db: Store = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Record:
    """Update attributes of an existing project (pipeline fields sent as null are cleared)."""
    owned_project(db, user, project_id)
    return ProjectService.update_project(
        db=db,
        project_id=project_id,
        name=payload.name,
        description=payload.description,
        **payload.model_dump(include=set(PIPELINE_FIELDS), exclude_unset=True),
    )


@router.post("/{project_id}/webhook-secret", response_model=ProjectResponse)
def rotate_webhook_secret(project_id: int, db: Store = Depends(get_db), user: User = Depends(get_current_user)) -> Record:
    """Generate a new GitHub webhook secret (the old one stops working)."""
    owned_project(db, user, project_id)
    return ProjectService.rotate_webhook_secret(db, project_id)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: int, db: Store = Depends(get_db), user: User = Depends(get_current_user)) -> None:
    """Delete a project and cascade delete its applications, test cases and pipeline runs."""
    owned_project(db, user, project_id)
    ProjectService.delete_project(db=db, project_id=project_id)
    return None
