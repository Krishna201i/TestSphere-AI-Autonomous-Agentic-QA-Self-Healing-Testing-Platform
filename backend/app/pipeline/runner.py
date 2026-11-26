"""
TestSphere-AI — Automated pipeline runner.

One pipeline run takes a project (live URL, optional repository and "what to
test" prompt) through every stage without manual steps:

    codebase  → ingest the repository (on push, or when there is no blueprint yet)
    analyze   → load the live page and inventory its elements
    plan      → build/refresh the test suite (page tests, linked pages, code routes)
                plus every test saved under the project's application
    execute   → run each test in Playwright with AI failure analysis
    heal      → summarize what self-healing repaired or could not
    security  → passive security scan (when the host is in the authorized scope)
    report    → pass/fail, regressions against the previous run, audit event

Runs are documents in ``pipeline_runs``, updated after every stage and test,
so the dashboard follows progress by polling.  Runs execute one at a time per
process (each needs a browser; small hosts have little memory) — others wait
as "queued".  With ``PIPELINE_EXECUTION=worker`` the API only queues runs and
``app.worker`` claims and executes them.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import re
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from agents.llm.budget import token_budget
from app import dbsource
from app.config import settings
from app.database.session import get_store
from app.database.store import Record, Store, StoreUnavailableError, now_iso
from app.models import (
    APPLICATIONS,
    BLUEPRINTS,
    FIX_PATCHES,
    PIPELINE_RUNS,
    PROJECTS,
    TEST_CASES,
    TEST_EXECUTIONS,
)
from app.models.test_execution import TestExecutionStatus
from app.notify import notify_run
from app.pipeline import ai_plan, coverage, explore, suite
from app.pipeline.profile import profile_of
from app.pipeline.profile import select as select_by_profile
from app.reporting.summary import run_summary
from app.services import test_studio as studio
from app.services.security_service import record_audit
from app.services.test_case_service import TestCaseService
from app.services.test_execution_service import TestExecutionService
from app.services.url_analyzer import URLAnalyzerService, get_verifying_first

logger = logging.getLogger("testsphere.pipeline")

STAGES = (
    ("codebase", "Codebase ingestion"),
    ("analyze", "Page analysis"),
    ("plan", "Test planning"),
    ("execute", "Test execution"),
    ("heal", "Self-healing"),
    ("security", "Security scan"),
    ("unit", "Repository tests"),
    ("fix", "Fix proposals"),
    ("report", "Report"),
)
ACTIVE = ("queued", "running")
TRIGGERS = ("manual", "schedule", "webhook")
GENERATED_PREFIX = "pipe-"
REPO_PREFIX = "repo-"  # tests imported from the repository's own Playwright files


def _retire_unplanned(db: Store, rows: list[Record], planned_ids: set[int]) -> int:
    """Mark generated tests this run did not plan as retired (a link that went
    away, an AI test the model no longer writes, a recording for an old goal),
    and un-retire planned ones.  Retired tests are not run and are hidden from
    the test list; their history stays.  Returns how many were retired now."""
    newly = 0
    for row in rows:
        if not str(row.get("external_id") or "").startswith(GENERATED_PREFIX):
            continue
        should = row["id"] not in planned_ids
        if bool(row.get("retired")) != should:
            db.update(TEST_CASES, row["id"], retired=should)
            newly += should
    return newly

_tasks: set = set()
_run_tasks: dict[int, asyncio.Task] = {}  # run_id -> Task, for cancellation
_lock_state: dict[str, Any] = {"loop": None, "lock": None}


def _run_lock() -> asyncio.Lock:
    """One lock per event loop (tests run several loops; the server has one)."""
    loop = asyncio.get_running_loop()
    if _lock_state["loop"] is not loop:
        _lock_state.update(loop=loop, lock=asyncio.Lock())
    return _lock_state["lock"]


# ---------------------------------------------------------------------------
# Creating and starting runs
# ---------------------------------------------------------------------------


def active_run(db: Store, project_id: int) -> Record | None:
    for status in ACTIVE:
        row = db.find_one(PIPELINE_RUNS, project_id=project_id, status=status)
        if row:
            return row
    return None


def cancel_run(db: Store, run: Record) -> Record:
    """Mark run cancelled in DB and cancel the asyncio Task if it is still running."""
    state = _RunState(db, run)
    state.end("Cancelled by user.")
    db.update(PIPELINE_RUNS, run["id"], status="cancelled")
    state.doc["status"] = "cancelled"
    task = _run_tasks.pop(run["id"], None)
    if task and not task.done():
        task.cancel()
    return db.get(PIPELINE_RUNS, run["id"]) or state.doc


def create_run(db: Store, project: Record, *, trigger: str, actor: str, detail: str | None = None,
               ingest: bool = False, commit_sha: str | None = None) -> Record:
    if trigger not in TRIGGERS:
        raise ValueError(f"Unknown trigger {trigger!r}")
    return db.insert(
        PIPELINE_RUNS,
        project_id=project["id"], project_name=project["name"], app_url=project.get("app_url"),
        owner_uid=project.get("owner_uid"), trigger=trigger, trigger_detail=detail, actor=actor,
        ingest=ingest, status="queued", error=None,
        stages=[{"key": k, "label": label, "status": "pending", "detail": None, "started_at": None, "finished_at": None}
                for k, label in STAGES],
        tests=[], summary=None, regressions=[], started_at=None, finished_at=None, commit_sha=commit_sha,
    )


def start_run(db: Store, project: Record, *, trigger: str, actor: str, detail: str | None = None,
              ingest: bool = False, executor: Callable[[int], Any] | None = None, commit_sha: str | None = None) -> Record:
    """Create a run; execute it in the background here, or leave it queued for a worker."""
    run = create_run(db, project, trigger=trigger, actor=actor, detail=detail, ingest=ingest, commit_sha=commit_sha)
    if settings.PIPELINE_EXECUTION != "worker" or executor is not None:
        task = asyncio.get_running_loop().create_task((executor or execute_run)(run["id"]))
        _tasks.add(task)
        _run_tasks[run["id"]] = task
        task.add_done_callback(_tasks.discard)
        task.add_done_callback(lambda t, rid=run["id"]: _run_tasks.pop(rid, None))
    record_audit(db, actor=actor, kind="pipeline", ref=str(run["id"]), owner_uid=project.get("owner_uid"),
                 message=f"Pipeline #{run['id']} queued for {project['name']} ({trigger}{f': {detail}' if detail else ''})")
    return run


def recover_interrupted(db: Store) -> int:
    """Inline execution: runs left queued/running by a restart can never finish; mark them so.
    (A worker's runs are its own business: queued ones wait for it, and it reaps
    stale running ones itself.)"""
    if settings.PIPELINE_EXECUTION == "worker":
        return 0
    count = 0
    for status in ACTIVE:
        for row in db.find(PIPELINE_RUNS, status=status):
            end_interrupted(db, row, "Interrupted: the server restarted before this run finished.")
            count += 1
    return count


def end_interrupted(db: Store, run: Record, error: str) -> None:
    """Close a run that stopped part-way: its running stage failed, the rest
    were not run, and the project shows this run as its last."""
    state = _RunState(db, run)
    state.end(error)




# ---------------------------------------------------------------------------
# Executing a run
# ---------------------------------------------------------------------------


class _RunState:
    """In-memory copy of the run document, written back on every change."""

    def __init__(self, db: Store, run: Record) -> None:
        self.db = db
        self.doc = dict(run)

    @property
    def id(self) -> int:
        return self.doc["id"]

    def save(self, **changes: Any) -> None:
        self.doc.update(changes)
        self.db.update(PIPELINE_RUNS, self.id, **changes)

    def stage(self, key: str, status: str, detail: str | None = None) -> None:
        stages = [dict(s) for s in self.doc["stages"]]
        for s in stages:
            if s["key"] == key:
                if status == "running":
                    if s.get("status") != "running" or not s.get("started_at"):
                        s["started_at"] = now_iso()  # a progress update keeps the stage's start
                elif status in ("done", "failed", "skipped"):
                    s["finished_at"] = now_iso()
                    s["started_at"] = s["started_at"] or s["finished_at"]
                s["status"] = status
                if detail is not None:
                    s["detail"] = detail
        self.save(stages=stages)

    def skip_rest(self, reason: str) -> None:
        for s in self.doc["stages"]:
            if s["status"] == "pending":
                self.stage(s["key"], "skipped", reason)

    def end(self, error: str) -> None:
        """End the run as an error: no stage is left running or pending, and
        the project's last-run status says so."""
        stages = [dict(s) for s in self.doc.get("stages") or []]
        for s in stages:
            if s["status"] in ("running", "pending"):
                stamp = now_iso()
                if s["status"] == "running":
                    s["status"], s["detail"] = "failed", error
                else:
                    s["status"], s["detail"] = "skipped", "Not run: the pipeline stopped early"
                s["finished_at"] = stamp
                s["started_at"] = s.get("started_at") or stamp
        self.save(stages=stages, status="error", error=error, finished_at=now_iso())
        project = self.db.get(PROJECTS, self.doc["project_id"])
        if project is not None:
            _finish_project(self.db, project, self)


