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
``backend.worker`` claims and executes them.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import Counter
from collections.abc import Callable
from typing import Any

import httpx

from backend import dbsource
from backend.config import settings
from backend.database.session import get_store
from backend.database.store import Record, Store, StoreUnavailableError, now_iso
from backend.models import (
    APPLICATIONS,
    BLUEPRINTS,
    PIPELINE_RUNS,
    PROJECTS,
    TEST_CASES,
    TEST_EXECUTIONS,
)
from backend.models.test_execution import TestExecutionStatus
from backend.notify import notify_run
from backend.pipeline import ai_plan, suite
from backend.services.security_service import record_audit
from backend.services.test_case_service import TestCaseService
from backend.services.test_execution_service import TestExecutionService
from backend.services.url_analyzer import URLAnalyzerService, get_verifying_first

logger = logging.getLogger("testsphere.pipeline")

STAGES = (
    ("codebase", "Codebase ingestion"),
    ("analyze", "Page analysis"),
    ("plan", "Test planning"),
    ("execute", "Test execution"),
    ("heal", "Self-healing"),
    ("security", "Security scan"),
    ("report", "Report"),
)
ACTIVE = ("queued", "running")
TRIGGERS = ("manual", "schedule", "webhook")
GENERATED_PREFIX = "pipe-"

_tasks: set = set()
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
        task.add_done_callback(_tasks.discard)
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
                    s["started_at"] = now_iso()
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
    async with _run_lock():
        state = _RunState(db, run)
        project = db.get(PROJECTS, run["project_id"])
        if project is None:
            state.save(status="error", error="The project was deleted.", finished_at=now_iso())
            return db.get(PIPELINE_RUNS, run_id)
        state.save(status="running", started_at=now_iso())
        try:
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
    """Show the run's result on the pushed commit in GitHub (when the owner connected GitHub)."""
    from backend.api.integrations import github_token
    from backend.github import GitHubClient, GitHubError, parse_repo
    from backend.notify import run_url

    repo = parse_repo(project.get("repo_url"))
    if not (run.get("commit_sha") and repo):
        return False
    token = github_token(db, project.get("owner_uid"))
    if not token:
        return False
    s = run.get("summary") or {}
    state = {"passed": "success", "failed": "failure"}.get(run.get("status"), "error")
    text = (f"{s.get('passed', 0)}/{s.get('total', 0)} tests passed" if s else (run.get("error") or run.get("status", "")))
    if s.get("goal_untested"):
        text += " (goal not tested)"
    elif s.get("goal_untested_parts"):
        text += " (goal partly tested)"
    try:
        with GitHubClient(token) as gh:
            gh.set_commit_status(*repo, run["commit_sha"], state, f"Run #{run['id']}: {text}", run_url(run["id"]))
        return True
    except GitHubError as exc:
        logger.warning("Could not set the commit status for run #%s: %s", run["id"], exc)
        return False


def _deploy_if_green(db: Store, project: Record, run: Record) -> None:
    """Close the loop: a clean run of a project with deploy_on_pass ships it (stage 6)."""
    from backend.pipeline import deploy

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
    analysis = await URLAnalyzerService.analyze_live_website(url=app_url, prompt=project.get("prompt"))
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
    application, test_cases, plan_detail = await _plan(db, project, analysis, blueprint)
    goal_untested = bool((project.get("prompt") or "").strip()) and not any(
        str(tc.get("external_id", "")).endswith("-interaction") for tc in test_cases)
    if goal_untested:
        plan_detail += (" · Your goal was not tested: no form fields or buttons were found on the page"
                        + ("" if analysis.get("rendered_in_browser") else " (even before scripts ran)"))
    # Parts of the goal no step tests ("…and fly to the moon"): say so, never claim them
    untested_parts = [] if goal_untested else \
        list(((analysis.get("synthesized_test_case") or {}).get("goal") or {}).get("untested") or [])
    if untested_parts:
        plan_detail += " · Not tested from your goal: " + "; ".join(f"“{p[:80]}”" for p in untested_parts)
    state.save(goal_untested=goal_untested, goal_untested_parts=untested_parts)
    state.stage("plan", "done", plan_detail)

    # ── execute (with AI analysis + healing inside the orchestrator) ──
    db_check = await asyncio.to_thread(dbsource.start_check, project)
    results = await _stage_execute(state, test_cases, orchestrator, owner)
    goal_text = URLAnalyzerService.prompt_values(project.get("prompt")).get("text")
    database = await asyncio.to_thread(dbsource.finish_check, db_check, [goal_text] if goal_text else [])
    state.save(database=database)

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
    security = await _stage_security(state, app_url, owner, scanner)

    # ── report ──
    _report(state, project, results, security)


