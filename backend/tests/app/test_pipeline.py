"""
Automated pipeline: suite planning, a full run through every stage (page
analysis, browser and network stubbed), regressions between runs, the
scheduler loop and the GitHub push webhook.
"""

import asyncio
import json
import textwrap
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.webhooks import signature_for
from app.config import settings
from app.main import app
from app.models import BLUEPRINTS, FIX_PATCHES, PIPELINE_RUNS, PROJECTS, TEST_CASES
from app.pipeline import runner, scheduler, suite
from app.services.project_service import ProjectService
from security import OutOfScopeError, PassiveScanner, ScopePolicy


@pytest.fixture(autouse=True)
def _no_suite_export(request, monkeypatch):
    """These tests check the security fix proposal; the exported test suite
    (its own patch, tests/app/test_suite_export.py) is off unless a test asks."""
    if "suite_export_on" not in request.keywords:
        monkeypatch.setattr(settings, "PIPELINE_EXPORT_SUITE", False)

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
    {"method": "ANY", "path": "/api/hello", "file": "pages/api/hello.ts", "line": 1},
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
        ("route", "http://app.test/pricing"),  # /about deduplicated; /users/{id}, POST and /api skipped
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
    async def fetch(self, url, **_):
        raise OutOfScopeError("app.test:80 is not in the authorized scope (127.0.0.1)")


@pytest.fixture
def stub_network(monkeypatch):
    state = {"analysis": analysis(), "codes": {"http://app.test/about": 200, "http://app.test/pricing": 404}}

    async def analyze(url, prompt=None, test_case_name=None, **options):
        state.setdefault("analyze_options", {})[url] = options
        return state["analysis"]

    async def reachable(urls):
        return {u: ({"status": code, "file": False, "digest": u} if (code := state["codes"].get(u)) else None)
                for u in urls}

    async def no_fallback(base_url):
        return state.get("fallback", set())

    from app.api import patches
    from ingestion import SourceError, is_git_url

    real_generate = patches.generate

    def offline_generate(repo, *args, **kwargs):
        # The fix stage clones the project's repository: never over the network
        # in tests (a local folder still builds a real patch)
        if is_git_url(repo):
            state.setdefault("clones", []).append(repo)
            raise SourceError(f"offline in tests: {repo}")
        return real_generate(repo, *args, **kwargs)

    monkeypatch.setattr("app.pipeline.runner.URLAnalyzerService.analyze_live_website", analyze)
    monkeypatch.setattr(runner, "_reachable", reachable)
    monkeypatch.setattr(runner, "_fallback_digests", no_fallback)
    monkeypatch.setattr(patches, "generate", offline_generate)

    from app.pipeline import unit_tests

    async def ci_results(repo_url, token, sha, *, wait, **_):
        # The repository's CI checks: whatever the test put in state["ci"] (none by default)
        state.setdefault("ci_reads", []).append((repo_url, sha))
        return state.get("ci")

    monkeypatch.setattr(unit_tests, "from_ci", ci_results)
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
    assert "Using the blueprint from 2026-10-20 10:00 (5 routes)" in stage(run, "codebase")["detail"]
    assert stage(run, "analyze")["status"] == "done"
    plan = stage(run, "plan")
    assert plan["status"] == "done"
    assert "4 tests: 4 generated (4 new)" in plan["detail"]
    assert "GET /pricing (404)" in plan["detail"]  # unreachable page left out, and said so
    assert orch.ran == ["Smoke: Shop Login", "Scenario: log in", "Content: heading 'Welcome back'", "Linked page: /about"]
    assert stage(run, "heal")["detail"].startswith("1 test(s) self-healed")
    assert stage(run, "security")["status"] == "done"
    assert run["summary"]["total"] == 4 and run["summary"]["healed"] == 1
    # Missing headers are hardening suggestions: listed, never counted as security findings
    assert run["summary"]["findings"] == {} and run["summary"]["hardening"] > 0
    assert any("hardening suggestion" in line for line in run["summary"]["narrative"])
    # The fix stage tried the project's repository (offline here) without failing the run
    assert stub_network["clones"] == ["https://github.com/acme/shop"]
    assert stage(run, "fix")["status"] == "failed" and "offline in tests" in stage(run, "fix")["detail"]
    assert all(s["status"] in ("done", "skipped") for s in run["stages"] if s["key"] != "fix")

    refreshed = fresh_store.get(PROJECTS, project["id"])
    assert refreshed["last_run_id"] == run["id"] and refreshed["last_run_status"] == "passed"


def test_a_login_forms_own_tests_run_and_a_goal_it_could_not_run_says_why(fresh_store, stub_network):
    """The analysis left the sign-in out (no credentials) and planned the form's own tests."""
    wrong = {"slug": "login-wrong-password", "name": "Login: a wrong password is refused with a message",
             "category": "functional", "steps": [{"step_number": 1, "action": "NAVIGATE", "value": URL}]}
    stub_network["analysis"] = analysis(
        synthesized_test_case={"steps": [{"step_number": 1, "action": "NAVIGATE", "value": URL}],
                               "goal": {"tested": [], "untested": ["test the login (needs credentials in the goal)"]}},
        auth_tests=[wrong])
    project = make_project(fresh_store, prompt="test the login", allow_test_accounts=True,
                           test_email_domain="qa.acme.dev")
    orch = FakeOrchestrator({})
    run = run_once(fresh_store, project, orch, scanner_for({"content-type": "text/html"}))

    assert stub_network["analyze_options"][URL] == {"allow_test_accounts": True, "email_domain": "qa.acme.dev",
                                                    "test_data": {}}
    assert "Login: a wrong password is refused with a message" in orch.ran
    detail = stage(run, "plan")["detail"]
    assert "Not tested from your goal: “test the login (needs credentials in the goal)”" in detail
    assert "no form fields" not in detail  # the reason given, not a wrong guess
    assert run["goal_untested"] is False and run["goal_untested_parts"] == ["test the login (needs credentials in the goal)"]


