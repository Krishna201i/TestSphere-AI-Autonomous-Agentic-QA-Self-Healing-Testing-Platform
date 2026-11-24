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

from app.api.ingest import _git_hosts
from app.api.integrations import git_auth
from app.auth import User, actor_for, ensure_owned, get_current_user, scope
from app.config import settings
from app.database.session import get_db
from app.database.store import Record, Store
from app.gitforges import parse_forge_repo
from app.github import parse_repo
from app.models import FIX_PATCHES, PROJECTS
from app.ratelimit import limit_runs
from app.services import security_service as findings_store
from app.services.security_service import record_audit
from ingestion import GitAuth, SourceError, clone, is_git_url, resolve_local
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


def _checkout(repo: str, auth: GitAuth | None = None) -> tuple[Path, Path | None]:
    """(directory to read, temporary folder to delete afterwards or None)."""
    if is_git_url(repo):
        tmp = Path(tempfile.mkdtemp(prefix="patch-", dir=_workspace()))
        return clone(repo, tmp, _git_hosts(), auth=auth), tmp
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


def generate(repo: str, findings: list[dict[str, Any]], site_url: str, auth: GitAuth | None = None) -> dict[str, Any]:
    """Clone *repo* into a temporary folder, build the patch for *findings*, delete the clone."""
    root, tmp = _checkout(repo, auth)
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


def read_files(repo: str, paths: list[str], auth: GitAuth | None = None) -> tuple[str | None, dict[str, str | None]]:
    """The repository's newest commit and the current content of *paths* in it
    (None for a file that does not exist yet); the clone is deleted after."""
    root, tmp = _checkout(repo, auth)
    try:
        current: dict[str, str | None] = {}
        for rel in paths:
            path = (root / rel).resolve()
            inside = path.is_relative_to(root.resolve())
            current[rel] = path.read_text(encoding="utf-8", errors="replace") if inside and path.is_file() else None
        return _commit(root), current
    finally:
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)


def _public(row: Record) -> dict[str, Any]:
    out = {k: row.get(k) for k in ("id", "target_url", "repo", "commit", "frameworks", "files", "applied",
                                    "manual", "patch", "finding_keys", "actor", "created_at", "pull_request",
                                    "run_id", "project_id", "kind", "verification", "explanation", "suite")}
    forge = "github" if parse_repo(row.get("repo")) else (parse_forge_repo(row.get("repo")) or (None,))[0]
    out["forge"] = forge if row.get("contents") else None
    out["github"] = out["forge"] is not None  # the dashboard's "can open a pull request" flag (any host)
    return out


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_patch(
    payload: PatchRequest,
    db: Store = Depends(get_db),
    user: User = Depends(limit_runs),
) -> dict[str, Any]:
    """Build a patch for the open findings of *target_url* against its repository."""
    rows = await asyncio.to_thread(findings_store.list_findings, db, target_url=payload.target_url, **scope(user))
    findings = [findings_store.serialize(r) for r in rows if r["status"] == "open"]
    if payload.finding_keys:
        wanted = set(payload.finding_keys)
        findings = [f for f in findings if f["key"] in wanted]
    elif any(f.get("approved_by") for f in findings):
        # Someone reviewed the proposals: change only what they approved
        findings = [f for f in findings if f.get("approved_by")]
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
        built = await asyncio.to_thread(generate, repo, findings, payload.target_url, git_auth(db, user.uid, repo))
    except SourceError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    row = store_patch(db, built, target_url=payload.target_url, repo=repo, findings=findings,
                      actor=actor_for(user, payload.actor), owner_uid=user.uid)
    return _public(row)


def store_patch(db: Store, built: dict[str, Any], *, target_url: str, repo: str, findings: list[dict[str, Any]],
                actor: str, owner_uid: str | None, **extra: Any) -> Record:
    """Save a built patch (from the API or a pipeline run) and record it in the audit trail."""
    row = db.insert(FIX_PATCHES, target_url=target_url, repo=repo, actor=actor, owner_uid=owner_uid,
                    finding_keys=[f["key"] for f in findings], **extra, **built)
    changed = len(built["files"])
    record_audit(db, actor=actor, kind="patch", ref=str(row["id"]), owner_uid=owner_uid,
                 level="info" if changed else "warn",
                 message=(f"Fix patch #{row['id']} for {target_url}: {len(built['applied'])} fix(es) in "
                          f"{changed} file(s) of {repo}" + (f", {len(built['manual'])} need a manual change"
                                                            if built["manual"] else "")))
    return row



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


