"""
TestSphere-AI — Verified deploy with automatic rollback (loop stage 6).

A deployment of a project:

  deploy    call the project's deploy hook (Render, Vercel, Netlify, or a host
            in DEPLOY_HOOK_HOSTS) and note the commit being shipped
            (``git ls-remote`` of its repository)
  health    wait until the site answers with the new version: its health URL
            must change or the settle time pass, then answer healthily
            DEPLOY_HEALTHY_CHECKS times in a row, within DEPLOY_TIMEOUT_SECONDS
  smoke     run the project's smoke tests in the browser
  rollback  only if health or smoke failed: call the rollback hook, or on
            Render redeploy the last verified commit (deploy hook + ``ref``),
            then check health again

Hooks are only ever sent to allow-listed hosts, without following redirects,
and the health URL goes through the same SSRF guard as tests.  Deployments
execute in the API process (they mostly wait on HTTP), also when pipeline runs
use a separate worker.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import subprocess
import time
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlsplit

import httpx

from backend.api.integrations import git_auth
from backend.config import git_hosts, settings
from backend.database.session import get_store
from backend.database.store import Record, Store, StoreUnavailableError, now_iso
from backend.models import APPLICATIONS, DEPLOYMENTS, PROJECTS, TEST_CASES
from backend.netguard import BlockedTargetError, check_target, guard_request
from backend.pipeline.deploy_config import (
    DeployConfigError,
    check_hook_url,
    provider_of,
    with_ref,
)
from backend.services.security_service import record_audit
from backend.services.test_execution_service import TestExecutionService
from ingestion.source import GitAuth, SourceError, git_env, validate_git_url

logger = logging.getLogger("testsphere.deploy")

STEPS = (("deploy", "Deploy"), ("health", "Health check"), ("smoke", "Smoke tests"), ("rollback", "Rollback"))
ACTIVE = ("queued", "deploying", "verifying", "rolling_back")

_tasks: set = set()


def remote_head(repo_url: str | None, auth: GitAuth | None = None) -> str | None:
    """Commit at the tip of the repository's default branch (None if unknown)."""
    if not repo_url:
        return None
    try:  # projects saved before the schema checked hosts; git must not reach internal addresses
        validate_git_url(repo_url, git_hosts())
    except SourceError:
        return None
    try:
        res = subprocess.run(["git", "ls-remote", repo_url, "HEAD"], capture_output=True, text=True, timeout=20,
                             env=git_env(repo_url, auth))
    except (OSError, subprocess.TimeoutExpired):
        return None
    line = res.stdout.strip().split("\t", 1)[0] if res.returncode == 0 else ""
    return line if len(line) == 40 else None


# ── Records ────────────────────────────────────────────────────────────────

def active_deployment(db: Store, project_id: int) -> Record | None:
    for status in ACTIVE:
        row = db.find_one(DEPLOYMENTS, project_id=project_id, status=status)
        if row:
            return row
    return None


def last_verified(db: Store, project_id: int, before: int | None = None) -> Record | None:
    for row in db.find(DEPLOYMENTS, project_id=project_id, order_by="id", descending=True, limit=25):
        if row["status"] == "verified" and (before is None or row["id"] < before):
            return row
    return None


def create_deployment(db: Store, project: Record, *, actor: str, trigger: str = "manual", run_id: int | None = None) -> Record:
    return db.insert(
        DEPLOYMENTS, project_id=project["id"], project_name=project["name"], owner_uid=project.get("owner_uid"),
        actor=actor, trigger=trigger, run_id=run_id, status="queued", provider=provider_of(project.get("deploy_hook_url")),
        commit=None, rollback_to=None, error=None, health=[],
        steps=[{"key": k, "label": label, "status": "pending", "detail": None, "started_at": None, "finished_at": None}
               for k, label in STEPS],
        started_at=None, finished_at=None,
    )


