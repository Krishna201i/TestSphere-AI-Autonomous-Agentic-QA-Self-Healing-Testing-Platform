"""
Automated pipeline: suite planning, a full run through every stage (page
analysis, browser and network stubbed), regressions between runs, the
scheduler loop and the GitHub push webhook.
"""

import asyncio
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.api.webhooks import signature_for
from backend.config import settings
from backend.main import app
from backend.models import BLUEPRINTS, PIPELINE_RUNS, PROJECTS, TEST_CASES
from backend.pipeline import runner, scheduler, suite
from backend.services.project_service import ProjectService
from security import OutOfScopeError, PassiveScanner, ScopePolicy

URL = "http://app.test/login"


def analysis(**overrides):
    base = {
        "success": True, "url": URL, "status_code": 200, "latency_ms": 42, "page_title": "Shop Login",
        "elements_inventory": {
            "inputs_count": 2, "buttons_count": 1, "links_count": 4,
            "headings": ["Welcome back"],
            "links": ["/about", "https://elsewhere.example/x", "/logout", "mailto:a@b.c"],
        },
        "synthesized_test_case": {"steps": [
            {"step_number": 1, "action": "NAVIGATE", "value": URL, "target": None, "description": "open"},
            {"step_number": 2, "action": "FILL", "target": "#username", "value": "u", "description": "fill"},
            {"step_number": 3, "action": "CLICK", "target": "button.radius", "value": None, "description": "click"},
        ]},
    }
    base.update(overrides)
    return base


BLUEPRINT = {"routes": [
    {"method": "GET", "path": "/pricing", "file": "app.py", "line": 1},
    {"method": "GET", "path": "/users/{id}", "file": "app.py", "line": 2},
    {"method": "POST", "path": "/login", "file": "app.py", "line": 3},
    {"method": "GET", "path": "/about", "file": "app.py", "line": 4},
]}


# ── suite planning ─────────────────────────────────────────────


def test_page_tests_cover_smoke_interaction_and_content():
    tests = suite.page_tests(analysis(), prompt="log in as admin")
    assert [t["slug"] for t in tests] == ["smoke", "interaction", "content"]
    assert tests[1]["name"] == "Scenario: log in as admin"
    assert tests[2]["steps"][1] == {"step_number": 2, "action": "ASSERT_CONTAINS_TEXT", "target": "body",
                                    "value": "Welcome back", "description": "Page shows 'Welcome back'"}


def test_candidate_pages_are_same_site_safe_and_parameter_free():
    pages = suite.candidate_pages(analysis(), BLUEPRINT)
    assert [(p["kind"], p["url"]) for p in pages] == [
        ("link", "http://app.test/about"),
        ("route", "http://app.test/pricing"),  # /about deduplicated, /users/{id} and POST skipped
    ]


# ── full run ───────────────────────────────────────────────────


class FakeOrchestrator:
    def __init__(self, outcomes):
        self.outcomes = outcomes  # test name substring -> (status, error)
        self.ran = []

    async def execute_test_run(self, db, execution_id, options=None):
        tc = db.get(TEST_CASES, db.get("test_executions", execution_id)["test_case_id"])
        self.ran.append(tc["name"])
        status, error = next((v for k, v in self.outcomes.items() if k in tc["name"]), ("PASSED", None))
        db.update("test_executions", execution_id, status=status, error_message=error)
        return {"status": status, "error_message": error}


def scanner_for(headers):
    transport = httpx.MockTransport(lambda r: httpx.Response(200, headers=headers, text=""))
    return PassiveScanner(ScopePolicy.of("app.test"), transport=transport)


class OutOfScope:
    async def fetch(self, url):
        raise OutOfScopeError("app.test:80 is not in the authorized scope (127.0.0.1)")


@pytest.fixture
def stub_network(monkeypatch):
    state = {"analysis": analysis(), "codes": {"http://app.test/about": 200, "http://app.test/pricing": 404}}

    async def analyze(url, prompt=None, test_case_name=None):
        return state["analysis"]

    async def reachable(urls):
        return {u: state["codes"].get(u) for u in urls}

    monkeypatch.setattr("backend.pipeline.runner.URLAnalyzerService.analyze_live_website", analyze)
    monkeypatch.setattr(runner, "_reachable", reachable)
    return state


