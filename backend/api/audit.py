"""
TestSphere-AI — Audit Trail API Router.
"""

from typing import Any

from fastapi import APIRouter, Depends, Query

from backend.auth import User, get_current_user, scope
from backend.database.session import get_db
from backend.database.store import Store
from backend.services.security_service import list_audit

router = APIRouter(prefix="/audit", tags=["Audit"])


@router.get("")
def get_audit(
    limit: int = Query(200, ge=1, le=1000), db: Store = Depends(get_db), user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """The caller's most recent audit events first: scans, approvals, retests, QA runs, pipelines, targets."""
    return list_audit(db, limit, **scope(user))