def start_deployment(db: Store, project: Record, *, actor: str, trigger: str = "manual", run_id: int | None = None,
                     executor: Callable[[int], Awaitable[Any]] | None = None) -> Record:
    dep = create_deployment(db, project, actor=actor, trigger=trigger, run_id=run_id)
    task = asyncio.get_running_loop().create_task((executor or execute_deployment)(dep["id"]))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    record_audit(db, actor=actor, kind="deploy", ref=str(dep["id"]), owner_uid=project.get("owner_uid"),
                 message=f"Deployment #{dep['id']} of {project['name']} started ({trigger})")
    return dep


def recover_interrupted(db: Store) -> int:
    """Deployments left mid-way by a restart can never finish; say so."""
    count = 0
    for status in ACTIVE:
        for row in db.find(DEPLOYMENTS, status=status):
            db.update(DEPLOYMENTS, row["id"], status="error", finished_at=now_iso(),
                      error="Interrupted: the server restarted during this deployment. Check the site.")
            count += 1
    return count


class _State:
    def __init__(self, db: Store, doc: Record) -> None:
        self.db, self.doc = db, dict(doc)

    @property
    def id(self) -> int:
        return self.doc["id"]

    def save(self, **changes: Any) -> None:
        self.doc.update(changes)
        self.db.update(DEPLOYMENTS, self.id, **changes)

    def step(self, key: str, status: str, detail: str | None = None) -> None:
        steps = [dict(s) for s in self.doc["steps"]]
        for s in steps:
            if s["key"] == key:
                if status == "running":
                    s["started_at"] = now_iso()
                else:
                    s["finished_at"] = now_iso()
                    s["started_at"] = s["started_at"] or s["finished_at"]
                s["status"] = status
                if detail is not None:
                    s["detail"] = detail
        self.save(steps=steps)


# ── Execution ──────────────────────────────────────────────────────────────

Sleep = Callable[[float], Awaitable[Any]]


async def _call_hook(client: httpx.AsyncClient, url: str) -> tuple[bool, str]:
    check_hook_url(url)
    try:
        resp = await client.post(url)
    except httpx.HTTPError as exc:
        return False, f"could not reach {urlsplit(url).hostname}: {exc}"
    if resp.status_code >= 400:
        return False, f"{urlsplit(url).hostname} answered HTTP {resp.status_code}"
    return True, f"{urlsplit(url).hostname} accepted it (HTTP {resp.status_code})"


async def _probe(client: httpx.AsyncClient, url: str) -> dict[str, Any]:
    started = time.monotonic()
    try:
        resp = await client.get(url)
        body = resp.content[:256_000]
        return {"at": now_iso(), "status": resp.status_code, "ok": resp.status_code < 400,
                "ms": round((time.monotonic() - started) * 1000), "hash": hashlib.sha256(body).hexdigest()[:16]}
    except httpx.HTTPError as exc:
        return {"at": now_iso(), "status": None, "ok": False, "ms": round((time.monotonic() - started) * 1000),
                "error": str(exc)[:200], "hash": None}


async def wait_healthy(state: _State, client: httpx.AsyncClient, url: str, before_hash: str | None,
                       sleep: Sleep, settle: bool = True, step: str = "health") -> tuple[bool, str]:
    """Poll *url* until the new version answers healthily N times in a row (progress on *step*)."""
    deadline = time.monotonic() + settings.DEPLOY_TIMEOUT_SECONDS
    settle_until = time.monotonic() + (settings.DEPLOY_SETTLE_SECONDS if settle else 0)
    changed = not settle or before_hash is None
    streak = 0
    samples = list(state.doc.get("health") or [])
    while time.monotonic() < deadline:
        sample = await _probe(client, url)
        samples = [*samples, sample][-60:]
        state.save(health=samples)
        changed = changed or (sample["ok"] and sample["hash"] != before_hash)
        live = changed or time.monotonic() >= settle_until
        streak = streak + 1 if sample["ok"] and live else 0
        state.step(step, "running", f"{'New version live' if changed else 'Waiting for the new version'} · "
                                        f"{streak}/{settings.DEPLOY_HEALTHY_CHECKS} healthy checks · "
                                        f"last: {sample['status'] or sample.get('error', 'no answer')}")
        if streak >= settings.DEPLOY_HEALTHY_CHECKS:
            how = "the page changed" if changed and before_hash else "the settle time passed"
            return True, f"Healthy {streak} times in a row after {how} ({sample['ms']} ms)"
        await sleep(settings.DEPLOY_POLL_SECONDS)
    last = samples[-1] if samples else {}
    return False, (f"Not healthy within {settings.DEPLOY_TIMEOUT_SECONDS}s "
                   f"(last answer: {last.get('status') or last.get('error', 'none')})")


