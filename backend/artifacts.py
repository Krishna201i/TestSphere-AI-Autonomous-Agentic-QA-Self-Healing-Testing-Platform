"""
TestSphere-AI — Test artifact storage (screenshots, DOM snapshots, traces).

The engine writes artifacts to local disk while a test runs; afterwards
``persist_run_artifacts`` copies the ones worth keeping into the artifact
store and returns their keys, which are saved on the execution record.

Backends (``ARTIFACT_STORE``):
  * ``local`` — files under ``ARTIFACTS_DIR`` (development, single server).
  * ``gcs``   — a Cloud Storage bucket (``ARTIFACT_BUCKET``), via the same
    firebase-admin credentials as Firestore.  Survives redeploys and is shared
    by the API and a separate worker.

Keys are ``{owner_uid}/executions/{execution_id}/{name}``; the API only
serves keys recorded on an execution the caller owns, so a key is never
taken from the request.
"""

from __future__ import annotations

import logging
import mimetypes
import re
import shutil
import time
from pathlib import Path
from typing import Any, Protocol

from backend.config import settings

logger = logging.getLogger("testsphere.artifacts")

# Per artifact; a full-page screenshot of a long page can be several MB
MAX_ARTIFACT_BYTES = 20 * 1024 * 1024
_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


class ArtifactStore(Protocol):
    def put(self, key: str, data: bytes, content_type: str) -> None: ...
    def get(self, key: str) -> tuple[bytes, str] | None: ...
    def delete_prefix(self, prefix: str) -> int: ...
    def expire_after(self, days: int) -> int: ...


def safe_part(value: Any) -> str:
    """One path segment: letters, digits, dot, dash, underscore only."""
    return _SAFE.sub("_", str(value)).strip("._") or "_"


def execution_prefix(owner_uid: str, execution_id: int) -> str:
    return f"{safe_part(owner_uid)}/executions/{int(execution_id)}/"