def make_project(db, **fields):
    return ProjectService.create_project(db, name="Shop", owner_uid="local-dev", app_url=URL, **fields)


def run_once(db, project, orchestrator, scanner, trigger="manual"):
    run = runner.create_run(db, project, trigger=trigger, actor="tester")
    return asyncio.run(runner.execute_run(run["id"], orchestrator=orchestrator, scanner=scanner))


def stage(run, key):
    return next(s for s in run["stages"] if s["key"] == key)


def test_full_run_chains_every_stage(fresh_store, stub_network):
    project = make_project(fresh_store, prompt="log in", repo_url="https://github.com/acme/shop")
    # An earlier ingestion of the repo: its GET routes become page tests
    fresh_store.insert(BLUEPRINTS, source=project["repo_url"], name="shop", project_id=project["id"], owner_uid="local-dev",
                       data=json.dumps({**BLUEPRINT, "analyzed_at": "2026-10-20T10:00:00+00:00"}))
    orch = FakeOrchestrator({"Scenario": ("HEALED", "Self-healed #user -> #username")})
    run = run_once(fresh_store, project, orch, scanner_for({"content-type": "text/html"}))

    assert run["status"] == "passed"
    assert stage(run, "codebase")["status"] == "done"
    assert "Using the blueprint from 2026-10-20 10:00 (4 routes)" in stage(run, "codebase")["detail"]
    assert stage(run, "analyze")["status"] == "done"
    plan = stage(run, "plan")
    assert plan["status"] == "done"
    assert "4 tests: 4 generated (4 new)" in plan["detail"]
    assert "GET /pricing (404)" in plan["detail"]  # unreachable page left out, and said so
    assert orch.ran == ["Smoke: Shop Login", "Scenario: log in", "Content: heading 'Welcome back'", "Linked page: /about"]
    assert stage(run, "heal")["detail"].startswith("1 test(s) self-healed")
    assert stage(run, "security")["status"] == "done"
    assert run["summary"]["total"] == 4 and run["summary"]["healed"] == 1 and run["summary"]["findings"]
    assert all(s["status"] in ("done", "skipped") for s in run["stages"])

    refreshed = fresh_store.get(PROJECTS, project["id"])
    assert refreshed["last_run_id"] == run["id"] and refreshed["last_run_status"] == "passed"


def test_second_run_reuses_generated_tests_and_reports_regressions(fresh_store, stub_network):
    project = make_project(fresh_store)
    first = run_once(fresh_store, project, FakeOrchestrator({}), OutOfScope())
    assert first["status"] == "passed"
    assert stage(first, "security")["status"] == "skipped"
    assert "SECURITY_SCAN_ALLOWED_HOSTS" in stage(first, "security")["detail"]

    second = run_once(fresh_store, project, FakeOrchestrator({"Smoke": ("FAILED", "Timeout")}), OutOfScope(), trigger="schedule")
    assert "0 new" in stage(second, "plan")["detail"]
    assert len(fresh_store.find(TEST_CASES)) == len(first["tests"])  # no duplicates
    assert second["status"] == "failed"
    assert second["regressions"] == [{"kind": "test", "name": "Smoke: Shop Login", "test_case_id": second["tests"][0]["test_case_id"],
                                      "was": "PASSED", "now": "FAILED", "error": "Timeout"}]
    assert second["summary"]["previous_run_id"] == first["id"]


def test_flaky_tests_are_flagged_after_flipping_twice(fresh_store, stub_network):
    project = make_project(fresh_store)
    outcomes = [{}, {"Smoke": ("FAILED", "Timeout")}, {}]  # pass, fail, pass: two flips
    runs = [run_once(fresh_store, project, FakeOrchestrator(o), OutOfScope()) for o in outcomes]
    smoke = next(t for t in runs[-1]["tests"] if t["name"].startswith("Smoke"))
    assert smoke["flaky"] is True
    assert runs[-1]["summary"]["flaky"] == 1
    assert not any(t["flaky"] for t in runs[1]["tests"])  # one flip is a regression, not yet flaky
    assert all(not t["flaky"] for t in runs[-1]["tests"] if t is not smoke)