async def _smoke(state: _State, project: Record, orchestrator: Any) -> tuple[bool | None, str, list[dict]]:
    """Run the project's smoke tests; None when it has none."""
    db = state.db
    apps = db.find(APPLICATIONS, project_id=project["id"])
    cases = [tc for app in apps for tc in db.find(TEST_CASES, application_id=app["id"])
             if (tc.get("category") == "smoke" or str(tc.get("name", "")).lower().startswith("smoke"))
             and not tc.get("quarantined")]
    if not cases:
        return None, "No smoke tests yet: run the pipeline once to generate them", []
    if orchestrator is None:
        from backend.orchestration.orchestrator import get_platform_orchestrator

        orchestrator = get_platform_orchestrator()
    from engine.schemas import RunOptions

    results = []
    for i, tc in enumerate(cases[:10], start=1):
        state.step("smoke", "running", f"Running {i} of {min(len(cases), 10)}: {tc['name']}")
        execution = TestExecutionService.create_execution(db, test_case_id=tc["id"], owner_uid=project.get("owner_uid"))
        try:
            res = await orchestrator.execute_test_run(db=db, execution_id=execution["id"], options=RunOptions(headless=True))
            status, error = res.get("status", "FAILED"), res.get("error_message")
        except StoreUnavailableError:
            raise
        except Exception as exc:  # noqa: BLE001 - a crashing test is a failed smoke test
            status, error = "FAILED", f"Execution error: {exc}"
        results.append({"test_case_id": tc["id"], "name": tc["name"], "execution_id": execution["id"],
                        "status": status, "error": error})
    failed = [r for r in results if r["status"] == "FAILED"]
    detail = f"{len(results) - len(failed)} of {len(results)} passed"
    if failed:
        detail += ": " + "; ".join(f"{r['name']} ({(r['error'] or '').splitlines()[0][:120] if r['error'] else 'failed'})" for r in failed[:3])
    return not failed, detail, results


async def execute_deployment(deployment_id: int, *, transport: httpx.AsyncBaseTransport | None = None,
                             orchestrator: Any = None, sleep: Sleep = asyncio.sleep) -> Record | None:
    """Deploy, verify and, if needed, roll back; never raises."""
    db = get_store()
    doc = db.get(DEPLOYMENTS, deployment_id)
    if doc is None:
        return None
    state = _State(db, doc)
    project = db.get(PROJECTS, doc["project_id"])
    try:
        if project is None:
            state.save(status="error", error="The project was deleted.", finished_at=now_iso())
            return db.get(DEPLOYMENTS, deployment_id)
        await _deploy(state, project, transport, orchestrator, sleep)
    except Exception as exc:  # keep the record honest instead of leaving it mid-way
        logger.exception("Deployment #%s crashed", deployment_id)
        try:
            state.save(status="error", error=f"Internal error: {exc}", finished_at=now_iso())
        except StoreUnavailableError:
            pass
    finished = db.get(DEPLOYMENTS, deployment_id)
    if project is not None and finished:
        level = {"verified": "success", "rolled_back": "warn"}.get(finished["status"], "error")
        record_audit(db, actor=finished["actor"], kind="deploy", ref=str(deployment_id), owner_uid=project.get("owner_uid"),
                     level=level, message=f"Deployment #{deployment_id} of {project['name']}: {finished['status'].replace('_', ' ')}"
                     + (f" ({finished['error']})" if finished.get("error") else ""))
        db.update(PROJECTS, project["id"], last_deploy_id=deployment_id, last_deploy_status=finished["status"])
    return finished


