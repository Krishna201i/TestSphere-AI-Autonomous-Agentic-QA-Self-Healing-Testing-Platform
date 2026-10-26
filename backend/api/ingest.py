"""
TestSphere-AI — Codebase Ingestion API Router (module 5.1).

POST a public Git URL (or, in development, a local folder path) and get back
a project blueprint: languages, frameworks, dependencies, test suites, entry
points, HTTP routes and static risks.  Blueprints are stored and audited.
The automated pipeline reuses ``ingest_source`` and ``save_blueprint``.
"""

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from backend.auth import User, actor_for, ensure_owned, get_current_user, scope
from backend.config import git_hosts, settings
from backend.database.session import get_db
from backend.database.store import Record, Store
from backend.models import BLUEPRINTS
from backend.ratelimit import limit_runs
from backend.services.security_service import record_audit, save_scan
from ingestion import (
    SourceError,
    as_findings,
    check_dependencies,
    pinned_packages,
    analyze_repo,
    clone,
    is_git_url,
    repo_name,
    resolve_local,
)

router = APIRouter(prefix="/ingest", tags=["Codebase Ingestion"])


class IngestRequest(BaseModel):
    source: str
    actor: str = "dev_active"


def _git_hosts() -> frozenset:
    return git_hosts()


def _summary(row: Record) -> dict[str, Any]:
    data = json.loads(row.data)
    langs = data.get("languages", {})
    return {
        "id": row.id,
        "name": row.name,
        "source": row.source,
        "created_at": data.get("analyzed_at"),
        "files_total": data.get("files_total", 0),
        "primary_language": max(langs, key=lambda k: langs[k]["lines"]) if langs else None,
        "frameworks": data.get("frameworks", []),
        "routes": len(data.get("routes", [])),
        "risks": len(data.get("risks", [])),
    }


def ingest_source(source: str) -> dict[str, Any]:
    """Clone (or resolve) and analyze *source*; raises ``SourceError`` with a readable cause."""
    if is_git_url(source):
        root = clone(source, Path(settings.INGEST_WORKSPACE), _git_hosts())
    elif settings.INGEST_ALLOW_LOCAL_PATHS:
        root = resolve_local(source)
    else:
        raise SourceError("Local folder paths are disabled on this server; use a public https Git URL.")
    blueprint = analyze_repo(root, source=source, name=repo_name(source)).model_dump(mode="json")
    if settings.DEPENDENCY_SCAN:
        packages = pinned_packages(root)
        blueprint["dependency_scan"] = check_dependencies(packages) | {"packages": packages[:200]}
    return blueprint


def record_dependency_findings(db: Store, source: str, blueprint: dict[str, Any], owner_uid: str | None) -> int:
    """Vulnerable dependencies as security findings of the repository; returns how many are open."""
    scan = blueprint.get("dependency_scan")
    if not scan or scan.get("error"):
        return 0  # unknown is not "fixed": leave earlier findings as they are
    saved = save_scan(db, source, as_findings(scan, source), owner_uid=owner_uid)
    return len(saved["current"])


def save_blueprint(
    db: Store, source: str, blueprint: dict[str, Any], *, actor: str, owner_uid: str | None,
    project_id: int | None = None,
) -> Record:
    """Store a blueprint and audit it."""
    row = db.insert(BLUEPRINTS, source=source, name=blueprint["name"], data=json.dumps(blueprint),
                    owner_uid=owner_uid, project_id=project_id)
    summary = _summary(row)
    vulnerable = record_dependency_findings(db, source, blueprint, owner_uid)
    record_audit(
        db, actor=actor, kind="ingest", level="warn" if summary["risks"] or vulnerable else "success", ref=str(row.id),
        message=f"Ingested {row.name}: {summary['files_total']} files, {summary['primary_language'] or 'no code'}, "
                f"{summary['routes']} route(s), {summary['risks']} risk(s)"
                + (f", {vulnerable} known-vulnerable dependency advisories" if vulnerable else ""),
        owner_uid=owner_uid,
    )
    return row


@router.post("", status_code=status.HTTP_201_CREATED)
def ingest(req: IngestRequest, db: Store = Depends(get_db), user: User = Depends(limit_runs)) -> dict[str, Any]:
    """Fetch and analyze a codebase. Runs in a worker thread (cloning can take a while)."""
    source = req.source.strip()
    actor = actor_for(user, req.actor)
    if not source:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Source is required.")
    try:
        blueprint = ingest_source(source)
    except (SourceError, NotADirectoryError) as exc:
        record_audit(db, actor=actor, kind="ingest", level="error", message=f"Ingestion failed for {source}: {exc}",
                     owner_uid=user.uid)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    row = save_blueprint(db, source, blueprint, actor=actor, owner_uid=user.uid)
    return {"id": row.id, **blueprint}


@router.get("")
def list_blueprints(db: Store = Depends(get_db), user: User = Depends(get_current_user)) -> list[dict[str, Any]]:
    rows = db.find(BLUEPRINTS, order_by="id", descending=True, limit=50, **scope(user))
    return [_summary(r) for r in rows]


@router.get("/{blueprint_id}")
def get_blueprint(blueprint_id: int, db: Store = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    row = ensure_owned(user, db.get(BLUEPRINTS, blueprint_id), "Blueprint")
    return {"id": row.id, **json.loads(row.data)}
