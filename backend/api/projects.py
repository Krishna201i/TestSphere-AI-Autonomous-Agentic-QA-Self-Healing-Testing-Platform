"""
TestSphere-AI — Projects API Router.

Provides CRUD endpoints for testing projects (only the caller's own).
Delegates persistence and business logic to ProjectService.
"""


import asyncio
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from backend import dbsource
from backend.api.schemas import ProjectCreate, ProjectResponse, ProjectUpdate
from backend.auth import User, actor_for, ensure_owned, get_current_user, scope
from backend.database.session import get_db
from backend.database.store import Record, Store, now_iso
from backend.models import PROJECTS
from backend.secretbox import SecretBoxError, encrypt
from backend.services.project_service import PIPELINE_FIELDS, ProjectService
from backend.services.security_service import record_audit

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


# ── The app's database (read-only input) ───────────────────────────────────


class DatabaseLink(BaseModel):
    url: str = Field(..., min_length=10, max_length=1000,
                     description="postgresql://user:password@host:5432/db (a read-only user is best), or sqlite:///path in development")


def _database_view(project: Record) -> dict[str, Any]:
    schema = json.loads(project["db_schema"]) if project.get("db_schema") else None
    return {
        "connected": bool(project.get("db_url")),
        "database": project.get("database"),
        "checked_at": project.get("db_checked_at"),
        "tables": [{"name": t["name"], "rows": t["rows"], "columns": [c["name"] for c in t["columns"]],
                    "foreign_keys": t["foreign_keys"]} for t in (schema or {}).get("tables", [])],
    }


@router.put("/{project_id}/database")
async def link_database(
    project_id: int, payload: DatabaseLink, db: Store = Depends(get_db), user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Connect read-only, read the schema, and keep the URL encrypted for pipeline runs."""
    owned_project(db, user, project_id)

    def read() -> dict[str, Any]:
        with dbsource.Database(payload.url) as conn:
            return conn.schema()

    try:
        schema = await asyncio.to_thread(read)
        sealed = encrypt(payload.url.strip())
    except dbsource.DatabaseError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except SecretBoxError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    row = db.update(PROJECTS, project_id, db_url=sealed, database=schema["database"], db_schema=json.dumps(schema),
                    db_checked_at=now_iso())
    record_audit(db, actor=actor_for(user, "dev_active"), kind="database", ref=str(project_id), owner_uid=user.uid,
                 message=f"Database {schema['database']} linked to {row['name']}: {len(schema['tables'])} table(s)")
    return _database_view(row)


@router.get("/{project_id}/database")
def get_database(project_id: int, db: Store = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    """The linked database and its schema as last read (the URL is never returned)."""
    return _database_view(owned_project(db, user, project_id))


@router.delete("/{project_id}/database", status_code=status.HTTP_204_NO_CONTENT)
def unlink_database(project_id: int, db: Store = Depends(get_db), user: User = Depends(get_current_user)) -> None:
    owned_project(db, user, project_id)
    db.update(PROJECTS, project_id, db_url=None, database=None, db_schema=None, db_checked_at=None)
