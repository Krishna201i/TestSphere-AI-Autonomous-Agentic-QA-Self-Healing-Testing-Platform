"""
TestSphere-AI — Document store.

All persistence goes through ``Store``: named collections of JSON-like
documents with integer ids, equality filters and simple ordering.  Three
backends implement it:

- ``FirestoreStore`` — Google Cloud Firestore (production), via firebase-admin.
- ``LocalStore``     — a JSON file on disk, for offline local development.
- ``MemoryStore``    — in-process dicts, for tests.

Documents are returned as ``Record`` (a dict with attribute access).
Timestamps are stored as ISO 8601 UTC strings, which sort correctly and
serialize the same way on every backend.

Backend failures (unreachable, bad credentials, missing database) raise
``StoreUnavailableError`` with a human-readable message; the API turns that
into a 503.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import threading
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

logger = logging.getLogger("testsphere.store")

COLLECTIONS = (
    "projects", "applications", "test_cases", "test_executions",
    "security_findings", "audit_events", "codebase_blueprints", "agent_memory",
)


class StoreUnavailableError(RuntimeError):
    """The storage backend cannot be reached or used; message says why."""


class Record(dict):
    """A stored document: a dict whose keys can also be read as attributes."""

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def to_iso(value: Any) -> Any:
    """Normalize datetimes to ISO UTC strings (naive datetimes are taken as UTC)."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    return value


def _clean(data: dict) -> dict:
    return {k: to_iso(v) for k, v in data.items()}


def _sort_and_limit(rows: list[Record], order_by: Optional[str], descending: bool, limit: Optional[int]) -> list[Record]:
    key = order_by or "id"
    rows.sort(key=lambda r: (r.get(key) is None, r.get(key) if r.get(key) is not None else 0), reverse=descending)
    return rows[:limit] if limit else rows


class Store(ABC):
    """Collection-of-documents storage interface."""

    name = "abstract"

    # ── Backend primitives ────────────────────────────────────

    @abstractmethod
    def _create(self, collection: str, data: dict) -> Record: ...

    @abstractmethod
    def get(self, collection: str, doc_id: int) -> Optional[Record]: ...

    @abstractmethod
    def find(self, collection: str, *, order_by: Optional[str] = None, descending: bool = False,
             limit: Optional[int] = None, **equals: Any) -> list[Record]: ...

    @abstractmethod
    def _update(self, collection: str, doc_id: int, changes: dict) -> Optional[Record]: ...

    @abstractmethod
    def delete(self, collection: str, doc_id: int) -> bool: ...

    @abstractmethod
    def ping(self) -> None:
        """Raise ``StoreUnavailableError`` if the backend is not usable."""

    @abstractmethod
    def clear(self) -> None:
        """Delete every document (tests and resets)."""

    # ── Helpers shared by all backends ────────────────────────

    def insert(self, collection: str, **fields: Any) -> Record:
        stamp = now_iso()
        data = {"created_at": stamp, "updated_at": stamp, **_clean(fields)}
        return self._create(collection, data)

    def update(self, collection: str, doc_id: int, **changes: Any) -> Optional[Record]:
        return self._update(collection, doc_id, {**_clean(changes), "updated_at": now_iso()})

    def find_one(self, collection: str, **equals: Any) -> Optional[Record]:
        rows = self.find(collection, limit=1, **equals)
        return rows[0] if rows else None

    def delete_where(self, collection: str, **equals: Any) -> list[Record]:
        rows = self.find(collection, **equals)
        for row in rows:
            self.delete(collection, row["id"])
        return rows


# ---------------------------------------------------------------------------
# In-memory / local JSON backends
# ---------------------------------------------------------------------------


