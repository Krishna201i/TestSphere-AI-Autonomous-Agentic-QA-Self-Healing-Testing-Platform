"""The trusted tests become Playwright files for the repository, and (auto_pr) a pull request."""

import asyncio
import json

from app.api import patches
from app.models import FIX_PATCHES, TEST_CASES
from app.pipeline import acceptance, runner, suite_export
from app.services.project_service import ProjectService
from app.services.test_studio import to_playwright

APP = "https://shop.test"
REPO = "https://github.com/acme/shop"
LOGIN = [{"step_number": 1, "action": "NAVIGATE", "value": f"{APP}/login"},
         {"step_number": 2, "action": "ASSERT_CONTAINS_TEXT", "target": "head > title", "value": "Sign in"},
         {"step_number": 3, "action": "FILL", "target": "#email", "value": "qa@example.com"},
         {"step_number": 4, "action": "CLICK", "target": "#go"},
         {"step_number": 5, "action": "ASSERT_URL", "value": f"{APP}/account"}]


def tc(db, name, category="functional", steps=LOGIN, **extra):
    return db.insert(TEST_CASES, name=name, category=category, external_id=f"pipe-1-{name}",
                     description=json.dumps({"steps": steps}), **extra)


def passed(*rows, status="PASSED"):
    return [{"test_case_id": r["id"], "status": status} for r in rows]


def test_export_uses_paths_on_the_site_and_checks_the_real_page_title():
    code = to_playwright("Sign in", LOGIN, base_url=APP)
    assert "page.goto(\"/login\")" in code
    assert "toHaveTitle(new RegExp(\"Sign\\\\ in\"))" in code
    assert "head > title" not in code
    assert "toHaveURL(new RegExp(\"/account\"))" in code
    # another site stays absolute
    assert 'page.goto("https://other.test/x")' in to_playwright(
        "x", [{"action": "NAVIGATE", "value": "https://other.test/x"}], base_url=APP)


def test_only_passing_trusted_tests_are_exported(fresh_store):
    db = fresh_store
    good = tc(db, "Sign in", acceptance={"status": "verified"})
    smoke = tc(db, "Smoke", category="smoke")
    quarantined = tc(db, "AI guess", category="ai", quarantined=True)
    failing = tc(db, "Broken")
    from_repo = db.insert(TEST_CASES, name="Theirs", external_id="repo-1-x", description=json.dumps({"steps": LOGIN}))
    results = passed(good, smoke, quarantined, from_repo) + [{"test_case_id": failing["id"], "status": "FAILED"}]
    built = suite_export.build([good, smoke, quarantined, failing, from_repo], results, base_url=APP,
                               steps_of=acceptance.steps_of, github=True)
    assert built["tests"] == 2 and built["verified"] == 1
    files = built["files"]
    assert set(files) == {"testsphere/package.json", "testsphere/playwright.config.ts", "testsphere/README.md",
                          "testsphere/tests/journeys.spec.ts", "testsphere/tests/smoke.spec.ts",
                          ".github/workflows/testsphere.yml"}
    assert "AI guess" not in "".join(files.values()) and "Broken" not in "".join(files.values())
    assert "process.env.BASE_URL" in files["testsphere/playwright.config.ts"]
    assert "vars.TESTSPHERE_BASE_URL" in files[".github/workflows/testsphere.yml"]
    # no workflow for a repository that is not on GitHub
    assert ".github/workflows/testsphere.yml" not in suite_export.build(
        [good], passed(good), base_url=APP, steps_of=acceptance.steps_of, github=False)["files"]


def test_new_file_diff_applies_with_git():
    d = suite_export.diff("testsphere/a.txt", None, "one\ntwo\n")
    assert d.startswith("diff --git a/testsphere/a.txt b/testsphere/a.txt\nnew file mode 100644\n--- /dev/null\n")
    assert suite_export.diff("x", "same\n", "same\n") == ""


def _project(db, **extra):
    return ProjectService.create_project(db, name="Shop", owner_uid="u1", app_url=APP, repo_url=REPO, **extra)


def _state(db, project):
    return runner._RunState(db, runner.create_run(db, project, trigger="manual", actor="t"))