def test_flaky_tests_ignore_steady_results():
    steady = [[{"test_case_id": 1, "status": "PASSED"}]] * 4
    flipping = [[{"test_case_id": 1, "status": s}] for s in ("PASSED", "FAILED", "HEALED")]
    assert runner.flaky_tests(steady, [{"test_case_id": 1, "status": "FAILED"}]) == set()
    assert runner.flaky_tests(flipping, [{"test_case_id": 1, "status": "HEALED"}]) == {1}


def test_a_quarantined_failure_is_reported_but_does_not_fail_the_run(fresh_store, stub_network):
    project = make_project(fresh_store)
    first = run_once(fresh_store, project, FakeOrchestrator({}), OutOfScope())
    smoke_id = next(t["test_case_id"] for t in first["tests"] if t["name"].startswith("Smoke"))
    fresh_store.update(TEST_CASES, smoke_id, quarantined=True)

    run = run_once(fresh_store, project, FakeOrchestrator({"Smoke": ("FAILED", "Timeout")}), OutOfScope())
    smoke = next(t for t in run["tests"] if t["test_case_id"] == smoke_id)
    assert smoke["status"] == "FAILED" and smoke["quarantined"] is True
    assert run["status"] == "passed"
    assert run["summary"]["failed"] == 0 and run["summary"]["quarantined_failed"] == 1
    assert stage(run, "execute")["status"] == "done"
    assert "1 quarantined failed" in stage(run, "execute")["detail"]  # never counted as a pass


def test_unreachable_target_stops_before_planning(fresh_store, stub_network):
    stub_network["analysis"] = analysis(success=False, status_code=404)
    run = run_once(fresh_store, make_project(fresh_store), FakeOrchestrator({}), OutOfScope())
    assert run["status"] == "error"
    assert "Could not load http://app.test/login (HTTP 404)" in run["error"]
    assert stage(run, "analyze")["detail"] == "http://app.test/login did not load (HTTP 404)"
    assert stage(run, "plan")["status"] == "skipped"
    assert fresh_store.find(TEST_CASES) == []


def test_saved_tests_run_alongside_generated_ones(fresh_store, stub_network):
    project = make_project(fresh_store)
    run_once(fresh_store, project, FakeOrchestrator({}), OutOfScope())
    app_id = fresh_store.find(TEST_CASES)[0]["application_id"]
    fresh_store.insert(TEST_CASES, application_id=app_id, external_id="my-checkout", name="My checkout test",
                       description=json.dumps({"steps": []}), owner_uid="local-dev", version=1)
    orch = FakeOrchestrator({})
    run_once(fresh_store, project, orch, OutOfScope())
    assert "My checkout test" in orch.ran


def test_restart_marks_unfinished_runs(fresh_store):
    run = runner.create_run(fresh_store, make_project(fresh_store), trigger="manual", actor="t")
    assert runner.recover_interrupted(fresh_store) == 1
    assert fresh_store.get(PIPELINE_RUNS, run["id"])["status"] == "error"


# ── API, scheduler, webhook ────────────────────────────────────


@pytest.fixture
def no_background(monkeypatch):
    """Record started runs instead of executing them."""
    started = []

    async def fake_execute(run_id, *a, **k):
        started.append(run_id)

    monkeypatch.setattr(runner, "execute_run", fake_execute)
    return started


def test_quick_run_creates_a_project_and_queues_a_run(no_background):
    client = TestClient(app)
    resp = client.post("/api/pipelines/quick", json={"url": "https://shop.example/", "prompt": "buy a hat"})
    assert resp.status_code == 202, resp.text
    run = resp.json()
    assert run["status"] == "queued" and run["trigger"] == "manual"
    project = client.get(f"/api/projects/{run['project_id']}").json()
    assert project["app_url"] == "https://shop.example/" and project["prompt"] == "buy a hat"
    assert project["webhook_secret"]
    # Same URL again while queued: refused, and no second project
    again = client.post("/api/pipelines/quick", json={"url": "https://shop.example/"})
    assert again.status_code == 409
    assert len(client.get("/api/projects").json()) == 1
    assert client.get(f"/api/pipelines/runs/{run['id']}").json()["id"] == run["id"]
    assert [r["id"] for r in client.get("/api/pipelines/runs").json()] == [run["id"]]


