"""
TestSphere-AI — Workflow Orchestration & Telemetry API Router.

Provides endpoints to trigger autonomous test runs and stream real-time
Server-Sent Events (SSE) telemetry to platform dashboards.
"""

from typing import Any, Dict
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from backend.database.session import get_db
from backend.orchestration.orchestrator import PlatformWorkflowOrchestrator

router = APIRouter(prefix="/workflow", tags=["Workflow & Orchestration"])

_workflow_orchestrator = PlatformWorkflowOrchestrator()


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