def test_the_stage_stores_a_suite_patch_and_reuses_it_while_unchanged(fresh_store, monkeypatch):
    db = fresh_store
    project = _project(db)
    good = tc(db, "Sign in")
    reads = []

    def fake_read(repo, paths, auth=None):
        reads.append(repo)
        return "abc123", {p: None for p in paths}

    monkeypatch.setattr(patches, "read_files", fake_read)
    monkeypatch.setattr("app.api.integrations.git_auth", lambda *a: None)
    state = _state(db, project)
    asyncio.run(runner._stage_suite(state, project, [good], passed(good)))
    row = db.get(FIX_PATCHES, state.doc["suite_patch"]["id"])
    assert row["kind"] == "suite" and row["commit"] == "abc123" and row["suite"]["tests"] == 1
    assert "testsphere/tests/journeys.spec.ts" in row["contents"]
    assert "ready for a pull request" in next(s for s in state.doc["stages"] if s["key"] == "fix")["detail"]

    again = _state(db, project)
    asyncio.run(runner._stage_suite(again, project, [good], passed(good)))
    assert again.doc["suite_patch"] == {"id": row["id"], "tests": 1, "pull_request": None, "unchanged": True}
    assert reads == [REPO]  # the unchanged suite did not clone the repository again


def test_auto_pr_opens_one_pull_request_then_updates_it(fresh_store, monkeypatch):
    db = fresh_store
    project = _project(db, auto_pr=True)
    opened, updated = [], []

    def fake_create(db_, row, uid, title=None):
        opened.append(row["id"])
        pr = {"url": "https://github.com/acme/shop/pull/7", "number": 7, "branch": f"testsphere/tests-{row['id']}"}
        db_.update(FIX_PATCHES, row["id"], pull_request=pr)
        return pr

    def fake_update(db_, row, previous, uid):
        updated.append((row["id"], previous["id"]))
        return {**previous["pull_request"], "updated_by_patch": row["id"]}

    monkeypatch.setattr(patches, "create_pull_request", fake_create)
    monkeypatch.setattr(patches, "update_pull_request", fake_update)
    monkeypatch.setattr(patches, "read_files", lambda repo, paths, auth=None: ("abc", {p: None for p in paths}))
    monkeypatch.setattr("app.api.integrations.git_auth", lambda *a: None)

    first = tc(db, "Sign in")
    state = _state(db, project)
    asyncio.run(runner._stage_suite(state, project, [first], passed(first)))
    asyncio.run(runner._auto_pull_requests(state, project))
    assert state.doc["suite_patch"]["pull_request"]["number"] == 7 and len(opened) == 1

    second = tc(db, "Checkout")  # the suite changed: a new commit on the same pull request
    later = _state(db, project)
    asyncio.run(runner._stage_suite(later, project, [first, second], passed(first, second)))
    asyncio.run(runner._auto_pull_requests(later, project))
    assert len(opened) == 1 and len(updated) == 1
    assert "new commit on pull request #7" in next(s for s in later.doc["stages"] if s["key"] == "fix")["detail"]


def test_without_auto_pr_nothing_is_opened(fresh_store, monkeypatch):
    db = fresh_store
    project = _project(db)
    monkeypatch.setattr(patches, "create_pull_request", lambda *a, **k: (_ for _ in ()).throw(AssertionError("opened")))
    state = _state(db, project)
    state.save(suite_patch={"id": 1})
    asyncio.run(runner._auto_pull_requests(state, project))


def test_a_pull_request_failure_is_noted_not_raised(fresh_store, monkeypatch):
    db = fresh_store
    project = _project(db, auto_pr=True)
    monkeypatch.setattr(patches, "read_files", lambda repo, paths, auth=None: ("abc", {p: None for p in paths}))
    monkeypatch.setattr("app.api.integrations.git_auth", lambda *a: None)

    def refuse(*a, **k):
        raise patches.PullRequestError("Connect GitHub first (Profile → Integrations).")

    monkeypatch.setattr(patches, "create_pull_request", refuse)
    good = tc(db, "Sign in")
    state = _state(db, project)
    asyncio.run(runner._stage_suite(state, project, [good], passed(good)))
    asyncio.run(runner._auto_pull_requests(state, project))
    detail = next(s for s in state.doc["stages"] if s["key"] == "fix")["detail"]
    assert "pull request not opened (Connect GitHub first" in detail
    assert state.doc["suite_patch"]["pull_request"] is None