def test_a_test_planned_as_unconfirmed_starts_quarantined(fresh_store, stub_network):
    """The logout test assumes a visible "Log out": it reports, but cannot fail a run until confirmed."""
    logout = {"slug": "login-logout", "name": "Login: logging out ends the session", "category": "functional",
              "quarantined": True, "steps": [{"step_number": 1, "action": "NAVIGATE", "value": URL}]}
    stub_network["analysis"] = analysis(auth_tests=[logout])
    project = make_project(fresh_store, prompt="log in with demo / secret")
    run = run_once(fresh_store, project, FakeOrchestrator({"logging out": ("FAILED", "assert_hidden failed")}),
                   scanner_for({"content-type": "text/html"}))

    row = fresh_store.find_one(TEST_CASES, name="Login: logging out ends the session")
    assert row["quarantined"] is True
    assert run["status"] == "passed"  # its failure is reported, not counted against the run
    assert any(t["name"] == row["name"] and t["status"] == "FAILED" and t["quarantined"] for t in run["tests"])


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


def test_an_analyzed_linked_page_is_checked_but_never_submitted():
    candidate = {"kind": "link", "url": "http://app.test/contact", "label": "/contact"}
    page = {"page_title": "Contact us", "elements_inventory": {
        "headings": ["Get in touch"],
        "inputs": [{"selector": "#csrf", "type": "hidden"}, {"selector": "#email", "type": "email", "name": "email"}],
        "buttons": [{"selector": "button", "text": "?"}, {"selector": "#send", "text": "Send"}],
    }}
    test = suite.page_check_test(candidate, page)
    assert test["slug"] == suite.render_test(candidate)["slug"]  # same stored test, now with more checks
    assert [(s["action"], s["target"]) for s in test["steps"]] == [
        ("NAVIGATE", None), ("ASSERT_CONTAINS_TEXT", "head > title"), ("ASSERT_CONTAINS_TEXT", "body"),
        ("ASSERT_VISIBLE", "#email"), ("ASSERT_VISIBLE", "#send"),
    ]
    assert not {s["action"] for s in test["steps"]} & {"FILL", "CLICK", "PRESS", "SELECT", "CHECK", "UPLOAD"}


def test_page_limits_come_from_settings(monkeypatch):
    many = {**analysis(), "elements_inventory": {"links": [f"/p{i}" for i in range(10)]}}
    assert len(suite.candidate_pages(many, None, link_limit=7)) == 7
    assert suite.candidate_pages(many, None, link_limit=0) == []


class SessionRecorder(FakeOrchestrator):
    """Records which session arguments each test got; the sign-in test 'signs in'."""

    def __init__(self):
        super().__init__({})
        self.sessions = {}

    async def execute_test_run(self, db, execution_id, options=None, storage_state=None, keep_state=None):
        result = await super().execute_test_run(db, execution_id, options)
        name = self.ran[-1]
        self.sessions[name] = (storage_state, keep_state is not None)
        if keep_state is not None:
            keep_state.append({"cookies": [{"name": "session", "value": "s3cret"}], "origins": []})
        return result


def test_sign_in_first_runs_the_login_test_first_and_shares_its_session_with_linked_pages(fresh_store, stub_network):
    project = make_project(fresh_store, prompt="log in with demo / secret", sign_in_first=True)
    orch = SessionRecorder()
    run = run_once(fresh_store, project, orch, OutOfScope())

    assert orch.ran[0].startswith("Scenario")  # the sign-in test goes first
    assert orch.sessions[orch.ran[0]] == (None, True)  # ... and hands its session on
    linked = next(n for n in orch.ran if n.startswith("Linked page"))
    assert orch.sessions[linked][0]["cookies"][0]["name"] == "session"
    smoke = next(n for n in orch.ran if n.startswith("Smoke"))
    assert orch.sessions[smoke] == (None, False)  # the target page is tested signed out
    assert "s3cret" not in json.dumps(run, default=str)  # the session is never stored


def test_without_sign_in_first_no_session_arguments_are_passed(fresh_store, stub_network):
    project = make_project(fresh_store, prompt="log in with demo / secret")
    run = run_once(fresh_store, project, FakeOrchestrator({}), OutOfScope())  # would fail on unknown kwargs
    assert run["status"] == "passed"


def gitlab_push(repo="https://gitlab.com/acme/shop", branch="main", sha="9f8e7d6c5b"):
    return json.dumps({
        "object_kind": "push", "ref": f"refs/heads/{branch}", "checkout_sha": sha, "user_username": "krishna",
        "project": {"web_url": repo, "git_http_url": repo + ".git", "default_branch": "main"},
        "commits": [{"id": sha, "message": "Tighten checkout validation\n\nbody"}],
    }).encode()


def deliver_gitlab(client, project, body, event="Push Hook", token=None):
    return client.post(f"/api/webhooks/gitlab/{project['id']}", content=body,
                       headers={"X-Gitlab-Event": event, "X-Gitlab-Token": token or project["webhook_secret"],
                                "Content-Type": "application/json"})


def test_gitlab_push_triggers_a_run_with_the_pushed_commit(fresh_store, no_background):
    client = TestClient(app)
    project = make_project(fresh_store, repo_url="https://gitlab.com/acme/shop.git")
    resp = deliver_gitlab(client, project, gitlab_push())
    assert resp.status_code == 200, resp.text
    run = fresh_store.get(PIPELINE_RUNS, resp.json()["started"])
    assert run["trigger"] == "webhook" and run["ingest"] is True and run["commit_sha"] == "9f8e7d6c5b"
    assert run["actor"] == "gitlab:krishna" and run["trigger_detail"] == "9f8e7d6 Tighten checkout validation"


