"""
TestSphere-AI — The goal explorer in the automated pipeline (plan stage).

When a project has a written goal and a real model is configured
(``PIPELINE_AI_EXPLORER`` = auto, on or off), the explorer agent
(``agents/explorer``) reaches the goal in a browser once and its verified
steps are saved as the test "AI explored: <goal>".  Later runs replay that
recording like any other test, without the model.  The goal is explored
again only when there is no recording yet, the goal changed, or the last
replay failed even after healing.  A new recording starts quarantined, like
every test a model wrote.  Any explorer failure leaves the run as it was and
says why in the plan stage.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from backend.config import settings
from backend.database.store import Record, Store
from backend.models import TEST_CASES, TEST_EXECUTIONS
from backend.models.test_execution import TestExecutionStatus
from backend.services.test_case_service import TestCaseService
from backend.services.url_analyzer import URLAnalyzerService

logger = logging.getLogger("testsphere.explore")

SLUG = "explored"


def enabled() -> bool:
    from agents.llm.config import LLMConfig

    mode = settings.PIPELINE_AI_EXPLORER
    return mode == "on" or (mode == "auto" and LLMConfig.from_env().provider != "mock")


def _recorded_goal(row: Record) -> str | None:
    try:
        return json.loads(row.get("description") or "{}").get("prompt")
    except (ValueError, AttributeError):
        return None


def needs_exploring(db: Store, row: Record | None, goal: str) -> str | None:
    """Why the goal must be explored (again), or None to replay the recording."""
    if row is None:
        return "no recording yet"
    if _recorded_goal(row) != goal:
        return "the goal changed"
    last = db.find(TEST_EXECUTIONS, test_case_id=row["id"], order_by="id", descending=True, limit=1)
    if last and last[0].get("status") == TestExecutionStatus.FAILED.value:
        return "the last replay failed"
    return None


async def explored_test(db: Store, project: Record, application: Record, *, explorer: Any = None,
                        external_prefix: str = "pipe-") -> tuple[Record | None, str | None]:
    """The project's AI-explored test (recorded now, or the existing recording) and a note for the plan stage."""
    goal = (project.get("prompt") or "").strip()
    if not goal or (explorer is None and not enabled()):
        return None, None
    external_id = f"{external_prefix}{project['id']}-{SLUG}"
    row = db.find_one(TEST_CASES, application_id=application["id"], external_id=external_id)
    why = needs_exploring(db, row, goal)
    if why is None:
        return row, "replaying the AI-explored recording"

    try:
        result = await asyncio.wait_for(_explore(project["app_url"], goal, explorer),
                                        timeout=settings.PIPELINE_AI_EXPLORER_TIMEOUT)
    except Exception as exc:  # noqa: BLE001 - the rest of the suite still runs
        logger.warning("AI explorer skipped for project %s: %s", project["id"], exc)
        return row, f"AI explorer skipped ({type(exc).__name__}: {str(exc)[:120] or 'no answer'})"
    if not result.reached:
        note = f"AI explorer could not reach the goal ({why}): {result.reason}"
        return row, note + (" · kept the previous recording" if row else "")

    description = json.dumps({"steps": result.steps, "generated_by": "explorer", "prompt": goal,
                              "outcome": result.outcome, "notes": result.notes})
    name = f"AI explored: {goal}"[:255]
    if row is None:
        row = TestCaseService.create_test_case(
            db, application_id=application["id"], external_id=external_id, name=name, description=description,
            category=SLUG, priority="normal", owner_uid=project.get("owner_uid"))
        row = db.update(TEST_CASES, row["id"], quarantined=True, healing_targets=result.healing_targets)
    else:
        # New steps replace what someone may have trusted: quarantined again until reviewed
        row = db.update(TEST_CASES, row["id"], name=name, description=description, quarantined=True,
                        healing_targets=result.healing_targets, version=int(row.get("version") or 1) + 1)
    actions = len(result.steps) - 2  # without the opening navigation and the outcome check
    return row, (f"AI explorer recorded the goal in {actions} action(s) with {result.model_calls} model call(s) ({why}), "
                 f"quarantined until you trust it")


async def _explore(app_url: str, goal: str, explorer: Any):
    from agents.explorer import GoalExplorer
    from backend.orchestration.orchestrator import create_platform_llm_client
    from engine.browser import BrowserSession
    from engine.schemas import EngineConfig

    explorer = explorer or GoalExplorer(create_platform_llm_client())
    async with BrowserSession(EngineConfig(headless=True)) as session:
        page = await session.new_page()
        return await explorer.explore(page, app_url, goal, URLAnalyzerService.prompt_values(goal))