async def _deploy(state: _State, project: Record, transport, orchestrator, sleep: Sleep) -> None:
    hook = project.get("deploy_hook_url")
    health_url = project.get("health_url") or project.get("app_url")
    if not hook or not health_url:
        state.save(status="error", finished_at=now_iso(),
                   error="Set the project's deploy hook and app URL (Autopilot → Settings) to deploy.")
        return
    try:
        check_hook_url(hook)
        check_target(health_url)
    except (DeployConfigError, BlockedTargetError) as exc:
        state.save(status="error", error=str(exc), finished_at=now_iso())
        return

    hooks = httpx.AsyncClient(timeout=15, follow_redirects=False, transport=transport)
    site = httpx.AsyncClient(timeout=15, follow_redirects=True, transport=transport,
                             event_hooks={"request": [guard_request]})
    async with hooks, site:
        state.save(status="deploying", started_at=now_iso())
        before = await _probe(site, health_url)
        commit = await asyncio.to_thread(remote_head, project.get("repo_url"),
                                         git_auth(state.db, project.get("owner_uid"), project.get("repo_url")))
        previous = last_verified(state.db, project["id"], before=state.id)
        state.save(commit=commit, rollback_to=previous.get("commit") if previous else None)

        state.step("deploy", "running")
        ok, detail = await _call_hook(hooks, hook)
        state.step("deploy", "done" if ok else "failed",
                   detail + (f" · commit {commit[:7]}" if commit else ""))
        if not ok:
            state.step("health", "skipped", "Not run: the deploy was not accepted")
            state.step("smoke", "skipped", "Not run: the deploy was not accepted")
            state.step("rollback", "skipped", "Nothing was deployed")
            state.save(status="failed", error=f"Deploy hook failed: {detail}", finished_at=now_iso())
            return

        state.save(status="verifying")
        state.step("health", "running")
        healthy, detail = await wait_healthy(state, site, health_url, before.get("hash"), sleep)
        state.step("health", "done" if healthy else "failed", detail)

        problem = None if healthy else detail
        if healthy:
            state.step("smoke", "running")
            passed, detail, results = await _smoke(state, project, orchestrator)
            state.save(smoke=results)
            state.step("smoke", "skipped" if passed is None else "done" if passed else "failed", detail)
            if passed is False:
                problem = f"Smoke tests failed: {detail}"
        else:
            state.step("smoke", "skipped", "Not run: the site never became healthy")

        if problem is None:
            state.step("rollback", "skipped", "Not needed")
            state.save(status="verified", finished_at=now_iso())
            return
        await _rollback(state, project, hooks, site, health_url, problem, sleep)


async def _rollback(state: _State, project: Record, hooks: httpx.AsyncClient, site: httpx.AsyncClient,
                    health_url: str, problem: str, sleep: Sleep) -> None:
    rollback_hook = project.get("rollback_hook_url")
    target = state.doc.get("rollback_to")
    if rollback_hook:
        url, how = rollback_hook, "rollback hook"
    elif provider_of(project.get("deploy_hook_url")) == "render" and target:
        url, how = with_ref(project["deploy_hook_url"], target), f"redeploy of last verified commit {target[:7]}"
    else:
        state.step("rollback", "skipped", "No rollback configured: add a rollback hook, or use a Render deploy hook "
                                          "so the last verified commit can be redeployed")
        state.save(status="failed", error=problem, finished_at=now_iso())
        return

    state.save(status="rolling_back")
    state.step("rollback", "running", f"Calling {how}")
    ok, detail = await _call_hook(hooks, url)
    if not ok:
        state.step("rollback", "failed", f"{how}: {detail}")
        state.save(status="rollback_failed", error=f"{problem}. Rollback failed: {detail}", finished_at=now_iso())
        return
    healthy, health_detail = await wait_healthy(state, site, health_url, None, sleep, settle=False, step="rollback")
    state.step("rollback", "done" if healthy else "failed", f"{how} · {health_detail}")
    state.save(status="rolled_back" if healthy else "rollback_failed", error=problem, finished_at=now_iso())
