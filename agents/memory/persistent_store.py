"""
TestSphere-AI — Persistent Memory Store

Write-through ``MemoryStore`` that survives restarts.  Every stored record is
written as JSON to the ``agent_memory`` collection of a document store
(Firestore in production) and kept in the in-memory indexes inherited from
``InMemoryStore``, so all query logic is shared; on construction the
collection is replayed to rebuild those indexes.

``store`` is any object with the document-store interface used by the
backend (``insert``, ``find``, ``delete_where``)::

    memory = PersistentMemoryStore(get_store())

Each persisted record carries the ``owner_uid`` of the run that produced it
(set with ``memory_owner``), so erasing an account removes its memory too.
Only the newest ``max_records`` records are replayed at start-up, so a cold
start reads a bounded number of documents however large the collection grows.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Iterator
from contextvars import ContextVar
from typing import Any

from agents.memory.in_memory_store import InMemoryStore
from agents.memory.memory_schemas import (
    ElementRecord,
    HealingRecord,
    TestExecutionRecord,
)

logger = logging.getLogger(__name__)

COLLECTION = "agent_memory"

# Records replayed at start-up (newest first); older ones stay stored but unread
DEFAULT_MAX_RECORDS = 2000

# Owner of the records stored in the current run (per asyncio task)
_owner: ContextVar[str | None] = ContextVar("agent_memory_owner", default=None)


@contextlib.contextmanager
def memory_owner(owner_uid: str | None) -> Iterator[None]:
    """Tag records persisted inside this block with *owner_uid*."""
    token = _owner.set(owner_uid)
    try:
        yield
    finally:
        _owner.reset(token)

_KINDS = {
    "execution": TestExecutionRecord,
    "element": ElementRecord,
    "healing": HealingRecord,
}


class PersistentMemoryStore(InMemoryStore):
    """``InMemoryStore`` whose records are also persisted to a document store."""

    def __init__(self, store: Any, max_records: int = DEFAULT_MAX_RECORDS) -> None:
        super().__init__()
        self._store = store
        self._max_records = max_records
        self._load()

    # ── Write-through ─────────────────────────────────────────

    def store_execution(self, record: TestExecutionRecord) -> None:
        super().store_execution(record)  # validates first
        self._persist("execution", record)

    def store_element(self, record: ElementRecord) -> None:
        super().store_element(record)
        self._persist("element", record)

    def store_healing_record(self, record: HealingRecord) -> None:
        super().store_healing_record(record)
        self._persist("healing", record)

    def clear(self) -> None:
        super().clear()
        for kind in _KINDS:
            self._store.delete_where(COLLECTION, kind=kind)

    def reload(self) -> None:
        """Rebuild the in-memory indexes from the stored records (e.g. after
        an account's records were erased)."""
        InMemoryStore.clear(self)
        self._load()

    # ── Internals ─────────────────────────────────────────────

    def _persist(self, kind: str, record) -> None:
        self._store.insert(COLLECTION, kind=kind, data=record.model_dump_json(), owner_uid=_owner.get())

    def _load(self) -> None:
        loaders = {
            "execution": super().store_execution,
            "element": super().store_element,
            "healing": super().store_healing_record,
        }
        counts = dict.fromkeys(_KINDS, 0)
        newest = self._store.find(COLLECTION, order_by="id", descending=True, limit=self._max_records)
        for row in reversed(newest):  # replay oldest first, as they were stored
            model = _KINDS.get(row.get("kind"))
            if model is None:
                continue
            try:
                loaders[row["kind"]](model.model_validate_json(row["data"]))
                counts[row["kind"]] += 1
            except ValueError as exc:  # schema drift / bad row: skip, don't crash startup
                logger.warning("Skipping unreadable %s memory record: %s", row["kind"], exc)
        logger.info("PersistentMemoryStore loaded %s", counts)
