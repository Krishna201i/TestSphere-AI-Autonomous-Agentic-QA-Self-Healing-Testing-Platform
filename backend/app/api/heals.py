"""
TestSphere-AI — Self-healing review.

    GET  /heals                          every heal in the caller's runs, newest first, with its evidence
    POST /heals/{execution_id}/review    approve or reject one heal

A heal is a broken locator the engine (fingerprint, fallbacks) or the AI
healer replaced with another one during a run.  Confident heals are written
back into the test automatically; review makes the decision a person's:

* **approve**: the replacement becomes the test's locator (written back if it
  was not yet), and stays out of the rejected list.
* **reject**: the replacement reached the wrong element.  A write-back is
  undone, the replacement is dropped from the learned fallbacks, and the pair
  is recorded on the test: a later run that heals to it again FAILS
  (``app/orchestration/orchestrator.py``) instead of passing on the wrong element.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.auth import User, actor_for, ensure_owned, get_current_user, scope
from app.database.session import get_db
from app.database.store import Record, Store
from app.models import TEST_CASES, TEST_EXECUTIONS
from app.orchestration.converters import drop_rejected, write_back_heals
from app.services.security_service import record_audit

router = APIRouter(prefix="/heals", tags=["Self-Healing"])

MAX_SCANNED = 500
_AI_HEAL = re.compile(r"Self-healed (.+?) -> (.+?) \(AI healer, confidence ([\d.]+)\)")


class Review(BaseModel):
    original_locator: str = Field(..., min_length=1, max_length=1000)
    decision: Literal["approve", "reject"]


def _heals_of(execution: Record) -> list[dict[str, Any]]:
    """(step heals of the engine) + (the AI healer's heal, read from the run's message)."""
    found: list[dict[str, Any]] = []
    for step in execution.get("steps") or []:
        healing = step.get("healing") if isinstance(step, dict) else None
        if isinstance(healing, dict) and healing.get("original_locator") and healing.get("selected_locator"):
            found.append({"step_id": step.get("step_id"), "step": step.get("description") or step.get("step_id"),
                          "original": healing["original_locator"], "selected": healing["selected_locator"],
                          "strategy": healing.get("strategy") or "engine",
                          "confidence": float(healing.get("confidence") or 0.0), "screenshot": step.get("screenshot")})
    for old, new, confidence in _AI_HEAL.findall(execution.get("error_message") or ""):
        if not any(h["original"] == old and h["selected"] == new for h in found):
            found.append({"step_id": None, "step": None, "original": old, "selected": new, "strategy": "ai_healer",
                          "confidence": float(confidence), "screenshot": None})
    return found


def _written_back(test_case: Record | None, old: str, new: str) -> bool:
    """Whether the test's stored steps now use *new* where they used *old*."""
    if not test_case:
        return False
    history = test_case.get("locator_history") or []
    last = next((h for h in reversed(history) if isinstance(h, dict) and {h.get("from"), h.get("to")} == {old, new}),
                None)
    return bool(last and last.get("from") == old)


def _view(execution: Record, test_case: Record | None, heal: dict[str, Any]) -> dict[str, Any]:
    review = (execution.get("heal_reviews") or {}).get(heal["original"])
    return {
        "key": f"{execution['id']}:{heal['original']}", "execution_id": execution["id"],
        "test_case_id": execution.get("test_case_id"), "test_name": (test_case or {}).get("name"),
        "at": execution.get("completed_at") or execution.get("created_at"), **heal,
        "written_back": _written_back(test_case, heal["original"], heal["selected"]),
        "review": review,
    }


@router.get("")
def list_heals(limit: int = Query(100, ge=1, le=500), db: Store = Depends(get_db),
               user: User = Depends(get_current_user)) -> dict[str, Any]:
    """Every heal of the caller's healed executions, newest first, and how many await review."""
    executions = db.find(TEST_EXECUTIONS, order_by="id", descending=True, limit=MAX_SCANNED, status="HEALED",
                         **scope(user))
    cases: dict[int, Record | None] = {}
    heals: list[dict[str, Any]] = []
    for execution in executions:
        tc_id = execution.get("test_case_id")
        if tc_id not in cases:
            cases[tc_id] = db.get(TEST_CASES, tc_id) if tc_id is not None else None
        heals += [_view(execution, cases[tc_id], h) for h in _heals_of(execution)]
    counts = {"total": len(heals), "pending": 0, "approved": 0, "rejected": 0}
    for h in heals:
        counts[h["review"]["decision"] if h["review"] else "pending"] += 1
    return {"heals": heals[:limit], **counts}


@router.post("/{execution_id}/review")
def review_heal(execution_id: int, body: Review, db: Store = Depends(get_db),
                user: User = Depends(get_current_user)) -> dict[str, Any]:
    execution = ensure_owned(user, db.get(TEST_EXECUTIONS, execution_id), "Execution")
    heal = next((h for h in _heals_of(execution) if h["original"] == body.original_locator), None)
    if heal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="This execution has no heal of that locator.")
    test_case = db.get(TEST_CASES, execution["test_case_id"])
    if test_case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="The healed test no longer exists.")

    old, new = heal["original"], heal["selected"]
    now = datetime.now(UTC).isoformat()
    rejected = [r for r in test_case.get("rejected_heals") or [] if isinstance(r, dict)
                and (r.get("from"), r.get("to")) != (old, new)]
    targets = list(test_case.get("healing_targets") or [])
    history = list(test_case.get("locator_history") or [])
    description = None

    if body.decision == "approve":
        if not _written_back(test_case, old, new):
            description, targets = write_back_heals(test_case.get("description"), targets, [(old, new)])
            if description is not None:
                history.append({"from": old, "to": new, "execution_id": execution_id, "at": now, "reviewed": True})
    else:
        rejected.append({"from": old, "to": new, "execution_id": execution_id, "at": now})
        if _written_back(test_case, old, new):
            description, targets = write_back_heals(test_case.get("description"), targets, [(new, old)])
            if description is not None:
                history.append({"from": new, "to": old, "execution_id": execution_id, "at": now, "reverted": True})
        targets = drop_rejected(targets, {old})

    changes: dict[str, Any] = {"rejected_heals": rejected[-50:], "healing_targets": targets,
                               "locator_history": history[-20:]}
    if description is not None:
        changes.update(description=description, version=int(test_case.get("version") or 1) + 1)
    test_case = db.update(TEST_CASES, test_case["id"], **changes) or test_case

    actor = actor_for(user, None)
    reviews = {**(execution.get("heal_reviews") or {}),
               old: {"decision": "approved" if body.decision == "approve" else "rejected", "by": actor, "at": now}}
    execution = db.update(TEST_EXECUTIONS, execution_id, heal_reviews=reviews) or execution
    record_audit(db, actor=actor, kind="heal", ref=str(execution_id), owner_uid=execution.get("owner_uid"),
                 level="success" if body.decision == "approve" else "warn",
                 message=f"Heal {body.decision}d on '{test_case.get('name')}': {old} -> {new}")
    return _view(execution, test_case, heal)
