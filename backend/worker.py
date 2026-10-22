"""
TestSphere-AI — Pipeline worker (``python -m backend.worker``).

With ``PIPELINE_EXECUTION=worker`` the API only queues pipeline runs; this
process executes them, so browser runs no longer share the API's memory and
queued runs survive API restarts or sleep.  It also runs the scheduler
(``SCHEDULER_ENABLED``), so scheduled runs keep firing while the API sleeps.

- Claim: the oldest queued run is taken with ``Store.update_if`` (queued →
  running), so several workers never execute the same run.
- Heartbeat: ``heartbeat_at`` is refreshed while a run executes; a running
  run whose heartbeat is older than ``WORKER_STALE_SECONDS`` belonged to a
  worker that died, and is marked interrupted (never silently re-run: a
  half-finished run may already have created tests and executions).
- One run at a time per worker (each needs a browser); scale by running more
  workers on separate machines.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import socket
from datetime import UTC, datetime, timedelta

from backend.config import pipeline_problem, settings
from backend.database.session import get_store, init_db
from backend.database.store import Record, Store, StoreUnavailableError, now_iso
from backend.models import PIPELINE_RUNS
from backend.observability import (
    configure_logging,
    default_log_format,
    init_error_reporting,
)
from backend.pipeline import runner

logger = logging.getLogger("testsphere.worker")

POLL_SECONDS = float(os.getenv("WORKER_POLL_SECONDS", "5"))
HEARTBEAT_SECONDS = float(os.getenv("WORKER_HEARTBEAT_SECONDS", "30"))
STALE_SECONDS = float(os.getenv("WORKER_STALE_SECONDS", "600"))


def worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def _parse(stamp: str | None) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(stamp) if stamp else None
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed and not parsed.tzinfo else parsed


def claim_next(db: Store, me: str) -> Record | None:
    """Atomically take the oldest queued run, or None when the queue is empty."""
    for row in sorted(db.find(PIPELINE_RUNS, status="queued"), key=lambda r: r["id"]):
        stamp = now_iso()
        if db.update_if(PIPELINE_RUNS, row["id"], "status", "queued",
                        status="running", worker=me, started_at=stamp, heartbeat_at=stamp):
            return db.get(PIPELINE_RUNS, row["id"])
    return None


def reap_stale(db: Store, now: datetime | None = None) -> list[int]:
    """Mark running runs whose worker stopped sending heartbeats as interrupted."""
    now = now or datetime.now(UTC)
    reaped = []
    for row in db.find(PIPELINE_RUNS, status="running"):
        last = _parse(row.get("heartbeat_at")) or _parse(row.get("started_at"))
        if last and now - last < timedelta(seconds=STALE_SECONDS):
            continue
        if db.update_if(PIPELINE_RUNS, row["id"], "heartbeat_at", row.get("heartbeat_at"),
                        status="error", finished_at=now_iso(),
                        error="Interrupted: the worker running it stopped before it finished."):
            reaped.append(row["id"])
    return reaped


async def _heartbeat(db: Store, run_id: int) -> None:
    while True:
        await asyncio.sleep(HEARTBEAT_SECONDS)
        try:
            db.update(PIPELINE_RUNS, run_id, heartbeat_at=now_iso())
        except StoreUnavailableError as exc:
            logger.warning("Heartbeat for run #%s failed: %s", run_id, exc)


async def run_one(db: Store, run: Record) -> None:
    beat = asyncio.create_task(_heartbeat(db, run["id"]))
    try:
        logger.info("Executing pipeline run #%s (%s)", run["id"], run.get("project_name"))
        result = await runner.execute_run(run["id"])
        logger.info("Pipeline run #%s finished: %s", run["id"], (result or {}).get("status"))
    finally:
        beat.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await beat


async def work(stop: asyncio.Event, db: Store | None = None) -> None:
    """Claim and execute queued runs until *stop* is set."""
    me = worker_id()
    logger.info("Worker %s polling every %ss", me, POLL_SECONDS)
    while not stop.is_set():
        db_now = db or get_store()
        try:
            if reaped := reap_stale(db_now):
                logger.warning("Marked run(s) %s interrupted (their worker stopped)", reaped)
            run = claim_next(db_now, me)
        except StoreUnavailableError as exc:
            logger.warning("Queue check skipped (database unavailable): %s", exc)
            run = None
        if run:
            await run_one(db_now, run)
            continue
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=POLL_SECONDS)


async def main() -> None:
    configure_logging(settings.LOG_LEVEL, default_log_format())
    init_error_reporting(settings.SENTRY_DSN, settings.APP_ENV, os.getenv("RENDER_GIT_COMMIT"))
    if problem := pipeline_problem():
        raise SystemExit(problem)
    if settings.PIPELINE_EXECUTION != "worker":
        logger.warning("PIPELINE_EXECUTION is %r: the API also executes runs; set it to 'worker' on both "
                       "services so runs are only executed here.", settings.PIPELINE_EXECUTION)
    init_db()

    from backend.netguard import check_target
    from engine.browser import set_request_guard

    set_request_guard(check_target)  # same SSRF policy for browser runs as in the API

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):  # not available on Windows
            loop.add_signal_handler(sig, stop.set)

    tasks = [asyncio.create_task(work(stop))]
    if settings.SCHEDULER_ENABLED:
        from backend.pipeline.scheduler import scheduler_loop

        tasks.append(asyncio.create_task(scheduler_loop()))
    await stop.wait()
    logger.info("Worker stopping: finishing the current run")
    await tasks[0]
    for task in tasks[1:]:
        task.cancel()


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main())
