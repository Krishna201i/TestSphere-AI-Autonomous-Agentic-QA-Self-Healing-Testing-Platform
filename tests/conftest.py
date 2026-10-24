"""Test-wide settings, applied before any test module imports the app."""

import os

import pytest

# Keep agent healing memory in-process and storage in memory, so tests never
# touch the dev database or Firestore.
os.environ.setdefault("AGENT_MEMORY_BACKEND", "memory")
os.environ.setdefault("DATABASE_BACKEND", "memory")
# Single local user (auth tests turn sign-in on explicitly); no background scheduler.
os.environ.setdefault("AUTH_REQUIRED", "false")
os.environ.setdefault("SCHEDULER_ENABLED", "false")
# Real-browser tests run without Playwright tracing unless a test turns it on
os.environ.setdefault("ARTIFACT_TRACES", "false")


@pytest.fixture(autouse=True)
def fresh_store():
    """Every test gets an empty in-memory store (also used by the API via get_db)."""
    from backend.database.session import set_store
    from backend.database.store import MemoryStore

    store = MemoryStore()
    set_store(store)
    yield store
    set_store(None)


@pytest.fixture(autouse=True)
def fresh_artifacts():
    """Screenshots and traces go to an in-memory store, never the dev data folder."""
    from backend.artifacts import MemoryArtifactStore, set_artifact_store

    store = MemoryArtifactStore()
    set_artifact_store(store)
    yield store
    set_artifact_store(None)


@pytest.fixture(autouse=True)
def fresh_rate_limits():
    """Rate-limit counts never carry over between tests."""
    from backend import ratelimit

    ratelimit.reset()
    yield
    ratelimit.reset()
