"""
TestSphere-AI — Test Studio API: write a test in plain English.

    POST /projects/{id}/studio/draft     description -> steps checked against the live page
    POST /projects/{id}/studio/verify    re-check steps after the user edited them
    GET  /projects/{id}/studio/tests     the project's studio tests (with their last result)
    POST /projects/{id}/studio/tests     save reviewed steps as a test
    PUT  /projects/{id}/studio/tests/{tc} change a saved test
    GET  /studio/tests/{tc}/playwright   any saved test as a Playwright .spec.ts

A saved test is an ordinary saved test case of the project: every pipeline run,
schedule and webhook runs it, self-healing writes repaired locators back into
it, and ``POST /workflow/plan-and-execute`` with its ``test_case_id`` runs it
alone.  Logic lives in ``app/services/test_studio.py``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from typing import Any
from urllib.parse import urljoin, urlparse

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from app.api.projects import owned_project
from app.auth import User, actor_for, ensure_owned, get_current_user
from app.config import settings
from app.database.session import get_db
from app.database.store import Record, Store
from app.models import APPLICATIONS, TEST_CASES
from app.ratelimit import limit_runs
from app.services import test_studio as studio
from app.services.security_service import record_audit
from app.services.test_case_service import TestCaseService
from app.services.test_execution_service import TestExecutionService
from app.services.url_analyzer import URLAnalyzerService

logger = logging.getLogger("testsphere.studio")

router = APIRouter(tags=["Test Studio"])

EXTERNAL_PREFIX = "studio-"
ANALYSIS_TTL = 300.0  # seconds an analysis is reused while a test is being edited
_analyses: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}


class DraftRequest(BaseModel):
    instruction: str = Field(..., min_length=3, max_length=studio.MAX_INSTRUCTION,
                             description="The test, in plain English")
    start_path: str | None = Field(None, max_length=500, description="Page of the project's site to start on")


class VerifyRequest(BaseModel):
    steps: list[dict[str, Any]] = Field(..., max_length=studio.MAX_STEPS)
    start_path: str | None = Field(None, max_length=500)


class SaveRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    instruction: str | None = Field(None, max_length=studio.MAX_INSTRUCTION)
    steps: list[dict[str, Any]] = Field(..., min_length=1, max_length=studio.MAX_STEPS)
    start_path: str | None = Field(None, max_length=500)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _start_url(project: Record, start_path: str | None) -> str:
    base = (project.get("app_url") or "").strip()
    if not base:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="This project has no site URL yet: set one in Autopilot first.")
    url = urljoin(base, (start_path or "").strip()) if start_path else base
    if (urlparse(url).hostname or "").lower() != (urlparse(base).hostname or "").lower():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="The start page must be on the project's own site.")
    return url


async def _analysis(owner: str, url: str, instruction: str | None = None) -> dict[str, Any]:
    """The live page's analysis; reused for a few minutes per user and page (edits re-check often)."""
    key = (owner, url)
    cached = _analyses.get(key)
    if instruction is None and cached and time.monotonic() - cached[0] < ANALYSIS_TTL:
        return cached[1]
    try:
        analysis = await URLAnalyzerService.analyze_live_website(url=url, prompt=instruction)
    except ValueError as exc:  # a URL the server may not fetch (netguard), or malformed
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    if not analysis.get("success"):
        reason = f"HTTP {analysis['status_code']}" if analysis.get("status_code") else analysis.get("error") or "unreachable"
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=f"Could not load {url} ({reason}), so the steps cannot be checked against it.")
    for k in [k for k, (at, _) in _analyses.items() if time.monotonic() - at >= ANALYSIS_TTL]:
        _analyses.pop(k, None)
    _analyses[key] = (time.monotonic(), analysis)
    return analysis


def _model_enabled() -> bool:
    from agents.llm.config import LLMConfig

    return LLMConfig.from_env().provider != "mock"


def _application(db: Store, project: Record) -> Record:
    """The project's application for its site (the one the pipeline runs tests under)."""
    app_url = project["app_url"]
    application = db.find_one(APPLICATIONS, project_id=project["id"], base_url=app_url)
    if application is None:
        application = db.insert(APPLICATIONS, project_id=project["id"], name=project["name"][:60], base_url=app_url,
                                description="Created by Test Studio", owner_uid=project.get("owner_uid"))
    return application


def _checked(body_steps: list[dict[str, Any]], analysis: dict[str, Any], url: str) -> dict[str, Any]:
    steps = studio.check_steps(body_steps, analysis, url)
    return {"steps": steps, "problems": studio.blocking(steps), "quarantine": studio.needs_quarantine(steps)}


