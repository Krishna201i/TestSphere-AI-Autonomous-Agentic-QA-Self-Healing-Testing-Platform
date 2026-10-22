"""
TestSphere-AI — Automated Pipeline API Router.

Start a full pipeline run for a project (or straight from a URL), follow its
progress, and list past runs.  Runs execute in the background; poll
``GET /pipelines/runs/{id}`` for stage-by-stage progress.
"""

import hmac
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field

from backend.api.projects import owned_project
from backend.api.schemas import _check_http_url
from backend.auth import User, actor_for, ensure_owned, get_current_user, scope
from backend.ratelimit import limit_runs
from backend.config import settings
from backend.database.session import get_db
from backend.database.store import Record, Store
from backend.models import PIPELINE_RUNS, PROJECTS
from backend.pipeline import scheduler
from backend.pipeline.runner import active_run, start_run
from backend.services.project_service import ProjectService

router = APIRouter(prefix="/pipelines", tags=["Automated Pipeline"])


class RunRequest(BaseModel):
    project_id: int
    ingest: bool = Field(False, description="Re-ingest the repository even if a blueprint exists")


class QuickRunRequest(BaseModel):
    url: str = Field(..., min_length=1, max_length=1024)
    prompt: Optional[str] = Field(None, max_length=500)
    repo_url: Optional[str] = Field(None, max_length=1024)


def _start(db: Store, user: User, project: Record, ingest: bool = False) -> Record:
    if not project.get("app_url"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="Set the project's app URL before running the pipeline.")
    running = active_run(db, project["id"])
    if running:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail=f"Pipeline #{running['id']} is already {running['status']} for this project.")
    return start_run(db, project, trigger="manual", actor=actor_for(user, None), ingest=ingest)


@router.post("/run", status_code=status.HTTP_202_ACCEPTED)
async def run_project(req: RunRequest, db: Store = Depends(get_db), user: User = Depends(limit_runs)) -> Dict[str, Any]:
    """Run the whole pipeline for one of the caller's projects."""
    return _start(db, user, owned_project(db, user, req.project_id), req.ingest)


@router.post("/quick", status_code=status.HTTP_202_ACCEPTED)
async def quick_run(req: QuickRunRequest, db: Store = Depends(get_db), user: User = Depends(limit_runs)) -> Dict[str, Any]:
    """One click from a URL: reuse the caller's project for that URL (or create one) and run it."""
    try:
        url = _check_http_url(req.url, "URL")
        repo = _check_http_url(req.repo_url, "Repository URL") or None
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    project = db.find_one(PROJECTS, app_url=url, **scope(user))
    if project is None:
        project = ProjectService.create_project(
            db, name=urlparse(url).netloc or url, description="Created from a one-click pipeline run",
            owner_uid=user.uid, app_url=url, repo_url=repo, prompt=req.prompt,
        )
    elif (req.prompt and req.prompt != project.get("prompt")) or (repo and repo != project.get("repo_url")):
        changes = {k: v for k, v in {"prompt": req.prompt, "repo_url": repo}.items() if v}
        project = ProjectService.update_project(db, project["id"], **changes)
    return _start(db, user, project)


@router.get("/runs")
def list_runs(
    project_id: Optional[int] = Query(None),
    limit: int = Query(30, ge=1, le=200),
    db: Store = Depends(get_db),
    user: User = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    """The caller's pipeline runs, newest first."""
    filters: Dict[str, Any] = scope(user)
    if project_id is not None:
        filters["project_id"] = project_id
    return db.find(PIPELINE_RUNS, order_by="id", descending=True, limit=limit, **filters)


@router.get("/runs/{run_id}")
def get_run(run_id: int, db: Store = Depends(get_db), user: User = Depends(get_current_user)) -> Dict[str, Any]:
    return ensure_owned(user, db.get(PIPELINE_RUNS, run_id), "Pipeline run")


@router.post("/scheduler/tick")
async def scheduler_tick(x_cron_secret: Optional[str] = Header(None), db: Store = Depends(get_db)) -> Dict[str, Any]:
    """Start every due scheduled run now.  For an external cron that keeps a
    sleeping host's schedules on time; requires ``X-Cron-Secret: $CRON_SECRET``."""
    if not settings.CRON_SECRET:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="The external scheduler trigger is off: set CRON_SECRET on the server.")
    if not hmac.compare_digest(x_cron_secret or "", settings.CRON_SECRET):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid cron secret.")
    return {"started": await scheduler.tick(db)}