async def _stage_codebase(state: _RunState, project: Record) -> dict[str, Any] | None:
    from backend.api.ingest import ingest_source, save_blueprint
    from backend.api.integrations import git_auth
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
                                    f"{len(blueprint.get('routes', []))} routes, {len(blueprint.get('risks', []))} risks{dep_note}")
    return blueprint


async def _reachable(urls: list[str]) -> dict[str, int | None]:
    """HTTP status per URL (None when unreachable), checked concurrently."""
    from backend.netguard import BlockedTargetError

    async def one(url: str) -> int | None:
        try:
            response, _ = await get_verifying_first(url, timeout=8.0,
                                                    headers={"User-Agent": URLAnalyzerService.USER_AGENT})
            return response.status_code
        except (httpx.HTTPError, BlockedTargetError):
            return None

    codes = await asyncio.gather(*(one(u) for u in urls))
    return dict(zip(urls, codes, strict=True))


async def _analyze_pages(urls: list[str]) -> dict[str, dict[str, Any]]:
    """Each page's analysis (title, headings, controls); a page that fails or
    takes too long is left out and keeps a plain render check."""
    async def one(url: str) -> dict[str, Any] | None:
        try:
            page = await asyncio.wait_for(URLAnalyzerService.analyze_live_website(url=url), timeout=45)
        except Exception as exc:  # noqa: BLE001 - one page's analysis never stops the run
            logger.info("Could not analyze %s for content checks: %s", url, exc)
            return None
        return page if page.get("success") else None

    found = await asyncio.gather(*(one(u) for u in urls))
    return {u: p for u, p in zip(urls, found, strict=True) if p}


async def _plan(db: Store, project: Record, analysis: dict[str, Any],
                blueprint: dict[str, Any] | None) -> tuple[Record, list[Record], str]:
    owner = project.get("owner_uid")
    app_url = project["app_url"]
    application = db.find_one(APPLICATIONS, project_id=project["id"], base_url=app_url)
    if application is None:
        application = db.insert(APPLICATIONS, project_id=project["id"], name=(analysis.get("page_title") or project["name"])[:60],
                                base_url=app_url, description="Created by the automated pipeline", owner_uid=owner)

    planned = suite.page_tests(analysis, project.get("prompt"))
    extra, ai_note = await ai_plan.ai_tests(analysis, project.get("prompt"), (blueprint or {}).get("frameworks"))
    planned += extra
    candidates = suite.candidate_pages(analysis, blueprint, link_limit=settings.PIPELINE_LINK_PAGES,
                                       route_limit=settings.PIPELINE_ROUTE_PAGES)
    codes = await _reachable([c["url"] for c in candidates]) if candidates else {}
    left_out = [f"{c['label']} ({codes[c['url']] or 'unreachable'})" for c in candidates
                if not codes.get(c["url"]) or codes[c["url"]] >= 400]
    reachable = [c for c in candidates if codes.get(c["url"]) and codes[c["url"]] < 400]
    pages = await _analyze_pages([c["url"] for c in reachable[:settings.PIPELINE_DEEP_PAGES]])
    planned += [suite.page_check_test(c, pages[c["url"]]) if pages.get(c["url"]) else suite.render_test(c)
                for c in reachable]

    generated, created = [], 0
    for test in planned:
        external_id = f"{GENERATED_PREFIX}{project['id']}-{test['slug']}"
        description = json.dumps({"steps": test["steps"], "generated_by": "pipeline", "prompt": project.get("prompt")})
        row = db.find_one(TEST_CASES, application_id=application["id"], external_id=external_id)
        if row is None:
            row = TestCaseService.create_test_case(
                db, application_id=application["id"], external_id=external_id, name=test["name"][:255],
                description=description, category=test["category"], priority="normal", owner_uid=owner,
            )
            if test["category"] == "ai":
                # A model wrote it: it runs and reports, but cannot fail a run until someone un-quarantines it
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

    saved = [tc for tc in db.find(TEST_CASES, application_id=application["id"], order_by="id")
             if not str(tc.get("external_id") or "").startswith(GENERATED_PREFIX)]
    detail = f"{len(generated) + len(saved)} tests: {len(generated)} generated ({created} new)"
    if saved:
        detail += f", {len(saved)} saved"
    if left_out:
        detail += f" · left out {len(left_out)} page(s) that did not load: " + ", ".join(left_out[:4])
    if ai_note:
        detail += f" · {ai_note}"
    return application, generated + saved, detail


