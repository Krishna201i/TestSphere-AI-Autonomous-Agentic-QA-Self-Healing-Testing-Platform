"""
TestSphere-AI — Health Check Endpoint.

Reports whether the API is up and whether its storage backend (Firestore in
production) is usable.  The storage probe is cached for a few seconds so
frequent dashboard polling does not hammer the database.
"""

import time

from fastapi import APIRouter

from backend.database import session as db_session
from backend.database.store import StoreUnavailableError

router = APIRouter(tags=["Health"])

_DB_CACHE_SECONDS = 10.0
_db_state: dict[str, object] = {"checked_at": 0.0, "ok": True, "error": None}


def _database_status() -> tuple[bool, str | None]:
    now = time.monotonic()
    if now - float(_db_state["checked_at"]) > _DB_CACHE_SECONDS:
        try:
            db_session.get_store().ping()
            _db_state.update(ok=True, error=None)
        except StoreUnavailableError as exc:
            _db_state.update(ok=False, error=f"Database unavailable: {exc}")
        _db_state["checked_at"] = now
    return bool(_db_state["ok"]), _db_state["error"]  # type: ignore[return-value]


@router.get("/health")
def health_check() -> dict[str, str | None]:
    """API status plus database reachability ("degraded" when the database is down)."""
    db_ok, db_error = _database_status()
    return {
        "status": "ok" if db_ok else "degraded",
        "service": "TestSphere-AI Backend",
        "database": "ok" if db_ok else "error",
        "database_error": db_error,
    }