class MemoryStore(Store):
    """Thread-safe in-process store (tests)."""

    name = "memory"

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._data: dict[str, dict[int, dict]] = {c: {} for c in COLLECTIONS}
        self._next: dict[str, int] = {c: 1 for c in COLLECTIONS}

    def _table(self, collection: str) -> dict[int, dict]:
        if collection not in self._data:
            self._data[collection] = {}
            self._next[collection] = 1
        return self._data[collection]

    def _persist(self) -> None:  # LocalStore writes to disk
        pass

    def _create(self, collection: str, data: dict) -> Record:
        with self._lock:
            table = self._table(collection)
            doc_id = self._next[collection]
            self._next[collection] = doc_id + 1
            table[doc_id] = {"id": doc_id, **copy.deepcopy(data)}
            self._persist()
            return Record(copy.deepcopy(table[doc_id]))

    def get(self, collection: str, doc_id: int) -> Optional[Record]:
        with self._lock:
            doc = self._table(collection).get(_as_int(doc_id))
            return Record(copy.deepcopy(doc)) if doc else None

    def find(self, collection, *, order_by=None, descending=False, limit=None, **equals):
        with self._lock:
            rows = [Record(copy.deepcopy(d)) for d in self._table(collection).values()
                    if all(d.get(k) == v for k, v in equals.items())]
        return _sort_and_limit(rows, order_by, descending, limit)

    def _update(self, collection, doc_id, changes):
        with self._lock:
            doc = self._table(collection).get(_as_int(doc_id))
            if doc is None:
                return None
            doc.update(copy.deepcopy(changes))
            self._persist()
            return Record(copy.deepcopy(doc))

    def delete(self, collection, doc_id):
        with self._lock:
            removed = self._table(collection).pop(_as_int(doc_id), None) is not None
            if removed:
                self._persist()
            return removed

    def ping(self) -> None:
        return None

    def clear(self) -> None:
        with self._lock:
            self._data = {c: {} for c in COLLECTIONS}
            self._next = {c: 1 for c in COLLECTIONS}
            self._persist()


class LocalStore(MemoryStore):
    """``MemoryStore`` persisted to a JSON file (offline local development)."""

    name = "local"

    def __init__(self, path: str | Path) -> None:
        super().__init__()
        self._path = Path(path)
        if self._path.exists():
            try:
                raw = json.loads(self._path.read_text(encoding="utf-8"))
                for coll, docs in raw.get("data", {}).items():
                    self._data[coll] = {int(k): v for k, v in docs.items()}
                self._next.update({k: int(v) for k, v in raw.get("next", {}).items()})
            except (OSError, ValueError) as exc:
                raise StoreUnavailableError(f"Local database file {self._path} is unreadable: {exc}") from exc

    def _persist(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        payload = {"data": {c: {str(k): v for k, v in t.items()} for c, t in self._data.items()}, "next": self._next}
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, self._path)  # atomic: never leaves a half-written file


def _as_int(doc_id: Any) -> int:
    try:
        return int(doc_id)
    except (TypeError, ValueError):
        return -1


# ---------------------------------------------------------------------------
# Firestore backend
# ---------------------------------------------------------------------------


def describe_firestore_error(exc: BaseException) -> str:
    """Readable cause + fix for Firestore / credential failures."""
    text = f"{type(exc).__name__}: {exc}"
    lower = text.lower()
    if "defaultcredentialserror" in lower or "could not automatically determine credentials" in lower:
        return ("No Firebase credentials. Set FIREBASE_CREDENTIALS to the service-account JSON "
                "(Firebase console → Project settings → Service accounts → Generate new private key).")
    if ("jsondecodeerror" in lower or "not in the expected format" in lower or "certificate credential" in lower
            or ("invalid" in lower and ("certificate" in lower or "service account" in lower or "private key" in lower))):
        return "FIREBASE_CREDENTIALS is not a valid service-account JSON. Paste the whole downloaded key file."
    if "filenotfounderror" in lower or "no such file" in lower:
        return ("FIREBASE_CREDENTIALS points to a file that does not exist. Set it to the key file's path, "
                "or paste the file's JSON contents directly.")
    if "database (default) does not exist" in lower or ("notfound" in lower and "database" in lower):
        return "Firestore is not enabled for this Firebase project. Open Firebase console → Firestore Database → Create database."
    if "has not been used" in lower or "is disabled" in lower:
        return "The Cloud Firestore API is disabled for this project. Enable it in Google Cloud console, wait a minute, then retry."
    if "permissiondenied" in lower or "insufficient permissions" in lower or "403" in lower:
        return "The service account lacks Firestore access. Use a key from Firebase → Service accounts (it has the right role)."
    if "unauthenticated" in lower or "invalid_grant" in lower:
        return "Firebase rejected the credentials (revoked or expired key). Generate a new private key."
    if "deadline" in lower or "unavailable" in lower or "timeout" in lower:
        return "Firestore did not respond in time. Check the server's internet connection."
    return "The backend could not use Firestore (check FIREBASE_CREDENTIALS and that Firestore is enabled)."


