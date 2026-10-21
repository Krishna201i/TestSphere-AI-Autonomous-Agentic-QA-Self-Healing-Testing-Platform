"""Test-wide settings, applied before any test module imports the app."""

import os

import pytest

# Keep agent healing memory in-process and storage in memory, so tests never
# touch the dev database or Firestore.
os.environ.setdefault("AGENT_MEMORY_BACKEND", "memory")
os.environ.setdefault("DATABASE_BACKEND", "memory")


@pytest.fixture(autouse=True)
def fresh_store():
    """Every test gets an empty in-memory store (also used by the API via get_db)."""
    from backend.database.session import set_store
    from backend.database.store import MemoryStore

    store = MemoryStore()
    set_store(store)
    yield store
    set_store(None)
