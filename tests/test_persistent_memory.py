"""Tests for agents/memory/persistent_store.py."""

from datetime import datetime, timezone

from sqlalchemy import create_engine, text

from agents.memory.memory_schemas import HealingRecord
from agents.memory.persistent_store import PersistentMemoryStore


def _record(i: int, old: str = "#old") -> HealingRecord:
    return HealingRecord(
        healing_id=f"h{i}",
        test_id="TC-1",
        old_selector=old,
        new_selector=f"#new{i}",
        confidence=0.9,
        timestamp=datetime(2026, 10, 21, 10, i, tzinfo=timezone.utc).isoformat(),
    )


def test_healing_history_survives_restart(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'mem.db'}")
    first = PersistentMemoryStore(engine)
    first.store_healing_record(_record(1))
    first.store_healing_record(_record(2))

    restarted = PersistentMemoryStore(engine)  # fresh process, same database
    history = restarted.get_healing_history("#old")
    assert [r.new_selector for r in history] == ["#new2", "#new1"]  # most recent first


def test_invalid_record_is_rejected_and_not_persisted(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'mem.db'}")
    store = PersistentMemoryStore(engine)
    bad = _record(1).model_copy(update={"healing_id": " "})
    try:
        store.store_healing_record(bad)
    except ValueError:
        pass
    with engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM agent_memory_records")).scalar() == 0


def test_unreadable_rows_are_skipped(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'mem.db'}")
    store = PersistentMemoryStore(engine)
    store.store_healing_record(_record(1))
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO agent_memory_records (kind, data) VALUES ('healing', '{\"bad\": 1}')"))
    assert len(PersistentMemoryStore(engine).get_healing_history("#old")) == 1


def test_clear_wipes_the_table(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'mem.db'}")
    store = PersistentMemoryStore(engine)
    store.store_healing_record(_record(1))
    store.clear()
    assert PersistentMemoryStore(engine).get_healing_history("#old") == []
