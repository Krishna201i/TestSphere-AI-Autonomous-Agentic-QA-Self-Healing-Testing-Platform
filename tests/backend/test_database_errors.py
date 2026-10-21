"""Storage outages must surface as readable 503s and a degraded health status."""

from fastapi.testclient import TestClient

from backend.api import health
from backend.database.session import set_store
from backend.database.store import MemoryStore, StoreUnavailableError
from backend.main import app

REASON = "Firestore is not enabled for this Firebase project. Open Firebase console → Firestore Database → Create database."


class BrokenStore(MemoryStore):
    """A store whose backend is down: every operation fails like Firestore would."""

    def _fail(self, *_a, **_kw):
        raise StoreUnavailableError(REASON)

    _create = get = find = _update = delete = ping = clear = _fail


def test_api_storage_failure_is_503_with_readable_detail() -> None:
    set_store(BrokenStore())
    resp = TestClient(app, raise_server_exceptions=False).get("/api/projects")
    assert resp.status_code == 503
    assert resp.json()["detail"] == f"Database unavailable: {REASON}"


def test_health_reports_degraded_database() -> None:
    set_store(BrokenStore())
    health._db_state["checked_at"] = 0.0
    try:
        body = TestClient(app).get("/api/health").json()
    finally:
        health._db_state["checked_at"] = 0.0  # don't leak the cached failure into other tests
    assert body["status"] == "degraded" and body["database"] == "error"
    assert "Create database" in body["database_error"]


def test_health_ok_with_working_store() -> None:
    health._db_state["checked_at"] = 0.0
    body = TestClient(app).get("/api/health").json()
    assert body == {"status": "ok", "service": "TestSphere-AI Backend", "database": "ok", "database_error": None}


def test_memory_store_falls_back_when_database_is_down(monkeypatch) -> None:
    from agents.memory.in_memory_store import InMemoryStore
    from agents.memory.persistent_store import PersistentMemoryStore
    from backend.config import settings
    from backend.orchestration import orchestrator

    monkeypatch.setattr(settings, "AGENT_MEMORY_BACKEND", "database")
    set_store(BrokenStore())
    store = orchestrator.create_memory_store()
    assert isinstance(store, InMemoryStore) and not isinstance(store, PersistentMemoryStore)


def test_store_creation_failure_is_503(monkeypatch) -> None:
    """A store that cannot even be created (bad credentials) still yields a clean 503."""
    from backend.database import session

    def fail_create(*_a, **_kw):
        raise StoreUnavailableError("No Firebase credentials.")

    set_store(None)
    monkeypatch.setattr(session, "create_store", fail_create)
    resp = TestClient(app, raise_server_exceptions=False).get("/api/applications")
    assert resp.status_code == 503 and "No Firebase credentials" in resp.json()["detail"]