def _stored(tc: Record) -> dict[str, Any]:
    try:
        data = json.loads(tc.get("description") or "{}")
    except ValueError:
        data = {}
    return data if isinstance(data, dict) else {}


def _view(db: Store, tc: Record) -> dict[str, Any]:
    data = _stored(tc)
    last = TestExecutionService.list_executions(db, test_case_id=tc["id"], limit=1)
    return {
        "id": tc["id"], "name": tc.get("name"), "version": tc.get("version") or 1,
        "quarantined": bool(tc.get("quarantined")), "created_at": tc.get("created_at"),
        "updated_at": tc.get("updated_at"), "instruction": data.get("instruction"),
        "start_url": data.get("start_url"), "steps": data.get("steps") or [],
        "last_result": ({"execution_id": last[0]["id"], "status": last[0].get("status"),
                         "finished_at": last[0].get("completed_at")} if last else None),
    }


def _studio_test(db: Store, user: User, project: Record, test_id: int) -> Record:
    tc = ensure_owned(user, db.get(TEST_CASES, test_id), "Test")
    app = db.get(APPLICATIONS, tc["application_id"])
    if not str(tc.get("external_id") or "").startswith(EXTERNAL_PREFIX) or not app \
            or app.get("project_id") != project["id"]:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such Test Studio test in this project.")
    return tc


def _refuse(problems: list[str]) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                         detail="The test cannot be saved yet: " + " ".join(problems))


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/projects/{project_id}/studio/draft")
async def draft_test(project_id: int, body: DraftRequest, db: Store = Depends(get_db),
                     user: User = Depends(limit_runs)) -> dict[str, Any]:
    """Turn a plain-English description into steps, checked against the live page (nothing runs)."""
    project = await asyncio.to_thread(owned_project, db, user, project_id)
    url = _start_url(project, body.start_path)
    analysis = await _analysis(user.uid, url, body.instruction)

    source, note, draft = "rules", None, None
    if _model_enabled():
        try:
            from app.orchestration.orchestrator import create_platform_llm_client

            draft = await studio.draft_with_model(body.instruction, analysis, create_platform_llm_client(),
                                                  timeout=settings.PIPELINE_AI_PLANNER_TIMEOUT)
            source = "ai"
        except Exception as exc:  # noqa: BLE001 - the rule-based planner answers instead, and says why
            logger.warning("Test Studio model draft failed: %s", exc)
            note = f"The AI model could not answer ({type(exc).__name__}); the rule-based planner wrote these steps."
    else:
        note = "No AI model is configured (LLM_PROVIDER=mock): the rule-based planner wrote these steps."
    if draft is None:
        draft = studio.draft_with_rules(body.instruction, analysis)

    return {
        "name": draft["name"] or studio.default_name(body.instruction),
        "instruction": body.instruction, "start_url": url, "page_title": analysis.get("page_title"),
        "source": source, "note": note, "not_covered": draft["not_covered"],
        **_checked(draft["steps"], analysis, url),
    }


@router.post("/projects/{project_id}/studio/verify")
async def verify_steps(project_id: int, body: VerifyRequest, db: Store = Depends(get_db),
                       user: User = Depends(get_current_user)) -> dict[str, Any]:
    """Check edited steps against the page again (nothing runs)."""
    project = await asyncio.to_thread(owned_project, db, user, project_id)
    url = _start_url(project, body.start_path)
    return _checked(body.steps, await _analysis(user.uid, url), url)


@router.get("/projects/{project_id}/studio/tests")
def list_studio_tests(project_id: int, db: Store = Depends(get_db),
                      user: User = Depends(get_current_user)) -> list[dict[str, Any]]:
    project = owned_project(db, user, project_id)
    tests: list[dict[str, Any]] = []
    for app in db.find(APPLICATIONS, project_id=project["id"]):
        tests += [_view(db, tc) for tc in db.find(TEST_CASES, order_by="id", application_id=app["id"])
                  if str(tc.get("external_id") or "").startswith(EXTERNAL_PREFIX)]
    return tests