def test_gitlab_webhook_checks_token_branch_repository_and_event(fresh_store, no_background):
    client = TestClient(app)
    project = make_project(fresh_store, repo_url="https://gitlab.com/acme/shop")
    assert deliver_gitlab(client, project, gitlab_push(), token="wrong-token").status_code == 401
    assert client.post("/api/webhooks/gitlab/999", content=b"{}").status_code == 401
    assert "default branch" in deliver_gitlab(client, project, gitlab_push(branch="feature")).json()["ignored"]
    assert "not this project" in deliver_gitlab(client, project, gitlab_push(repo="https://gitlab.com/x/y")).json()["ignored"]
    assert "do not trigger" in deliver_gitlab(client, project, gitlab_push(), event="Merge Request Hook").json()["ignored"]
    assert no_background == []


def test_a_page_that_redirected_gets_no_content_checks_from_where_it_landed():
    candidate = {"kind": "link", "url": "http://app.test/account", "label": "/account"}
    assert suite.redirected(candidate, {"final_url": "http://app.test/login?next=/account"})
    assert not suite.redirected(candidate, {"final_url": "http://app.test/account/"})
    assert not suite.redirected(candidate, {})


def test_sign_in_first_checks_linked_pages_stay_put_instead_of_signed_out_content(fresh_store, stub_network):
    # Analysis is signed out: here every page "is" the login page it redirects to
    stub_network["analysis"] = {**analysis(), "final_url": "http://app.test/login"}
    project = make_project(fresh_store, prompt="log in with demo / secret", sign_in_first=True)
    run_once(fresh_store, project, SessionRecorder(), OutOfScope())
    linked = next(tc for tc in fresh_store.find(TEST_CASES) if tc["name"].startswith("Linked page"))
    steps = json.loads(linked["description"])["steps"]
    assert [(s["action"], s.get("value")) for s in steps][-1] == ("ASSERT_URL", "/about")
    assert not any(s["action"] == "ASSERT_CONTAINS_TEXT" for s in steps)  # nothing from the signed-out page


def test_active_scan_runs_in_the_pipeline_only_when_project_and_server_both_allow(fresh_store, stub_network, monkeypatch):
    import app.api.security as sec_api

    calls = {"n": 0}

    class SpyActive:
        def __init__(self, scope=None, *a, **k):
            self.scope = scope

        async def scan(self, url):
            calls["n"] += 1
            return []

    monkeypatch.setattr(sec_api, "ActiveScanner", SpyActive)
    # The active scanner only attacks listed (or verified) hosts
    monkeypatch.setattr(settings, "SECURITY_SCAN_ALLOWED_HOSTS", "app.test")

    # Project flag on but server off → not run
    monkeypatch.setattr(settings, "SECURITY_ACTIVE_SCAN", False)
    project = make_project(fresh_store, active_scan=True)
    run_once(fresh_store, project, FakeOrchestrator({}), scanner_for({"content-type": "text/html"}))
    assert calls["n"] == 0

    # Both on → run (on the app URL and the pages the run reached)
    monkeypatch.setattr(settings, "SECURITY_ACTIVE_SCAN", True)
    run_once(fresh_store, project, FakeOrchestrator({}), scanner_for({"content-type": "text/html"}))
    assert calls["n"] >= 1

    # Server on but project flag off → not run
    calls["n"] = 0
    plain = make_project(fresh_store)  # active_scan defaults off
    run_once(fresh_store, plain, FakeOrchestrator({}), scanner_for({"content-type": "text/html"}))
    assert calls["n"] == 0

    # Sign-in on: the project's owner must be listed in SECURITY_ACTIVE_SCAN_USERS
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    monkeypatch.setattr(settings, "SECURITY_ACTIVE_SCAN_USERS", "someone-else")
    run_once(fresh_store, project, FakeOrchestrator({}), scanner_for({"content-type": "text/html"}))
    assert calls["n"] == 0
    monkeypatch.setattr(settings, "SECURITY_ACTIVE_SCAN_USERS", "local-dev")
    run_once(fresh_store, project, FakeOrchestrator({}), scanner_for({"content-type": "text/html"}))
    assert calls["n"] >= 1  # (at least: every page the run reached)


def test_every_result_says_what_it_checked_and_how_long_it_took(fresh_store, stub_network):
    class Timed(FakeOrchestrator):
        async def execute_test_run(self, db, execution_id, options=None):
            return {**await super().execute_test_run(db, execution_id, options), "duration_ms": 1234}

    run = run_once(fresh_store, make_project(fresh_store), Timed({}), OutOfScope())
    smoke = next(t for t in run["tests"] if t["category"] == "smoke")
    # A passed test reports what passed, not only that it did
    assert smoke["status"] == "PASSED" and smoke["duration_ms"] == 1234
    assert smoke["step_count"] >= 2 and any(c.startswith("Page title contains") for c in smoke["checks"])
    assert all(len(t["checks"]) <= runner.MAX_LISTED_CHECKS for t in run["tests"])


