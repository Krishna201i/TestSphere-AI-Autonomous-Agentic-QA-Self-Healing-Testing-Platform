"""
TestSphere-AI — Persistent Memory Store

Write-through ``MemoryStore`` that survives restarts.  Every stored record is
written to a SQL table as JSON and kept in the in-memory indexes inherited
from ``InMemoryStore``, so all query logic is shared; on construction the
table is replayed to rebuild those indexes.

Works with any SQLAlchemy engine (SQLite locally, Supabase PostgreSQL in
production)::

    store = PersistentMemoryStore(engine)
"""

from __future__ import annotations

import logging

from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table, Text, delete, func, insert, select
from sqlalchemy.engine import Engine

from agents.memory.in_memory_store import InMemoryStore
from agents.memory.memory_schemas import ElementRecord, HealingRecord, TestExecutionRecord

logger = logging.getLogger(__name__)

_metadata = MetaData()

memory_records = Table(
    "agent_memory_records",
    _metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("kind", String(16), nullable=False, index=True),
    Column("data", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

_KINDS = {
    "execution": TestExecutionRecord,
    "element": ElementRecord,
    "healing": HealingRecord,
}


class PersistentMemoryStore(InMemoryStore):
    """``InMemoryStore`` whose records are also persisted to SQL."""

    def __init__(self, engine: Engine) -> None:
        super().__init__()
        self._engine = engine
        _metadata.create_all(engine, tables=[memory_records])
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
        with self._engine.begin() as conn:
            conn.execute(delete(memory_records))

    # ── Internals ─────────────────────────────────────────────

    def _persist(self, kind: str, record) -> None:
        with self._engine.begin() as conn:
            conn.execute(insert(memory_records).values(kind=kind, data=record.model_dump_json()))

    def _load(self) -> None:
        loaders = {
            "execution": super().store_execution,
            "element": super().store_element,
            "healing": super().store_healing_record,
        }
        counts = dict.fromkeys(_KINDS, 0)
        with self._engine.connect() as conn:
            rows = conn.execute(select(memory_records.c.kind, memory_records.c.data).order_by(memory_records.c.id))
            for kind, data in rows:
                model = _KINDS.get(kind)
                if model is None:
                    continue
                try:
                    loaders[kind](model.model_validate_json(data))
                    counts[kind] += 1
                except ValueError as exc:  # schema drift / bad row: skip, don't crash startup
                    logger.warning("Skipping unreadable %s memory record: %s", kind, exc)
        logger.info("PersistentMemoryStore loaded %s", counts)
