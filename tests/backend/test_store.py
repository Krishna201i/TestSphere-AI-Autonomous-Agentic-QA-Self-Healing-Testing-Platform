"""
Contract tests for every ``Store`` backend.

The same behaviour is required of MemoryStore, LocalStore (JSON file) and
FirestoreStore.  Firestore runs only when the official emulator is available
(``FIRESTORE_EMULATOR_HOST`` set, e.g. via ``firebase emulators:exec``).
"""

import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest

import backend.database.store as store_module
from backend.database.store import (
    FirestoreStore,
    LocalStore,
    MemoryStore,
    Record,
    StoreUnavailableError,
    _service_account_source,
    create_store,
    describe_firestore_error,
)

BACKENDS = ["memory", "local", "firestore"]


@pytest.fixture(params=BACKENDS)
def store(request, tmp_path: Path):
    if request.param == "memory":
        yield MemoryStore()
    elif request.param == "local":
        yield LocalStore(tmp_path / "db.json")
    else:
        if not os.getenv("FIRESTORE_EMULATOR_HOST"):
            pytest.skip("Firestore emulator not running (set FIRESTORE_EMULATOR_HOST)")
        s = FirestoreStore.from_settings(None, "demo-testsphere")
        s.clear()
        yield s
        s.clear()


# ── Contract ──────────────────────────────────────────────────


def test_insert_assigns_increasing_ids_and_timestamps(store) -> None:
    a = store.insert("projects", name="A")
    b = store.insert("projects", name="B")
    assert (a.id, b.id) == (1, 2)
    assert isinstance(a, Record) and a.name == "A"
    assert datetime.fromisoformat(a.created_at).tzinfo is not None
    assert a.created_at == a.updated_at


def test_ids_are_per_collection(store) -> None:
    store.insert("projects", name="P")
    assert store.insert("applications", name="A", project_id=1).id == 1


def test_get_returns_none_for_missing_and_bad_ids(store) -> None:
    assert store.get("projects", 99) is None
    assert store.get("projects", "not-a-number") is None


def test_find_filters_orders_and_limits(store) -> None:
    for i, project in enumerate([1, 2, 1, 1]):
        store.insert("applications", name=f"app{i}", project_id=project, rank=10 - i)
    assert [r.name for r in store.find("applications", project_id=1)] == ["app0", "app2", "app3"]
    assert [r.name for r in store.find("applications", project_id=1, order_by="rank")] == ["app3", "app2", "app0"]
    assert [r.id for r in store.find("applications", order_by="id", descending=True, limit=2)] == [4, 3]
    assert store.find_one("applications", name="app2").project_id == 1
    assert store.find_one("applications", name="nope") is None


def test_find_handles_none_values(store) -> None:
    store.insert("security_findings", key="k1", retest_result=None)
    store.insert("security_findings", key="k2", retest_result="pass")
    assert [r.key for r in store.find("security_findings", retest_result="pass")] == ["k2"]


def test_update_merges_and_bumps_updated_at(store) -> None:
    rec = store.insert("test_executions", test_case_id=1, status="PENDING", duration_ms=None)
    updated = store.update("test_executions", rec.id, status="PASSED", duration_ms=12,
                           completed_at=datetime(2026, 10, 21, 7, 0, tzinfo=UTC))
    assert (updated.status, updated.duration_ms, updated.test_case_id) == ("PASSED", 12, 1)
    assert updated.completed_at == "2026-10-21T07:00:00+00:00"   # datetimes stored as ISO UTC
    assert updated.updated_at >= rec.updated_at
    assert store.get("test_executions", rec.id).status == "PASSED"
    assert store.update("test_executions", 999, status="X") is None


def test_delete_and_delete_where(store) -> None:
    a = store.insert("test_executions", test_case_id=1)
    store.insert("test_executions", test_case_id=1)
    keep = store.insert("test_executions", test_case_id=2)
    assert store.delete("test_executions", a.id) is True
    assert store.delete("test_executions", a.id) is False
    removed = store.delete_where("test_executions", test_case_id=1)
    assert len(removed) == 1
    assert [r.id for r in store.find("test_executions")] == [keep.id]


def test_returned_records_are_copies(store) -> None:
    rec = store.insert("projects", name="A")
    rec["name"] = "mutated locally"
    assert store.get("projects", rec.id).name == "A"


def test_clear_and_ping(store) -> None:
    store.insert("projects", name="A")
    store.ping()
    store.clear()
    assert store.find("projects") == []
    assert store.insert("projects", name="B").id == 1  # counters reset too


# ── Backend specifics ─────────────────────────────────────────


def test_local_store_persists_across_restarts(tmp_path: Path) -> None:
    path = tmp_path / "db.json"
    first = LocalStore(path)
    first.insert("projects", name="Kept")
    second = LocalStore(path)
    assert second.get("projects", 1).name == "Kept"
    assert second.insert("projects", name="Next").id == 2