def test_a_run_records_what_its_llm_calls_used(fresh_store, stub_network, monkeypatch):
    from agents.llm.client import LLMClient, LLMClientSession
    from agents.llm.config import LLMConfig
    from agents.llm.schemas import LLMRequest, LLMResponse, LLMUsage

    class Groq(LLMClient):
        async def generate(self, request):
            return LLMResponse(content="ok", model="llama-3.3-70b-versatile", provider="api",
                               usage=LLMUsage(prompt_tokens=1000, completion_tokens=500))

    session = LLMClientSession(Groq(LLMConfig(provider="api", api_key="k", model="llama-3.3-70b-versatile")))
    real_execute = runner._execute

    async def execute_with_ai(state, project, orchestrator, scanner):
        await session.generate(LLMRequest(prompt="plan"))
        await asyncio.to_thread(lambda: asyncio.run(session.generate(LLMRequest(prompt="triage"))))
        await real_execute(state, project, orchestrator, scanner)

    monkeypatch.setattr(runner, "_execute", execute_with_ai)
    monkeypatch.setattr(settings, "LLM_MAX_TOKENS_PER_RUN", 2000)
    run = run_once(fresh_store, make_project(fresh_store), FakeOrchestrator({}), scanner_for({"content-type": "text/html"}))
    usage = run["llm_usage"]
    assert (usage["calls"], usage["input_tokens"], usage["output_tokens"]) == (2, 2000, 1000)
    assert usage["limit"] == 2000 and usage["budget_exhausted"]

    second = run_once(fresh_store, make_project(fresh_store), FakeOrchestrator({}), scanner_for({"content-type": "text/html"}))
    assert second["llm_usage"]["calls"] == 2  # each run has its own budget, not a running total


def test_a_non_ascii_webhook_signature_is_refused_not_a_server_error(fresh_store, no_background):
    client = TestClient(app, raise_server_exceptions=False)
    project = make_project(fresh_store, repo_url="https://github.com/acme/shop")
    resp = client.post(f"/api/webhooks/github/{project['id']}", content=push_payload(),
                       headers={"X-GitHub-Event": "push", "X-Hub-Signature-256": "sha256=é".encode()})
    assert resp.status_code == 401
    assert no_background == []


def test_generated_tests_no_longer_planned_are_retired_and_hidden(fresh_store):
    """A link that went away left its generated test behind forever (never run, still listed)."""
    project = make_project(fresh_store)
    app_row = fresh_store.insert("applications", project_id=project["id"], name="A", base_url="https://a.example",
                                 owner_uid=project.get("owner_uid"))
    keep = fresh_store.insert(TEST_CASES, application_id=app_row["id"], external_id=f"pipe-{project['id']}-smoke", name="smoke", version=1)
    gone = fresh_store.insert(TEST_CASES, application_id=app_row["id"], external_id=f"pipe-{project['id']}-link-old", name="old link", version=1)
    mine = fresh_store.insert(TEST_CASES, application_id=app_row["id"], external_id="TC-MANUAL", name="saved by hand", version=1)

    rows = fresh_store.find(TEST_CASES, application_id=app_row["id"])
    assert runner._retire_unplanned(fresh_store, rows, {keep["id"]}) == 1
    assert fresh_store.get(TEST_CASES, gone["id"])["retired"] is True
    assert not fresh_store.get(TEST_CASES, keep["id"]).get("retired")
    assert not fresh_store.get(TEST_CASES, mine["id"]).get("retired")  # saved tests are never retired

    client = TestClient(app)
    listed = {r["id"] for r in client.get("/api/test-cases").json()}
    assert listed == {keep["id"], mine["id"]}
    assert gone["id"] in {r["id"] for r in client.get("/api/test-cases?include_retired=true").json()}

    # Planned again (the link is back): un-retired
    rows = fresh_store.find(TEST_CASES, application_id=app_row["id"])
    assert runner._retire_unplanned(fresh_store, rows, {keep["id"], gone["id"]}) == 0
    assert fresh_store.get(TEST_CASES, gone["id"])["retired"] is False


def test_the_security_stage_scans_the_pages_the_run_reached(fresh_store, stub_network):
    """It scanned the app URL only; the linked pages the QA stage already reached are scanned too."""
    from app.models import PIPELINE_RUNS, SECURITY_FINDINGS

    fetched = []
    scanner = scanner_for({"content-type": "text/html"})
    original = scanner.fetch

    async def spy(url, **kwargs):
        fetched.append(url)
        return await original(url, **kwargs)

    scanner.fetch = spy
    project = make_project(fresh_store)
    run_once(fresh_store, project, FakeOrchestrator({}), scanner)

    assert fetched == [URL, "http://app.test/about"]  # /pricing did not load: never a test, never scanned
    targets = {r["target_url"] for r in fresh_store.find(SECURITY_FINDINGS)}
    assert targets == {URL, "http://app.test/about"}  # each page's findings are tracked on their own
    stage = next(s for s in fresh_store.find(PIPELINE_RUNS)[0]["stages"] if s["key"] == "security")
    assert stage["detail"].startswith("2 pages scanned")


def test_the_pipeline_adds_ai_triage_to_its_findings(fresh_store, stub_network, monkeypatch):
    from app.models import PIPELINE_RUNS, SECURITY_FINDINGS
    from security import ai as security_ai
    from tests.app.test_security_api import _fake_triage

    monkeypatch.setattr(security_ai, "enabled", lambda: True)
    monkeypatch.setattr(security_ai, "triage", _fake_triage)
    project = make_project(fresh_store)
    run_once(fresh_store, project, FakeOrchestrator({}), scanner_for({"content-type": "text/html"}))

    rows = fresh_store.find(SECURITY_FINDINGS)
    assert rows and all(r.get("ai", {}).get("summary", "").startswith("note:") for r in rows)
    stage = next(s for s in fresh_store.find(PIPELINE_RUNS)[0]["stages"] if s["key"] == "security")
    assert "AI triage added" in stage["detail"]


# ── fix proposals: each run turns its open findings into a patch for review ──


FIX_APP = textwrap.dedent("""
    from fastapi import FastAPI

    app = FastAPI()
""").lstrip()