async def _stage_execute(state: _RunState, test_cases: list[Record], orchestrator: Any,
                         owner: str | None) -> list[dict[str, Any]]:
    from backend.orchestration.orchestrator import get_platform_orchestrator
    from engine.schemas import RunOptions

    orch = orchestrator or get_platform_orchestrator()
    db = state.db
    results: list[dict[str, Any]] = []
    state.stage("execute", "running", f"0 of {len(test_cases)} run")
    for idx, tc in enumerate(test_cases, start=1):
        state.stage("execute", "running", f"Running {idx} of {len(test_cases)}: {tc['name']}")
        execution = TestExecutionService.create_execution(db, test_case_id=tc["id"], owner_uid=owner)
        visual = None
        try:
            res = await orch.execute_test_run(db=db, execution_id=execution["id"], options=RunOptions(headless=True))
            status, error = res.get("status", "FAILED"), res.get("error_message")
            visual = res.get("visual")
        except StoreUnavailableError:
            raise
        except Exception as exc:
            logger.exception("Pipeline #%s: test %s crashed", state.id, tc["id"])
            status, error = TestExecutionStatus.FAILED.value, f"Execution error: {exc}"
            db.update(TEST_EXECUTIONS, execution["id"], status=status, error_message=error, completed_at=now_iso())
        healed = status == TestExecutionStatus.HEALED.value or (
            status == TestExecutionStatus.PASSED.value and str(error or "").startswith("Self-healed"))
        results.append({"test_case_id": tc["id"], "name": tc["name"], "category": tc.get("category"),
                        "execution_id": execution["id"], "status": status, "error": error, "healed": healed,
                        "quarantined": bool(tc.get("quarantined")),
                        "visual_changed": bool((visual or {}).get("changed"))})
        state.save(tests=results)
    all_failed = sum(1 for r in results if r["status"] == TestExecutionStatus.FAILED.value)
    failed = sum(1 for r in results if r["status"] == TestExecutionStatus.FAILED.value and not r.get("quarantined"))
    quarantined_failed = all_failed - failed
    state.stage("execute", "failed" if failed else "done",
                f"{len(results) - all_failed} of {len(results)} passed" + (f", {failed} failed" if failed else "")
                + (f", {quarantined_failed} quarantined failed (does not fail the run)" if quarantined_failed else ""))
    return results


async def _stage_security(state: _RunState, app_url: str, owner: str | None, scanner: Any) -> dict[str, Any] | None:
    from backend.api.security import get_scanner, scan_result
    from security import OutOfScopeError, ScanError

    scanner = scanner or get_scanner()
    state.stage("security", "running")
    try:
        snap = await scanner.fetch(app_url)
    except OutOfScopeError as exc:
        state.stage("security", "skipped", f"{exc}. Add the host to SECURITY_SCAN_ALLOWED_HOSTS (only hosts you own) to scan it.")
        return None
    except ScanError as exc:
        state.stage("security", "failed", str(exc))
        return None
    result = scan_result(state.db, scanner, snap, app_url, actor=state.doc["actor"], owner_uid=owner)
    counts = Counter(f["severity"] for f in result["findings"])
    detail = ", ".join(f"{counts[s]} {s}" for s in ("critical", "high", "medium", "low", "info") if counts[s]) or "no findings"
    if result["reopened"]:
        detail += f" · {len(result['reopened'])} reappeared"
    state.stage("security", "done", detail)
    return result


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
        "findings": dict(Counter(f["severity"] for f in (security or {}).get("findings", []))) if security else None,
        "previous_run_id": previous["id"] if previous else None,
        "visual_changes": sum(1 for r in results if r.get("visual_changed")),
        "database": state.doc.get("database"),
    }
    status = "failed" if failed else "passed"
    state.stage("report", "done", f"{summary['passed']}/{summary['total']} passed"
                                  + (f" · {len(regressions)} regression(s)" if regressions else "")
                                  + (f" · {summary['visual_changes']} visual change(s) to review"
                                     if summary["visual_changes"] else "")
                                  + (f" · compared with run #{previous['id']}" if previous else " · first run")
                                  + (f" · {line}" if (line := dbsource.summary_line(summary["database"])) else ""))
    state.save(status=status, summary=summary, regressions=regressions, tests=results, finished_at=now_iso())
    _finish_project(db, project, state)
    record_audit(
        db, actor=state.doc["actor"], kind="pipeline", ref=str(state.id), owner_uid=project.get("owner_uid"),
        level="error" if regressions or failed else ("warn" if summary["healed"] else "success"),
        message=f"Pipeline #{state.id} for {project['name']}: {summary['passed']}/{summary['total']} passed"
                + (f", {summary['healed']} healed" if summary["healed"] else "")
                + (f", {len(regressions)} regression(s)" if regressions else ""),
    )


def _finish_project(db: Store, project: Record, state: _RunState) -> None:
    db.update(PROJECTS, project["id"], last_run_id=state.id, last_run_status=state.doc["status"],
              last_run_at=state.doc.get("finished_at") or now_iso())
