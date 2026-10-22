"""
TestSphere-AI — Workflow Orchestration & Telemetry API Router.

Provides endpoints to trigger autonomous test runs and stream real-time
Server-Sent Events (SSE) telemetry to platform dashboards.
"""

import json
import logging
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from backend.auth import User, actor_for, ensure_owned, get_current_user, scope
from backend.ratelimit import limit_runs
from backend.database.session import get_db
from backend.database.store import Store, StoreUnavailableError
from backend.models import APPLICATIONS, TEST_CASES, TEST_EXECUTIONS
from backend.models.test_execution import TestExecutionStatus
from backend.services.application_service import default_project
from backend.services.test_case_service import TestCaseService
from backend.services.test_execution_service import TestExecutionService
from agents.schemas.member3_contract import format_sse_event
from backend.orchestration.orchestrator import get_platform_orchestrator
from backend.services.security_service import record_audit
from backend.services.url_analyzer import URLAnalyzerService
from engine.schemas import RunOptions

logger = logging.getLogger("testsphere.workflow")

router = APIRouter(prefix="/workflow", tags=["Workflow & Orchestration"])

_workflow_orchestrator = get_platform_orchestrator()


class PlanAndExecuteRequest(BaseModel):
    application_id: Optional[int] = None
    app_name: Optional[str] = "Demo Application"
    app_url: Optional[str] = "https://example.com"
    test_case_id: Optional[int] = None
    test_case_name: Optional[str] = None
    prompt: Optional[str] = None
    steps: Optional[List[Dict[str, Any]]] = None
    headless: bool = True


class AnalyzeURLRequest(BaseModel):
    url: str
    prompt: Optional[str] = None
    test_case_name: Optional[str] = None


@router.post("/analyze", status_code=status.HTTP_200_OK)
async def analyze_url_endpoint(req: AnalyzeURLRequest, _user: User = Depends(limit_runs)) -> Dict[str, Any]:
    """Perform live DOM element extraction, security/a11y audit, and QA synthesis on any URL."""
    return await URLAnalyzerService.analyze_live_website(
        url=req.url,
        prompt=req.prompt,
        test_case_name=req.test_case_name,
    )


