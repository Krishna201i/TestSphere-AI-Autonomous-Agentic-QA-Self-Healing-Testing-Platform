"""
TestSphere-AI — Project Service.

Encapsulates storage and business operations for projects.

A project is also the unit of the automated pipeline: ``app_url`` is the live
site it tests, ``repo_url`` the codebase it ingests, ``schedule_minutes`` how
often it re-runs, and ``webhook_secret`` signs GitHub push webhooks.
"""

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from backend.database.store import Record, Store
from backend.models import APPLICATIONS, PIPELINE_RUNS, PROJECTS
from backend.services.exceptions import ProjectNotFoundError

# Fields a client may set on a project besides name/description
PIPELINE_FIELDS = ("app_url", "repo_url", "prompt", "schedule_minutes")


def new_webhook_secret() -> str:
    return secrets.token_hex(20)


def next_run_after(minutes: int | None, now: datetime | None = None) -> str | None:
    if not minutes:
        return None
    return ((now or datetime.now(UTC)) + timedelta(minutes=minutes)).isoformat()


class ProjectService:
    """Service layer for Project entities."""

    @staticmethod
    def create_project(
        db: Store, name: str, description: str | None = None, owner_uid: str | None = None, **pipeline: Any,
    ) -> Record:
        fields = {k: pipeline.get(k) for k in PIPELINE_FIELDS}
        return db.insert(
            PROJECTS, name=name, description=description, owner_uid=owner_uid, **fields,
            next_run_at=next_run_after(fields["schedule_minutes"]), webhook_secret=new_webhook_secret(),
        )

    @staticmethod
    def list_projects(db: Store, **filters: Any) -> list[Record]:
        return db.find(PROJECTS, **filters)

    @staticmethod
    def get_project(db: Store, project_id: int) -> Record:
        project = db.get(PROJECTS, project_id)
        if not project:
            raise ProjectNotFoundError(f"Project with ID {project_id} not found")
        return project

    @staticmethod
    def update_project(
        db: Store, project_id: int, name: str | None = None, description: str | None = None,
        **pipeline: Any,
    ) -> Record:
        """Update a project.  For pipeline fields, an explicit ``None`` or empty
        string clears the value (e.g. turns the schedule off); omitted keys are kept."""
        ProjectService.get_project(db, project_id)
        changes = {k: v for k, v in {"name": name, "description": description}.items() if v is not None}
        for key in PIPELINE_FIELDS:
            if key in pipeline:
                changes[key] = pipeline[key] or None
        if "schedule_minutes" in changes:
            changes["next_run_at"] = next_run_after(changes["schedule_minutes"])
        return db.update(PROJECTS, project_id, **changes)

    @staticmethod
    def rotate_webhook_secret(db: Store, project_id: int) -> Record:
        ProjectService.get_project(db, project_id)
        return db.update(PROJECTS, project_id, webhook_secret=new_webhook_secret())

    @staticmethod
    def delete_project(db: Store, project_id: int) -> None:
        """Delete a project and, like the old foreign-key cascade, everything under it."""
        from backend.services.application_service import ApplicationService

        ProjectService.get_project(db, project_id)
        for app in db.find(APPLICATIONS, project_id=project_id):
            ApplicationService.delete_application(db, app["id"])
        db.delete_where(PIPELINE_RUNS, project_id=project_id)
        db.delete(PROJECTS, project_id)
