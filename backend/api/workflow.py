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


@router.post("/plan-and-execute", status_code=status.HTTP_200_OK)
async def plan_and_execute_workflow(
    payload: Optional[PlanAndExecuteRequest] = None,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Autonomous plan and execute workflow endpoint.
    
    Dynamically identifies or provisions the target application context,
    synthesizes or loads test cases with multi-step definitions, creates
    an execution record, and executes the complete autonomous QA loop.
    """
    req = payload or PlanAndExecuteRequest()
    try:
        if req.test_case_id:
            tc = db.query(TestCase).filter(TestCase.id == req.test_case_id).first()
            if not tc:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"TestCase #{req.test_case_id} not found",
                )
        else:
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
                    .filter(Application.name == req.app_name)
                    .first()
                )
                if not app_entity:
                    app_entity = Application(
                        project_id=proj.id,
                        name=req.app_name or "Demo Application",
                        base_url=req.app_url or "https://example.com",
                    )
                    db.add(app_entity)
                    db.commit()
                    db.refresh(app_entity)

            desc_content = (
                json.dumps({"steps": req.steps})
                if req.steps
                else (req.prompt or "Autonomous test case")
            )
            tc = TestCase(
                application_id=app_entity.id,
                name=req.test_case_name or "Autonomous Planned Test Case",
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

        return await _workflow_orchestrator.execute_test_run(
            db=db,
            execution_id=execution.id,
            options=RunOptions(headless=req.headless),
        )
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