class LocalArtifactStore:
    def __init__(self, root: str) -> None:
        self.root = Path(root).resolve()

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root not in path.parents:
            raise ValueError(f"artifact key escapes the store: {key!r}")
        return path

    def put(self, key: str, data: bytes, content_type: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def get(self, key: str) -> tuple[bytes, str] | None:
        path = self._path(key)
        if not path.is_file():
            return None
        return path.read_bytes(), mimetypes.guess_type(path.name)[0] or "application/octet-stream"

    def delete_prefix(self, prefix: str) -> int:
        path = self._path(prefix.rstrip("/"))
        if not path.exists():
            return 0
        count = sum(1 for p in path.rglob("*") if p.is_file())
        shutil.rmtree(path, ignore_errors=True)
        return count

    def expire_after(self, days: int) -> int:
        """Delete files older than *days*; returns how many."""
        if not self.root.exists():
            return 0
        cutoff = time.time() - days * 86400
        old = [p for p in self.root.rglob("*") if p.is_file() and p.stat().st_mtime < cutoff]
        for p in old:
            p.unlink(missing_ok=True)
        return len(old)


class MemoryArtifactStore:
    """Process-local store (tests)."""

    def __init__(self) -> None:
        self.files: dict[str, tuple[bytes, str]] = {}

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self.files[key] = (data, content_type)

    def get(self, key: str) -> tuple[bytes, str] | None:
        return self.files.get(key)

    def delete_prefix(self, prefix: str) -> int:
        gone = [k for k in self.files if k.startswith(prefix)]
        for k in gone:
            del self.files[k]
        return len(gone)

    def expire_after(self, days: int) -> int:
        return 0


class GCSArtifactStore:
    """Cloud Storage bucket; everything lives under ROOT so a lifecycle rule
    can expire it without touching anything else in the bucket."""

    ROOT = "testsphere-artifacts/"

    def __init__(self, bucket: str) -> None:
        from firebase_admin import storage

        from backend.database.store import firebase_app

        app = firebase_app(settings.FIREBASE_CREDENTIALS or None, settings.FIREBASE_PROJECT_ID or None)
        self.bucket = storage.bucket(bucket, app=app)

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self.bucket.blob(self.ROOT + key).upload_from_string(data, content_type=content_type)

    def get(self, key: str) -> tuple[bytes, str] | None:
        blob = self.bucket.blob(self.ROOT + key)
        if not blob.exists():
            return None
        data = blob.download_as_bytes()
        return data, blob.content_type or "application/octet-stream"

    def delete_prefix(self, prefix: str) -> int:
        blobs = list(self.bucket.list_blobs(prefix=self.ROOT + prefix))
        for blob in blobs:
            blob.delete()
        return len(blobs)

    def expire_after(self, days: int) -> int:
        """Ask Cloud Storage to delete artifacts after *days* (a bucket lifecycle rule)."""
        self.bucket.reload()
        rules = [r for r in self.bucket.lifecycle_rules
                 if self.ROOT not in (r.get("condition", {}).get("matchesPrefix") or [])]
        self.bucket.lifecycle_rules = rules
        self.bucket.add_lifecycle_delete_rule(age=days, matches_prefix=[self.ROOT])
        self.bucket.patch()
        return 0


_store: ArtifactStore | None = None


def get_artifact_store() -> ArtifactStore:
    """The configured store (created on first use)."""
    global _store
    if _store is None:
        if settings.ARTIFACT_STORE == "gcs":
            if not settings.ARTIFACT_BUCKET:
                raise RuntimeError("ARTIFACT_STORE=gcs needs ARTIFACT_BUCKET (e.g. your-project.appspot.com).")
            _store = GCSArtifactStore(settings.ARTIFACT_BUCKET)
        else:
            _store = LocalArtifactStore(settings.ARTIFACTS_DIR)
    return _store


def set_artifact_store(store: ArtifactStore | None) -> None:
    """Swap the store (tests)."""
    global _store
    _store = store


def _upload(store: ArtifactStore, key: str, path: str | None) -> str | None:
    """Copy one local file into the store; None when missing, too big or the upload fails."""
    if not path:
        return None
    src = Path(path)
    try:
        if not src.is_file() or src.stat().st_size > MAX_ARTIFACT_BYTES:
            return None
        content_type = mimetypes.guess_type(src.name)[0] or "application/octet-stream"
        store.put(key, src.read_bytes(), content_type)
        return key
    except Exception as exc:  # noqa: BLE001 - an artifact is never worth failing the run for
        logger.warning("Could not store artifact %s: %s", key, exc)
        return None


def _short(text: str | None, limit: int) -> str | None:
    if not text:
        return text
    return text if len(text) <= limit else text[: limit - 1] + "…"


def persist_run_artifacts(
    engine_result: Any,
    owner_uid: str,
    execution_id: int,
    descriptions: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Store screenshots, DOM snapshots and the trace of an engine run.

    Returns ``{"steps": [...], "trace": key | None}`` ready to save on the
    execution record: one compact entry per step (status, timing, locator,
    trimmed error, healing evidence, artifact keys).
    """
    descriptions = descriptions or {}
    prefix = execution_prefix(owner_uid, execution_id)
    try:
        store = get_artifact_store()
    except Exception as exc:  # noqa: BLE001 - keep the step results even without storage
        logger.warning("Artifact store unavailable: %s", exc)
        store = None

    steps: list[dict[str, Any]] = []
    for st in getattr(engine_result, "steps", []) or []:
        step_part = safe_part(st.step_id)
        healing = None
        if st.healing:
            healing = {
                "original_locator": st.healing.original_locator,
                "selected_locator": st.healing.selected_locator,
                "strategy": st.healing.strategy_used,
                "confidence": round(float(st.healing.confidence), 3),
                "candidates": [
                    {"locator": c.locator, "score": round(float(c.score), 3)}
                    for c in (st.healing.candidates or [])[:3]
                ],
            }
        status = st.status.value if hasattr(st.status, "value") else str(st.status)
        steps.append({
            "step_id": st.step_id,
            "description": descriptions.get(st.step_id),
            "status": status,
            "duration_ms": st.duration_ms,
            "locator": st.locator_used,
            "error": _short(st.error, 2000),
            "healing": healing,
            "console": [_short(m, 300) for m in (st.console_logs or [])[:10]],
            "network_errors": [_short(m, 300) for m in (st.network_errors or [])[:10]],
            "screenshot": store and _upload(store, f"{prefix}{step_part}/screenshot.png", st.screenshot_path),
            "dom": store and _upload(store, f"{prefix}{step_part}/dom.html", st.dom_snapshot_path),
        })

    trace = None
    run_dir = getattr(engine_result, "artifacts_dir", None)
    if store and run_dir:
        trace = _upload(store, f"{prefix}trace.zip", str(Path(run_dir) / "_trace.zip"))
    return {"steps": steps, "trace": trace}


def baseline_key(owner_uid: str, test_case_id: int) -> str:
    return f"{safe_part(owner_uid)}/baselines/{int(test_case_id)}.png"


def load_baseline(owner_uid: str, test_case_id: int) -> bytes | None:
    """The approved screenshot of a test case, if it has one."""
    try:
        found = get_artifact_store().get(baseline_key(owner_uid, test_case_id))
    except Exception as exc:  # noqa: BLE001 - no baseline means no comparison, never a failed run
        logger.warning("Could not read the baseline of test case %s: %s", test_case_id, exc)
        return None
    return found[0] if found else None


def record_visual(visual: dict[str, Any] | None, owner_uid: str, execution_id: int, test_case_id: int,
                  baseline: bytes | None, *, passed: bool) -> dict[str, Any] | None:
    """Store a run's visual check; the first passing run's screenshot becomes the baseline.

    Returns what the execution keeps: ``changed`` (more than VISUAL_DIFF_THRESHOLD of the
    pixels differ), the share of changed pixels and the artifact keys.
    """
    if not visual or not visual.get("current"):
        return None
    try:
        store = get_artifact_store()
        prefix = execution_prefix(owner_uid, execution_id)
        current = _upload(store, f"{prefix}visual/current.png", visual["current"])
        key = baseline_key(owner_uid, test_case_id)
        if baseline is None:
            if not passed or store.get(key):  # one was accepted while this run went on
                return None
            store.put(key, Path(visual["current"]).read_bytes(), "image/png")
            return {"baseline_created": True, "changed": False, "current": current}
        # Re-saved on every comparison, so retention never expires a baseline
        # that is in use, but only while it is still the one compared: a
        # baseline accepted during this run must not be put back to the old one
        stored = store.get(key)
        if stored and stored[0] == baseline:
            store.put(key, baseline, "image/png")
        ratio = float(visual.get("ratio") or 0)
        return {
            "changed": bool(visual.get("size_changed")) or ratio > settings.VISUAL_DIFF_THRESHOLD,
            "ratio": ratio, "size_changed": bool(visual.get("size_changed")), "current": current,
            "diff": _upload(store, f"{prefix}visual/diff.png", visual.get("diff")),
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not store the visual check of execution %s: %s", execution_id, exc)
        return None


def accept_baseline(owner_uid: str, execution_id: int, test_case_id: int) -> bool:
    """Make an execution's screenshot the test case's baseline (a change that was intended)."""
    store = get_artifact_store()
    found = store.get(f"{execution_prefix(owner_uid, execution_id)}visual/current.png")
    if not found:
        return False
    store.put(baseline_key(owner_uid, test_case_id), found[0], "image/png")
    return True


def delete_owner_artifacts(owner_uid: str) -> int:
    """Erase every artifact of one account (account deletion)."""
    try:
        return get_artifact_store().delete_prefix(f"{safe_part(owner_uid)}/")
    except Exception as exc:  # noqa: BLE001 - reported, never blocks the erasure of records
        logger.error("Could not delete artifacts of %s: %s", owner_uid, exc)
        return 0


def delete_execution_artifacts(owner_uid: str, execution_id: int) -> int:
    try:
        return get_artifact_store().delete_prefix(execution_prefix(owner_uid, execution_id))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not delete artifacts of execution %s: %s", execution_id, exc)
        return 0


_last_expiry = 0.0
EXPIRY_EVERY_SECONDS = 6 * 3600


def expire_old_artifacts(force: bool = False) -> int | None:
    """Apply ARTIFACT_RETENTION_DAYS, at most every few hours; None when skipped."""
    global _last_expiry
    days = settings.ARTIFACT_RETENTION_DAYS
    if days <= 0 or (not force and time.time() - _last_expiry < EXPIRY_EVERY_SECONDS):
        return None
    _last_expiry = time.time()
    try:
        removed = get_artifact_store().expire_after(days)
    except Exception as exc:  # noqa: BLE001 - retried on the next window
        logger.warning("Could not apply the %s-day artifact retention: %s. On Cloud Storage the service "
                       "account needs storage.buckets.update, or add the lifecycle rule in the console.", days, exc)
        return None
    if removed:
        logger.info("Removed %s artifact(s) older than %s days", removed, days)
    return removed
