"""
TestSphere-AI — Fix patches (module 5.5): open security findings turned into
a unified diff against the app's own repository.

POST /security/patches clones the repository (the project's ``repo_url`` for
the finding's site, or one given in the request) into a temporary folder,
builds the patch with ``security.patcher``, deletes the clone and stores the
result.  The patch is a proposal: a human downloads it, reviews it and runs
``git apply``; the scanner's retest then confirms the fix on the live site.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from backend.api.ingest import _git_hosts
from backend.auth import User, actor_for, ensure_owned, get_current_user, scope
from backend.config import settings
from backend.database.session import get_db
from backend.database.store import Record, Store
from backend.github import parse_repo
from backend.models import FIX_PATCHES, PROJECTS
from backend.ratelimit import limit_runs
from backend.services import security_service as findings_store
from backend.services.security_service import record_audit
from ingestion import SourceError, clone, is_git_url, resolve_local
from security.patcher import build_patch

router = APIRouter(prefix="/security/patches", tags=["Security Testing"])


class PatchRequest(BaseModel):
    target_url: str = Field(..., max_length=2048, description="The site whose open findings to fix")
    repo: str | None = Field(None, max_length=1024, description="Repository to patch; default: the project's repo_url")
    finding_keys: list[str] | None = Field(None, max_length=50, description="Only these findings (default: all open)")
    actor: str = "dev_active"


def _host(url: str | None) -> str:
    try:
        return (urlsplit(url or "").hostname or "").lower()
    except ValueError:
        return ""


def _repo_for(db: Store, user: User, target_url: str) -> tuple[str | None, Record | None]:
    """The repo_url of the caller's project that serves *target_url* (same host)."""
    host = _host(target_url)
    for project in db.find(PROJECTS, **scope(user)):
        if project.get("repo_url") and _host(project.get("app_url")) == host:
            return project["repo_url"], project
    return None, None


def _checkout(repo: str) -> tuple[Path, Path | None]:
    """(directory to read, temporary folder to delete afterwards or None)."""
    if is_git_url(repo):
        tmp = Path(tempfile.mkdtemp(prefix="patch-", dir=_workspace()))
        return clone(repo, tmp, _git_hosts()), tmp
    if settings.INGEST_ALLOW_LOCAL_PATHS:
        return resolve_local(repo), None
    raise SourceError("Local folder paths are disabled on this server; use a public https Git URL.")


def _workspace() -> Path:
    path = Path(settings.INGEST_WORKSPACE) / "patches"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _commit(root: Path) -> str | None:
    try:
        res = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                             capture_output=True, text=True, timeout=10)
        return res.stdout.strip() or None if res.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _generate(repo: str, findings: list[dict[str, Any]], site_url: str) -> dict[str, Any]:
    root, tmp = _checkout(repo)
    try:
        result = build_patch(root, findings, site_url)
        return {
            "commit": _commit(root),
            "frameworks": result.frameworks,
            "files": [{k: v for k, v in vars(f).items() if k != "content"} for f in result.files],
            "contents": {f.path: f.content for f in result.files},  # stays on the server
            "applied": [vars(a) for a in result.applied],
            "manual": [vars(m) for m in result.manual],
            "patch": result.patch,
        }
    finally:
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)


def _public(row: Record) -> dict[str, Any]:
    out = {k: row.get(k) for k in ("id", "target_url", "repo", "commit", "frameworks", "files", "applied",
                                    "manual", "patch", "finding_keys", "actor", "created_at", "pull_request")}
    out["github"] = parse_repo(row.get("repo")) is not None and bool(row.get("contents"))
    return out


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_patch(
    payload: PatchRequest,
    db: Store = Depends(get_db),
    user: User = Depends(limit_runs),
) -> dict[str, Any]:
    """Build a patch for the open findings of *target_url* against its repository."""
    rows = findings_store.list_findings(db, target_url=payload.target_url, **scope(user))
    findings = [findings_store.serialize(r) for r in rows if r["status"] == "open"]
    if payload.finding_keys:
        wanted = set(payload.finding_keys)
        findings = [f for f in findings if f["key"] in wanted]
    if not findings:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="No open findings for this site; scan it first.")

    repo = (payload.repo or "").strip() or None
    if not repo:
        repo, _project = _repo_for(db, user, payload.target_url)
    if not repo:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="No repository is linked to this site. Add the repository to its project in "
                                   "Autopilot (Settings → Git repository), or enter one here.")
    try:
        built = await asyncio.to_thread(_generate, repo, findings, payload.target_url)
    except SourceError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    actor = actor_for(user, payload.actor)
    row = db.insert(FIX_PATCHES, target_url=payload.target_url, repo=repo, actor=actor, owner_uid=user.uid,
                    finding_keys=[f["key"] for f in findings], **built)
    changed = len(built["files"])
    record_audit(db, actor=actor, kind="patch", ref=str(row["id"]), owner_uid=user.uid,
                 level="info" if changed else "warn",
                 message=(f"Fix patch #{row['id']} for {payload.target_url}: {len(built['applied'])} fix(es) in "
                          f"{changed} file(s) of {repo}" + (f", {len(built['manual'])} need a manual change"
                                                            if built["manual"] else "")))
    return _public(row)


