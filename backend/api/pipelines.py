"""
TestSphere-AI — Automated Pipeline API Router.

Start a full pipeline run for a project (or straight from a URL), follow its
progress, and list past runs.  Runs execute in the background; poll
``GET /pipelines/runs/{id}`` for stage-by-stage progress.
"""

import hmac
import html
import re
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from backend.api.projects import owned_project
from backend.api.schemas import _check_http_url
from backend.auth import User, actor_for, ensure_owned, get_current_user, scope
from backend.config import settings
from backend.database.session import get_db
from backend.database.store import Record, Store
from backend.models import DEPLOYMENTS, PIPELINE_RUNS, PROJECTS
from backend.pipeline import deploy, scheduler
from backend.pipeline.runner import active_run, cancel_run, start_run
from backend.ratelimit import limit_runs
from backend.services.project_service import ProjectService

router = APIRouter(prefix="/pipelines", tags=["Automated Pipeline"])


class RunRequest(BaseModel):
    project_id: int
    ingest: bool = Field(False, description="Re-ingest the repository even if a blueprint exists")


class QuickRunRequest(BaseModel):
    url: str = Field(..., min_length=1, max_length=1024)
    prompt: str | None = Field(None, max_length=500)
    repo_url: str | None = Field(None, max_length=1024)


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
async def run_project(req: RunRequest, db: Store = Depends(get_db), user: User = Depends(limit_runs)) -> dict[str, Any]:
    """Run the whole pipeline for one of the caller's projects."""
    return _start(db, user, owned_project(db, user, req.project_id), req.ingest)


@router.post("/quick", status_code=status.HTTP_202_ACCEPTED)
async def quick_run(req: QuickRunRequest, db: Store = Depends(get_db), user: User = Depends(limit_runs)) -> dict[str, Any]:
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
    project_id: int | None = Query(None),
    limit: int = Query(30, ge=1, le=200),
    db: Store = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """The caller's pipeline runs, newest first."""
    filters: dict[str, Any] = scope(user)
    if project_id is not None:
        filters["project_id"] = project_id
    return db.find(PIPELINE_RUNS, order_by="id", descending=True, limit=limit, **filters)


@router.get("/runs/{run_id}")
def get_run(run_id: int, db: Store = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    return ensure_owned(user, db.get(PIPELINE_RUNS, run_id), "Pipeline run")


_XML_INVALID = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")


def _xml_text(value: Any) -> str:
    """Escaped XML text/attribute value; drops characters XML 1.0 cannot hold (e.g. ANSI escapes)."""
    return html.escape(_XML_INVALID.sub("", str(value)), quote=True)


def _tag(name: str, attrs: dict[str, Any], body: str | None = None) -> str:
    attr = "".join(f' {k}="{_xml_text(v)}"' for k, v in attrs.items())
    return f"<{name}{attr}/>" if body is None else f"<{name}{attr}>{body}</{name}>"


def junit_xml(run: dict[str, Any]) -> str:
    """The run's tests as a JUnit XML report (what CI systems and test dashboards read).

    Written as escaped text: nothing is parsed, so no XML library is needed."""
    tests = run.get("tests") or []
    cases = []
    for t in tests:
        error = (t.get("error") or "").strip()
        first_line = error.splitlines()[0][:300] if error else ""
        inner = ""
        if t.get("status") == "FAILED" and t.get("quarantined"):
            inner += _tag("skipped", {"message": f"quarantined: {first_line}"})
        elif t.get("status") == "FAILED":
            inner += _tag("failure", {"message": first_line or "failed"}, _xml_text(error))
        notes = [n for n, on in (("self-healed", t.get("healed")), ("flaky", t.get("flaky"))) if on]
        if notes:
            inner += _tag("system-out", {}, _xml_text(f"{', '.join(notes)} (execution #{t.get('execution_id')})"))
        cases.append(_tag("testcase", {"classname": t.get("category") or "saved", "name": t.get("name", "")}, inner))
    suite = _tag("testsuite", {
        "name": f"TestSphere: {run.get('project_name', 'project')}",
        "tests": len(tests),
        "failures": sum(1 for t in tests if t.get("status") == "FAILED" and not t.get("quarantined")),
        "skipped": sum(1 for t in tests if t.get("status") == "FAILED" and t.get("quarantined")),
        "timestamp": run.get("started_at") or run.get("created_at") or "",
        "id": run.get("id"),
    }, "".join(cases))
    return f"<?xml version='1.0' encoding='utf-8'?>\n<testsuites>{suite}</testsuites>"




@router.post("/runs/{run_id}/cancel", status_code=status.HTTP_200_OK)
def cancel_pipeline_run(
    run_id: int, db: Store = Depends(get_db), user: User = Depends(get_current_user)
) -> dict[str, Any]:
    """Cancel a queued or running pipeline run."""
    run = ensure_owned(user, db.get(PIPELINE_RUNS, run_id), "Pipeline run")
    if run["status"] not in ("queued", "running"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Run #{run_id} is already {run['status']} \u2014 cannot cancel.",
        )
    return cancel_run(db, run)


@router.get("/runs/{run_id}/junit")
def get_run_junit(run_id: int, db: Store = Depends(get_db), user: User = Depends(get_current_user)) -> Response:
    run = ensure_owned(user, db.get(PIPELINE_RUNS, run_id), "Pipeline run")
    return Response(content=junit_xml(run), media_type="application/xml",
                    headers={"Content-Disposition": f'attachment; filename="testsphere-run-{run_id}.xml"'})


@router.post("/projects/{project_id}/deploy", status_code=status.HTTP_201_CREATED)
async def deploy_project(project_id: int, db: Store = Depends(get_db), user: User = Depends(limit_runs)) -> dict[str, Any]:
    """Deploy the project through its hook, verify health and smoke tests, roll back on failure."""
    project = owned_project(db, user, project_id)
    if not project.get("deploy_hook_url"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="Add a deploy hook to the project first (Autopilot → Settings).")
    if deploy.active_deployment(db, project_id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A deployment of this project is already running.")
    return deploy.start_deployment(db, project, actor=actor_for(user, "dev_active"))


@router.get("/deployments")
def list_deployments(
    project_id: int | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    db: Store = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    filters: dict[str, Any] = scope(user)
    if project_id is not None:
        filters["project_id"] = project_id
    return db.find(DEPLOYMENTS, order_by="id", descending=True, limit=limit, **filters)


@router.get("/deployments/{deployment_id}")
def get_deployment(deployment_id: int, db: Store = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    return ensure_owned(user, db.get(DEPLOYMENTS, deployment_id), "Deployment")


@router.post("/scheduler/tick")
async def scheduler_tick(x_cron_secret: str | None = Header(None), db: Store = Depends(get_db)) -> dict[str, Any]:
    """Start every due scheduled run now.  For an external cron that keeps a
    sleeping host's schedules on time; requires ``X-Cron-Secret: $CRON_SECRET``."""
    if not settings.CRON_SECRET:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="The external scheduler trigger is off: set CRON_SECRET on the server.")
    if not hmac.compare_digest(x_cron_secret or "", settings.CRON_SECRET):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid cron secret.")
    return {"started": await scheduler.tick(db)}