@router.get("/{patch_id}")
def get_patch(patch_id: int, db: Store = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    """One patch: the proposal a pipeline run links to (``fix_patch.id``), for review."""
    return _public(ensure_owned(user, db.get(FIX_PATCHES, patch_id), "Fix patch"))


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


def _tests_pr_body(row: Record) -> str:
    """A verified AI fix for the repository's failing tests."""
    v = row.get("verification") or {}
    before, after = v.get("before") or {}, v.get("after") or {}
    lines = ["A fix proposed by **TestSphere AI** for tests that failed in this repository, approved by a person.",
             "", "### Why", row.get("explanation") or "(no explanation given)", "", "### Verified",
             f"The repository's tests ran again with this change in TestSphere's sandbox ({v.get('framework') or 'tests'}): "
             f"{before.get('failed', '?')} failing before, all {after.get('passed', '?')} passing after. "
             "No test file was changed.", "", "### Files"]
    lines += [f"- `{f['path']}`" for f in row.get("files") or []]
    lines += ["", "Review it as you would any change: passing tests show it fixes what they check, not that it is "
              "right for everything else."]
    return "\n".join(lines)


def _pr_body(row: Record) -> str:
    if row.get("kind") == "tests":
        return _tests_pr_body(row)
    lines = ["Security fixes proposed by **TestSphere AI** for issues its security scan found on "
             f"{row['target_url']}.", "", "### What changes"]
    lines += [f"- `{a['check_id']}`: {a['how']} (`{a['file']}`)" for a in row.get("applied") or []]
    manual = row.get("manual") or []
    if manual:
        lines += ["", "### Still needs a change by hand"] + [f"- `{m['check_id']}`: {m['reason']}" for m in manual]
    checks = [f"- `{f['path']}`: {_check_text(f)}" for f in row.get("files") or []]
    lines += ["", "### Checked", *checks, "", "Deploy, then retest the findings in TestSphere (Security → Validation) "
              "to confirm the fix on the live site."]
    return "\n".join(lines)


def _suite_pr_body(row: Record) -> str:
    """The generated browser suite, committed as Playwright tests with a CI workflow."""
    suite = row.get("suite") or {}
    lines = [f"Browser tests for **{row['target_url']}**, generated by **TestSphere AI** and exported as plain "
             "[Playwright](https://playwright.dev) tests.", "",
             "### What is in it",
             f"- {suite.get('tests', '?')} test(s) that passed in TestSphere run #{row.get('run_id') or '?'} "
             "and are trusted (not quarantined)"]
    if suite.get("verified"):
        lines.append(f"- {suite['verified']} of them were also seen to **fail** on a deliberately broken copy of "
                     "their page, so they check something real")
    lines += [f"- `{f['path']}`" for f in row.get("files") or []]
    lines += ["", "### Run them", "```bash", "cd testsphere && npm install && npx playwright install --with-deps chromium",
              f"BASE_URL={row['target_url']} npx playwright test", "```"]
    if suite.get("workflow"):
        lines += ["", "The workflow in `.github/workflows/testsphere.yml` runs them on every push and pull request. "
                  "Set the `TESTSPHERE_BASE_URL` repository variable to test another deployment."]
    lines += ["", "TestSphere keeps this branch up to date while the pull request is open: a later run that changes "
              "the suite adds a commit here instead of opening another pull request."]
    return "\n".join(lines)


def default_pr_title(row: Record) -> str:
    kind = row.get("kind")
    if kind == "tests":
        return "Fix failing tests (verified by TestSphere)"
    if kind == "suite":
        return f"Add TestSphere browser tests ({(row.get('suite') or {}).get('tests', 0)} Playwright tests)"
    return ("Security headers and cookie fixes from TestSphere "
            f"({', '.join(sorted({a['check_id'] for a in row.get('applied') or []}))})")


def pr_body(row: Record) -> str:
    return _suite_pr_body(row) if row.get("kind") == "suite" else _pr_body(row)


class PullRequestError(Exception):
    """Why a pull request could not be opened, in words a person can act on."""


def create_pull_request(db: Store, row: Record, uid: str | None, title: str | None = None) -> dict[str, Any]:
    """Open a pull request (GitHub, Bitbucket) or merge request (GitLab) with
    patch *row* on the repository it was built from, as *uid*; stores it on the
    patch.  Blocking (call it from a thread).  Raises ``PullRequestError``."""
    from app.api.integrations import git_auth, github_token
    from app.gitforges import BitbucketClient, GitLabClient
    from app.github import GitHubClient, GitHubError

    if row.get("pull_request"):
        return row["pull_request"]
    repo = parse_repo(row.get("repo"))
    forge = parse_forge_repo(row.get("repo"))
    if not repo and not forge:
        raise PullRequestError("Pull requests can be opened on https://github.com, https://gitlab.com "
                               "and https://bitbucket.org repositories.")
    contents = row.get("contents") or {}
    if not contents or not row.get("commit"):
        raise PullRequestError("This patch changes no files, or was made before pull requests were supported. "
                               "Generate it again.")
    token = github_token(db, uid) if repo else None
    auth = git_auth(db, uid, row.get("repo")) if forge else None
    if repo and not token:
        raise PullRequestError("Connect GitHub first (Profile → Integrations).")
    if forge and not auth:
        host = "gitlab.com" if forge[0] == "gitlab" else "bitbucket.org"
        raise PullRequestError(f"Save a {host} credential with write access first "
                               "(Profile → Integrations → Git credentials).")
    prefix = "testsphere/tests" if row.get("kind") == "suite" else "testsphere/fix"
    args = {"base_sha": row["commit"], "files": sorted(contents.items()), "branch": f"{prefix}-{row['id']}",
            "title": (title or default_pr_title(row))[:200], "body": pr_body(row)}
    try:
        if repo:
            with GitHubClient(token) as gh:
                pr = gh.open_fix_pr(*repo, **args)
        else:
            client = GitLabClient(auth.token) if forge[0] == "gitlab" else BitbucketClient(auth.username, auth.token)
            with client:
                pr = client.open_fix_pr(forge[1], **args)
    except GitHubError as exc:
        raise PullRequestError(str(exc)) from exc
    db.update(FIX_PATCHES, row["id"], pull_request=pr)
    return pr


def update_pull_request(db: Store, row: Record, previous: Record, uid: str | None) -> dict[str, Any] | None:
    """Push patch *row*'s files as a new commit on the branch of *previous*'s
    pull request when that pull request is still open on GitHub (and not from
    a fork); stores the pull request on *row*.  None when there is nothing to
    update, so the caller opens a new one.  Raises ``PullRequestError``."""
    from app.api.integrations import github_token
    from app.github import GitHubClient, GitHubError

    pr = previous.get("pull_request") or {}
    repo = parse_repo(row.get("repo"))
    if not pr.get("number") or not pr.get("branch") or pr.get("fork") or not repo or previous.get("repo") != row.get("repo"):
        return None
    token = github_token(db, uid)
    if not token:
        raise PullRequestError("Connect GitHub first (Profile → Integrations).")
    try:
        with GitHubClient(token) as gh:
            if not gh.pull_request_open(*repo, pr["number"]):
                return None
            sha = gh.push_to_branch(*repo, pr["branch"], sorted((row.get("contents") or {}).items()),
                                    f"Update TestSphere browser tests (run #{row.get('run_id') or '?'})")
    except GitHubError as exc:
        raise PullRequestError(str(exc)) from exc
    updated = {**pr, "updated_by_patch": row["id"], "head_sha": sha}
    db.update(FIX_PATCHES, row["id"], pull_request=updated)
    return updated


@router.post("/{patch_id}/pull-request", status_code=status.HTTP_201_CREATED)
async def open_pull_request(
    patch_id: int,
    payload: PullRequestRequest | None = None,
    db: Store = Depends(get_db),
    user: User = Depends(limit_runs),
) -> dict[str, Any]:
    """Open a pull request (GitHub, Bitbucket) or merge request (GitLab) with this
    patch on the repository it was built from."""
    row = ensure_owned(user, db.get(FIX_PATCHES, patch_id), "Fix patch")
    if row.get("pull_request"):
        return row["pull_request"]
    try:
        pr = await asyncio.to_thread(create_pull_request, db, row, user.uid, payload.title if payload else None)
    except PullRequestError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    record_audit(db, actor=actor_for(user, "dev_active"), kind="patch", ref=str(patch_id), owner_uid=user.uid,
                 message=f"Pull request #{pr['number']} opened on {row.get('repo')} for fix patch #{patch_id}")
    return pr