async def execute_run(run_id: int, orchestrator: Any = None, scanner: Any = None) -> Record | None:
    """Run every stage of pipeline run *run_id*; never raises (failures end up on the run)."""
    db = get_store()
    run = db.get(PIPELINE_RUNS, run_id)
    if run is None:
        return None
    if run.get("status") == "cancelled":
        return run
    async with _run_lock():
        state = _RunState(db, run)
        project = db.get(PROJECTS, run["project_id"])
        if project is None:
            state.save(status="error", error="The project was deleted.", finished_at=now_iso())
            return db.get(PIPELINE_RUNS, run_id)
        state.save(status="running", started_at=now_iso())
        budget = None
        try:
            with token_budget(settings.LLM_MAX_TOKENS_PER_RUN) as budget:
                if settings.PIPELINE_SHARED_BROWSER:
                    from engine.browser import shared_browsers

                    # One browser for the whole run; each test still gets its own context
                    async with shared_browsers():
                        await _execute(state, project, orchestrator, scanner)
                else:
                    await _execute(state, project, orchestrator, scanner)
        except StoreUnavailableError as exc:
            logger.error("Pipeline #%s stopped: database unavailable: %s", run_id, exc)
            try:
                state.end(f"Database unavailable: {exc}")
            except StoreUnavailableError:
                pass
        except Exception as exc:  # keep the run's record honest instead of leaving it "running"
            logger.exception("Pipeline #%s crashed", run_id)
            state.end(f"Internal error: {exc}")
        if budget is not None and budget.calls:
            with contextlib.suppress(StoreUnavailableError):
                state.save(llm_usage=budget.summary())
        finished = db.get(PIPELINE_RUNS, run_id)
        try:
            current = db.get(PROJECTS, project["id"]) or project
            await notify_run(current, finished)
            await asyncio.to_thread(report_commit_status, db, current, finished)
            _deploy_if_green(db, current, finished)
            _start_pending_push(db, current)
        except StoreUnavailableError:
            pass
        return finished


def _start_pending_push(db: Store, project: Record) -> Record | None:
    """Start the run for a push that arrived while this project's run was active."""
    push = project.get("pending_push")
    if not push or not project.get("app_url"):
        return None
    if not db.update_if(PROJECTS, project["id"], "pending_push", push, pending_push=None):
        return None  # another process took it (or a newer push replaced it and will be taken)
    return start_run(db, project, trigger="webhook", actor=push.get("actor") or "github",
                     detail=push.get("detail"), ingest=True, commit_sha=push.get("commit_sha"))


def report_commit_status(db: Store, project: Record, run: Record) -> bool:
    """Show the run's result on the pushed commit in GitHub, GitLab or Bitbucket
    (with the owner's connected GitHub or saved Git credential)."""
    from app.api.integrations import git_auth, github_token
    from app.gitforges import (
        BitbucketClient,
        GitLabClient,
        parse_forge_repo,
        set_bitbucket_status,
        set_gitlab_status,
    )
    from app.github import GitHubClient, GitHubError, parse_repo
    from app.notify import run_url

    repo = parse_repo(project.get("repo_url"))
    forge = None if repo else parse_forge_repo(project.get("repo_url"))
    if not (run.get("commit_sha") and (repo or forge)):
        return False
    token = github_token(db, project.get("owner_uid")) if repo else None
    auth = git_auth(db, project.get("owner_uid"), project.get("repo_url")) if forge else None
    if not (token or auth):
        return False
    s = run.get("summary") or {}
    state = {"passed": "success", "failed": "failure"}.get(run.get("status"), "error")
    text = (f"{s.get('passed', 0)}/{s.get('total', 0)} tests passed" if s else (run.get("error") or run.get("status", "")))
    if s.get("goal_untested"):
        text += " (goal not tested)"
    elif s.get("goal_untested_parts"):
        text += " (goal partly tested)"
    description = f"Run #{run['id']}: {text}"
    try:
        if repo:
            with GitHubClient(token) as gh:
                gh.set_commit_status(*repo, run["commit_sha"], state, description, run_url(run["id"]))
        elif forge[0] == "gitlab":
            with GitLabClient(auth.token) as gl:
                set_gitlab_status(gl, forge[1], run["commit_sha"], state, description, run_url(run["id"]))
        else:
            with BitbucketClient(auth.username, auth.token) as bb:
                set_bitbucket_status(bb, forge[1], run["commit_sha"], state, description, run_url(run["id"]))
        return True
    except GitHubError as exc:
        logger.warning("Could not set the commit status for run #%s: %s", run["id"], exc)
        return False


def _deploy_if_green(db: Store, project: Record, run: Record) -> None:
    """Close the loop: a clean run of a project with deploy_on_pass ships it (stage 6)."""
    from app.pipeline import deploy

    if not (project.get("deploy_on_pass") and project.get("deploy_hook_url")):
        return
    if run.get("status") != "passed" or run.get("regressions"):
        return
    if deploy.active_deployment(db, project["id"]):
        return
    deploy.start_deployment(db, project, actor=run.get("actor") or "pipeline", trigger="pipeline", run_id=run["id"])


async def _execute(state: _RunState, project: Record, orchestrator: Any, scanner: Any) -> None:
    db = state.db
    owner = project.get("owner_uid")
    app_url = project.get("app_url")
    if not app_url:
        state.skip_rest("Not run: the project has no app URL")
        state.save(status="error", error="Set the project's app URL to run the pipeline.", finished_at=now_iso())
        return

    blueprint = await _stage_codebase(state, project)

    # ── analyze ──
    state.stage("analyze", "running")
    analysis = await URLAnalyzerService.analyze_live_website(
        url=app_url, prompt=project.get("prompt"), allow_test_accounts=bool(project.get("allow_test_accounts")),
        email_domain=project.get("test_email_domain"), test_data=profile_of(project).test_data)
    if not analysis.get("success"):
        reason = f"HTTP {analysis['status_code']}" if analysis.get("status_code") else (analysis.get("error") or "unreachable")
        state.stage("analyze", "failed", f"{app_url} did not load ({reason})")
        state.skip_rest("Not run: the target did not load")
        state.save(status="error", error=f"Could not load {app_url} ({reason}). No tests were planned from an error page.",
                   finished_at=now_iso())
        _finish_project(db, project, state)
        record_audit(db, actor=state.doc["actor"], kind="pipeline", level="error", ref=str(state.id), owner_uid=owner,
                     message=f"Pipeline #{state.id} for {project['name']}: {app_url} did not load ({reason})")
        return
    inv = analysis.get("elements_inventory") or {}
    state.stage("analyze", "done", f"HTTP {analysis['status_code']} in {analysis['latency_ms']} ms · "
                                   f"{inv.get('inputs_count', 0)} inputs, {inv.get('buttons_count', 0)} buttons, "
                                   f"{inv.get('links_count', 0)} links")

    # ── plan ──
    state.stage("plan", "running")
    snapshot: dict[str, Any] = {}
    application, test_cases, plan_detail = await _plan(db, project, analysis, blueprint, snapshot)
    state.save(analysis=analysis_snapshot(analysis, snapshot.get("pages") or {}))
    coverage = (analysis.get("synthesized_test_case") or {}).get("goal") or {}
    # No goal test at all, and the analysis did not say why (it does for a
    # sign-in without credentials, a sign-up without test accounts, a CAPTCHA)
    goal_untested = bool((project.get("prompt") or "").strip()) and not coverage.get("untested") and not any(
        str(tc.get("external_id", "")).endswith("-interaction") for tc in test_cases)
    if goal_untested:
        plan_detail += (" · Your goal was not tested: no form fields or buttons were found on the page"
                        + ("" if analysis.get("rendered_in_browser") else " (even before scripts ran)"))
    # Parts of the goal no step tests ("…and fly to the moon"): say so, never claim them
    untested_parts = [] if goal_untested else list(coverage.get("untested") or [])
    if untested_parts:
        plan_detail += " · Not tested from your goal: " + "; ".join(f"“{p[:120]}”" for p in untested_parts)
    state.save(goal_untested=goal_untested, goal_untested_parts=untested_parts)
    state.stage("plan", "done", plan_detail)

    # ── execute (with AI analysis + healing inside the orchestrator) ──
    db_check = await asyncio.to_thread(dbsource.start_check, project)
    results = await _stage_execute(state, test_cases, orchestrator, owner,
                                   sign_in_first=bool(project.get("sign_in_first")))
    goal_text = URLAnalyzerService.prompt_values(project.get("prompt")).get("text")
    database = await asyncio.to_thread(dbsource.finish_check, db_check, [goal_text] if goal_text else [])
    state.save(database=database)
    if profile_of(project).acceptance:
        await _stage_acceptance(state, test_cases, results, app_url)

    # ── heal ──
    healed = [r for r in results if r["healed"]]
    unhealed = [r for r in results if r["status"] == TestExecutionStatus.FAILED.value]
    if healed or unhealed:
        parts = []
        if healed:
            parts.append(f"{len(healed)} test(s) self-healed: " + "; ".join(r["name"] for r in healed))
        if unhealed:
            parts.append(f"{len(unhealed)} failure(s) could not be healed")
        state.stage("heal", "done", " · ".join(parts))
    else:
        state.stage("heal", "done", "Nothing needed healing")

    # ── security ──
    security = await _stage_security(state, app_url, owner, scanner, active=bool(project.get("active_scan")),
                                     pages=_tested_pages(test_cases, app_url),
                                     routes=(blueprint or {}).get("routes"))

    # ── the repository's own unit tests: its CI results, or the sandbox ──
    await _stage_unit(state, project, blueprint)

    # ── fix proposals: a patch for the open findings, for a human to approve ──
    await _stage_fix(state, project, security)
    # ── the trusted tests as Playwright files for the repository, and pull requests ──
    await _stage_suite(state, project, test_cases, results)
    await _auto_pull_requests(state, project)

    # ── report ──
    _report(state, project, results, security)


async def _stage_codebase(state: _RunState, project: Record) -> dict[str, Any] | None:
    from app.api.ingest import ingest_source, save_blueprint
    from app.api.integrations import git_auth
    from ingestion import SourceError

    db = state.db
    repo = project.get("repo_url")
    previous = db.find(BLUEPRINTS, project_id=project["id"], order_by="id", descending=True, limit=1)
    latest = json.loads(previous[0]["data"]) if previous else None
    if not repo:
        state.stage("codebase", "skipped", "No repository linked to this project")
        return None
    if latest and not state.doc.get("ingest") and state.doc["trigger"] != "webhook":
        state.stage("codebase", "done", f"Using the blueprint from {latest.get('analyzed_at', '')[:16].replace('T', ' ')} "
                                        f"({len(latest.get('routes', []))} routes); re-ingested on every push")
        return latest
    state.stage("codebase", "running")
    try:
        blueprint = await asyncio.to_thread(ingest_source, repo, git_auth(db, project.get("owner_uid"), repo))
    except (SourceError, NotADirectoryError) as exc:
        state.stage("codebase", "failed", f"{exc}" + (" — using the previous blueprint" if latest else ""))
        return latest
    save_blueprint(db, repo, blueprint, actor=state.doc["actor"], owner_uid=project.get("owner_uid"),
                   project_id=project["id"])
    langs = blueprint.get("languages", {})
    primary = max(langs, key=lambda k: langs[k]["lines"]) if langs else "no code"
    deps = blueprint.get("dependency_scan") or {}
    dep_note = (f" · dependencies not checked: {deps['error']}" if deps.get("error") else
                f" · {deps['vulnerable']} of {deps['checked']} pinned packages have known vulnerabilities"
                if deps.get("vulnerable") else f" · {deps['checked']} pinned packages, none known vulnerable" if deps else "")
    state.stage("codebase", "done", f"{blueprint.get('files_total', 0)} files, {primary}, "
                                    f"{_count(len(blueprint.get('routes', [])), 'route')}, "
                                    f"{_count(len(blueprint.get('risks', [])), 'risk')}{dep_note}")
    return blueprint


