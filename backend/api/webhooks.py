"""
TestSphere-AI — GitHub webhook: re-run a project's pipeline on every push.

In the GitHub repository: Settings → Webhooks → Add webhook
    Payload URL   <backend>/api/webhooks/github/<project id>
    Content type  application/json
    Secret        the project's webhook secret (shown in its settings)
    Events        Just the push event

Each delivery is verified with the project's own secret (HMAC-SHA256 in
``X-Hub-Signature-256``), so the endpoint needs no sign-in.  Pushes to the
repository's default branch re-ingest the codebase and run the pipeline.
"""

import hashlib
import hmac
import json
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from backend.database.session import get_db
from backend.database.store import Store
from backend.models import PROJECTS
from backend.pipeline.runner import active_run, start_run

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


def _normalize_repo(url: Optional[str]) -> str:
    url = (url or "").strip().lower().rstrip("/")
    return url[:-4] if url.endswith(".git") else url


def signature_for(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


@router.post("/github/{project_id}")
async def github_webhook(
    project_id: int,
    request: Request,
    x_github_event: Optional[str] = Header(None),
    x_hub_signature_256: Optional[str] = Header(None),
    db: Store = Depends(get_db),
) -> Dict[str, Any]:
    project = db.get(PROJECTS, project_id)
    body = await request.body()
    # Same answer for "no such project" and "bad signature": ids are not confirmed
    if project is None or not project.get("webhook_secret") or not hmac.compare_digest(
        signature_for(project["webhook_secret"], body), x_hub_signature_256 or ""
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook signature.")

    if x_github_event == "ping":
        return {"ok": True, "message": f"Webhook connected to project {project['name']}."}
    if x_github_event != "push":
        return {"ignored": f"'{x_github_event}' events do not trigger runs"}

    try:
        payload = json.loads(body or b"{}")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Body is not JSON.") from exc
    repo = payload.get("repository") or {}
    if project.get("repo_url") and _normalize_repo(project["repo_url"]) not in {
        _normalize_repo(repo.get("html_url")), _normalize_repo(repo.get("clone_url"))
    }:
        return {"ignored": f"push is for {repo.get('html_url')}, not this project's repository"}
    branch = str(payload.get("ref", "")).removeprefix("refs/heads/")
    if repo.get("default_branch") and branch != repo["default_branch"]:
        return {"ignored": f"push to '{branch}' (only the default branch '{repo['default_branch']}' triggers runs)"}
    if not project.get("app_url"):
        return {"ignored": "the project has no app URL to test"}
    running = active_run(db, project_id)
    if running:
        return {"ignored": f"pipeline #{running['id']} is already {running['status']}"}

    head = payload.get("head_commit") or {}
    message = (head.get("message") or "").splitlines()[0][:80] if head.get("message") else ""
    detail = f"{(payload.get('after') or '')[:7]} {message}".strip()
    pusher = (payload.get("pusher") or {}).get("name") or "github"
    run = start_run(db, project, trigger="webhook", actor=f"github:{pusher}", detail=detail or None, ingest=True)
    return {"started": run["id"]}
