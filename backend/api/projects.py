"""
TestSphere-AI — Projects API Router.

Provides CRUD endpoints for testing projects.
Delegates persistence and business logic to ProjectService.
"""

from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.api.schemas import ProjectCreate, ProjectResponse, ProjectUpdate
from backend.database.session import get_db
from backend.models.project import Project
from backend.services.exceptions import ProjectNotFoundError
from backend.services.project_service import ProjectService

router = APIRouter(prefix="/projects", tags=["Projects"])


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db)) -> Project:
    """Create a new testing project."""
    return ProjectService.create_project(
        db=db,
        name=payload.name,
        description=payload.description,
    )


@router.get("", response_model=List[ProjectResponse])
def list_projects(db: Session = Depends(get_db)) -> List[Project]:
    """Retrieve all testing projects."""
    return ProjectService.list_projects(db=db)


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(project_id: int, db: Session = Depends(get_db)) -> Project:
    """Retrieve a project by its primary key."""
    try:
        return ProjectService.get_project(db=db, project_id=project_id)
    except ProjectNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )


@router.put("/{project_id}", response_model=ProjectResponse)
def update_project(
    project_id: int,
    payload: ProjectUpdate,
    db: Session = Depends(get_db),
) -> Project:
    """Update attributes of an existing project."""
    try:
        return ProjectService.update_project(
            db=db,
            project_id=project_id,
            name=payload.name,
            description=payload.description,
        )
    except ProjectNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: int, db: Session = Depends(get_db)) -> None:
    """Delete a project and cascade delete its associated applications and test cases."""
    try:
        ProjectService.delete_project(db=db, project_id=project_id)
    except ProjectNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    return None