def test_project_schedule_validation_and_clearing():
    client = TestClient(app)
    bad = client.post("/api/projects", json={"name": "x", "schedule_minutes": 7})
    assert bad.status_code == 422
    pid = client.post("/api/projects", json={"name": "x", "app_url": URL, "schedule_minutes": 60}).json()["id"]
    project = client.get(f"/api/projects/{pid}").json()
    assert project["schedule_minutes"] == 60 and project["next_run_at"]
    cleared = client.put(f"/api/projects/{pid}", json={"schedule_minutes": None}).json()
    assert cleared["schedule_minutes"] is None and cleared["next_run_at"] is None
    assert cleared["app_url"] == URL  # untouched fields are kept


def test_scheduler_starts_due_projects_once(fresh_store, no_background):
    due = make_project(fresh_store, schedule_minutes=60)
    fresh_store.update(PROJECTS, due["id"], next_run_at=(datetime.now(UTC) - timedelta(minutes=1)).isoformat())
    make_project(fresh_store, schedule_minutes=60)  # next run an hour away
    make_project(fresh_store)  # no schedule

    async def go():
        first = await scheduler.tick(fresh_store)
        await asyncio.sleep(0)
        second = await scheduler.tick(fresh_store)
        return first, second

    first, second = asyncio.run(go())
    assert len(first) == 1 and second == []
    assert fresh_store.get(PIPELINE_RUNS, first[0])["trigger"] == "schedule"
    assert datetime.fromisoformat(fresh_store.get(PROJECTS, due["id"])["next_run_at"]) > datetime.now(UTC)


def test_two_schedulers_racing_start_one_run(fresh_store, no_background, monkeypatch):
    """Both read the project as due before either moved its schedule (two
    instances, or the cron tick racing the in-process loop): one run, not two."""
    due = make_project(fresh_store, schedule_minutes=60)
    fresh_store.update(PROJECTS, due["id"], next_run_at=(datetime.now(UTC) - timedelta(minutes=1)).isoformat())
    stale = scheduler.due_projects(fresh_store, datetime.now(UTC))
    monkeypatch.setattr(scheduler, "due_projects", lambda db, now: stale)
    monkeypatch.setattr(scheduler, "active_run", lambda db, pid: None)  # neither has seen the other's run yet

    async def go():
        return await asyncio.gather(scheduler.tick(fresh_store), scheduler.tick(fresh_store))

    first, second = asyncio.run(go())
    assert len(first) + len(second) == 1
    assert len(fresh_store.find(PIPELINE_RUNS, project_id=due["id"])) == 1


def test_cron_tick_requires_the_secret(monkeypatch, no_background):
    client = TestClient(app)
    assert client.post("/api/pipelines/scheduler/tick").status_code == 503
    monkeypatch.setattr(settings, "CRON_SECRET", "s3cret")
    assert client.post("/api/pipelines/scheduler/tick", headers={"X-Cron-Secret": "nope"}).status_code == 401
    assert client.post("/api/pipelines/scheduler/tick", headers={"X-Cron-Secret": "s3cret"}).json() == {"started": []}


def push_payload(repo="https://github.com/acme/shop", branch="main"):
    return json.dumps({
        "ref": f"refs/heads/{branch}", "after": "abc1234def",
        "repository": {"html_url": repo, "clone_url": repo + ".git", "default_branch": "main"},
        "head_commit": {"message": "Fix login button\n\nlong body"}, "pusher": {"name": "krishna"},
    }).encode()


def deliver(client, project, body, event="push", secret=None):
    sig = signature_for(secret or project["webhook_secret"], body)
    return client.post(f"/api/webhooks/github/{project['id']}", content=body,
                       headers={"X-GitHub-Event": event, "X-Hub-Signature-256": sig, "Content-Type": "application/json"})


