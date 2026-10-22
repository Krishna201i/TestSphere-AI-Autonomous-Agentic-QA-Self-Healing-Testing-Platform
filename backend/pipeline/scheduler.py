"""
TestSphere-AI — Scheduled pipeline re-runs (the regression loop).

Projects with ``schedule_minutes`` get a run whenever ``next_run_at`` has
passed.  ``scheduler_loop`` checks every ``SCHEDULER_INTERVAL_SECONDS`` while
the server is awake; hosts that sleep when idle (e.g. Render's free tier) can
be woken by an external cron calling ``POST /api/pipelines/scheduler/tick``.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import List, Optional

from backend.config import settings
from backend.database.session import get_store
from backend.database.store import Store, StoreUnavailableError
from backend.models import PROJECTS
from backend.pipeline.runner import active_run, start_run
from backend.services.project_service import next_run_after

logger = logging.getLogger("testsphere.scheduler")


def _parse(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def due_projects(db: Store, now: datetime) -> list:
    return [
        p for p in db.find(PROJECTS)
        if p.get("schedule_minutes") and p.get("app_url")
        and (_parse(p.get("next_run_at")) or now) <= now
    ]


async def tick(db: Optional[Store] = None, now: Optional[datetime] = None) -> List[int]:
    """Start a run for every due project; returns the new run ids."""
    db = db or get_store()
    now = now or datetime.now(timezone.utc)
    started: List[int] = []
    for project in due_projects(db, now):
        # Claim the slot by moving the schedule forward from the value we read:
        # only one scheduler (another instance, or the cron tick racing the
        # in-process loop) wins; the others see it changed and skip.  Moving it
        # forward also keeps a busy or failing project from spinning.
        claimed = db.update_if(PROJECTS, project["id"], "next_run_at", project.get("next_run_at"),
                               next_run_at=next_run_after(project["schedule_minutes"], now))
        if not claimed:
            logger.info("Project %s: slot already claimed by another scheduler", project["id"])
            continue
        if active_run(db, project["id"]):
            logger.info("Project %s: previous run still active, skipping this slot", project["id"])
            continue
        run = start_run(db, project, trigger="schedule", actor="scheduler",
                        detail=f"every {project['schedule_minutes']} min")
        started.append(run["id"])
    return started


async def scheduler_loop() -> None:
    logger.info("Pipeline scheduler running every %ss", settings.SCHEDULER_INTERVAL_SECONDS)
    while True:
        try:
            started = await tick()
            if started:
                logger.info("Scheduled pipeline runs started: %s", started)
        except StoreUnavailableError as exc:
            logger.warning("Scheduler skipped a tick (database unavailable): %s", exc)
        except Exception:
            logger.exception("Scheduler tick failed")
        await asyncio.sleep(max(15, settings.SCHEDULER_INTERVAL_SECONDS))
