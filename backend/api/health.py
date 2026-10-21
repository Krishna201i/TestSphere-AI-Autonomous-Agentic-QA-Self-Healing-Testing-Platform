"""
TestSphere-AI — Health Check Endpoint.

Reports whether the API is up and whether its database is reachable.  The
database probe is cached for a few seconds so frequent dashboard polling
does not hammer the database.
"""

import time
from typing import Dict, Optional

from fastapi import APIRouter
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from backend.database import session as db_session
from backend.database.errors import describe_db_error

router = APIRouter(tags=["Health"])

_DB_CACHE_SECONDS = 10.0
_db_state: Dict[str, object] = {"checked_at": 0.0, "ok": True, "error": None}


def _database_status() -> tuple[bool, Optional[str]]:
    now = time.monotonic()
    if now - float(_db_state["checked_at"]) > _DB_CACHE_SECONDS:
        try:
            with db_session.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            _db_state.update(ok=True, error=None)
        except SQLAlchemyError as exc:
            _db_state.update(ok=False, error=describe_db_error(exc))
        _db_state["checked_at"] = now
    return bool(_db_state["ok"]), _db_state["error"]  # type: ignore[return-value]


@router.get("/health")
def health_check() -> Dict[str, Optional[str]]:
    """API status plus database reachability ("degraded" when the database is down)."""
    db_ok, db_error = _database_status()
    return {
        "status": "ok" if db_ok else "degraded",
        "service": "TestSphere-AI Backend",
        "database": "ok" if db_ok else "error",
        "database_error": db_error,
    }
