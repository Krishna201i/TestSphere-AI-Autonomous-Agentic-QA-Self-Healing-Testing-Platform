"""
TestSphere-AI — Storage provider.

Creates the configured ``Store`` once per process and hands it to route
handlers through the ``get_db`` dependency (name kept for compatibility).
"""

import logging
import threading
from typing import Generator, Optional

from backend.config import settings
from backend.database.store import Store, StoreUnavailableError, create_store

logger = logging.getLogger("testsphere.database")

_store: Optional[Store] = None
_lock = threading.Lock()


def get_store() -> Store:
    """The process-wide store; raises ``StoreUnavailableError`` if it cannot be created."""
    global _store
    if _store is None:
        with _lock:
            if _store is None:
                _store = create_store(
                    settings.DATABASE_BACKEND,
                    local_path=settings.LOCAL_DB_PATH,
                    credentials=settings.FIREBASE_CREDENTIALS or None,
                    project_id=settings.FIREBASE_PROJECT_ID or None,
                )
                logger.info("Storage backend: %s", _store.name)
    return _store


def set_store(store: Optional[Store]) -> None:
    """Replace the process-wide store (tests)."""
    global _store
    with _lock:
        _store = store


def get_db() -> Generator[Store, None, None]:
    """FastAPI dependency yielding the store."""
    yield get_store()


def init_db() -> bool:
    """Verify the storage backend is reachable at startup."""
    try:
        get_store().ping()
        return True
    except StoreUnavailableError as exc:
        raise RuntimeError(f"Storage initialization failed: {exc}") from exc