def test_local_store_writes_atomically(tmp_path: Path) -> None:
    path = tmp_path / "db.json"
    LocalStore(path).insert("projects", name="A")
    assert json.loads(path.read_text(encoding="utf-8"))["data"]["projects"]["1"]["name"] == "A"
    assert not path.with_suffix(".tmp").exists()


def test_local_store_reports_corrupt_file(tmp_path: Path) -> None:
    path = tmp_path / "db.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(StoreUnavailableError, match="unreadable"):
        LocalStore(path)


def test_memory_store_is_thread_safe() -> None:
    store = MemoryStore()
    threads = [threading.Thread(target=lambda: [store.insert("audit_events", n=i) for i in range(50)]) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    ids = [r.id for r in store.find("audit_events")]
    assert len(ids) == 400 and len(set(ids)) == 400


def test_unknown_backend_is_reported() -> None:
    with pytest.raises(StoreUnavailableError, match="Unknown DATABASE_BACKEND"):
        create_store("mongodb", local_path="x", credentials=None, project_id=None)


@pytest.mark.parametrize(("error", "expected"), [
    ("DefaultCredentialsError: Your default credentials were not found", "FIREBASE_CREDENTIALS"),
    ("ValueError: Invalid service account certificate", "valid service-account JSON"),
    ('ValueError: Failed to initialize a certificate credential. Caused by: "Service account info was not in the expected format"', "valid service-account JSON"),
    ("JSONDecodeError: Expecting property name enclosed in double quotes", "valid service-account JSON"),
    ("FileNotFoundError: [Errno 2] No such file or directory: 'key.json'", "does not exist"),
    ("NotFound: 404 The database (default) does not exist for project x", "Create database"),
    ("PermissionDenied: 403 Cloud Firestore API has not been used in project x", "API is disabled"),
    ("PermissionDenied: 403 Missing or insufficient permissions.", "lacks Firestore access"),
    ("RefreshError: invalid_grant: Invalid JWT Signature.", "rejected the credentials"),
    ("DeadlineExceeded: 504 Deadline Exceeded", "did not respond"),
])
def test_firestore_errors_are_explained(error: str, expected: str) -> None:
    assert expected in describe_firestore_error(Exception(error))


def test_firestore_bad_credentials_raise_store_error(monkeypatch) -> None:
    monkeypatch.delenv("FIRESTORE_EMULATOR_HOST", raising=False)
    import firebase_admin
    try:
        firebase_admin.delete_app(firebase_admin.get_app("testsphere"))
    except ValueError:
        pass
    with pytest.raises(StoreUnavailableError, match="service-account"):
        FirestoreStore.from_settings('{"type": "service_account", "project_id": "x"}', None)


def test_service_account_json_is_parsed_even_when_quoted() -> None:
    assert _service_account_source("'{\"project_id\": \"p\"}'") == {"project_id": "p"}


def test_missing_key_file_falls_back_to_secret_files(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "key.json").write_text("{}")
    monkeypatch.setattr(store_module, "SECRET_FILES_DIR", tmp_path)
    assert _service_account_source("C:/Users/me/key.json") == str(tmp_path / "key.json")


def test_missing_key_file_names_the_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(store_module, "SECRET_FILES_DIR", tmp_path)
    with pytest.raises(StoreUnavailableError, match=r"\(key\.json\)"):
        _service_account_source("serviceAccount/key.json")


def test_update_if_applies_only_while_the_field_is_unchanged(store) -> None:
    row = store.insert("projects", name="p", next_run_at="t1")
    assert store.update_if("projects", row["id"], "next_run_at", "t1", next_run_at="t2") is True
    assert store.update_if("projects", row["id"], "next_run_at", "t1", next_run_at="t3") is False
    assert store.get("projects", row["id"])["next_run_at"] == "t2"
    assert store.update_if("projects", 999, "next_run_at", "t2", next_run_at="t4") is False


def test_update_if_treats_a_missing_field_as_none(store) -> None:
    row = store.insert("projects", name="p")
    assert store.update_if("projects", row["id"], "next_run_at", None, next_run_at="t1") is True
    assert store.get("projects", row["id"])["next_run_at"] == "t1"


def test_concurrent_update_if_has_exactly_one_winner(store) -> None:
    row = store.insert("projects", name="p", next_run_at="t0")
    wins = []

    def claim(n):
        if store.update_if("projects", row["id"], "next_run_at", "t0", next_run_at=f"claimed-{n}"):
            wins.append(n)

    threads = [threading.Thread(target=claim, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(wins) == 1
    assert store.get("projects", row["id"])["next_run_at"] == f"claimed-{wins[0]}"
