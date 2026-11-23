"""Tests for agents/memory/persistent_store.py (healing memory that survives restarts)."""

from datetime import UTC, datetime
from pathlib import Path

from agents.memory.memory_schemas import HealingRecord
from agents.memory.persistent_store import (
    COLLECTION,
    PersistentMemoryStore,
    memory_owner,
)
from backend.database.store import LocalStore


def _record(i: int, old: str = "#old") -> HealingRecord:
    return HealingRecord(
        healing_id=f"h{i}",
        test_id="TC-1",
        old_selector=old,
        new_selector=f"#new{i}",
        confidence=0.9,
        timestamp=datetime(2026, 10, 21, 10, i, tzinfo=UTC).isoformat(),
    )


def test_healing_history_survives_restart(tmp_path: Path) -> None:
    path = tmp_path / "db.json"
    first = PersistentMemoryStore(LocalStore(path))
    first.store_healing_record(_record(1))
    first.store_healing_record(_record(2))

    restarted = PersistentMemoryStore(LocalStore(path))  # fresh process, same database
    history = restarted.get_healing_history("#old")
    assert [r.new_selector for r in history] == ["#new2", "#new1"]  # most recent first


def test_invalid_record_is_rejected_and_not_persisted(fresh_store) -> None:
    memory = PersistentMemoryStore(fresh_store)
    bad = _record(1).model_copy(update={"healing_id": " "})
    try:
        memory.store_healing_record(bad)
    except ValueError:
        pass
    assert fresh_store.find(COLLECTION) == []


def test_unreadable_rows_are_skipped(fresh_store) -> None:
    PersistentMemoryStore(fresh_store).store_healing_record(_record(1))
    fresh_store.insert(COLLECTION, kind="healing", data='{"bad": 1}')
    assert len(PersistentMemoryStore(fresh_store).get_healing_history("#old")) == 1


def test_clear_wipes_the_collection(fresh_store) -> None:
    memory = PersistentMemoryStore(fresh_store)
    memory.store_healing_record(_record(1))
    memory.clear()
    assert PersistentMemoryStore(fresh_store).get_healing_history("#old") == []


def test_owner_isolation_prevents_cross_tenant_healing_leak(fresh_store) -> None:
    memory = PersistentMemoryStore(fresh_store)

    with memory_owner("tenant_a"):
        memory.store_healing_record(_record(1, old="#btn"))

    with memory_owner("tenant_b"):
        memory.store_healing_record(_record(2, old="#btn"))

    # Tenant A only sees their own healed selector
    with memory_owner("tenant_a"):
        history_a = memory.get_healing_history("#btn")
        assert len(history_a) == 1
        assert history_a[0].new_selector == "#new1"

    # Tenant B only sees their own healed selector
    with memory_owner("tenant_b"):
        history_b = memory.get_healing_history("#btn")
        assert len(history_b) == 1
        assert history_b[0].new_selector == "#new2"

    # Unrelated Tenant C sees nothing
    with memory_owner("tenant_c"):
        assert memory.get_healing_history("#btn") == []

    # Unscoped / system query sees both
    history_all = memory.get_healing_history("#btn")
    assert len(history_all) == 2


def test_owner_isolation_survives_reload(tmp_path: Path) -> None:
    path = tmp_path / "tenant_db.json"
    first = PersistentMemoryStore(LocalStore(path))

    with memory_owner("alice"):
        first.store_healing_record(_record(1, old="#menu"))
    with memory_owner("bob"):
        first.store_healing_record(_record(2, old="#menu"))

    # Fresh process / restarted store
    restarted = PersistentMemoryStore(LocalStore(path))

    with memory_owner("alice"):
        records = restarted.get_healing_history("#menu")
        assert len(records) == 1
        assert records[0].new_selector == "#new1"

    with memory_owner("bob"):
        records = restarted.get_healing_history("#menu")
        assert len(records) == 1
        assert records[0].new_selector == "#new2"