@pytest.fixture
def fix_repo(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "INGEST_ALLOW_LOCAL_PATHS", True)
    monkeypatch.setattr(settings, "INGEST_WORKSPACE", str(tmp_path / "ws"))
    root = tmp_path / "shop"
    root.mkdir()
    (root / "main.py").write_text(FIX_APP, encoding="utf-8")
    return root


def bare_site():
    # No security headers at all: the scan finds them missing
    return scanner_for({"content-type": "text/html"})


def test_after_the_scan_come_repository_tests_fix_proposals_and_the_report():
    keys = [k for k, _ in runner.STAGES]
    assert keys[keys.index("security"):] == ["security", "unit", "fix", "report"]


def test_a_run_proposes_a_patch_for_its_findings_and_links_it(fresh_store, stub_network, fix_repo):
    project = make_project(fresh_store, repo_url=str(fix_repo))
    run = run_once(fresh_store, project, FakeOrchestrator({}), bare_site())

    fix = stage(run, "fix")
    assert fix["status"] == "done", fix
    assert "ready for review" in fix["detail"]
    proposal = run["fix_patch"]
    assert proposal["id"] and proposal["files"] == 1 and proposal["fixes"] >= 1 and proposal["pull_request"] is None

    patch = fresh_store.get(FIX_PATCHES, proposal["id"])
    assert patch["run_id"] == run["id"] and patch["project_id"] == project["id"]
    assert '"X-Frame-Options"' in patch["patch"]
    assert (fix_repo / "main.py").read_text(encoding="utf-8") == FIX_APP  # the repository is never changed

    # The run page loads the proposal by id
    body = TestClient(app).get(f"/api/security/patches/{proposal['id']}").json()
    assert body["run_id"] == run["id"] and body["files"][0]["path"] == "main.py"
    assert "contents" not in body  # file contents stay on the server


def test_an_unchanged_proposal_is_not_stored_again(fresh_store, stub_network, fix_repo):
    project = make_project(fresh_store, repo_url=str(fix_repo))
    first = run_once(fresh_store, project, FakeOrchestrator({}), bare_site())
    second = run_once(fresh_store, project, FakeOrchestrator({}), bare_site())

    assert second["fix_patch"]["id"] == first["fix_patch"]["id"]
    assert len(fresh_store.find(FIX_PATCHES)) == 1
    assert f"unchanged since run #{first['id']}" in stage(second, "fix")["detail"]


def test_a_proposal_already_in_a_pull_request_says_so(fresh_store, stub_network, fix_repo):
    project = make_project(fresh_store, repo_url=str(fix_repo))
    first = run_once(fresh_store, project, FakeOrchestrator({}), bare_site())
    fresh_store.update(FIX_PATCHES, first["fix_patch"]["id"], pull_request={"number": 7, "url": "https://x/pull/7"})

    second = run_once(fresh_store, project, FakeOrchestrator({}), bare_site())
    assert second["fix_patch"]["pull_request"]["number"] == 7
    assert "already proposed in pull request #7" in stage(second, "fix")["detail"]


def test_without_a_repository_the_stage_is_skipped(fresh_store, stub_network):
    run = run_once(fresh_store, make_project(fresh_store), FakeOrchestrator({}), bare_site())
    assert stage(run, "fix")["status"] == "skipped"
    assert "No repository linked" in stage(run, "fix")["detail"]
    assert run.get("fix_patch") is None


def test_without_a_scan_the_stage_is_skipped(fresh_store, stub_network, fix_repo):
    run = run_once(fresh_store, make_project(fresh_store, repo_url=str(fix_repo)), FakeOrchestrator({}), OutOfScope())
    assert stage(run, "security")["status"] == "skipped"
    assert stage(run, "fix")["status"] == "skipped"
    assert stage(run, "fix")["detail"] == "No security scan in this run"


def test_without_open_findings_the_stage_is_skipped(fresh_store, stub_network, fix_repo, monkeypatch):
    monkeypatch.setattr("app.services.security_service.list_findings", lambda *a, **k: [])
    run = run_once(fresh_store, make_project(fresh_store, repo_url=str(fix_repo)), FakeOrchestrator({}), bare_site())
    assert stage(run, "fix")["status"] == "skipped"
    assert stage(run, "fix")["detail"] == "No open findings to fix"
    assert fresh_store.find(FIX_PATCHES) == []


def test_a_repository_that_cannot_be_read_never_fails_the_run(fresh_store, stub_network, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "INGEST_ALLOW_LOCAL_PATHS", True)
    project = make_project(fresh_store, repo_url=str(tmp_path / "missing"))
    run = run_once(fresh_store, project, FakeOrchestrator({}), bare_site())

    assert stage(run, "fix")["status"] == "failed"
    assert "Could not" in stage(run, "fix")["detail"]
    assert run["status"] == "passed"  # the tests passed; the proposal is extra
    assert stage(run, "report")["status"] == "done"


# ── the repository's own Playwright tests: read at ingestion, replayed every run ──


REPO_SPEC = """import { test, expect } from '@playwright/test';
test('logs in', async ({ page }) => {
  await page.goto('http://app.test/login');
  await page.fill('#username', 'tom');
  await page.click('button.radius');
  await expect(page.locator('body')).toContainText('Welcome back');
});
test('no check', async ({ page }) => {
  await page.goto('http://app.test/login');
});
"""


def test_ingestion_reads_the_repositorys_playwright_tests_without_running_them(tmp_path, monkeypatch):
    from app.api.ingest import ingest_source

    monkeypatch.setattr(settings, "INGEST_ALLOW_LOCAL_PATHS", True)
    monkeypatch.setattr(settings, "DEPENDENCY_SCAN", False)
    (tmp_path / "e2e").mkdir()
    (tmp_path / "e2e" / "login.spec.ts").write_text(REPO_SPEC, encoding="utf-8")
    (tmp_path / "sum.test.js").write_text("test('adds', () => { expect(1 + 1).toBe(2); });", encoding="utf-8")

    specs = ingest_source(str(tmp_path))["playwright_specs"]
    assert [s["file"] for s in specs] == ["e2e/login.spec.ts"]  # the Jest unit test is not a browser test
    assert [t["name"] for t in specs[0]["tests"]] == ["logs in", "no check"]


