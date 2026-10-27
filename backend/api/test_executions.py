"""
TestSphere-AI — Test Executions API Router.

Provides endpoints to record and inspect test execution state (only the caller's own).
Delegates persistence and business logic to TestExecutionService.
Does not launch Playwright, execute browser tests, or invoke AI agents.
"""


from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from backend.api.schemas import (
    TestExecutionCreate,
    TestExecutionDetail,
    TestExecutionResponse,
    TestExecutionUpdate,
)
from backend.artifacts import (
    accept_baseline,
    baseline_key,
    delete_execution_artifacts,
    get_artifact_store,
)
from backend.auth import User, actor_for, ensure_owned, get_current_user, scope
from backend.database.session import get_db
from backend.database.store import Record, Store
from backend.models import TEST_CASES, TEST_EXECUTIONS
from backend.services.exceptions import InvalidExecutionStatusError
from backend.services.security_service import record_audit
from backend.services.test_execution_service import TestExecutionService

router = APIRouter(prefix="/test-executions", tags=["Test Executions"])


def owned_execution(db: Store, user: User, execution_id: int) -> Record:
    return ensure_owned(user, db.get(TEST_EXECUTIONS, execution_id), "Test execution")


@router.post("", response_model=TestExecutionResponse, status_code=status.HTTP_201_CREATED)
def create_test_execution(
    payload: TestExecutionCreate,
    db: Store = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Record:
    """Record a new test execution instance."""
    ensure_owned(user, db.get(TEST_CASES, payload.test_case_id), "Test case")
    try:
        return TestExecutionService.create_execution(
            db=db,
            test_case_id=payload.test_case_id,
            status=payload.status,
            started_at=payload.started_at,
            completed_at=payload.completed_at,
            duration_ms=payload.duration_ms,
            error_message=payload.error_message,
            owner_uid=user.uid,
        )
    except InvalidExecutionStatusError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.get("", response_model=list[TestExecutionResponse])
def list_test_executions(
    test_case_id: int | None = Query(None, description="Filter by parent TestCase ID"),
    limit: int | None = Query(None, ge=1, le=1000, description="Only the newest N (still returned oldest first)"),
    db: Store = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Record]:
    """Retrieve the caller's test executions, oldest first, with optional test_case_id filtering."""
    return TestExecutionService.list_executions(db=db, test_case_id=test_case_id, limit=limit, **scope(user))


@router.get("/stats")
def test_execution_stats(db: Store = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, int]:
    """Totals over all of the caller's finished executions (counted, not downloaded)."""
    counts = TestExecutionService.execution_counts(db, **scope(user))
    return {"total": sum(counts.values()), **counts}


@router.get("/{execution_id}", response_model=TestExecutionDetail)
def get_test_execution(
    execution_id: int,
    db: Store = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Record:
    """Retrieve a single test execution with its step results and artifact keys
    (for a visual check, also the key of the baseline it is compared with)."""
    execution = owned_execution(db, user, execution_id)
    if execution.get("visual"):
        baseline = baseline_key(execution.get("owner_uid") or "local-dev", execution["test_case_id"])
        execution = {**execution, "visual": {**execution["visual"], "baseline": baseline}}
    return execution


def artifact_keys(execution: Record) -> set[str]:
    """Every artifact key recorded on *execution* (the only ones it may serve)."""
    keys = {execution.get("trace")}
    for step in execution.get("steps") or []:
        keys.update((step.get("screenshot"), step.get("dom")))
    visual = execution.get("visual") or {}
    keys.update((visual.get("current"), visual.get("diff")))
    if visual:  # the baseline it was compared with (the test case's current one)
        keys.add(baseline_key(execution.get("owner_uid") or "local-dev", execution["test_case_id"]))
    return {k for k in keys if k}


@router.get("/{execution_id}/artifact")
def get_execution_artifact(
    execution_id: int,
    key: str = Query(..., max_length=500, description="An artifact key from the execution's steps or trace"),
    db: Store = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    """A screenshot (shown inline), DOM snapshot or Playwright trace (downloads)."""
    execution = owned_execution(db, user, execution_id)
    if key not in artifact_keys(execution):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No such artifact on this execution.")
    found = get_artifact_store().get(key)
    if not found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="This artifact has expired or was removed.")
    data, content_type = found
    name = key.rsplit("/", 2)
    filename = f"execution-{execution_id}-{'-'.join(name[-2:])}" if len(name) >= 2 else f"execution-{execution_id}"
    headers = {
        "Cache-Control": "private, max-age=3600",
        "X-Content-Type-Options": "nosniff",
        # A saved page is someone else's HTML: never render it on this origin
        "Content-Security-Policy": "sandbox",
    }
    if content_type == "image/png":
        headers["Content-Disposition"] = f'inline; filename="{filename}"'
    else:
        headers["Content-Disposition"] = f'attachment; filename="{filename}"'
        if content_type.startswith("text/"):
            content_type = "text/plain; charset=utf-8"
    return Response(content=data, media_type=content_type, headers=headers)


@router.post("/{execution_id}/accept-visual")
def accept_visual_change(
    execution_id: int,
    db: Store = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """The screen changed on purpose: make this execution's screenshot the test's new baseline."""
    execution = owned_execution(db, user, execution_id)
    owner = execution.get("owner_uid") or "local-dev"
    if not (execution.get("visual") or {}).get("current") or \
            not accept_baseline(owner, execution_id, execution["test_case_id"]):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="This execution has no screenshot to accept (it failed, or its artifacts expired).")
    visual = {**execution["visual"], "changed": False, "accepted": True}
    db.update(TEST_EXECUTIONS, execution_id, visual=visual)
    record_audit(db, actor=actor_for(user, "dev_active"), kind="visual", ref=str(execution_id), owner_uid=user.uid,
                 message=f"New visual baseline for test case #{execution['test_case_id']} from execution #{execution_id}")
    return {"accepted": True, "visual": visual}


@router.put("/{execution_id}", response_model=TestExecutionResponse)
def update_test_execution(
    execution_id: int,
    payload: TestExecutionUpdate,
    db: Store = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Record:
    """Update execution lifecycle state and metrics."""
    owned_execution(db, user, execution_id)
    try:
        return TestExecutionService.update_execution(
            db=db,
            execution_id=execution_id,
            status=payload.status,
            started_at=payload.started_at,
            completed_at=payload.completed_at,
            duration_ms=payload.duration_ms,
            error_message=payload.error_message,
        )
    except InvalidExecutionStatusError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


@router.delete("/{execution_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_test_execution(
    execution_id: int,
    db: Store = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    """Delete a test execution record."""
    execution = owned_execution(db, user, execution_id)
    TestExecutionService.delete_execution(db=db, execution_id=execution_id)
    delete_execution_artifacts(execution.get("owner_uid") or user.uid, execution_id)
    return None
