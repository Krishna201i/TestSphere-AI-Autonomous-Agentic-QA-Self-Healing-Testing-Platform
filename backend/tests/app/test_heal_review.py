"""Self-healing review: every heal listed with its evidence; approve writes it in, reject undoes it for good."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.database.session import get_store
from app.main import app
from app.models import TEST_CASES, TEST_EXECUTIONS
from app.orchestration.converters import drop_rejected
from app.orchestration.orchestrator import rejected_heals
from app.services.application_service import ApplicationService
from app.services.project_service import ProjectService
from app.services.test_case_service import TestCaseService
from app.services.test_execution_service import TestExecutionService

STEPS = [{"step_number": 1, "action": "NAVIGATE", "value": "https://shop.example/"},
         {"step_number": 2, "action": "CLICK", "target": "#login"},
         {"step_number": 3, "action": "ASSERT_VISIBLE", "target": "#welcome"}]


@pytest.fixture
def client():
    return TestClient(app)


def healed_run(*, written_back: bool, ai: bool = False):
    """A test whose #login healed to #sign-in in one execution."""
    db = get_store()
    project = ProjectService.create_project(db, name="Shop")
    application = ApplicationService.create_application(db, project.id, name="Shop", base_url="https://shop.example/")
    steps = json.loads(json.dumps(STEPS))
    history = []
    if written_back:
        steps[1]["target"] = "#sign-in"
        history = [{"from": "#login", "to": "#sign-in", "execution_id": 1}]
    tc = TestCaseService.create_test_case(db, application.id, external_id="studio-1-a", name="Sign in",
                                          description=json.dumps({"steps": steps}))
    db.update(TEST_CASES, tc.id, locator_history=history, healing_targets=[
        {"locator": "#sign-in" if written_back else "#login",
         "fallback_locators": ["#login" if written_back else "#sign-in", "button.primary"], "fingerprint": None}])
    execution = TestExecutionService.create_execution(db, tc.id)
    if ai:
        fields = {"error_message": "Self-healed #login -> #sign-in (AI healer, confidence 0.82)", "steps": []}
    else:
        fields = {"error_message": "Self-healed #login -> #sign-in (fingerprint, confidence 0.95)",
                  "steps": [{"step_id": "step-2", "description": "click Log in", "status": "HEALED", "screenshot": "s/2.png",
                             "healing": {"original_locator": "#login", "selected_locator": "#sign-in",
                                         "strategy": "fingerprint", "confidence": 0.95, "candidates": []}}]}
    db.update(TEST_EXECUTIONS, execution.id, status="HEALED", completed_at="2026-11-23T10:00:00+00:00", **fields)
    return db, tc.id, execution.id


def stored_steps(db, tc_id):
    return json.loads(db.get(TEST_CASES, tc_id)["description"])["steps"]


def test_heals_are_listed_with_their_evidence(client):
    _, tc_id, ex_id = healed_run(written_back=True)
    body = client.get("/heals").json()
    assert body["total"] == 1 and body["pending"] == 1
    [heal] = body["heals"]
    assert heal["execution_id"] == ex_id and heal["test_case_id"] == tc_id and heal["test_name"] == "Sign in"
    assert (heal["original"], heal["selected"], heal["strategy"]) == ("#login", "#sign-in", "fingerprint")
    assert heal["confidence"] == 0.95 and heal["screenshot"] == "s/2.png" and heal["step"] == "click Log in"
    assert heal["written_back"] is True and heal["review"] is None


def test_the_ai_healers_heals_are_listed_too(client):
    healed_run(written_back=False, ai=True)
    [heal] = client.get("/heals").json()["heals"]
    assert heal["strategy"] == "ai_healer" and heal["confidence"] == 0.82 and heal["written_back"] is False


def test_approving_writes_an_unsure_heal_into_the_test(client):
    db, tc_id, ex_id = healed_run(written_back=False)
    res = client.post(f"/heals/{ex_id}/review", json={"original_locator": "#login", "decision": "approve"})
    assert res.status_code == 200, res.text
    assert res.json()["review"]["decision"] == "approved" and res.json()["written_back"] is True
    assert stored_steps(db, tc_id)[1]["target"] == "#sign-in"
    tc = db.get(TEST_CASES, tc_id)
    assert tc["version"] == 2 and tc["locator_history"][-1]["reviewed"] is True
    assert client.get("/heals").json()["approved"] == 1


def test_rejecting_undoes_the_write_back_and_forgets_the_replacement(client):
    db, tc_id, ex_id = healed_run(written_back=True)
    res = client.post(f"/heals/{ex_id}/review", json={"original_locator": "#login", "decision": "reject"})
    assert res.json()["review"]["decision"] == "rejected" and res.json()["written_back"] is False
    tc = db.get(TEST_CASES, tc_id)
    assert stored_steps(db, tc_id)[1]["target"] == "#login"  # back to what the author wrote
    assert rejected_heals(tc) == {"#login"}
    [target] = tc["healing_targets"]  # nothing learned about #login is left to heal with
    assert target["locator"] == "#login" and target["fallback_locators"] == [] and target["fingerprint"] is None
    assert client.get("/heals").json()["rejected"] == 1


def test_approving_after_rejecting_clears_the_rejection(client):
    db, tc_id, ex_id = healed_run(written_back=False)
    client.post(f"/heals/{ex_id}/review", json={"original_locator": "#login", "decision": "reject"})
    client.post(f"/heals/{ex_id}/review", json={"original_locator": "#login", "decision": "approve"})
    assert rejected_heals(db.get(TEST_CASES, tc_id)) == set()
    assert stored_steps(db, tc_id)[1]["target"] == "#sign-in"


def test_reviews_are_audited(client):
    _, _, ex_id = healed_run(written_back=False)
    client.post(f"/heals/{ex_id}/review", json={"original_locator": "#login", "decision": "reject"})
    assert any(a["kind"] == "heal" and "#login -> #sign-in" in a["message"] for a in client.get("/audit").json())


def test_unknown_heal_is_404(client):
    _, _, ex_id = healed_run(written_back=False)
    res = client.post(f"/heals/{ex_id}/review", json={"original_locator": "#nope", "decision": "approve"})
    assert res.status_code == 404


def test_drop_rejected_forgets_everything_learned_about_that_locator_only():
    targets = [{"locator": "#a", "fallback_locators": ["#x", "#y"], "fingerprint": {"tag": "button"}},
               {"locator": "#b", "fallback_locators": ["#x"], "fingerprint": None}]
    assert drop_rejected(targets, {"#a"}) == [{"locator": "#a", "fallback_locators": [], "fingerprint": None},
                                              {"locator": "#b", "fallback_locators": ["#x"], "fingerprint": None}]