_INVENTORY_COUNTS = ("inputs_count", "buttons_count", "forms_count", "links_count", "headings_count",
                     "images_count", "hidden_controls")


def _page_audit(analysis: dict[str, Any]) -> dict[str, Any]:
    """One analyzed page as the report shows it: how it answered, what is on
    it, and its health audit.  No element lists, no page text beyond the
    title, description and headings."""
    inv = analysis.get("elements_inventory") or {}
    return {
        "url": analysis.get("url"), "final_url": analysis.get("final_url"),
        "status_code": analysis.get("status_code"), "latency_ms": analysis.get("latency_ms"),
        "title": analysis.get("page_title"), "description": (analysis.get("meta_description") or "")[:300] or None,
        "lang": analysis.get("page_lang"), "html_kb": round((analysis.get("html_bytes") or 0) / 1024, 1),
        "rendered_in_browser": bool(analysis.get("rendered_in_browser")),
        "visibility_checked": bool(analysis.get("visibility_checked")),
        "counts": {k.removesuffix("_count"): inv.get(k) for k in _INVENTORY_COUNTS if inv.get(k) is not None},
        "headings": [str(h)[:80] for h in (inv.get("headings") or [])[:12]],
        "images_without_alt": sum(1 for i in inv.get("images") or [] if not i.get("has_alt")),
        "headers": analysis.get("response_headers") or {},
        "health": analysis.get("health_audit") or {},
    }


