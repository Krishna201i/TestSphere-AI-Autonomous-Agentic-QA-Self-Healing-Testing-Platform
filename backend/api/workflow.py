"""
TestSphere-AI — Workflow Orchestration & Telemetry API Router.

Provides endpoints to trigger autonomous test runs and stream real-time
Server-Sent Events (SSE) telemetry to platform dashboards.
"""

import json
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from backend.database.session import get_db
from backend.models.application import Application
from backend.models.project import Project
from backend.models.test_case import TestCase
from backend.models.test_execution import TestExecution, TestExecutionStatus
from backend.orchestration.orchestrator import PlatformWorkflowOrchestrator
from backend.services.url_analyzer import URLAnalyzerService
from engine.schemas import RunOptions

router = APIRouter(prefix="/workflow", tags=["Workflow & Orchestration"])

_workflow_orchestrator = PlatformWorkflowOrchestrator()


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
async def analyze_url_endpoint(req: AnalyzeURLRequest) -> Dict[str, Any]:
    """Perform live DOM element extraction, security/a11y audit, and QA synthesis on any URL."""
    return await URLAnalyzerService.analyze_live_website(
        url=req.url,
        prompt=req.prompt,
        test_case_name=req.test_case_name,
    )


@router.post("/plan-and-execute", status_code=status.HTTP_200_OK)
async def plan_and_execute_workflow(
    payload: Optional[PlanAndExecuteRequest] = None,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Autonomous plan and execute workflow endpoint.
    
    Dynamically identifies or provisions the target application context,
    performs live DOM analysis on real URLs, synthesizes executable test steps,
    creates an execution record, and executes the complete autonomous QA loop.
    """
    req = payload or PlanAndExecuteRequest()
    try:
        live_analysis = None
        if req.test_case_id:
            tc = db.query(TestCase).filter(TestCase.id == req.test_case_id).first()
            if not tc:
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
            except Exception as exc:
                live_analysis = None

            # Locate or create project
            proj = db.query(Project).first()
            if not proj:
                proj = Project(
                    name="TestSphere Auto QA",
                    description="Autonomous agentic QA testing workspace",
                )
                db.add(proj)
                db.commit()
                db.refresh(proj)

            # Determine application name and URL
            resolved_app_name = req.app_name
            resolved_app_url = target_url
            if live_analysis and live_analysis.get("page_title"):
                if not resolved_app_name or resolved_app_name in ("Demo Application", "E-Commerce Webapp"):
                    resolved_app_name = live_analysis["page_title"][:60]
                resolved_app_url = live_analysis["url"]

            # Locate or create application
            if req.application_id:
                app_entity = (
                    db.query(Application)
                    .filter(Application.id == req.application_id)
                    .first()
                )
                if not app_entity:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"Application #{req.application_id} not found",
                    )
            else:
                app_entity = (
                    db.query(Application)
                    .filter(Application.name == resolved_app_name)
                    .first()
                )
                if not app_entity:
                    app_entity = Application(
                        project_id=proj.id,
                        name=resolved_app_name or "Demo Application",
                        base_url=resolved_app_url,
                    )
                    db.add(app_entity)
                    db.commit()
                    db.refresh(app_entity)

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

            tc = TestCase(
                application_id=app_entity.id,
                name=resolved_tc_name or "Autonomous Planned Test Case",
                description=desc_content,
                external_id=f"tc-auto-{app_entity.id}",
            )
            db.add(tc)
            db.commit()
            db.refresh(tc)

        # Create execution record
        execution = TestExecution(
            test_case_id=tc.id,
            status=TestExecutionStatus.PENDING.value,
        )
        db.add(execution)
        db.commit()
        db.refresh(execution)

        res = await _workflow_orchestrator.execute_test_run(
            db=db,
            execution_id=execution.id,
            options=RunOptions(headless=req.headless),
        )

        if live_analysis and "analysis" not in res:
            res["analysis"] = live_analysis

        return res
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Plan-and-execute workflow error: {exc}",
        )


@router.post("/execute/{execution_id}", status_code=status.HTTP_200_OK)
async def execute_test_workflow(
    execution_id: int,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Execute a test execution run with autonomous AI diagnosis and self-healing."""
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
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Workflow execution encountered an error: {exc}",
        )


@router.get("/stream/{workflow_id}")
async def stream_workflow_events(workflow_id: str) -> StreamingResponse:
    """Stream live workflow state transitions and events using Server-Sent Events (SSE)."""
    return StreamingResponse(
        _workflow_orchestrator.stream_execution_events(workflow_id),
        media_type="text/event-stream",
    )