def repo_blueprint(db, project, spec_text=REPO_SPEC):
    from app.services.playwright_import import parse_spec

    specs = [parse_spec(spec_text, "e2e/login.spec.ts")] if spec_text else []
    db.insert(BLUEPRINTS, source=project["repo_url"], name="shop", project_id=project["id"], owner_uid="local-dev",
              data=json.dumps({**BLUEPRINT, "analyzed_at": "2026-10-20T10:00:00+00:00", "playwright_specs": specs}))


def repo_tests(db):
    return [t for t in db.find(TEST_CASES, order_by="id") if t["external_id"].startswith(runner.REPO_PREFIX)]


def test_each_run_replays_the_repositorys_playwright_tests(fresh_store, stub_network):
    project = make_project(fresh_store, repo_url="https://github.com/acme/shop")
    repo_blueprint(fresh_store, project)
    orch = FakeOrchestrator({})
    run = run_once(fresh_store, project, orch, scanner_for({"content-type": "text/html"}))

    [imported] = repo_tests(fresh_store)
    assert imported["name"] == "logs in (e2e/login.spec.ts)" and imported["category"] == "repository"
    steps = json.loads(imported["description"])["steps"]
    assert [s["action"] for s in steps] == ["NAVIGATE", "FILL", "CLICK", "ASSERT_CONTAINS_TEXT"]
    # Its selectors are not on the analyzed page: it runs, but cannot fail the run until trusted
    assert imported["quarantined"] is True
    assert "logs in (e2e/login.spec.ts)" in orch.ran
    plan = stage(run, "plan")["detail"]
    assert "1 from the repository's Playwright tests" in plan
    assert "1 new, 0 updated from the repository's Playwright tests" in plan
    assert "1 repository test(s) left out" in plan  # 'no check' has nothing that can fail


def test_repository_tests_follow_the_repository(fresh_store, stub_network):
    project = make_project(fresh_store, repo_url="https://github.com/acme/shop")
    repo_blueprint(fresh_store, project)
    run_once(fresh_store, project, FakeOrchestrator({}), scanner_for({"content-type": "text/html"}))
    [first] = repo_tests(fresh_store)
    fresh_store.update(TEST_CASES, first["id"], quarantined=False)  # someone trusted it

    # Unchanged: the same test, and the lifted quarantine stays lifted
    run_once(fresh_store, project, FakeOrchestrator({}), scanner_for({"content-type": "text/html"}))
    [same] = repo_tests(fresh_store)
    assert same["id"] == first["id"] and same["quarantined"] is False and same.get("version", 1) == first.get("version", 1)

    # Changed in the repository: updated in place, quarantined again
    repo_blueprint(fresh_store, project, REPO_SPEC.replace("'tom'", "'ann'"))
    run_once(fresh_store, project, FakeOrchestrator({}), scanner_for({"content-type": "text/html"}))
    [changed] = repo_tests(fresh_store)
    assert changed["id"] == first["id"] and "'ann'" not in changed["name"]
    assert any(s.get("value") == "ann" for s in json.loads(changed["description"])["steps"])
    assert changed["quarantined"] is True and changed["version"] == 2

    # Deleted from the repository: retired, and no longer run
    repo_blueprint(fresh_store, project, None)
    orch = FakeOrchestrator({})
    run = run_once(fresh_store, project, orch, scanner_for({"content-type": "text/html"}))
    assert repo_tests(fresh_store)[0]["retired"] is True
    assert not any("e2e/login.spec.ts" in name for name in orch.ran)
    assert "retired 1 repository test(s) no longer in it" in stage(run, "plan")["detail"]


def test_a_blueprint_from_before_specs_were_read_changes_nothing(fresh_store, stub_network):
    project = make_project(fresh_store, repo_url="https://github.com/acme/shop")
    fresh_store.insert(BLUEPRINTS, source=project["repo_url"], name="shop", project_id=project["id"], owner_uid="local-dev",
                       data=json.dumps({**BLUEPRINT, "analyzed_at": "2026-10-20T10:00:00+00:00"}))
    run = run_once(fresh_store, project, FakeOrchestrator({}), scanner_for({"content-type": "text/html"}))
    assert repo_tests(fresh_store) == []
    assert "repository" not in stage(run, "plan")["detail"]


# ── the repository's own unit tests (stage "unit") ──


def ci_result(status, failed=0):
    return {"source": "ci", "commit": "a" * 40, "status": status, "passed": 3, "failed": failed, "running": 0,
            "checks": [], "detail": f"CI on aaaaaaa: 3 passed, {failed} failed"}


def test_failing_repository_ci_fails_the_run(fresh_store, stub_network):
    stub_network["ci"] = ci_result("failed", failed=1)
    project = make_project(fresh_store, repo_url="https://github.com/acme/shop")
    run = run_once(fresh_store, project, FakeOrchestrator({}), scanner_for({"content-type": "text/html"}))

    assert stub_network["ci_reads"] == [("https://github.com/acme/shop", None)]
    assert stage(run, "unit")["status"] == "failed" and stage(run, "unit")["detail"] == "CI on aaaaaaa: 3 passed, 1 failed"
    assert run["status"] == "failed"  # every browser test passed; the project's own tests did not
    assert run["summary"]["unit_tests"] == {"source": "ci", "status": "failed", "passed": 3, "failed": 1,
                                            "running": 0, "framework": None}
    assert "repository tests failed" in stage(run, "report")["detail"]


