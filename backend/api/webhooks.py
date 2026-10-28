"""
TestSphere-AI — GitHub and GitLab webhooks: re-run a project's pipeline on every push.

In the GitHub repository: Settings → Webhooks → Add webhook
    Payload URL   <backend>/api/webhooks/github/<project id>
    Content type  application/json
    Secret        the project's webhook secret (shown in its settings)
    Events        Just the push event

Each delivery is verified with the project's own secret (HMAC-SHA256 in
``X-Hub-Signature-256``), so the endpoint needs no sign-in.  Pushes to the
repository's default branch re-ingest the codebase and run the pipeline.

GitLab: Settings → Webhooks, URL ``<backend>/api/webhooks/gitlab/<project id>``,
Secret token = the same project webhook secret (GitLab sends it as-is in
``X-Gitlab-Token``), trigger "Push events".
"""

import hashlib
import hmac
import json
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from backend.database.session import get_db
from backend.database.store import Store
from backend.models import PROJECTS
from backend.pipeline.runner import active_run, start_run

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


def _normalize_repo(url: str | None) -> str:
    url = (url or "").strip().lower().rstrip("/")
    return url[:-4] if url.endswith(".git") else url


def signature_for(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


@router.post("/github/{project_id}")
async def github_webhook(
    project_id: int,
    request: Request,
    x_github_event: str | None = Header(None),
    x_hub_signature_256: str | None = Header(None),
    db: Store = Depends(get_db),
) -> dict[str, Any]:
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
    head = payload.get("head_commit") or {}
    pusher = (payload.get("pusher") or {}).get("name") or "github"
    return _start_or_queue(db, project, f"github:{pusher}", payload.get("after"), head.get("message"))


def _start_or_queue(db: Store, project: dict[str, Any], actor: str, sha: str | None,
                    message: str | None) -> dict[str, Any]:
    """Run the pipeline for this pushed commit, or after the run in progress."""
    project_id = project["id"]
    first_line = (message or "").splitlines()[0][:80] if message else ""
    detail = f"{(sha or '')[:7]} {first_line}".strip()
    push = {"actor": actor, "detail": detail or None, "commit_sha": sha or None}

    running = active_run(db, project_id)
    if running:
        # Test this commit once the current run ends (a newer push replaces it)
        db.update(PROJECTS, project_id, pending_push=push)
        return {"queued_after": running["id"],
                "message": f"pipeline #{running['id']} is {running['status']}; this commit runs when it ends"}

    run = start_run(db, project, trigger="webhook", actor=push["actor"], detail=push["detail"], ingest=True,
                    commit_sha=push["commit_sha"])
    return {"started": run["id"]}


@router.post("/gitlab/{project_id}")
async def gitlab_webhook(
    project_id: int,
    request: Request,
    x_gitlab_event: str | None = Header(None),
    x_gitlab_token: str | None = Header(None),
    db: Store = Depends(get_db),
) -> dict[str, Any]:
    project = db.get(PROJECTS, project_id)
    # GitLab sends the secret itself; same answer for "no such project" and "wrong token"
    if project is None or not project.get("webhook_secret") or not hmac.compare_digest(
        project["webhook_secret"].encode(), (x_gitlab_token or "").encode()
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook token.")
    if x_gitlab_event != "Push Hook":
        return {"ignored": f"'{x_gitlab_event}' events do not trigger runs"}

    try:
        payload = json.loads(await request.body() or b"{}")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Body is not JSON.") from exc
    repo = payload.get("project") or {}
    if project.get("repo_url") and _normalize_repo(project["repo_url"]) not in {
        _normalize_repo(repo.get("web_url")), _normalize_repo(repo.get("git_http_url"))
    }:
        return {"ignored": f"push is for {repo.get('web_url')}, not this project's repository"}
    branch = str(payload.get("ref", "")).removeprefix("refs/heads/")
    if repo.get("default_branch") and branch != repo["default_branch"]:
        return {"ignored": f"push to '{branch}' (only the default branch '{repo['default_branch']}' triggers runs)"}
    if not project.get("app_url"):
        return {"ignored": "the project has no app URL to test"}
    sha = payload.get("checkout_sha") or payload.get("after")
    commits = payload.get("commits") or []
    message = next((c.get("message") for c in commits if c.get("id") == sha), None)
    return _start_or_queue(db, project, f"gitlab:{payload.get('user_username') or 'gitlab'}", sha, message)