def analysis_snapshot(analysis: dict[str, Any], pages: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """What the run's analysis found, kept with the run for its report: the
    start page and every other page analyzed."""
    return {"start": _page_audit(analysis),
            "pages": [_page_audit(p) for u, p in pages.items() if u != analysis.get("url")]}


def _count(n: int, word: str) -> str:
    """'1 risk', '3 risks'."""
    return f"{n} {word}{'' if n == 1 else 's'}"


# Answers a browser shows as a page; anything else (a CSV, a spreadsheet, JSON) is a file
_PAGE_TYPES = ("text/html", "application/xhtml+xml", "text/plain", "")
# A path no site has: what a single-page-app host answers for every unknown URL
FALLBACK_PROBE_PATH = "/__testsphere-probe-not-a-page"


async def _reachable(urls: list[str]) -> dict[str, dict[str, Any] | None]:
    """What each URL answers (None when unreachable), checked concurrently:
    ``status``, whether it is a ``file`` (a download, not a page) and a
    ``digest`` of the body (to recognise a catch-all answer)."""
    from app.netguard import BlockedTargetError

    async def one(url: str) -> dict[str, Any] | None:
        try:
            response, _ = await get_verifying_first(url, timeout=8.0,
                                                    headers={"User-Agent": URLAnalyzerService.USER_AGENT})
        except (httpx.HTTPError, BlockedTargetError):
            return None
        kind = response.headers.get("content-type", "").split(";")[0].strip().lower()
        attachment = "attachment" in response.headers.get("content-disposition", "").lower()
        return {"status": response.status_code, "file": attachment or kind not in _PAGE_TYPES,
                "digest": hashlib.sha256(response.content).hexdigest()}

    found = await asyncio.gather(*(one(u) for u in urls))
    return dict(zip(urls, found, strict=True))


async def _fallback_digests(base_url: str) -> set[str]:
    """Bodies that mean "not this route": what the site sends for a path that
    cannot exist, when it answers that with a page (a single-page app's host
    sends its index for every URL), and the start page itself.  A code route
    answering one of them is not served there.  The probe is tried twice: a
    slow host's first answer can take longer than a check waits."""
    root = urlparse(base_url)
    probe_url = f"{root.scheme}://{root.netloc}{FALLBACK_PROBE_PATH}"
    digests: set[str] = set()
    for _ in range(2):
        answers = await _reachable([probe_url, base_url])
        for answer in answers.values():
            if answer and answer["status"] < 400 and not answer["file"]:
                digests.add(answer["digest"])
        if answers[probe_url]:
            break
    return digests


CHANGE_READS = 3


def _cookie_header(session: dict | None, url: str) -> str | None:
    """The session's cookies for *url*'s host, as a Cookie header (None: none)."""
    host = (urlparse(url).hostname or "").lower()
    pairs = [f"{c['name']}={c['value']}" for c in (session or {}).get("cookies") or []
             if c.get("name") and "value" in c
             and (host == str(c.get("domain", "")).lstrip(".").lower()
                  or host.endswith("." + str(c.get("domain", "")).lstrip(".").lower()))]
    return "; ".join(pairs) or None


async def _mark_changing_text(pages: list[dict[str, Any]], session: dict | None = None) -> int:
    """Read each page again a few times and note, as its ``changing_text``,
    the headings that differ between visits; returns how many.  Judged only
    on pages whose HTML carries headings (a page built by scripts is not), and
    only when the reads disagree, or share no heading with the analysis.  A
    page analyzed signed in is read with the *session*'s cookies, and judged
    only by the reads disagreeing (a read that was not let in shows the same
    sign-in page every time, which proves nothing)."""
    from app.services.url_analyzer import visible_markup

    async def reads(url: str, signed_in: bool) -> list[set[str]]:
        headers = {"User-Agent": URLAnalyzerService.USER_AGENT}
        if signed_in and (cookie := _cookie_header(session, url)):
            headers["Cookie"] = cookie
        found = []
        for _ in range(CHANGE_READS):
            try:
                response, _ = await get_verifying_first(url, timeout=8.0, headers=headers)
            except Exception:  # noqa: BLE001 - nothing to compare with: leave the page as analyzed
                return []
            found.append({h.lower() for h in URLAnalyzerService._extract_headings(visible_markup(response.text))})
        return found

    results = await asyncio.gather(*(reads(p["url"], bool(p.get("signed_in"))) for p in pages))
    marked = 0
    for page, rs in zip(pages, results, strict=True):
        if not rs or not any(rs):
            continue
        seen = (page.get("elements_inventory") or {}).get("headings") or []
        known = {h.lower() for h in seen}
        # The reads differ, or none of what the analysis saw is in them (swapped
        # wholesale); a heading only scripts add is no reason (the rest agree)
        disagree = len({frozenset(r) for r in rs}) > 1 or (not page.get("signed_in") and not (known & set.union(*rs)))
        if disagree:
            everywhere = set.intersection(*rs)
            changed = [h for h in seen if h.lower() not in everywhere]
            if changed:
                page["changing_text"] = changed
                marked += len(changed)
    return marked


async def _second_hop(analysis: dict[str, Any], candidates: list[dict[str, Any]],
                      pages: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """Same-site pages linked from the analyzed pages but not from the start
    page: the ones that loaded (to analyze and test), and those left out.
    Never more than the page limits leave room for."""
    links = sum(1 for c in candidates if c["kind"] == "link")
    room = min(settings.PIPELINE_DEEP_PAGES - len(pages), settings.PIPELINE_LINK_PAGES - links)
    if room <= 0 or not pages:
        return [], []
    known = {suite.normalize(analysis["url"])} | {suite.normalize(c["url"]) for c in candidates}
    found: list[dict[str, Any]] = []
    for url, page in pages.items():
        if suite.redirected({"url": url}, page):
            continue
        for c in suite.candidate_pages({**page, "url": url}, None, link_limit=50, route_limit=0):
            if suite.normalize(c["url"]) not in known:
                known.add(suite.normalize(c["url"]))
                found.append(c)
    found = found[: room * 2]  # some will not load
    answers = await _reachable([c["url"] for c in found]) if found else {}
    ok = [c for c in found if (a := answers.get(c["url"])) and a["status"] < 400 and not a.get("file")]
    left_out = [f"{c['label']} ({(answers.get(c['url']) or {}).get('status') or 'unreachable'})" for c in found
                if not answers.get(c["url"]) or answers[c["url"]]["status"] >= 400]
    return ok[:room], left_out


async def _analyze_pages(urls: list[str], session: dict | None = None) -> dict[str, dict[str, Any]]:
    """Each page's analysis (title, headings, controls), signed in when given
    a *session*; a page that fails or takes too long is left out and keeps a
    plain render check."""
    async def one(url: str) -> dict[str, Any] | None:
        try:
            page = await asyncio.wait_for(URLAnalyzerService.analyze_live_website(url=url, storage_state=session),
                                          timeout=45)
        except Exception as exc:  # noqa: BLE001 - one page's analysis never stops the run
            logger.info("Could not analyze %s for content checks: %s", url, exc)
            return None
        return page if page.get("success") else None

    found = await asyncio.gather(*(one(u) for u in urls))
    return {u: p for u, p in zip(urls, found, strict=True) if p}


async def _plan(db: Store, project: Record, analysis: dict[str, Any],
                blueprint: dict[str, Any] | None, snapshot: dict[str, Any] | None = None) -> tuple[Record, list[Record], str]:
    """Plan the run's tests and save them as test cases.  *snapshot*, when
    given, receives the other pages analyzed (for the report's page audit)."""
    owner = project.get("owner_uid")
    app_url = project["app_url"]
    application = db.find_one(APPLICATIONS, project_id=project["id"], base_url=app_url)
    if application is None:
        application = db.insert(APPLICATIONS, project_id=project["id"], name=(analysis.get("page_title") or project["name"])[:60],
                                base_url=app_url, description="Created by the automated pipeline", owner_uid=owner)

    profile = profile_of(project)
    changing = await _mark_changing_text([analysis])
    planned = suite.page_tests(analysis, project.get("prompt"))
    candidates = suite.candidate_pages(analysis, blueprint, link_limit=settings.PIPELINE_LINK_PAGES,
                                       route_limit=settings.PIPELINE_ROUTE_PAGES)
    answers = await _reachable([c["url"] for c in candidates]) if candidates else {}
    left_out = [f"{c['label']} ({(answers.get(c['url']) or {}).get('status') or 'unreachable'})" for c in candidates
                if not answers.get(c["url"]) or answers[c["url"]]["status"] >= 400]
    reachable = [c for c in candidates if answers.get(c["url"]) and answers[c["url"]]["status"] < 400]
    # A linked file downloads (a browser cannot open it as a page): the request above checked it
    files = [c for c in reachable if answers[c["url"]].get("file")]
    # A code route answered with the site's catch-all page is not served there
    # (a front end deployed without its API): no test can pass or mean anything
    fallback = await _fallback_digests(analysis["url"]) if any(c["kind"] == "route" for c in reachable) else set()
    # (not a front-end router's page: the app's one HTML page is how those are served)
    unserved = [c for c in reachable if c["kind"] == "route" and not c.get("client")
                and answers[c["url"]].get("digest") in fallback]
    left_out += [f"{c['label']} (answers with the site's catch-all page: not served here)" for c in unserved]
    reachable = [c for c in reachable if c not in files and c not in unserved]
    pages: dict[str, dict[str, Any]] = {}
    # "Sign in first": sign in once now, so the pages behind the login are
    # analyzed (and covered) as a signed-in visitor sees them
    session, landing = (await _sign_in_session(planned, analysis["url"])) if project.get("sign_in_first") else (None, None)
    sign_in_note = None
    if session and landing and urlparse(landing).netloc == urlparse(analysis["url"]).netloc and             suite.normalize(landing) not in {suite.normalize(u) for u in [analysis["url"], *(c["url"] for c in reachable)]}:
        # Where signing in leads (a dashboard): rarely linked from the sign-in page itself
        reachable.insert(0, {"kind": "link", "url": landing, "label": urlparse(landing).path or "/"})
    if project.get("sign_in_first") and session is None:
        # No session (no sign-in test, or it did not get in): analysis would see
        # the sign-in redirect, so these pages only check they stay put
        planned += [suite.stays_on_page_test(c) for c in reachable]
        sign_in_note = "signed-in pages only checked to stay put: signing in while planning did not work"
    else:
        pages = await _analyze_pages([c["url"] for c in reachable[:settings.PIPELINE_DEEP_PAGES]], session)
        # One hop further: pages linked only from the pages just analyzed (a
        # blog's posts, a docs section), within the same page limits
        hop, hop_left_out = await _second_hop(analysis, candidates, pages)
        if hop:
            pages.update(await _analyze_pages([c["url"] for c in hop], session))
            reachable += hop
        left_out += hop_left_out
        # Text a page shows differently on each visit never becomes a check
        changing += await _mark_changing_text(list(pages.values()), session)
        # A page that redirected was analyzed as the page it led to: no content checks from that
        for c in reachable:
            page = pages.get(c["url"])
            if page and not suite.redirected(c, page):
                planned.append({**suite.page_check_test(c, page), **({"signed_in": True} if session else {})})
            elif session:
                planned.append(suite.stays_on_page_test(c))  # even signed in, it sent the visitor away
            else:
                # Sent elsewhere signed out (a protected page): check it stays that way
                planned.append((page and suite.redirect_test(c, page)) or suite.render_test(c))
        if session:
            sign_in_note = f"signed in while planning: {len(pages)} page(s) behind the login analyzed and covered"

    # The AI planner sees every page analyzed above (not one that redirected
    # elsewhere), so its tests can be journeys across the site
    journey_pages = {c["url"]: pages[c["url"]] for c in reachable
                     if c["url"] in pages and not suite.redirected(c, pages[c["url"]])}
    # (AI tests run signed out: never planned across pages seen signed in)
    extra, ai_note = ([], None) if profile.max_ai_tests == 0 else await ai_plan.ai_tests(
        analysis, project.get("prompt"), (blueprint or {}).get("frameworks"), profile=profile,
        pages={} if session else journey_pages)
    planned += extra

    # Breadth: a test per heading, field, button, link and image of every page
    # analyzed above (app/pipeline/coverage.py), after the core tests
    covered: list[dict[str, Any]] = []
    if settings.PIPELINE_COVERAGE:
        covered = coverage.site_coverage(analysis["url"], analysis, journey_pages)
        if session:  # the pages behind the login run from the sign-in test's session
            behind = {suite.normalize(u) for u in journey_pages}
            covered = [{**t, "signed_in": True} if suite.normalize(urljoin(analysis["url"], t.get("page") or "/")) in behind
                       else t for t in covered]
        planned += covered
    if snapshot is not None:
        snapshot["pages"] = journey_pages

    planned = select_by_profile(planned, profile)
    cut = max(0, len(planned) - settings.PIPELINE_MAX_TESTS)
    planned = planned[:settings.PIPELINE_MAX_TESTS]  # the core suite comes first, so coverage is cut first
    generated, created = [], 0
    for test in planned:
        external_id = f"{GENERATED_PREFIX}{project['id']}-{test['slug']}"
        stored: dict[str, Any] = {"steps": test["steps"], "generated_by": "pipeline", "prompt": project.get("prompt")}
        if test.get("about"):  # a coverage test: what it protects and on which page
            stored.update(about=test["about"], page=test.get("page"))
        if test.get("viewport"):  # runs at this screen size (a responsive check)
            stored["viewport"] = test["viewport"]
        if test.get("signed_in"):  # starts from the sign-in test's session
            stored["signed_in"] = True
        description = json.dumps(stored)
        row = db.find_one(TEST_CASES, application_id=application["id"], external_id=external_id)
        if row is None:
            row = TestCaseService.create_test_case(
                db, application_id=application["id"], external_id=external_id, name=test["name"][:255],
                description=description, category=test["category"], priority="normal", owner_uid=owner,
            )
            if test["category"] == "ai" or test.get("quarantined"):
                # A model wrote it, or it assumes what the analysis could not see (a "Log out"
                # control): it runs and reports, but cannot fail a run until someone un-quarantines it
                row = db.update(TEST_CASES, row["id"], quarantined=True)
            created += 1
        elif row.get("description") != description or row.get("name") != test["name"][:255]:
            changes = {"name": test["name"][:255], "description": description,
                       "version": int(row.get("version") or 1) + 1}
            if test["category"] == "ai" and row.get("description") != description:
                # The model reused the id for different steps: what the user
                # trusted is gone, so the new test starts quarantined again
                changes["quarantined"] = True
            row = db.update(TEST_CASES, row["id"], **changes)
        generated.append(row)

    # The written goal, reached once by the AI explorer and replayed from its recording
    explored, explore_note = await explore.explored_test(db, project, application, external_prefix=GENERATED_PREFIX)
    if explored is not None:
        generated.append(explored)

    repo_note = _sync_repo_tests(db, project, application, analysis, blueprint)

    all_rows = db.find(TEST_CASES, application_id=application["id"], order_by="id")
    retired = _retire_unplanned(db, all_rows, {row["id"] for row in generated})
    saved = [tc for tc in all_rows
             if not str(tc.get("external_id") or "").startswith(GENERATED_PREFIX) and not tc.get("retired")]
    from_repo = sum(1 for tc in saved if str(tc.get("external_id") or "").startswith(REPO_PREFIX))
    detail = f"{len(generated) + len(saved)} tests: {len(generated)} generated ({created} new)"
    kept_cov = coverage.counts(t for t in planned if str(t.get("slug", "")).startswith("cov-"))
    if kept_cov:
        detail += (f" · coverage of {1 + len(journey_pages)} page(s): "
                   + ", ".join(f"{n} {kind}" for kind, n in kept_cov.items()))
    if cut:
        detail += f" · {cut} more planned test(s) left out (PIPELINE_MAX_TESTS={settings.PIPELINE_MAX_TESTS})"
    if saved:
        detail += f", {len(saved)} saved" + (f" ({from_repo} from the repository's Playwright tests)" if from_repo else "")
    if repo_note:
        detail += f" · {repo_note}"
    if retired:
        detail += f" · retired {retired} generated test(s) no longer planned"
    if left_out:
        detail += f" · left out {len(left_out)} page(s) that did not load: " + ", ".join(left_out[:4])
    if files:
        detail += (f" · {len(files)} file or data URL(s) answered fine (checked by request, not opened as pages): "
                   + ", ".join(c["label"] for c in files[:4]))
    hidden = (analysis.get("elements_inventory") or {}).get("hidden_controls")
    if hidden:
        detail += f" · {hidden} control(s) hidden on load (in a dialog, tab or menu) were not tested"
    if sign_in_note:
        detail += f" · {sign_in_note}"
    if changing:
        detail += f" · {changing} heading(s) that change between visits (A/B tests, rotating content) not checked"
    if ai_note:
        detail += f" · {ai_note}"
    if explore_note:
        detail += f" · {explore_note}"
    return application, generated + saved, detail


def _sync_repo_tests(db: Store, project: Record, application: Record, analysis: dict[str, Any],
                     blueprint: dict[str, Any] | None) -> str | None:
    """Keep the repository's own Playwright tests as saved tests of the project.

    Ingestion reads them (never runs them) into the blueprint's
    ``playwright_specs``; here each becomes a test the run replays, with its
    steps checked against the analyzed page as Test Studio checks them.  A test
    with a step that cannot be checked is quarantined (it runs and reports but
    cannot fail the run) until someone trusts it, and keeps a lifted quarantine
    while it is unchanged.  A test that cannot be saved (a step Studio would
    refuse, or no check at all) is left out and counted.  Tests no longer in
    the repository are retired.  A blueprint from before specs were read
    changes nothing.  Returns a note for the plan stage, or None.
    """
    specs = (blueprint or {}).get("playwright_specs")
    if specs is None:
        return None
    owner = project.get("owner_uid")
    app_url = project["app_url"]
    prefix = f"{REPO_PREFIX}{project['id']}-"
    seen: set[str] = set()
    created = updated = left_out = 0
    for spec in specs:
        for test in spec.get("tests") or []:
            key = hashlib.sha256(f"{spec['file']}::{test['name']}".encode()).hexdigest()[:16]
            external_id = prefix + key
            checked = studio.check_steps(test.get("steps") or [], analysis, app_url)
            if studio.blocking(checked):
                left_out += 1
                continue
            seen.add(external_id)
            name = f"{test['name']} ({spec['file']})"[:255]
            description = json.dumps({"steps": studio.stored_steps(checked, app_url), "generated_by": "repository",
                                      "file": spec["file"], "start_url": app_url})
            quarantine = studio.needs_quarantine(checked)
            row = db.find_one(TEST_CASES, application_id=application["id"], external_id=external_id)
            if row is None:
                row = TestCaseService.create_test_case(
                    db, application_id=application["id"], external_id=external_id, name=name,
                    description=description, category="repository", priority="normal", owner_uid=owner)
                db.update(TEST_CASES, row["id"], quarantined=quarantine)
                created += 1
            elif row.get("description") != description or row.get("name") != name or row.get("retired"):
                db.update(TEST_CASES, row["id"], name=name, description=description, retired=False,
                          quarantined=quarantine, version=int(row.get("version") or 1) + 1)
                updated += 1
    retired = 0
    for row in db.find(TEST_CASES, application_id=application["id"], order_by="id"):
        if str(row.get("external_id") or "").startswith(prefix) and row["external_id"] not in seen                 and not row.get("retired"):
            db.update(TEST_CASES, row["id"], retired=True)
            retired += 1
    parts = []
    if created or updated:
        parts.append(f"{created} new, {updated} updated from the repository's Playwright tests")
    if left_out:
        parts.append(f"{left_out} repository test(s) left out (a step that cannot run here, or no check)")
    if retired:
        parts.append(f"retired {retired} repository test(s) no longer in it")
    return " · ".join(parts) or None


def _is_sign_in(tc: Record) -> bool:
    """The goal's form test (the one that signs in when the goal is a login)."""
    return str(tc.get("external_id") or "").startswith(GENERATED_PREFIX)         and str(tc.get("external_id")).endswith("-interaction")


def _signed_in_kwargs(tc: Record, sign_in_first: bool, session: list[dict]) -> dict[str, Any]:
    """Session arguments for one test when "sign in first" is on: the sign-in
    test captures its session, linked and route pages start from it.  The
    target page's own tests stay signed out (they check the page as analyzed)."""
    if not sign_in_first:
        return {}
    if _is_sign_in(tc):
        return {"keep_state": session}
    if session and (tc.get("category") in ("link", "route") or _stored(tc).get("signed_in")):
        return {"storage_state": session[-1]}
    return {}


def _stored(tc: Record) -> dict[str, Any]:
    """A test case's stored description (steps and notes), or {}."""
    try:
        stored = json.loads(tc.get("description") or "{}")
    except ValueError:
        return {}
    return stored if isinstance(stored, dict) else {}


async def _sign_in_session(tests: list[dict[str, Any]], url: str) -> tuple[dict | None, str | None]:
    """Run the planned sign-in (the goal's form test) once and return the
    signed-in session it ends with and the page it ended on, or (None, None)
    when there is no sign-in test or it did not get in.  The session stays in
    memory: it holds login cookies."""
    sign_in = next((t for t in tests if t.get("slug") == "interaction"), None)
    if sign_in is None:
        return None, None
    from agents.planner.schemas import TestCase as PlannedCase
    from app.orchestration.converters import test_case_to_engine_plan
    from app.orchestration.orchestrator import parse_stored_steps
    from engine.runner import run_test
    from engine.schemas import RunOptions

    kept: list[dict] = []
    try:
        steps, checks = parse_stored_steps(sign_in["steps"], url)
        case = PlannedCase(test_id="plan-sign-in", name=sign_in["name"], page_url=url, steps=steps, assertions=checks)
        result = await asyncio.wait_for(
            run_test(test_case_to_engine_plan(case, url), RunOptions(headless=True), keep_state=kept), timeout=120)
    except Exception as exc:  # noqa: BLE001 - planning goes on signed out
        logger.info("Signing in while planning did not work: %s", exc)
        return None, None
    if not kept:
        return None, None
    landing = next((s.page_url for s in reversed(result.steps) if s.page_url), None)
    return kept[-1], landing


MAX_LISTED_CHECKS = 8
_VIEWPORT = re.compile(r"^[1-9]\d{2,3}x[1-9]\d{2,3}$")


def _viewport_of(tc: Record) -> str | None:
    """The screen size a test runs at (a responsive check), or None for the default."""
    try:
        stored = json.loads(tc.get("description") or "{}")
    except ValueError:
        return None
    size = stored.get("viewport") if isinstance(stored, dict) else None
    return size if isinstance(size, str) and _VIEWPORT.match(size) else None


def _what_it_checks(tc: Record) -> dict[str, Any]:
    """For the report: how many steps a test has, what its checks verify,
    which page it starts on and (coverage tests) what it protects, so a
    passed test says what passed, not only that it did."""
    try:
        stored = json.loads(tc.get("description") or "{}")
    except ValueError:
        return {}
    steps = stored.get("steps") if isinstance(stored, dict) else stored
    if not isinstance(steps, list):
        return {}
    checks = [str(s.get("description") or "").strip() for s in steps
              if isinstance(s, dict) and "assert" in str(s.get("action") or "").lower()]
    out: dict[str, Any] = {"step_count": len(steps), "checks": [c for c in checks if c][:MAX_LISTED_CHECKS]}
    start = next((s.get("value") for s in steps if isinstance(s, dict)
                  and str(s.get("action") or "").upper() in ("NAVIGATE", "GOTO") and s.get("value")), None)
    page = (stored.get("page") if isinstance(stored, dict) else None) or (urlparse(str(start)).path or "/" if start else None)
    if page:
        out["page"] = page
    if isinstance(stored, dict) and stored.get("about"):
        out["about"] = stored["about"]
    if isinstance(stored, dict) and stored.get("viewport"):
        out["viewport"] = stored["viewport"]
    return out


async def _stage_execute(state: _RunState, test_cases: list[Record], orchestrator: Any,
                         owner: str | None, *, sign_in_first: bool = False) -> list[dict[str, Any]]:
    from app.orchestration.orchestrator import get_platform_orchestrator

    orch = orchestrator or get_platform_orchestrator()
    results: list[dict[str, Any]] = []
    # In memory for this run only: it holds the app's login cookies
    session: list[dict] = []
    if sign_in_first:  # the sign-in test runs first so later pages can start signed in
        test_cases = sorted(test_cases, key=lambda tc: not _is_sign_in(tc))
    state.stage("execute", "running", f"0 of {len(test_cases)} run")
    slots = asyncio.Semaphore(settings.PIPELINE_TEST_CONCURRENCY)
    finished: dict[int, dict[str, Any]] = {}

    async def run_one(idx: int, tc: Record) -> None:
        async with slots:
            await _execute_one(state, orch, tc, owner, sign_in_first, session, finished, idx)
            # In plan order, whichever finished first
            results[:] = [finished[i] for i in sorted(finished)]
            state.stage("execute", "running", f"{len(finished)} of {len(test_cases)} run · last: {tc['name']}")
            state.save(tests=results)

    first = 1
    if sign_in_first and test_cases and _is_sign_in(test_cases[0]):
        # Its session must exist before the signed-in pages start
        await run_one(1, test_cases[0])
        first = 2
    await asyncio.gather(*(run_one(idx, tc) for idx, tc in enumerate(test_cases[first - 1:], start=first)))
    all_failed = sum(1 for r in results if r["status"] == TestExecutionStatus.FAILED.value)
    failed = sum(1 for r in results if r["status"] == TestExecutionStatus.FAILED.value and not r.get("quarantined"))
    quarantined_failed = all_failed - failed
    state.stage("execute", "failed" if failed else "done",
                f"{len(results) - all_failed} of {len(results)} passed" + (f", {failed} failed" if failed else "")
                + (f", {quarantined_failed} quarantined failed (does not fail the run)" if quarantined_failed else ""))
    return results


async def _execute_one(state: _RunState, orch: Any, tc: Record, owner: str | None, sign_in_first: bool,
                       session: list[dict], finished: dict[int, dict[str, Any]], idx: int) -> None:
    """Run one test case and record its result under its plan position *idx*."""
    from engine.schemas import RunOptions

    db = state.db
    execution = TestExecutionService.create_execution(db, test_case_id=tc["id"], owner_uid=owner)
    visual, duration_ms, diagnosis = None, None, None
    try:
        res = await orch.execute_test_run(db=db, execution_id=execution["id"],
                                          options=RunOptions(headless=True, viewport=_viewport_of(tc)),
                                          **_signed_in_kwargs(tc, sign_in_first, session))
        status, error = res.get("status", "FAILED"), res.get("error_message")
        visual, duration_ms, diagnosis = res.get("visual"), res.get("duration_ms"), res.get("diagnosis")
    except StoreUnavailableError:
        raise
    except Exception as exc:
        logger.exception("Pipeline #%s: test %s crashed", state.id, tc["id"])
        status, error = TestExecutionStatus.FAILED.value, f"Execution error: {exc}"
        db.update(TEST_EXECUTIONS, execution["id"], status=status, error_message=error, completed_at=now_iso())
    healed = status == TestExecutionStatus.HEALED.value or (
        status == TestExecutionStatus.PASSED.value and str(error or "").startswith("Self-healed"))
    finished[idx] = {"test_case_id": tc["id"], "name": tc["name"], "category": tc.get("category"),
                     "execution_id": execution["id"], "status": status, "error": error, "healed": healed,
                     "quarantined": bool(tc.get("quarantined")),
                     "visual_changed": bool((visual or {}).get("changed")),
                     "duration_ms": duration_ms, "diagnosis": diagnosis, **_what_it_checks(tc)}


async def _stage_acceptance(state: _RunState, test_cases: list[Record], results: list[dict[str, Any]],
                            app_url: str) -> None:
    """Run new or changed tests that passed on a deliberately broken page
    (``app/pipeline/acceptance.py``) and note each test's verdict."""
    from app.pipeline import acceptance

    counts = {} if settings.ACCEPTANCE_MAX_PER_RUN <= 0 else await acceptance.check_new_tests(
        state.db, test_cases, results, app_url, limit=settings.ACCEPTANCE_MAX_PER_RUN)
    # Re-read: the check above stored new verdicts on the test cases
    fresh = [state.db.get(TEST_CASES, tc["id"]) or tc for tc in test_cases]
    graduated = acceptance.graduate(state.db, fresh, results)
    for r in results:
        if any(g["id"] == r["test_case_id"] for g in graduated):
            r["graduated"] = True
    if graduated:
        record_audit(state.db, actor=state.doc["actor"], kind="pipeline", ref=str(state.id),
                     owner_uid=state.doc.get("owner_uid"), level="success",
                     message=f"Pipeline #{state.id}: {len(graduated)} test(s) left quarantine after failing on a "
                             f"broken page and passing {acceptance.TRUST_PASSES} runs in a row: "
                             + ", ".join(str(g.get('name')) for g in graduated[:5]))
    verdicts = {tc["id"]: (state.db.get(TEST_CASES, tc["id"]) or {}).get("acceptance") for tc in test_cases}
    for r in results:
        if (v := verdicts.get(r["test_case_id"])) and v.get("status"):
            r["acceptance"] = v["status"]
    state.save(tests=results)
    if counts:
        stage = next((s for s in state.doc["stages"] if s["key"] == "execute"), None)
        words = {"verified": "verified", "asserts_nothing": "check nothing", "inconclusive": "inconclusive",
                 "unverifiable": "cannot be checked this way"}
        summary = ", ".join(f"{n} {words.get(k, k)}" for k, n in sorted(counts.items()))
        if stage:
            state.stage("execute", stage["status"], f"{stage.get('detail') or ''} · broken-page check: {summary}")
    if graduated:
        stage = next((s for s in state.doc["stages"] if s["key"] == "execute"), None)
        if stage:
            state.stage("execute", stage["status"], f"{stage.get('detail') or ''} · {len(graduated)} test(s) earned "
                                                    "trust and now count toward the verdict")


def _tested_pages(test_cases: list[Record], app_url: str) -> list[str]:
    """Same-site pages this run's linked-page and route tests opened: the
    security stage scans them as well as the app URL (no crawl of its own)."""
    from urllib.parse import urlsplit

    host = urlsplit(app_url).netloc.lower()
    pages: list[str] = []
    for tc in test_cases:
        if not re.search(r"-(?:link|route)-", str(tc.get("external_id") or "")):
            continue
        try:
            steps = json.loads(tc.get("description") or "{}").get("steps") or []
        except (ValueError, AttributeError):
            continue
        url = next((s.get("value") for s in steps if str(s.get("action", "")).upper() in ("NAVIGATE", "GOTO")), None)
        if url and urlsplit(url).netloc.lower() == host:
            pages.append(url)
    return list(dict.fromkeys(pages))


async def _stage_security(state: _RunState, app_url: str, owner: str | None, scanner: Any,
                          *, active: bool = False, pages: list[str] | None = None,
                          routes: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    from app.api.security import (
        _attach_ai,
        active_scan_refusal,
        get_active_scanner,
        get_scanner,
        scan_result,
        widen_active_scope,
    )
    from app.services import domain_verify
    from security import ActiveScanError, OutOfScopeError, ScanError
    from security import ai as security_ai

    scanner = scanner or get_scanner()
    # Active scanning only when the project asked for it and the server allows it for the owner
    refusal = active_scan_refusal(owner, app_url, state.db) if active else None
    run_active = active and refusal is None
    state.stage("security", "running")
    # One active scanner for every page: its request budget covers the whole run
    active_scanner = get_active_scanner() if run_active else None
    if active_scanner is not None:  # plus the owner's verified sites
        widen_active_scope(active_scanner, domain_verify.active_hosts(state.db, owner))
    urls = list(dict.fromkeys([app_url, *(pages or [])]))[: 1 + settings.SECURITY_MAX_PAGES]
    result: dict[str, Any] = {"findings": [], "reopened": [], "resolved": [], "pages": []}
    found: list[Any] = []  # every page's findings, for AI triage
    skipped = 0
    active_out_of_scope = 0
    for url in urls:
        try:
            snap = await scanner.fetch(url, probe_files=url == app_url)
            # Passive may visit any public site; the active scanner only its own scope
            attack = active_scanner is not None and active_scanner.scope.allows(url)
            if active_scanner is not None and not attack:
                active_out_of_scope += 1
            active_findings = await active_scanner.scan(url) if attack else []
        except OutOfScopeError as exc:
            if url == app_url:
                state.stage("security", "skipped", f"{exc}. Add the host to SECURITY_SCAN_ALLOWED_HOSTS (only hosts you own) to scan it.")
                return None
            skipped += 1
            continue
        except (ScanError, ActiveScanError) as exc:
            if url == app_url:
                state.stage("security", "failed", str(exc))
                return None
            skipped += 1  # another page that did not answer: the rest still count
            continue
        page = scan_result(state.db, scanner, snap, url, actor=state.doc["actor"], owner_uid=owner,
                           extra_findings=active_findings, active=attack,
                           probed=url == app_url and scanner.can_probe(url), routes=routes)
        for key in ("findings", "reopened", "resolved"):
            result[key] += page[key]
        result["pages"].append(url)
        found += scanner.analyze(snap) + active_findings
    detail = tier_detail(result["findings"])
    if len(result["pages"]) > 1:
        detail = f"{len(result['pages'])} pages scanned · {detail}"
    if found and security_ai.enabled():
        # Best effort, as in the API: reasons over these findings only, never contacts the site
        await _attach_ai(result, app_url, found, db=state.db, owner_uid=owner)
        if result.get("ai_triage"):
            detail += " · AI triage added"
    if skipped:
        detail += f" · {skipped} page(s) could not be scanned"
    if result["reopened"]:
        detail += f" · {len(result['reopened'])} reappeared"
    if refusal:
        detail += f" · active scan skipped: {refusal}"
    elif active_out_of_scope:
        detail += " · active scan skipped: the host is not in SECURITY_SCAN_ALLOWED_HOSTS (passive checks ran)"
    state.stage("security", "done", detail)
    return result


def tier_detail(findings: list[dict[str, Any]]) -> str:
    """'1 proven (1 critical) · 2 to check by hand · 6 hardening suggestions', or 'no findings'."""
    proven = Counter(f["severity"] for f in findings if f.get("tier") == "proven")
    parts = []
    if proven:
        by = ", ".join(f"{proven[s]} {s}" for s in ("critical", "high", "medium", "low", "info") if proven[s])
        parts.append(f"{sum(proven.values())} proven ({by})")
    if n := sum(1 for f in findings if f.get("tier") == "unconfirmed"):
        parts.append(f"{n} to check by hand")
    if n := sum(1 for f in findings if f.get("tier") == "hardening"):
        parts.append(_count(n, "hardening suggestion"))
    return " · ".join(parts) or "no findings"


FLAKY_WINDOW = 10  # recent finished runs looked at
FLAKY_FLIPS = 2    # pass↔fail changes in that window that make a test flaky


def flaky_tests(history: list[list[dict[str, Any]]], current: list[dict[str, Any]]) -> set[int]:
    """Test cases whose result flipped between pass and fail at least FLAKY_FLIPS
    times over *history* (older runs' tests, oldest first) plus *current*."""
    outcomes: dict[int, list[bool]] = {}
    for tests in [*history, current]:
        for t in tests:
            outcomes.setdefault(t["test_case_id"], []).append(t["status"] != TestExecutionStatus.FAILED.value)
    return {tc for tc, seq in outcomes.items()
            if sum(1 for a, b in zip(seq, seq[1:], strict=False) if a != b) >= FLAKY_FLIPS}


async def _stage_unit(state: _RunState, project: Record, blueprint: dict[str, Any] | None) -> None:
    """The repository's own unit tests (see ``app.pipeline.unit_tests``): its CI
    checks on the run's commit, else a sandboxed run.  Failing tests fail the
    run; CI still running, or a sandbox that cannot run, never does.  The result
    is kept on the run as ``unit_tests``."""
    from app.api.integrations import git_auth, github_token
    from app.github import GitHubError
    from app.pipeline import ai_fix, unit_tests
    from ingestion import (
        SourceError,
        clone,
        discard_checkout,
        is_git_url,
        resolve_local,
    )

    db = state.db
    owner = project.get("owner_uid")
    repo = (project.get("repo_url") or "").strip()
    mode = settings.UNIT_TESTS
    if mode == "off":
        state.stage("unit", "skipped", "Off on this server (UNIT_TESTS=off)")
        return
    if not repo:
        state.stage("unit", "skipped", "No repository linked to this project")
        return
    if blueprint is not None and "test_suites" in blueprint and not blueprint["test_suites"]:
        state.stage("unit", "skipped", "The repository has no unit tests")
        return

    state.stage("unit", "running")
    result: dict[str, Any] | None = None
    ci_note = ""
    if mode in ("auto", "ci"):
        try:
            token = await asyncio.to_thread(github_token, db, owner)
            result = await unit_tests.from_ci(repo, token, state.doc.get("commit_sha"),
                                              wait=settings.UNIT_TESTS_CI_WAIT)
        except GitHubError as exc:
            ci_note = f"CI results not readable: {exc}"
        if result is None and not ci_note:
            ci_note = "No CI checks on this commit" if "github.com" in repo else "CI results are read from GitHub only"
    # The sandbox: the tests themselves when CI has no results, and to reproduce a
    # CI failure for an AI fix (a fix is kept only when the sandbox shows it works)
    want_tests = result is None and mode in ("auto", "sandbox")
    want_fix = result is not None and result["status"] == "failed" and mode != "ci" and ai_fix.enabled()
    fix_note = ""
    if want_tests or want_fix:
        reason = await asyncio.to_thread(unit_tests.unavailable_reason)
        if reason and want_tests:
            state.stage("unit", "skipped", (f"{ci_note}; " if ci_note else "") + f"sandbox not used: {reason}")
            return
        if reason:
            fix_note = f"AI fix not tried: {reason}"
        root = None
        try:
            if not reason:
                if is_git_url(repo):
                    auth = await asyncio.to_thread(git_auth, db, owner, repo)
                    from app.api.ingest import _git_hosts

                    root = await asyncio.to_thread(clone, repo, Path(settings.INGEST_WORKSPACE), _git_hosts(), auth=auth)
                elif settings.INGEST_ALLOW_LOCAL_PATHS:
                    root = resolve_local(repo)
                else:
                    raise SourceError("Local folder paths are disabled on this server")
                plan = unit_tests.plan_for(root)
                if plan is None and want_tests:
                    state.stage("unit", "skipped", (f"{ci_note}; " if ci_note else "")
                                + "no pytest, npm/yarn/pnpm test script or go test found to run")
                    return
                if plan is None:
                    fix_note = "AI fix not tried: no test command the sandbox can run"
                else:
                    sandboxed = await asyncio.to_thread(unit_tests.run_in_sandbox, root, plan)
                    if want_tests:
                        result = sandboxed
                    if sandboxed["status"] == "failed" and ai_fix.enabled():
                        fix_note = await _ai_fix(state, project, root, plan, sandboxed)
                    elif want_fix:
                        fix_note = "AI fix not tried: the CI failure did not reproduce in the sandbox"
        except (SourceError, unit_tests.SandboxError) as exc:
            if want_tests:
                state.stage("unit", "failed", f"Sandbox: {exc}")
                return
            fix_note = f"AI fix not tried: {exc}"
        finally:
            if root is not None and is_git_url(repo):
                discard_checkout(root)
    if result is None:
        state.stage("unit", "skipped", ci_note)
        return

    state.save(unit_tests=result)
    status = {"passed": "done", "failed": "failed", "pending": "done", "none": "done", "error": "failed"}[result["status"]]
    state.stage("unit", status, result["detail"] + (f" · {fix_note}" if fix_note else ""))


async def _ai_fix(state: _RunState, project: Record, root: Path, plan: Any, failing: dict[str, Any]) -> str:
    """Ask for a verified AI fix of the failing tests (``app.pipeline.ai_fix``) and,
    when there is one, store it as a fix patch for review (``ai_fix`` on the run).
    A commit already tried by an earlier run is not tried again: that run's fix
    (or its "no fix") is reused, so a schedule does not ask the model every time.
    Returns a note for the stage."""
    from app.api import patches
    from app.pipeline import ai_fix

    db = state.db
    commit = await asyncio.to_thread(patches._commit, root)
    if commit:
        for earlier in db.find(PIPELINE_RUNS, project_id=project["id"], order_by="id", descending=True, limit=20):
            tried = earlier.get("ai_fix") or {}
            if earlier["id"] < state.id and tried.get("commit") == commit:
                state.save(ai_fix=tried)
                return (f"AI fix from run #{earlier['id']} (same commit) ready for review" if tried.get("id")
                        else f"no AI fix for this commit (tried in run #{earlier['id']})")
    proposal = await ai_fix.propose(root, plan, failing)
    if proposal["status"] != "verified":
        state.save(ai_fix={"id": None, "commit": commit, "note": proposal["note"]})
        return f"no AI fix: {proposal['note']}"

    files = proposal["files"]
    built = {
        "commit": commit, "frameworks": [plan.framework],
        "files": [{"path": f["path"], "diff": f["diff"], "verified": True, "check_note": None} for f in files],
        "contents": {f["path"]: f["content"] for f in files},  # stays on the server, for the pull request
        "applied": [{"check_id": "TESTS", "how": proposal["explanation"] or "AI fix", "file": f["path"]} for f in files],
        "manual": [], "patch": "".join(f["diff"] for f in files),
    }
    verification = {"framework": plan.framework, "before": proposal["before"], "after": proposal["after"]}
    row = await asyncio.to_thread(
        patches.store_patch, db, built, target_url=project["app_url"], repo=project["repo_url"], findings=[],
        actor=state.doc["actor"], owner_uid=project.get("owner_uid"), run_id=state.id, project_id=project["id"],
        kind="tests", explanation=proposal["explanation"], verification=verification)
    state.save(ai_fix={"id": row["id"], "commit": commit, "files": len(files), "attempts": proposal["attempts"],
                       "pull_request": None})
    return (f"AI fix verified in the sandbox ({proposal['before']['failed']} failing → all "
            f"{proposal['after']['passed']} passing), ready for review")


async def _stage_fix(state: _RunState, project: Record, security: dict[str, Any] | None) -> None:
    """Build a fix patch for the open findings this run's scan left, against the
    project's repository, and link it to the run (``fix_patch``).

    Nothing is changed in the repository: the patch is a proposal that the run
    page shows for review, and a pull request is opened only when a person
    approves it.  A patch identical to the newest one already proposed for this
    project is not stored again (scheduled runs would pile up copies); the run
    links that one instead, with its pull request if one was opened.  Failing to
    build a patch never fails the run.
    """
    from app.api import patches
    from app.api.integrations import git_auth
    from app.services import security_service as findings_store
    from ingestion import SourceError

    db = state.db
    owner = project.get("owner_uid")
    repo = (project.get("repo_url") or "").strip()
    if security is None:
        state.stage("fix", "skipped", "No security scan in this run")
        return
    if not repo:
        state.stage("fix", "skipped", "No repository linked to the project: add it to propose code fixes")
        return
    owned = {"owner_uid": owner} if owner else {}
    findings = [
        findings_store.serialize(row)
        for url in security.get("pages") or [project["app_url"]]
        for row in findings_store.list_findings(db, target_url=url, **owned)
        if row["status"] == "open"
    ]
    findings = list({f["key"]: f for f in findings}.values())
    if not findings:
        state.stage("fix", "skipped", "No open findings to fix")
        return

    state.stage("fix", "running")
    try:
        auth = await asyncio.to_thread(git_auth, db, owner, repo)
        built = await asyncio.to_thread(patches.generate, repo, findings, project["app_url"], auth)
    except SourceError as exc:
        state.stage("fix", "failed", f"Could not read the repository: {exc}")
        return
    except Exception as exc:  # a proposal is extra: the run's results stand without it
        logger.exception("Pipeline #%s: fix proposal failed", state.id)
        state.stage("fix", "failed", f"Could not build a fix patch: {exc}")
        return

    if not built["files"]:
        why = f"{len(built['manual'])} finding(s) need a change by hand" if built["manual"] else "no automatic fix applies"
        state.stage("fix", "done", f"No code change proposed: {why}")
        state.save(fix_patch={"id": None, "fixes": 0, "files": 0, "manual": len(built["manual"]), "pull_request": None})
        return

    previous = [r for r in db.find(FIX_PATCHES, project_id=project["id"], order_by="id", descending=True, limit=10,
                                   **owned) if r.get("kind") not in ("tests", "suite")][:1]
    if previous and previous[0].get("patch") == built["patch"] and previous[0].get("repo") == repo:
        row = previous[0]
        reused = True
    else:
        row = await asyncio.to_thread(
            patches.store_patch, db, built, target_url=project["app_url"], repo=repo, findings=findings,
            actor=state.doc["actor"], owner_uid=owner, run_id=state.id, project_id=project["id"])
        reused = False
    pr = row.get("pull_request")
    detail = f"{len(built['applied'])} fix(es) in {len(built['files'])} file(s)"
    if pr:
        detail += f" · already proposed in pull request #{pr.get('number')}"
    else:
        detail += " · ready for review" + (f" (unchanged since run #{row.get('run_id')})"
                                          if reused and row.get("run_id") else "")
    if built["manual"]:
        detail += f" · {len(built['manual'])} need a change by hand"
    state.stage("fix", "done", detail)
    state.save(fix_patch={"id": row["id"], "fixes": len(built["applied"]), "files": len(built["files"]),
                          "manual": len(built["manual"]), "pull_request": pr})


def _add_to_stage(state: _RunState, key: str, status: str | None, note: str) -> None:
    """Append *note* to a stage's detail; *status* replaces a skipped one."""
    stage = next((s for s in state.doc["stages"] if s["key"] == key), None)
    if stage is None:
        return
    current = stage.get("status")
    new_status = status if status and current in ("skipped", "pending", None) else current
    detail = stage.get("detail") or ""
    if current == "skipped" and status:
        detail = ""  # the earlier "skipped" reason no longer describes the stage
    state.stage(key, new_status, f"{detail} · {note}" if detail else note)


async def _stage_suite(state: _RunState, project: Record, test_cases: list[Record],
                       results: list[dict[str, Any]]) -> None:
    """Export the tests TestSphere trusts for this project as Playwright files
    for its repository (``app/pipeline/suite_export.py``), stored as a patch
    (``kind`` "suite") linked to the run as ``suite_patch``.  An unchanged
    suite reuses the newest patch without reading the repository again."""
    from app.api import patches
    from app.api.integrations import git_auth
    from app.pipeline import acceptance, suite_export
    from ingestion import SourceError

    db = state.db
    repo = (project.get("repo_url") or "").strip()
    if not repo or not settings.PIPELINE_EXPORT_SUITE:
        return
    fresh = [db.get(TEST_CASES, tc["id"]) or tc for tc in test_cases]
    built = suite_export.build(fresh, results, base_url=project["app_url"], steps_of=acceptance.steps_of,
                               github=suite_export.is_github(repo))
    if built is None:
        _add_to_stage(state, "fix", "done", "no passing, trusted test to commit to the repository yet")
        return
    owned = {"owner_uid": project.get("owner_uid")} if project.get("owner_uid") else {}
    previous = next((r for r in db.find(FIX_PATCHES, project_id=project["id"], order_by="id", descending=True,
                                        limit=20, **owned) if r.get("kind") == "suite"), None)
    if previous and (previous.get("suite") or {}).get("hash") == built["hash"] and previous.get("repo") == repo:
        state.save(suite_patch={"id": previous["id"], "tests": built["tests"], "pull_request": previous.get("pull_request"),
                                "unchanged": True})
        pr = previous.get("pull_request")
        _add_to_stage(state, "fix", "done", f"test suite unchanged ({built['tests']} tests)"
                      + (f", in pull request #{pr.get('number')}" if pr else ""))
        return
    try:
        auth = await asyncio.to_thread(git_auth, db, project.get("owner_uid"), repo)
        commit, current = await asyncio.to_thread(patches.read_files, repo, sorted(built["files"]), auth)
    except SourceError as exc:
        _add_to_stage(state, "fix", "failed", f"test suite not exported: could not read the repository ({exc})")
        return
    changed = {path: content for path, content in built["files"].items() if current.get(path) != content}
    if not changed:
        _add_to_stage(state, "fix", "done", f"the repository already has these {built['tests']} tests")
        return
    files = [{"path": path, "diff": suite_export.diff(path, current.get(path), content), "verified": None,
              "check_note": None} for path, content in sorted(changed.items())]
    record = {
        "commit": commit, "frameworks": ["playwright"], "files": files, "contents": changed,
        "applied": [{"check_id": "SUITE", "how": f"{built['tests']} browser test(s) as Playwright files",
                     "file": f"{suite_export.ROOT}/"}],
        "manual": [], "patch": "".join(f["diff"] for f in files),
    }
    row = await asyncio.to_thread(
        patches.store_patch, db, record, target_url=project["app_url"], repo=repo, findings=[],
        actor=state.doc["actor"], owner_uid=project.get("owner_uid"), run_id=state.id, project_id=project["id"],
        kind="suite", suite={k: built[k] for k in ("tests", "verified", "groups", "workflow", "hash")})
    state.save(suite_patch={"id": row["id"], "tests": built["tests"], "pull_request": None})
    _add_to_stage(state, "fix", "done", f"{built['tests']} trusted test(s) exported as Playwright files "
                                        f"({len(changed)} file(s) to add or change), ready for a pull request")


async def _auto_pull_requests(state: _RunState, project: Record) -> None:
    """With the project's ``auto_pr`` on, propose this run's patches without a
    click: the test suite (pushed onto TestSphere's open suite pull request
    when there is one, so runs never pile up pull requests) and the security
    fixes.  A failure is noted on the stage; it never fails the run."""
    from app.api import patches

    if not project.get("auto_pr"):
        return
    db = state.db
    uid = project.get("owner_uid")
    notes = []
    for field in ("suite_patch", "fix_patch"):
        link = state.doc.get(field) or {}
        row = db.get(FIX_PATCHES, link["id"]) if link.get("id") else None
        if row is None or row.get("pull_request") or not row.get("contents"):
            continue
        what = "test suite" if field == "suite_patch" else "security fixes"
        try:
            pr = None
            if row.get("kind") == "suite":
                earlier = next((r for r in db.find(FIX_PATCHES, project_id=project["id"], order_by="id",
                                                   descending=True, limit=20)
                                if r.get("kind") == "suite" and r["id"] < row["id"] and r.get("pull_request")), None)
                if earlier:
                    pr = await asyncio.to_thread(patches.update_pull_request, db, row, earlier, uid)
                    if pr:
                        notes.append(f"{what}: new commit on pull request #{pr['number']}")
            if pr is None:
                pr = await asyncio.to_thread(patches.create_pull_request, db, row, uid)
                notes.append(f"{what}: opened pull request #{pr['number']}")
        except patches.PullRequestError as exc:
            notes.append(f"{what}: pull request not opened ({exc})")
            continue
        state.save(**{field: {**link, "pull_request": pr}})
        record_audit(db, actor=state.doc["actor"], kind="patch", ref=str(row["id"]), owner_uid=uid,
                     message=f"Pipeline #{state.id} proposed its {what} in pull request #{pr['number']} on {row['repo']}")
    if notes:
        _add_to_stage(state, "fix", None, "auto pull request: " + "; ".join(notes))


def _report(state: _RunState, project: Record, results: list[dict[str, Any]], security: dict[str, Any] | None) -> None:
    db = state.db
    state.stage("report", "running")
    finished = [r for r in db.find(PIPELINE_RUNS, project_id=project["id"], order_by="id", descending=True,
                                   limit=FLAKY_WINDOW + 5)
                if r["id"] < state.id and r["status"] in ("passed", "failed")]
    previous = finished[0] if finished else None
    flaky = flaky_tests([r.get("tests") or [] for r in reversed(finished[:FLAKY_WINDOW])], results)
    for r in results:
        r["flaky"] = r["test_case_id"] in flaky
    before = {t["test_case_id"]: t["status"] for t in (previous or {}).get("tests", [])}
    regressions = [
        {"kind": "test", "name": r["name"], "test_case_id": r["test_case_id"], "was": before[r["test_case_id"]],
         "now": r["status"], "error": r["error"]}
        for r in results
        if r["status"] == TestExecutionStatus.FAILED.value and before.get(r["test_case_id"]) in ("PASSED", "HEALED")
    ]
    for f in (security or {}).get("reopened", []):
        regressions.append({"kind": "security", "name": f"{f['check_id']}: {f['title']}", "was": "resolved", "now": "open"})

    counts = Counter(r["status"] for r in results)
    # A quarantined test still runs and is reported, but cannot fail the run
    failed = sum(1 for r in results if r["status"] == TestExecutionStatus.FAILED.value and not r.get("quarantined"))
    summary = {
        "goal_untested": bool(state.doc.get("goal_untested")),
        "goal_untested_parts": list(state.doc.get("goal_untested_parts") or []),
        "total": len(results),
        "passed": counts.get(TestExecutionStatus.PASSED.value, 0) + counts.get(TestExecutionStatus.HEALED.value, 0),
        "failed": failed,
        "healed": sum(1 for r in results if r["healed"]),
        "flaky": len(flaky & {r["test_case_id"] for r in results}),
        "quarantined_failed": counts.get(TestExecutionStatus.FAILED.value, 0) - failed,
        # Only proven findings count in severity totals and the verdict; the rest are listed, not counted
        "findings": dict(Counter(f["severity"] for f in (security or {}).get("findings", [])
                                 if f.get("tier") == "proven")) if security else None,
        "unconfirmed": sum(1 for f in (security or {}).get("findings", []) if f.get("tier") == "unconfirmed"),
        "hardening": sum(1 for f in (security or {}).get("findings", []) if f.get("tier") == "hardening"),
        # Passing tests the broken-page check showed fail when their page breaks
        "verified": sum(1 for r in results if r.get("acceptance") == "verified"
                        and r["status"] in (TestExecutionStatus.PASSED.value, TestExecutionStatus.HEALED.value)),
        "render_only": sum(1 for r in results if r.get("acceptance") in ("unverifiable", "asserts_nothing")),
        "previous_run_id": previous["id"] if previous else None,
        "visual_changes": sum(1 for r in results if r.get("visual_changed")),
        "database": state.doc.get("database"),
    }
    summary["narrative"] = run_summary(summary, results, regressions)
    unit = state.doc.get("unit_tests") or {}
    summary["unit_tests"] = ({k: unit.get(k) for k in ("source", "status", "passed", "failed", "running", "framework")}
                             if unit else None)
    status = "failed" if failed or unit.get("status") == "failed" else "passed"
    state.stage("report", "done", f"{summary['passed']}/{summary['total']} passed"
                                  + (f" · repository tests failed ({unit.get('detail')})" if unit.get("status") == "failed" else "")
                                  + (f" · {len(regressions)} regression(s)" if regressions else "")
                                  + (f" · {summary['visual_changes']} visual change(s) to review"
                                     if summary["visual_changes"] else "")
                                  + (f" · compared with run #{previous['id']}" if previous else " · first run")
                                  + (f" · {line}" if (line := dbsource.summary_line(summary["database"])) else ""))
    state.save(status=status, summary=summary, regressions=regressions, tests=results, finished_at=now_iso(),
               security_findings=_findings_for_report(security))
    _finish_project(db, project, state)
    record_audit(
        db, actor=state.doc["actor"], kind="pipeline", ref=str(state.id), owner_uid=project.get("owner_uid"),
        level="error" if regressions or failed else ("warn" if summary["healed"] else "success"),
        message=f"Pipeline #{state.id} for {project['name']}: {summary['passed']}/{summary['total']} passed"
                + (f", {summary['healed']} healed" if summary["healed"] else "")
                + (f", {len(regressions)} regression(s)" if regressions else ""),
    )


MAX_REPORTED_FINDINGS = 100
_SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
_TIER_RANK = {"proven": 0, "unconfirmed": 1, "hardening": 2}


def _findings_for_report(security: dict[str, Any] | None) -> list[dict[str, Any]] | None:
    """The scan's findings as the report lists them, most serious first (None: no scan ran)."""
    if not security:
        return None
    rows = sorted(security.get("findings") or [], key=lambda f: (_TIER_RANK.get(f.get("tier"), 3),
                                                                 _SEVERITY_RANK.get(f.get("severity"), 5)))
    return [{"check_id": f.get("check_id"), "title": f.get("title"), "severity": f.get("severity"),
             "tier": f.get("tier"), "component": str(f.get("component") or "")[:300],
             "evidence": [str(e)[:300] for e in (f.get("evidence") or [])[:3]],
             "root_cause": str(f.get("root_cause") or "")[:500], "recommendation": str(f.get("recommendation") or "")[:500]}
            for f in rows[:MAX_REPORTED_FINDINGS]]


def _finish_project(db: Store, project: Record, state: _RunState) -> None:
    db.update(PROJECTS, project["id"], last_run_id=state.id, last_run_status=state.doc["status"],
              last_run_at=state.doc.get("finished_at") or now_iso())
