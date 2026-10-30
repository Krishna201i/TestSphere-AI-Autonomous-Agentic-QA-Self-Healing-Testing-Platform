"""The explorer in the pipeline: record once, replay later, explore again only when needed."""

from __future__ import annotations

import json

from agents.explorer import GoalExplorer
from agents.memory.in_memory_store import InMemoryStore
from backend.models import TEST_CASES, TEST_EXECUTIONS
from backend.models.test_execution import TestExecutionStatus
from backend.orchestration.orchestrator import (
    PlatformWorkflowOrchestrator,
    create_default_orchestrator,
)
from backend.pipeline import explore
from backend.services.application_service import ApplicationService
from backend.services.project_service import ProjectService
from backend.services.test_execution_service import TestExecutionService
from tests.explorer.test_explorer import ScriptedModel, num, site  # noqa: F401 - site is a fixture

GOAL = "open the Patient portal and reach the sign-in page"


def reach_portal() -> ScriptedModel:
    return ScriptedModel(
        lambda p: {"action": "click", "element": num(p, "Select Portal ↓")},
        lambda p: {"action": "click", "element": num(p, "Patient portal")},
        lambda p: {"action": "done", "check": {"type": "url_contains", "value": "/patient/login"}},
    )


def setup(db, url, goal=GOAL):
    project = ProjectService.create_project(db, name="CareLink", owner_uid="local-dev", app_url=url + "/", prompt=goal)
    app = ApplicationService.create_application(db, project["id"], name="CareLink", base_url=url + "/")
    return project, app


async def test_the_goal_is_recorded_once_quarantined_and_then_replayed(fresh_store, site):  # noqa: F811
    project, app = setup(fresh_store, site)

    row, note = await explore.explored_test(fresh_store, project, app, explorer=GoalExplorer(reach_portal()))
    assert row["name"] == f"AI explored: {GOAL}" and row["category"] == "explored" and row["quarantined"]
    stored = json.loads(row["description"])
    assert stored["generated_by"] == "explorer" and stored["prompt"] == GOAL
    assert [s["action"] for s in stored["steps"]] == ["NAVIGATE", "CLICK", "CLICK", "ASSERT_URL"]
    assert row["healing_targets"][0]["locator"] == "#menu"  # fallbacks for the healer
    assert note.startswith("AI explorer recorded the goal in 2 action(s) with 3 model call(s) (no recording yet)")

    # Next run: the recording replays, the model is not asked (a call would fail: no turns left)
    again, note = await explore.explored_test(fresh_store, project, app, explorer=GoalExplorer(ScriptedModel()))
    assert again["id"] == row["id"] and note == "replaying the AI-explored recording"


async def test_the_recording_passes_through_the_real_orchestrator(fresh_store, site):  # noqa: F811
    project, app = setup(fresh_store, site)
    row, _ = await explore.explored_test(fresh_store, project, app, explorer=GoalExplorer(reach_portal()))

    execution = TestExecutionService.create_execution(fresh_store, row["id"])
    service = PlatformWorkflowOrchestrator(create_default_orchestrator(InMemoryStore()))
    result = await service.execute_test_run(db=fresh_store, execution_id=execution["id"])
    assert result["status"] == "PASSED", result.get("error_message")


async def test_a_failed_replay_or_a_new_goal_is_explored_again(fresh_store, site):  # noqa: F811
    project, app = setup(fresh_store, site)
    row, _ = await explore.explored_test(fresh_store, project, app, explorer=GoalExplorer(reach_portal()))
    fresh_store.update(TEST_CASES, row["id"], quarantined=False)  # the user trusted it

    execution = TestExecutionService.create_execution(fresh_store, row["id"])
    fresh_store.update(TEST_EXECUTIONS, execution["id"], status=TestExecutionStatus.FAILED.value)
    again, note = await explore.explored_test(fresh_store, project, app, explorer=GoalExplorer(reach_portal()))
    assert again["id"] == row["id"] and again["version"] == 2 and again["quarantined"]  # new steps: review again
    assert "(the last replay failed)" in note

    project = ProjectService.update_project(fresh_store, project["id"], prompt="open the Doctor portal")
    doctor = ScriptedModel(
        lambda p: {"action": "click", "element": num(p, "Select Portal ↓")},
        lambda p: {"action": "click", "element": num(p, "Doctor portal")},
        lambda p: {"action": "done", "check": {"type": "url_contains", "value": "/doctor/login"}},
    )
    changed, note = await explore.explored_test(fresh_store, project, app, explorer=GoalExplorer(doctor))
    assert "(the goal changed)" in note and json.loads(changed["description"])["prompt"] == "open the Doctor portal"


async def test_an_exploration_that_fails_keeps_the_previous_recording(fresh_store, site):  # noqa: F811
    project, app = setup(fresh_store, site)
    row, _ = await explore.explored_test(fresh_store, project, app, explorer=GoalExplorer(reach_portal()))
    execution = TestExecutionService.create_execution(fresh_store, row["id"])
    fresh_store.update(TEST_EXECUTIONS, execution["id"], status=TestExecutionStatus.FAILED.value)

    stuck = ScriptedModel(lambda p: {"action": "give_up", "reason": "the menu is gone"})
    kept, note = await explore.explored_test(fresh_store, project, app, explorer=GoalExplorer(stuck))
    assert kept["id"] == row["id"] and kept["version"] == row.get("version", 1)
    assert note == ("AI explorer could not reach the goal (the last replay failed): "
                    "the model gave up: the menu is gone · kept the previous recording")


async def test_no_goal_or_no_model_means_no_exploration(fresh_store, site):  # noqa: F811
    project, app = setup(fresh_store, site, goal="")
    assert await explore.explored_test(fresh_store, project, app, explorer=GoalExplorer(ScriptedModel())) == (None, None)
    project, app = setup(fresh_store, site)
    assert await explore.explored_test(fresh_store, project, app) == (None, None)  # tests run on the mock model
