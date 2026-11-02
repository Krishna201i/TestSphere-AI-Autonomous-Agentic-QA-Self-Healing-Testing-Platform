"""
TestSphere-AI — Health Check Endpoint.

Reports whether the API is up and whether its storage backend (Firestore in
production) is usable.  The storage probe is cached for a few seconds so
frequent dashboard polling does not hammer the database.

With ``PIPELINE_EXECUTION=worker`` it also reports the queue: ``worker`` is
"stalled" when runs are queued, none is running, and the oldest has waited
longer than an idle worker takes to poll, i.e. no worker is taking runs.
"""

import time
from datetime import UTC, datetime

from fastapi import APIRouter

from backend.config import settings
from backend.database import session as db_session
from backend.database.store import StoreUnavailableError
from backend.models import PIPELINE_RUNS

router = APIRouter(tags=["Health"])

_DB_CACHE_SECONDS = 60.0  # each check is a database read
_db_state: dict[str, object] = {"checked_at": 0.0, "ok": True, "error": None}
_queue_state: dict[str, object] = {"checked_at": 0.0, "queued": 0, "worker": "ok"}


def _queued_seconds(row, now: datetime) -> float:
    try:
        created = datetime.fromisoformat(row.get("created_at") or "")
    except ValueError:
        return 0.0
    return (now - (created if created.tzinfo else created.replace(tzinfo=UTC))).total_seconds()


def _queue_status() -> tuple[int, str]:
    """(runs waiting, "ok" or "stalled"), cached like the database probe."""
    from backend.worker import (
        IDLE_POLL_SECONDS,  # imported here: the worker module pulls in the pipeline
    )

    now = time.monotonic()
    if now - float(_queue_state["checked_at"]) > _DB_CACHE_SECONDS:
        store = db_session.get_store()
        queued = store.find(PIPELINE_RUNS, status="queued")
        oldest = max((_queued_seconds(r, datetime.now(UTC)) for r in queued), default=0.0)
        idle = not store.find(PIPELINE_RUNS, status="running", limit=1)
        stalled = queued and idle and oldest > 2 * IDLE_POLL_SECONDS
        _queue_state.update(checked_at=now, queued=len(queued), worker="stalled" if stalled else "ok")
    return int(_queue_state["queued"]), str(_queue_state["worker"])


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
def health_check() -> dict[str, str | int | None]:
    """API status plus database reachability ("degraded" when the database or the worker is down)."""
    db_ok, db_error = _database_status()
    body: dict[str, str | int | None] = {
        "status": "ok" if db_ok else "degraded",
        "service": "TestSphere-AI Backend",
        "database": "ok" if db_ok else "error",
        "database_error": db_error,
    }
    if db_ok and settings.PIPELINE_EXECUTION == "worker":
        try:
            body["queued"], body["worker"] = _queue_status()
        except StoreUnavailableError:
            body["worker"] = "unknown"
        if body["worker"] == "stalled":
            body["status"] = "degraded"
    return body