@router.get("")
def list_patches(
    target_url: str | None = Query(None, max_length=2048),
    limit: int = Query(20, ge=1, le=100),
    db: Store = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    filters = scope(user)
    if target_url:
        filters["target_url"] = target_url
    return [_public(r) for r in db.find(FIX_PATCHES, order_by="id", descending=True, limit=limit, **filters)]


@router.get("/{patch_id}/download")
def download_patch(patch_id: int, db: Store = Depends(get_db), user: User = Depends(get_current_user)) -> Response:
    row = ensure_owned(user, db.get(FIX_PATCHES, patch_id), "Fix patch")
    return Response(content=row.get("patch") or "", media_type="text/x-diff",
                    headers={"Content-Disposition": f'attachment; filename="testsphere-fix-{patch_id}.patch"',
                             "X-Content-Type-Options": "nosniff"})


class PullRequestRequest(BaseModel):
    title: str | None = Field(None, max_length=200)


def _check_text(file: dict[str, Any]) -> str:
    if file.get("verified") is True:
        return "still parses"
    if file.get("verified") is False:
        return f"syntax error: {file.get('check_note') or 'see the file'}"
    return "not syntax-checked"


def _pr_body(row: Record) -> str:
    lines = ["Security fixes proposed by **TestSphere AI** for issues its passive scan found on "
             f"{row['target_url']}.", "", "### What changes"]
    lines += [f"- `{a['check_id']}`: {a['how']} (`{a['file']}`)" for a in row.get("applied") or []]
    manual = row.get("manual") or []
    if manual:
        lines += ["", "### Still needs a change by hand"] + [f"- `{m['check_id']}`: {m['reason']}" for m in manual]
    checks = [f"- `{f['path']}`: {_check_text(f)}" for f in row.get("files") or []]
    lines += ["", "### Checked", *checks, "", "Deploy, then retest the findings in TestSphere (Security → Validation) "
              "to confirm the fix on the live site."]
    return "\n".join(lines)


@router.post("/{patch_id}/pull-request", status_code=status.HTTP_201_CREATED)
async def open_pull_request(
    patch_id: int,
    payload: PullRequestRequest | None = None,
    db: Store = Depends(get_db),
    user: User = Depends(limit_runs),
) -> dict[str, Any]:
    """Open a pull request with this patch on the repository it was built from."""
    from backend.api.integrations import github_token
    from backend.github import GitHubClient, GitHubError

    row = ensure_owned(user, db.get(FIX_PATCHES, patch_id), "Fix patch")
    if row.get("pull_request"):
        return row["pull_request"]
    repo = parse_repo(row.get("repo"))
    if not repo:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="Pull requests can only be opened on https://github.com repositories.")
    contents = row.get("contents") or {}
    if not contents or not row.get("commit"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="This patch changes no files, or was made before pull requests were supported. "
                                   "Generate it again.")
    token = github_token(db, user.uid)
    if not token:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="Connect GitHub first (Profile → Integrations).")
    title = (payload.title if payload and payload.title else None) or \
        f"Security headers and cookie fixes from TestSphere ({', '.join(sorted({a['check_id'] for a in row.get('applied') or []}))})"[:200]

    def open_pr() -> dict[str, Any]:
        with GitHubClient(token) as gh:
            return gh.open_fix_pr(*repo, base_sha=row["commit"], files=sorted(contents.items()),
                                  branch=f"testsphere/fix-{patch_id}", title=title, body=_pr_body(row))

    try:
        pr = await asyncio.to_thread(open_pr)
    except GitHubError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    db.update(FIX_PATCHES, patch_id, pull_request=pr)
    record_audit(db, actor=actor_for(user, "dev_active"), kind="patch", ref=str(patch_id), owner_uid=user.uid,
                 message=f"Pull request #{pr['number']} opened on {'/'.join(repo)} for fix patch #{patch_id}")
    return pr
