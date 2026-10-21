"""Database outages must surface as readable 503s and a degraded health status."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError

from backend.api import health
from backend.database.errors import describe_db_error
from backend.database.session import get_db
from backend.main import app

SUPABASE_ERROR = (
    'connection to server at "15.165.245.138", port 5432 failed: FATAL: (ENOTFOUND) '
    "tenant/user postgres.uhqaudrvlpwmuxldloyv not found"
)


def _op_error(message: str) -> OperationalError:
    return OperationalError("SELECT 1", {}, Exception(message))


@pytest.mark.parametrize(("raw", "expected"), [
    (SUPABASE_ERROR, "project may be paused"),
    ('FATAL:  password authentication failed for user "postgres"', "password"),
    ("could not translate host name \"db.x.supabase.co\" to address", "cannot be resolved"),
    ("connection timed out", "did not respond"),
    ("something else entirely", "could not reach its database"),
])
def test_describe_db_error(raw: str, expected: str) -> None:
    message = describe_db_error(_op_error(raw))
    assert message.startswith("Database unavailable:")
    assert expected in message
    assert "15.165.245.138" not in message


def test_api_db_failure_is_503_with_readable_detail() -> None:
    def broken_db():
        raise _op_error(SUPABASE_ERROR)
        yield  # pragma: no cover

    app.dependency_overrides[get_db] = broken_db
    try:
        resp = TestClient(app, raise_server_exceptions=False).get("/api/projects")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 503
    assert "Supabase" in resp.json()["detail"] and "tenant" not in resp.json()["detail"]


def test_health_reports_degraded_database() -> None:
    bad_engine = create_engine("sqlite:///:memory:")
    health._db_state["checked_at"] = 0.0
    with patch.object(health.db_session, "engine", bad_engine), \
         patch.object(bad_engine, "connect", side_effect=_op_error(SUPABASE_ERROR)):
        body = TestClient(app).get("/api/health").json()
    health._db_state["checked_at"] = 0.0  # don't leak the cached failure into other tests
    assert body["status"] == "degraded" and body["database"] == "error"
    assert "paused" in body["database_error"]


def test_memory_store_falls_back_when_database_is_down(monkeypatch) -> None:
    from agents.memory.in_memory_store import InMemoryStore
    from agents.memory.persistent_store import PersistentMemoryStore
    from backend.config import settings
    from backend.orchestration import orchestrator

    monkeypatch.setattr(settings, "AGENT_MEMORY_BACKEND", "database")

    def boom(engine):
        raise _op_error("connection refused")

    monkeypatch.setattr(orchestrator, "PersistentMemoryStore", boom)
    store = orchestrator.create_memory_store()
    assert isinstance(store, InMemoryStore) and not isinstance(store, PersistentMemoryStore)