@router.post("/plan-and-execute", status_code=status.HTTP_200_OK)
async def plan_and_execute_workflow(
    payload: Optional[PlanAndExecuteRequest] = None,
    db: Store = Depends(get_db),
    user: User = Depends(limit_runs),
) -> Dict[str, Any]:
    """Autonomous plan and execute workflow endpoint.
    
    Dynamically identifies or provisions the target application context,
    performs live DOM analysis on real URLs, synthesizes executable test steps,
    creates an execution record, and executes the complete autonomous QA loop.
    """
    req = payload or PlanAndExecuteRequest()
    actor = actor_for(user, None)
    try:
        live_analysis = None
        if req.test_case_id:
            tc = db.get(TEST_CASES, req.test_case_id)
            if not tc or not (user.local or tc.get("owner_uid") == user.uid):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"TestCase #{req.test_case_id} not found",
                )
        else:
            # Perform live website inspection on the target URL
            target_url = req.app_url or "https://example.com"
            try:
                live_analysis = await URLAnalyzerService.analyze_live_website(
                    url=target_url,
                    prompt=req.prompt,
                    test_case_name=req.test_case_name,
                )
            except Exception as exc:  # noqa: BLE001 - reported to the user below
                logger.exception("Page analysis of %s crashed", target_url)
                live_analysis = {"success": False, "error": f"page analysis failed ({type(exc).__name__}: {exc})"}

            # Never synthesize tests from a page that failed to load: a 404 page
            # would yield a test asserting "Not Found" and pass.
            if not req.steps and not (live_analysis and live_analysis.get("success")):
                reason = (
                    f"HTTP {live_analysis.get('status_code')}" if live_analysis and live_analysis.get("status_code")
                    else (live_analysis or {}).get("error") or "unreachable"
                )
                record_audit(db, actor=actor, kind="qa", level="error", owner_uid=user.uid,
                             message=f"QA run refused: {target_url} did not load ({reason})")
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Could not load {target_url} ({reason}). Check the URL — no tests were planned from an error page.",
                )

            # Locate or create project
            proj = default_project(db, None if user.local else user.uid)

            # Determine application name and URL
            resolved_app_name = req.app_name
            resolved_app_url = target_url
            if live_analysis and live_analysis.get("page_title"):
                if not resolved_app_name or resolved_app_name in ("Demo Application", "E-Commerce Webapp"):
                    resolved_app_name = live_analysis["page_title"][:60]
                resolved_app_url = live_analysis["url"]

            # Locate or create application
            if req.application_id:
                app_entity = db.get(APPLICATIONS, req.application_id)
                if not app_entity or not (user.local or app_entity.get("owner_uid") == user.uid):
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Application #{req.application_id} not found",
                    )
            else:
                app_entity = (
                    db.find_one(APPLICATIONS, name=resolved_app_name, **scope(user)) if resolved_app_name else None
                )
                if not app_entity:
                    app_entity = db.insert(
                        APPLICATIONS,
                        project_id=proj.id,
                        name=resolved_app_name or "Demo Application",
                        base_url=resolved_app_url,
                        description=None,
                        owner_uid=user.uid,
                    )

            # Determine executable test steps
            effective_steps = req.steps
            if not effective_steps and live_analysis:
                effective_steps = live_analysis["synthesized_test_case"]["steps"]

            resolved_tc_name = req.test_case_name
            if not resolved_tc_name and live_analysis:
                resolved_tc_name = live_analysis["synthesized_test_case"]["name"]

            desc_content = json.dumps({
                "steps": effective_steps or [],
                "analysis": live_analysis,
                "prompt": req.prompt,
            })

            tc = TestCaseService.create_test_case(
                db,
                application_id=app_entity.id,
                name=resolved_tc_name or "Autonomous Planned Test Case",
                description=desc_content,
                external_id=f"tc-auto-{app_entity.id}",
                owner_uid=user.uid,
            )

        # Create execution record
        execution = TestExecutionService.create_execution(
            db, test_case_id=tc.id, status=TestExecutionStatus.PENDING, owner_uid=user.uid,
        )

        res = await _workflow_orchestrator.execute_test_run(
            db=db,
            execution_id=execution.id,
            options=RunOptions(headless=req.headless),
        )

        if live_analysis and "analysis" not in res:
            res["analysis"] = live_analysis

        run_status = res.get("status", "UNKNOWN")
        record_audit(
            db, actor=actor, kind="qa", ref=str(execution.id), owner_uid=user.uid,
            level={"FAILED": "error", "HEALED": "warn", "PASSED": "success"}.get(run_status, "info"),
            message=f"QA run #{execution.id} ({tc.name}) -> {run_status}"
                    + (f": {res['error_message']}" if res.get("error_message") else ""),
        )
        return res
    except (HTTPException, StoreUnavailableError):
        raise
    except Exception as exc:  # noqa: BLE001 - logged with traceback, generic answer to the client
        logger.exception("Plan-and-execute failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Plan-and-execute failed unexpectedly ({type(exc).__name__}). The error is in the server log.",
        ) from exc


@router.post("/execute/{execution_id}", status_code=status.HTTP_200_OK)
async def execute_test_workflow(
    execution_id: int,
    db: Store = Depends(get_db),
    user: User = Depends(limit_runs),
) -> Dict[str, Any]:
    """Execute a test execution run with autonomous AI diagnosis and self-healing."""
    ensure_owned(user, db.get(TEST_EXECUTIONS, execution_id), f"TestExecution #{execution_id}")
    try:
        return await _workflow_orchestrator.execute_test_run(
            db=db,
            execution_id=execution_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    except StoreUnavailableError:
        raise  # handled app-wide as 503 with a readable cause
    except Exception as exc:  # noqa: BLE001 - logged with traceback, generic answer to the client
        logger.exception("Workflow execution #%s failed", execution_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Workflow execution failed unexpectedly ({type(exc).__name__}). The error is in the server log.",
        ) from exc


@router.get("/stream/{workflow_id}")
async def stream_workflow_events(
    workflow_id: str,
    db: Store = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Recorded events of a workflow run, as Server-Sent Events (SSE).

    *workflow_id* is ``wf-exec-<execution id>`` or the bare execution id; only
    the execution's owner may read it.
    """
    raw = workflow_id.removeprefix("wf-exec-")
    execution = db.get(TEST_EXECUTIONS, int(raw)) if raw.isdigit() else None
    ensure_owned(user, execution, "Workflow")
    events = _workflow_orchestrator.execution_events(execution["id"])
    if not events:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="No recorded events for this workflow (it has not run since the server started).")
    return StreamingResponse(
        (format_sse_event(event) for event in events),
        media_type="text/event-stream",
    )
