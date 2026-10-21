"""
TestSphere-AI — Audit Trail API Router.
"""

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Query

from backend.database.session import get_db
from backend.database.store import Store
from backend.services.security_service import list_audit

router = APIRouter(prefix="/audit", tags=["Audit"])


@router.get("")
def get_audit(limit: int = Query(200, ge=1, le=1000), db: Store = Depends(get_db)) -> List[Dict[str, Any]]:
    """Most recent audit events first: scans, approvals, retests, QA runs, targets."""
    return list_audit(db, limit)