def test_passing_or_still_running_ci_does_not_fail_the_run(fresh_store, stub_network):
    project = make_project(fresh_store, repo_url="https://github.com/acme/shop")
    for status in ("passed", "pending"):
        stub_network["ci"] = ci_result(status)
        run = run_once(fresh_store, project, FakeOrchestrator({}), scanner_for({"content-type": "text/html"}))
        assert stage(run, "unit")["status"] == "done" and run["status"] == "passed"


def test_a_pushed_commits_ci_is_read(fresh_store, stub_network):
    stub_network["ci"] = ci_result("passed")
    project = make_project(fresh_store, repo_url="https://github.com/acme/shop")
    run = runner.create_run(fresh_store, project, trigger="webhook", actor="github", commit_sha="c" * 40)
    asyncio.run(runner.execute_run(run["id"], orchestrator=FakeOrchestrator({}),
                                   scanner=scanner_for({"content-type": "text/html"})))
    assert stub_network["ci_reads"][-1] == ("https://github.com/acme/shop", "c" * 40)


def test_without_ci_or_sandbox_the_stage_says_why(fresh_store, stub_network, monkeypatch):
    project = make_project(fresh_store, repo_url="https://github.com/acme/shop")
    run = run_once(fresh_store, project, FakeOrchestrator({}), scanner_for({"content-type": "text/html"}))
    assert stage(run, "unit")["status"] == "skipped"
    assert stage(run, "unit")["detail"] == ("No CI checks on this commit; sandbox not used: "
                                           "the sandbox is off (SANDBOX_ENABLED)")
    assert run["status"] == "passed"

    monkeypatch.setattr(settings, "UNIT_TESTS", "off")
    run = run_once(fresh_store, project, FakeOrchestrator({}), scanner_for({"content-type": "text/html"}))
    assert stage(run, "unit")["detail"] == "Off on this server (UNIT_TESTS=off)"


def test_a_repository_without_unit_tests_is_not_cloned(fresh_store, stub_network):
    project = make_project(fresh_store, repo_url="https://github.com/acme/shop")
    fresh_store.insert(BLUEPRINTS, source=project["repo_url"], name="shop", project_id=project["id"], owner_uid="local-dev",
                       data=json.dumps({**BLUEPRINT, "analyzed_at": "2026-10-20T10:00:00+00:00", "test_suites": []}))
    run = run_once(fresh_store, project, FakeOrchestrator({}), scanner_for({"content-type": "text/html"}))
    assert stage(run, "unit") == stage(run, "unit") | {"status": "skipped", "detail": "The repository has no unit tests"}
    assert "ci_reads" not in stub_network


def test_without_ci_the_sandbox_runs_the_repositorys_tests(fresh_store, stub_network, tmp_path, monkeypatch):
    from app.pipeline import unit_tests

    monkeypatch.setattr(settings, "INGEST_ALLOW_LOCAL_PATHS", True)
    (tmp_path / "test_a.py").write_text("def test_a():\n    assert False\n", encoding="utf-8")
    ran = []
    monkeypatch.setattr(unit_tests, "unavailable_reason", lambda: None)

    def fake_sandbox(root, plan):
        ran.append((root, plan.framework))
        return {"source": "sandbox", "framework": "pytest", "status": "failed", "passed": 0, "failed": 1,
                "exit_code": 1, "output": "1 failed", "detail": "Sandbox (pytest): 0 passed, 1 failed"}

    monkeypatch.setattr(unit_tests, "run_in_sandbox", fake_sandbox)
    project = make_project(fresh_store, repo_url=str(tmp_path))
    run = run_once(fresh_store, project, FakeOrchestrator({}), scanner_for({"content-type": "text/html"}))

    assert ran == [(tmp_path, "pytest")]
    assert stage(run, "unit")["status"] == "failed" and run["status"] == "failed"
    assert run["unit_tests"]["output"] == "1 failed"
    assert tmp_path.exists()  # a local folder is never deleted (only a clone is)


# ── AI fixes for the repository's failing tests (verified in the sandbox) ──