class FirestoreStore(Store):
    """Cloud Firestore backend.

    Documents live in a collection per entity with the integer id as the
    document id; ids come from per-collection counters in ``_meta/counters``
    incremented transactionally.  Equality filters run in Firestore; ordering
    with filters is done in Python so no composite indexes are required.
    """

    name = "firestore"

    def __init__(self, client: Any) -> None:
        self._db = client

    @classmethod
    def from_settings(cls, credentials: str | None, project_id: str | None) -> "FirestoreStore":
        try:
            import firebase_admin
            from firebase_admin import credentials as fb_credentials, firestore
        except ImportError as exc:  # pragma: no cover - dependency is in requirements
            raise StoreUnavailableError("firebase-admin is not installed on the server.") from exc

        try:
            app = firebase_admin.get_app("testsphere")
        except ValueError:
            try:
                options = {"projectId": project_id} if project_id else None
                if os.getenv("FIRESTORE_EMULATOR_HOST"):
                    from google.auth.credentials import AnonymousCredentials

                    class _EmulatorCredentials(fb_credentials.Base):
                        def get_credential(self):
                            return AnonymousCredentials()

                    cred = _EmulatorCredentials()
                    options = {"projectId": project_id or "demo-testsphere"}
                elif credentials:
                    info = credentials.strip()
                    cred = fb_credentials.Certificate(json.loads(info) if info.startswith("{") else info)
                else:
                    cred = fb_credentials.ApplicationDefault()
                app = firebase_admin.initialize_app(cred, options, name="testsphere")
            except Exception as exc:
                raise StoreUnavailableError(describe_firestore_error(exc)) from exc
        try:
            return cls(firestore.client(app))
        except Exception as exc:
            raise StoreUnavailableError(describe_firestore_error(exc)) from exc

    def _call(self, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except StoreUnavailableError:
            raise
        except Exception as exc:
            # google-api errors carry ~30 lines of metadata; the first line is the useful part
            logger.error("Firestore error: %s", (str(exc).splitlines() or [repr(exc)])[0][:300])
            raise StoreUnavailableError(describe_firestore_error(exc)) from exc

    def _next_id(self, collection: str) -> int:
        from google.cloud import firestore as gcf

        counters = self._db.collection("_meta").document("counters")
        transaction = self._db.transaction()

        @gcf.transactional
        def bump(txn) -> int:
            snap = counters.get(transaction=txn)
            current = (snap.to_dict() or {}).get(collection, 0) if snap.exists else 0
            txn.set(counters, {collection: current + 1}, merge=True)
            return current + 1

        return bump(transaction)

    def _create(self, collection, data):
        def run():
            doc_id = self._next_id(collection)
            doc = {"id": doc_id, **data}
            self._db.collection(collection).document(str(doc_id)).set(doc)
            return Record(doc)
        return self._call(run)

    def get(self, collection, doc_id):
        def run():
            snap = self._db.collection(collection).document(str(_as_int(doc_id))).get()
            return Record(snap.to_dict()) if snap.exists else None
        return self._call(run)

    def find(self, collection, *, order_by=None, descending=False, limit=None, **equals):
        def run():
            from google.cloud.firestore_v1.base_query import FieldFilter

            query = self._db.collection(collection)
            for field, value in equals.items():
                query = query.where(filter=FieldFilter(field, "==", value))
            if not equals and order_by:
                # single-field order + limit: served by Firestore's automatic index
                direction = "DESCENDING" if descending else "ASCENDING"
                query = query.order_by(order_by, direction=direction)
                if limit:
                    query = query.limit(limit)
                return [Record(s.to_dict()) for s in query.stream()]
            rows = [Record(s.to_dict()) for s in query.stream()]
            return _sort_and_limit(rows, order_by, descending, limit)
        return self._call(run)

    def _update(self, collection, doc_id, changes):
        def run():
            ref = self._db.collection(collection).document(str(_as_int(doc_id)))
            if not ref.get().exists:
                return None
            ref.update(changes)
            return Record(ref.get().to_dict())
        return self._call(run)

    def delete(self, collection, doc_id):
        def run():
            ref = self._db.collection(collection).document(str(_as_int(doc_id)))
            if not ref.get().exists:
                return False
            ref.delete()
            return True
        return self._call(run)

    def ping(self) -> None:
        self._call(lambda: self._db.collection("_meta").document("counters").get())

    def clear(self) -> None:
        def run():
            for name in (*COLLECTIONS, "_meta"):
                for snap in self._db.collection(name).stream():
                    snap.reference.delete()
        self._call(run)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_store(backend: str, *, local_path: str, credentials: str | None, project_id: str | None) -> Store:
    if backend == "memory":
        return MemoryStore()
    if backend == "local":
        return LocalStore(local_path)
    if backend == "firestore":
        return FirestoreStore.from_settings(credentials, project_id)
    raise StoreUnavailableError(f"Unknown DATABASE_BACKEND '{backend}' (use firestore, local or memory).")


def iter_ids(rows: Iterable[Record]) -> list[int]:
    return [r["id"] for r in rows]
