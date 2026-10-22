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
"""

from __future__ import annotations

import logging
from typing import Any

from agents.memory.in_memory_store import InMemoryStore
from agents.memory.memory_schemas import (
    ElementRecord,
    HealingRecord,
    TestExecutionRecord,
)

logger = logging.getLogger(__name__)

COLLECTION = "agent_memory"

_KINDS = {
    "execution": TestExecutionRecord,
    "element": ElementRecord,
    "healing": HealingRecord,
}


class PersistentMemoryStore(InMemoryStore):
    """``InMemoryStore`` whose records are also persisted to a document store."""

    def __init__(self, store: Any) -> None:
        super().__init__()
        self._store = store
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

    # ── Internals ─────────────────────────────────────────────

    def _persist(self, kind: str, record) -> None:
        self._store.insert(COLLECTION, kind=kind, data=record.model_dump_json())

    def _load(self) -> None:
        loaders = {
            "execution": super().store_execution,
            "element": super().store_element,
            "healing": super().store_healing_record,
        }
        counts = dict.fromkeys(_KINDS, 0)
        for row in self._store.find(COLLECTION, order_by="id"):
            model = _KINDS.get(row.get("kind"))
            if model is None:
                continue
            try:
                loaders[row["kind"]](model.model_validate_json(row["data"]))
                counts[row["kind"]] += 1
            except ValueError as exc:  # schema drift / bad row: skip, don't crash startup
                logger.warning("Skipping unreadable %s memory record: %s", row["kind"], exc)
        logger.info("PersistentMemoryStore loaded %s", counts)