def git_repo(path):
    import subprocess

    path.mkdir(parents=True)
    (path / "test_a.py").write_text("from a import f\n\ndef test_f():\n    assert f() == 1\n", encoding="utf-8")
    (path / "a.py").write_text("def f():\n    return 0\n", encoding="utf-8")
    for cmd in (["init", "-q"], ["add", "."], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x"]):
        subprocess.run(["git", "-C", str(path), *cmd], check=True, capture_output=True)
    return path


@pytest.fixture
def sandbox_fails(monkeypatch, tmp_path):
    """The sandbox runs (faked): the repository's tests fail; AI fixes are on (faked)."""
    from app.pipeline import ai_fix, unit_tests

    monkeypatch.setattr(settings, "INGEST_ALLOW_LOCAL_PATHS", True)
    monkeypatch.setattr(settings, "INGEST_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setattr(unit_tests, "unavailable_reason", lambda: None)
    calls = {"sandbox": 0, "propose": 0}

    def sandbox(root, plan):
        calls["sandbox"] += 1
        return {"source": "sandbox", "framework": "pytest", "status": calls.get("status", "failed"),
                "passed": 2, "failed": 1, "exit_code": 1, "output": "FAILED test_a.py::test_f",
                "detail": "Sandbox (pytest): 2 passed, 1 failed"}

    async def propose(root, plan, failing):
        calls["propose"] += 1
        return calls.get("proposal") or {
            "status": "verified", "attempts": 1, "explanation": "f() returned 0.", "framework": "pytest",
            "before": {"passed": 2, "failed": 1}, "after": {"passed": 3, "failed": 0},
            "files": [{"path": "a.py", "diff": "--- a/a.py\n+++ b/a.py\n-    return 0\n+    return 1\n",
                       "verified": True, "content": "def f():\n    return 1\n"}]}

    monkeypatch.setattr(unit_tests, "run_in_sandbox", sandbox)
    monkeypatch.setattr(ai_fix, "enabled", lambda: True)
    monkeypatch.setattr(ai_fix, "propose", propose)
    return calls


def test_a_verified_ai_fix_is_proposed_for_failing_repository_tests(fresh_store, stub_network, sandbox_fails, tmp_path):
    repo = git_repo(tmp_path / "shop")
    project = make_project(fresh_store, repo_url=str(repo))
    run = run_once(fresh_store, project, FakeOrchestrator({}), scanner_for({"content-type": "text/html"}))

    detail = stage(run, "unit")["detail"]
    assert detail.startswith("Sandbox (pytest): 2 passed, 1 failed")
    assert "AI fix verified in the sandbox (1 failing → all 3 passing), ready for review" in detail
    assert run["status"] == "failed"  # the repository's tests still fail until the fix is merged
    [patch] = [p for p in fresh_store.find(FIX_PATCHES) if p.get("kind") == "tests"]
    assert run["ai_fix"]["id"] == patch["id"] and patch["run_id"] == run["id"]
    assert patch["contents"] == {"a.py": "def f():\n    return 1\n"} and patch["commit"]
    assert patch["verification"]["after"] == {"passed": 3, "failed": 0}

    from app.api.patches import _pr_body, _public

    body = _pr_body(patch)
    assert "1 failing before, all 3 passing after" in body and "No test file was changed" in body
    assert "f() returned 0." in body
    assert _public(patch)["kind"] == "tests" and _public(patch)["github"] is False  # a local folder: no pull request


def test_the_same_commit_is_not_sent_to_the_model_twice(fresh_store, stub_network, sandbox_fails, tmp_path):
    project = make_project(fresh_store, repo_url=str(git_repo(tmp_path / "shop")))
    first = run_once(fresh_store, project, FakeOrchestrator({}), scanner_for({"content-type": "text/html"}))
    second = run_once(fresh_store, project, FakeOrchestrator({}), scanner_for({"content-type": "text/html"}))

    assert sandbox_fails["propose"] == 1
    assert second["ai_fix"]["id"] == first["ai_fix"]["id"]
    assert f"AI fix from run #{first['id']} (same commit) ready for review" in stage(second, "unit")["detail"]

    sandbox_fails["proposal"] = {"status": "not_found", "attempts": 2, "note": "no change made every test pass"}
    other = ProjectService.create_project(fresh_store, name="Other", owner_uid="local-dev", app_url=URL,
                                          repo_url=str(git_repo(tmp_path / "other")))
    run_once(fresh_store, other, FakeOrchestrator({}), scanner_for({"content-type": "text/html"}))
    again = run_once(fresh_store, other, FakeOrchestrator({}), scanner_for({"content-type": "text/html"}))
    assert sandbox_fails["propose"] == 2
    assert "no AI fix for this commit (tried in run #" in stage(again, "unit")["detail"]


def test_a_ci_failure_is_reproduced_in_the_sandbox_before_an_ai_fix(fresh_store, stub_network, sandbox_fails, tmp_path):
    project = make_project(fresh_store, repo_url=str(git_repo(tmp_path / "shop")))
    stub_network["ci"] = ci_result("failed", failed=1)
    run = run_once(fresh_store, project, FakeOrchestrator({}), scanner_for({"content-type": "text/html"}))
    assert sandbox_fails["sandbox"] == 1 and sandbox_fails["propose"] == 1
    assert stage(run, "unit")["detail"].startswith("CI on aaaaaaa: 3 passed, 1 failed · AI fix verified")
    assert run["unit_tests"]["source"] == "ci"  # the stage reports CI's result

    sandbox_fails["status"] = "passed"  # fails in CI, passes in the sandbox: nothing to verify a fix against
    other = ProjectService.create_project(fresh_store, name="Other", owner_uid="local-dev", app_url=URL,
                                          repo_url=str(git_repo(tmp_path / "other")))
    run = run_once(fresh_store, other, FakeOrchestrator({}), scanner_for({"content-type": "text/html"}))
    assert "AI fix not tried: the CI failure did not reproduce in the sandbox" in stage(run, "unit")["detail"]
    assert sandbox_fails["propose"] == 1


def test_security_proposals_ignore_test_fix_patches(fresh_store, stub_network, fix_repo):
    project = make_project(fresh_store, repo_url=str(fix_repo))
    first = run_once(fresh_store, project, FakeOrchestrator({}), bare_site())
    fresh_store.insert(FIX_PATCHES, project_id=project["id"], kind="tests", patch="other", repo=str(fix_repo),
                       owner_uid="local-dev")
    second = run_once(fresh_store, project, FakeOrchestrator({}), bare_site())
    assert second["fix_patch"]["id"] == first["fix_patch"]["id"]


@pytest.mark.suite_export_on
def test_the_exported_suite_never_stands_in_for_the_security_proposal(fresh_store, stub_network, fix_repo):
    """With the suite exported too, an unchanged security patch is still recognised
    as unchanged (the suite patch in between is not "the previous proposal")."""
    assert settings.PIPELINE_EXPORT_SUITE is True
    project = make_project(fresh_store, repo_url=str(fix_repo))
    first = run_once(fresh_store, project, FakeOrchestrator({}), bare_site())
    second = run_once(fresh_store, project, FakeOrchestrator({}), bare_site())
    assert first["fix_patch"]["id"] and second["fix_patch"]["id"] == first["fix_patch"]["id"]