def test_github_push_triggers_a_run_with_reingestion(fresh_store, no_background):
    client = TestClient(app)
    project = make_project(fresh_store, repo_url="https://github.com/acme/shop.git")
    assert deliver(client, project, b"{}", event="ping").json()["ok"] is True

    resp = deliver(client, project, push_payload())
    assert resp.status_code == 200, resp.text
    run = fresh_store.get(PIPELINE_RUNS, resp.json()["started"])
    assert run["trigger"] == "webhook" and run["ingest"] is True
    assert run["trigger_detail"] == "abc1234 Fix login button" and run["actor"] == "github:krishna"


def test_github_webhook_rejects_bad_signatures_and_ignores_other_pushes(fresh_store, no_background):
    client = TestClient(app)
    project = make_project(fresh_store, repo_url="https://github.com/acme/shop")
    assert deliver(client, project, push_payload(), secret="wrong").status_code == 401
    assert client.post("/api/webhooks/github/999", content=b"{}").status_code == 401
    assert "default branch" in deliver(client, project, push_payload(branch="feature")).json()["ignored"]
    assert "not this project" in deliver(client, project, push_payload(repo="https://github.com/other/repo")).json()["ignored"]
    assert no_background == []


def test_scheduler_moves_slot_forward_for_projects_without_app_url(fresh_store, no_background):
    past = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    project = fresh_store.insert(PROJECTS, name="no-url", schedule_minutes=30, next_run_at=past, app_url=None)
    assert asyncio.run(scheduler.tick(fresh_store)) == []
    assert fresh_store.get(PROJECTS, project["id"])["next_run_at"] > past
    assert scheduler.due_projects(fresh_store, datetime.now(UTC)) == []


# ── A run that stops part-way never looks unfinished ───────────


def test_a_crash_closes_the_running_stage_and_updates_the_project(fresh_store, stub_network, monkeypatch):
    async def broken_plan(*a, **k):
        raise RuntimeError("planner exploded")

    monkeypatch.setattr(runner, "_plan", broken_plan)
    project = make_project(fresh_store)
    fresh_store.update(PROJECTS, project["id"], last_run_status="passed")
    run = run_once(fresh_store, project, FakeOrchestrator({}), OutOfScope())

    assert run["status"] == "error" and "planner exploded" in run["error"]
    assert stage(run, "plan")["status"] == "failed" and "planner exploded" in stage(run, "plan")["detail"]
    assert not [s for s in run["stages"] if s["status"] in ("running", "pending")]
    assert fresh_store.get(PROJECTS, project["id"])["last_run_status"] == "error"


def test_restart_closes_the_stages_of_unfinished_runs(fresh_store):
    project = make_project(fresh_store)
    run = runner.create_run(fresh_store, project, trigger="manual", actor="t")
    stages = [dict(s) for s in run["stages"]]
    stages[0]["status"], stages[1]["status"] = "done", "running"
    fresh_store.update(PIPELINE_RUNS, run["id"], status="running", stages=stages)

    runner.recover_interrupted(fresh_store)

    done = fresh_store.get(PIPELINE_RUNS, run["id"])
    assert [s["status"] for s in done["stages"]][:3] == ["done", "failed", "skipped"]
    assert fresh_store.get(PROJECTS, project["id"])["last_run_status"] == "error"


def test_a_push_during_a_run_is_tested_when_the_run_ends(fresh_store, no_background):
    client = TestClient(app)
    project = make_project(fresh_store, repo_url="https://github.com/acme/shop")
    first = runner.create_run(fresh_store, project, trigger="manual", actor="t")
    fresh_store.update(PIPELINE_RUNS, first["id"], status="running")

    resp = deliver(client, project, push_payload())
    assert resp.json()["queued_after"] == first["id"]
    assert fresh_store.get(PROJECTS, project["id"])["pending_push"]["commit_sha"] == "abc1234def"

    fresh_store.update(PIPELINE_RUNS, first["id"], status="passed")

    async def finish():
        return runner._start_pending_push(fresh_store, fresh_store.get(PROJECTS, project["id"]))

    follow_up = asyncio.run(finish())
    assert follow_up["commit_sha"] == "abc1234def" and follow_up["ingest"] is True
    assert follow_up["trigger"] == "webhook" and follow_up["actor"] == "github:krishna"
    assert fresh_store.get(PROJECTS, project["id"])["pending_push"] is None
    assert asyncio.run(finish()) is None  # started once
