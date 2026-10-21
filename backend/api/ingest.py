"""
TestSphere-AI — Codebase Ingestion API Router (module 5.1).

POST a public Git URL (or, in development, a local folder path) and get back
a project blueprint: languages, frameworks, dependencies, test suites, entry
points, HTTP routes and static risks.  Blueprints are stored and audited.
"""

import json
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.config import settings
from backend.database.session import get_db
from backend.models.security import CodebaseBlueprint
from backend.services.security_service import record_audit
from ingestion import SourceError, analyze_repo, clone, is_git_url, repo_name, resolve_local

router = APIRouter(prefix="/ingest", tags=["Codebase Ingestion"])


class IngestRequest(BaseModel):
    source: str
    actor: str = "dev_active"


def _git_hosts() -> frozenset:
    return frozenset(h.strip().lower() for h in settings.INGEST_GIT_HOSTS.split(",") if h.strip())


def _summary(row: CodebaseBlueprint) -> Dict[str, Any]:
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


def _ingest(source: str) -> Dict[str, Any]:
    if is_git_url(source):
        root = clone(source, Path(settings.INGEST_WORKSPACE), _git_hosts())
    elif settings.INGEST_ALLOW_LOCAL_PATHS:
        root = resolve_local(source)
    else:
        raise SourceError("Local folder paths are disabled on this server; use a public https Git URL.")
    return analyze_repo(root, source=source, name=repo_name(source)).model_dump(mode="json")


@router.post("", status_code=status.HTTP_201_CREATED)
def ingest(req: IngestRequest, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Fetch and analyze a codebase. Runs in a worker thread (cloning can take a while)."""
    source = req.source.strip()
    if not source:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Source is required.")
    try:
        blueprint = _ingest(source)
    except (SourceError, NotADirectoryError) as exc:
        record_audit(db, actor=req.actor, kind="ingest", level="error", message=f"Ingestion failed for {source}: {exc}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    row = CodebaseBlueprint(source=source, name=blueprint["name"], data=json.dumps(blueprint))
    db.add(row)
    db.commit()
    db.refresh(row)
    summary = _summary(row)
    record_audit(
        db, actor=req.actor, kind="ingest", level="warn" if summary["risks"] else "success", ref=str(row.id),
        message=f"Ingested {row.name}: {summary['files_total']} files, {summary['primary_language'] or 'no code'}, "
                f"{summary['routes']} route(s), {summary['risks']} risk(s)",
    )
    return {"id": row.id, **blueprint}


@router.get("")
def list_blueprints(db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    rows = db.query(CodebaseBlueprint).order_by(CodebaseBlueprint.id.desc()).limit(50).all()
    return [_summary(r) for r in rows]


@router.get("/{blueprint_id}")
def get_blueprint(blueprint_id: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    row = db.query(CodebaseBlueprint).filter(CodebaseBlueprint.id == blueprint_id).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Blueprint not found")
    return {"id": row.id, **json.loads(row.data)}