@router.post("/projects/{project_id}/studio/tests", status_code=status.HTTP_201_CREATED)
async def save_studio_test(project_id: int, body: SaveRequest, db: Store = Depends(get_db),
                           user: User = Depends(get_current_user)) -> dict[str, Any]:
    """Save reviewed steps as a test the pipeline runs (quarantined while a step is unverified)."""
    project = await asyncio.to_thread(owned_project, db, user, project_id)
    url = _start_url(project, body.start_path)
    checked = _checked(body.steps, await _analysis(user.uid, url), url)
    if checked["problems"]:
        raise _refuse(checked["problems"])

    def save() -> Record:
        application = _application(db, project)
        description = json.dumps({"steps": studio.stored_steps(checked["steps"], url), "generated_by": "studio",
                                  "instruction": body.instruction, "start_url": url})
        tc = TestCaseService.create_test_case(
            db, application_id=application["id"], external_id=f"{EXTERNAL_PREFIX}{project['id']}-{uuid.uuid4().hex[:12]}",
            name=body.name.strip(), description=description, category="studio", priority="normal",
            owner_uid=project.get("owner_uid"))
        tc = db.update(TEST_CASES, tc["id"], quarantined=checked["quarantine"]) or tc
        record_audit(db, actor=actor_for(user, None), kind="qa", ref=str(tc["id"]), owner_uid=project.get("owner_uid"),
                     message=f"Test Studio: saved '{tc['name']}' in {project['name']}"
                             + (" (quarantined: a step is not on the analyzed page)" if checked["quarantine"] else ""))
        return tc

    return _view(db, await asyncio.to_thread(save))


@router.put("/projects/{project_id}/studio/tests/{test_id}")
async def update_studio_test(project_id: int, test_id: int, body: SaveRequest, db: Store = Depends(get_db),
                             user: User = Depends(get_current_user)) -> dict[str, Any]:
    """Change a saved test's name or steps (a new version; checked again first)."""
    project = await asyncio.to_thread(owned_project, db, user, project_id)
    tc = await asyncio.to_thread(_studio_test, db, user, project, test_id)
    url = _start_url(project, body.start_path)
    checked = _checked(body.steps, await _analysis(user.uid, url), url)
    if checked["problems"]:
        raise _refuse(checked["problems"])
    old = _stored(tc)
    description = json.dumps({"steps": studio.stored_steps(checked["steps"], url), "generated_by": "studio",
                              "instruction": body.instruction if body.instruction is not None else old.get("instruction"),
                              "start_url": url})
    changes: dict[str, Any] = {"name": body.name.strip(), "description": description,
                               "quarantined": checked["quarantine"]}
    if description != tc.get("description"):
        changes["version"] = int(tc.get("version") or 1) + 1
    tc = await asyncio.to_thread(db.update, TEST_CASES, tc["id"], **changes)
    return _view(db, tc)


@router.get("/studio/tests/{test_id}/playwright", response_class=PlainTextResponse)
def export_playwright(test_id: int, db: Store = Depends(get_db),
                      user: User = Depends(get_current_user)) -> PlainTextResponse:
    """Any saved test (studio or generated) as a Playwright Test file."""
    tc = ensure_owned(user, db.get(TEST_CASES, test_id), "Test")
    steps = _stored(tc).get("steps")
    if not isinstance(steps, list) or not steps:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="This test has no stored steps.")
    slug = re.sub(r"[^a-z0-9]+", "-", str(tc.get("name") or "test").lower()).strip("-")[:60] or "test"
    return PlainTextResponse(studio.to_playwright(str(tc.get("name") or "Test"), steps),
                             headers={"Content-Disposition": f'attachment; filename="{slug}.spec.ts"'})


# ---------------------------------------------------------------------------
# Codebase-aware: suggested flows and imported Playwright tests
# ---------------------------------------------------------------------------


class SuggestRequest(BaseModel):
    start_path: str | None = Field(None, max_length=500)


class ImportRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=200_000, description="A Playwright test file's contents")
    filename: str = Field("spec.ts", max_length=200)
    start_path: str | None = Field(None, max_length=500)


MAX_REPO_SPECS = 40


def _latest_blueprint(db: Store, project: Record) -> dict[str, Any] | None:
    from app.models import BLUEPRINTS

    rows = db.find(BLUEPRINTS, project_id=project["id"], order_by="id", descending=True, limit=1)
    if not rows:
        return None
    try:
        data = json.loads(rows[0].get("data") or "{}")
    except ValueError:
        return None
    return {**data, "_id": rows[0]["id"], "_at": rows[0].get("created_at")} if isinstance(data, dict) else None


@router.post("/projects/{project_id}/studio/suggest")
async def suggest_flows(project_id: int, body: SuggestRequest | None = None, db: Store = Depends(get_db),
                        user: User = Depends(limit_runs)) -> dict[str, Any]:
    """The user flows most worth testing, from the project's latest codebase blueprint and its start page."""
    from app.pipeline.profile import profile_of
    from app.services import flow_suggest

    project = await asyncio.to_thread(owned_project, db, user, project_id)
    url = _start_url(project, body.start_path if body else None)
    analysis = await _analysis(user.uid, url)
    blueprint = await asyncio.to_thread(_latest_blueprint, db, project)

    source, note, flows = "rules", None, None
    if _model_enabled():
        try:
            from app.orchestration.orchestrator import create_platform_llm_client

            flows = await flow_suggest.model_flows(blueprint, analysis, create_platform_llm_client(),
                                                   timeout=settings.PIPELINE_AI_PLANNER_TIMEOUT)
            source = "ai"
        except Exception as exc:  # noqa: BLE001 - the rules answer instead, and say why
            logger.warning("Flow suggestions from the model failed: %s", exc)
            note = f"The AI model could not answer ({type(exc).__name__}); these come from your routes and page."
    else:
        note = "No AI model is configured: these come from your routes and the page."
    if flows is None:
        flows = flow_suggest.rule_flows(blueprint, analysis, profile_of(project).test_data)
    if blueprint is None:
        hint = "Link a repository to the project (Projects, or Integrations) for suggestions from your code too."
        note = f"{note} {hint}" if note else hint
    return {"source": source, "note": note, "flows": flows,
            "blueprint": {"id": blueprint["_id"], "name": blueprint.get("name"), "analyzed_at": blueprint.get("_at"),
                          "routes": len(blueprint.get("routes") or [])} if blueprint else None}


def _imported(parsed: list[dict[str, Any]], analysis: dict[str, Any], url: str) -> list[dict[str, Any]]:
    """Each parsed file's tests with their steps checked against the start page."""
    out = []
    for f in parsed:
        tests = []
        for t in f["tests"]:
            checked = _checked(t["steps"], analysis, url)
            tests.append({"name": t["name"], "not_imported": t["not_imported"], **checked})
        out.append({"file": f["file"], "tests": tests, "skipped_tests": f.get("skipped_tests", 0)})
    return out


@router.post("/projects/{project_id}/studio/import")
async def import_playwright(project_id: int, body: ImportRequest, db: Store = Depends(get_db),
                            user: User = Depends(get_current_user)) -> dict[str, Any]:
    """A Playwright test file read as text (never run) and turned into reviewable drafts."""
    from app.services.playwright_import import parse_spec

    project = await asyncio.to_thread(owned_project, db, user, project_id)
    url = _start_url(project, body.start_path)
    parsed = parse_spec(body.text, body.filename.rsplit("/", 1)[-1])
    if not parsed["tests"]:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="No Playwright tests found: expected test('name', async ({ page }) => { ... }).")
    return {"files": _imported([parsed], await _analysis(user.uid, url), url)}


def _repo_specs(repo_url: str, auth: Any) -> list[dict[str, Any]]:
    """Clone the repository (the ingestion clone: shallow, limited, no hooks), read its test files, delete it."""
    from pathlib import Path

    from app.api.ingest import _git_hosts
    from app.services.playwright_import import MAX_FILE_BYTES, SPEC_FILE, parse_spec
    from ingestion.source import clone, discard_checkout

    root = clone(repo_url, Path(settings.INGEST_WORKSPACE), _git_hosts(), auth=auth)
    try:
        parsed = []
        for path in sorted(root.rglob("*")):
            if len(parsed) >= MAX_REPO_SPECS:
                break
            rel = path.relative_to(root).as_posix()
            if not path.is_file() or not SPEC_FILE.search(path.name) or "node_modules/" in rel or path.stat().st_size > MAX_FILE_BYTES:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if "@playwright/test" not in text and "page." not in text:
                continue  # a Jest or Vitest unit test, not a browser test
            result = parse_spec(text, rel)
            if result["tests"]:
                parsed.append(result)
        return parsed
    finally:
        discard_checkout(root)


@router.post("/projects/{project_id}/studio/import-repo")
async def import_from_repo(project_id: int, body: SuggestRequest | None = None, db: Store = Depends(get_db),
                           user: User = Depends(limit_runs)) -> dict[str, Any]:
    """Every Playwright test in the project's repository, as reviewable drafts (nothing in it runs)."""
    from app.api.integrations import git_auth
    from ingestion import SourceError

    project = await asyncio.to_thread(owned_project, db, user, project_id)
    repo = (project.get("repo_url") or "").strip()
    if not repo:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="This project has no repository: add its Git URL in Projects first.")
    url = _start_url(project, body.start_path if body else None)
    try:
        auth = await asyncio.to_thread(git_auth, db, user.uid, repo)
        parsed = await asyncio.to_thread(_repo_specs, repo, auth)
    except SourceError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    if not parsed:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="No Playwright tests found in the repository (*.spec.ts / *.test.js using @playwright/test).")
    return {"files": _imported(parsed, await _analysis(user.uid, url), url)}
