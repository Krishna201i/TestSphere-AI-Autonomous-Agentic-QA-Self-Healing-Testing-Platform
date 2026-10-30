"""What a run tells people: why a test failed, and the run in plain sentences."""

from __future__ import annotations

import asyncio

from agents.analyzer.analyzer import FailureAnalyzerAgent, engine_expected_actual
from agents.analyzer.schemas import FailureContext
from agents.memory.in_memory_store import InMemoryStore
from agents.schemas.enums import ConfidenceLevel, FailureType
from backend.reporting.diagnosis import NEXT_STEPS, diagnosis_of
from backend.reporting.summary import run_summary


def test_the_engines_check_failures_name_expected_and_actual():
    assert engine_expected_actual("assert_url failed: expected '/hospital/' in 'https://x.net/'") == ("/hospital/", "https://x.net/")
    assert engine_expected_actual("assert_text failed: expected exactly 'Hi', got 'Hello'") == ("Hi", "Hello")
    assert engine_expected_actual("assert_text failed: expected 'Sign in' in 'Welcome…' (4,812 characters)") == ("Sign in", "Welcome…")
    assert engine_expected_actual("assert_visible failed: '#x' is not visible") is None


def test_a_failed_url_check_is_diagnosed_as_a_check_that_did_not_hold():
    failure = FailureContext(test_id="t", execution_id="e", failed_step=2, action="assert_url", target_selector="",
                             error_message="assert_url failed: expected '/hospital/' in 'https://x.net/'")
    analysis = asyncio.run(FailureAnalyzerAgent(InMemoryStore()).analyze(failure))
    assert analysis.failure_type == FailureType.ASSERTION_FAILURE and analysis.confidence == ConfidenceLevel.HIGH

    d = diagnosis_of(analysis)
    assert d["label"] == "Check did not hold" and d["confidence"] == "high"
    assert d["expected"] == "/hospital/" and d["actual"] == "https://x.net/"
    assert "/hospital/" in d["explanation"] and d["next_step"] == NEXT_STEPS["ASSERTION_FAILURE"]
    assert diagnosis_of(None) is None


def _results(passed, failed, *, quarantined=True, label="Check did not hold"):
    return ([{"name": f"P{i}", "status": "PASSED", "category": "smoke"} for i in range(passed)]
            + [{"name": f"AI: Navigate {i}", "status": "FAILED", "category": "ai", "quarantined": quarantined,
                "diagnosis": {"label": label}} for i in range(failed)])


def test_a_run_with_only_quarantined_failures_reads_as_healthy():
    lines = run_summary({"total": 16, "passed": 12, "previous_run_id": 50, "flaky": 1}, _results(12, 4), [])
    assert lines == [
        "12 of 16 tests passed (75%).",
        "Nothing that passed in run #50 fails now.",
        "4 tests failed, all quarantined (4 AI-written), so they do not fail the run. Most common cause: check did not hold (4).",
        "Also: 1 test is flaky (results keep changing between runs).",
        "Verdict: the app looks healthy, but review the quarantined failures.",
    ]


def test_a_regression_needs_attention_and_singulars_read_right():
    results = [{"name": "Smoke: Shop", "status": "FAILED", "category": "smoke", "diagnosis": {"label": "Timed out"}},
               {"name": "Content", "status": "PASSED", "category": "content"}]
    lines = run_summary({"total": 2, "passed": 1, "previous_run_id": 7}, results,
                        [{"kind": "test", "name": "Smoke: Shop"}])
    assert "1 test passed in run #7 and fails now: “Smoke: Shop”." in lines
    assert "1 test failed and fails the run: “Smoke: Shop”. Most common cause: timed out (1)." in lines
    assert lines[-1] == "Verdict: needs attention."


def test_a_first_clean_run():
    assert run_summary({"total": 3, "passed": 3, "previous_run_id": None}, _results(3, 0), []) == [
        "All 3 tests passed.",
        "This is the project's first run, so there is nothing to compare with yet.",
        "Verdict: the app looks healthy.",
    ]


# ── The run's report document (HTML and PDF) ──────────────────

PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360f8cfc0f01f0005000201e2d6a3"
    "c00000000049454e44ae426082")


def _seed_run(owner="local-dev", status="failed"):
    import pytest  # noqa: F401 - keeps this helper importable by other modules' fixtures

    from backend.artifacts import MemoryArtifactStore, set_artifact_store
    from backend.database.session import get_store
    from backend.models import PIPELINE_RUNS, TEST_EXECUTIONS
    from backend.services.application_service import ApplicationService
    from backend.services.project_service import ProjectService
    from backend.services.test_case_service import TestCaseService

    db = get_store()
    store = MemoryArtifactStore()
    store.put("u/1/step-2.png", PNG_1PX, "image/png")
    set_artifact_store(store)
    project = ProjectService.create_project(db, name="<script>alert(1)</script> Shop", owner_uid=owner)
    app_row = ApplicationService.create_application(db, project["id"], name="Shop", base_url="https://shop.test/")
    tc = TestCaseService.create_test_case(db, app_row["id"], external_id=None, name="Hospital portal", description="{}")
    diagnosis = {"kind": "ASSERTION_FAILURE", "label": "Check did not hold", "explanation": "Expected '/hospital/'.",
                 "next_step": "Compare expected and actual.", "confidence": "high", "expected": "/hospital/", "actual": "https://shop.test/"}
    execution = db.insert(TEST_EXECUTIONS, test_case_id=tc["id"], status="FAILED", owner_uid=owner, diagnosis=diagnosis, steps=[
        {"step_id": "s1", "status": "passed", "description": "Open the page"},
        {"step_id": "s2", "status": "failed", "description": "URL contains '/hospital/'",
         "error": "assert_url failed: expected '/hospital/' in 'https://shop.test/'", "screenshot": "u/1/step-2.png"}])
    tests = [{"name": "Smoke", "status": "PASSED", "category": "smoke", "execution_id": 900, "checks": ["Page title contains 'Shop'"], "duration_ms": 1200},
             {"name": "AI: <b>Hospital</b> portal", "status": "FAILED", "category": "ai", "execution_id": execution["id"], "quarantined": True,
              "error": "assert_url failed: expected '/hospital/' in 'https://shop.test/'", "diagnosis": diagnosis, "duration_ms": 5100}]
    summary = {"total": 2, "passed": 1, "failed": 0, "quarantined_failed": 1, "healed": 0, "flaky": 0,
               "narrative": ["1 of 2 tests passed (50%).", "Verdict: the app looks healthy, but review the quarantined failures."]}
    run = db.insert(PIPELINE_RUNS, project_id=project["id"], project_name=project["name"], owner_uid=owner, status=status,
                    trigger="manual", tests=tests, summary=summary, regressions=[], finished_at="2026-10-31T10:00:00+00:00",
                    stages=[{"key": "execute", "label": "Test execution", "status": "done", "detail": "1 of 2 passed"}])
    return run


def test_the_report_document_shows_summary_diagnosis_and_screenshot_and_escapes_markup():
    from fastapi.testclient import TestClient

    from backend.main import app

    run = _seed_run()
    resp = TestClient(app).get(f"/api/pipelines/runs/{run['id']}/report")
    assert resp.status_code == 200 and resp.headers["content-type"].startswith("text/html")
    assert "default-src 'none'" in resp.headers["content-security-policy"]
    page = resp.text
    assert "Verdict: the app looks healthy" in page and "Check did not hold" in page and "Next step:" in page
    assert "Failing step 2:" in page and "data:image/png;base64," in page   # the screenshot is embedded
    assert "Page title contains &#x27;Shop&#x27;" in page                     # what a passed test checked
    # Text from the site or a user is never markup in the report
    assert "<script>" not in page and "&lt;script&gt;" in page and "&lt;b&gt;Hospital&lt;/b&gt;" in page


def test_only_a_finished_run_of_ones_own_has_a_report(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import auth
    from backend.config import settings
    from backend.main import app

    # Signed in, as in production (with sign-in off the one local user owns everything)
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    monkeypatch.setattr(auth, "verify_token", lambda token: {
        "uid": token.removeprefix("token-"), "email": f"{token}@example.com", "firebase": {"sign_in_provider": "password"}})
    client = TestClient(app)
    alice, bob = {"Authorization": "Bearer token-alice"}, {"Authorization": "Bearer token-bob"}

    run = _seed_run(owner="alice")
    assert client.get(f"/api/pipelines/runs/{run['id']}/report", headers=alice).status_code == 200
    assert client.get(f"/api/pipelines/runs/{run['id']}/report", headers=bob).status_code == 404
    assert client.get(f"/api/pipelines/runs/{run['id']}/report.pdf", headers=bob).status_code == 404
    assert client.get(f"/api/pipelines/runs/{run['id']}/report").status_code == 401
    running = _seed_run(owner="alice", status="running")
    assert client.get(f"/api/pipelines/runs/{running['id']}/report", headers=alice).status_code == 409


def test_the_pdf_report_is_a_real_pdf():
    from fastapi.testclient import TestClient

    from backend.main import app

    run = _seed_run()
    resp = TestClient(app).get(f"/api/pipelines/runs/{run['id']}/report.pdf")
    assert resp.status_code == 200 and resp.headers["content-type"] == "application/pdf"
    assert resp.content.startswith(b"%PDF") and len(resp.content) > 5_000
    assert f"testsphere-run-{run['id']}-report.pdf" in resp.headers["content-disposition"]


# ── Read-only share links ─────────────────────────────────────

def _signed_in(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import auth
    from backend.config import settings
    from backend.main import app

    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    monkeypatch.setattr(settings, "DASHBOARD_URL", "https://testsphere.example")
    monkeypatch.setattr(auth, "verify_token", lambda token: {
        "uid": token.removeprefix("token-"), "email": f"{token}@example.com", "firebase": {"sign_in_provider": "password"}})
    return TestClient(app), {"Authorization": "Bearer token-alice"}, {"Authorization": "Bearer token-bob"}


def test_a_share_link_shows_only_that_report_without_signing_in(monkeypatch):
    from backend.database.session import get_store
    from backend.models import AUDIT_EVENTS, REPORT_SHARES

    client, alice, _ = _signed_in(monkeypatch)
    run = _seed_run(owner="alice")
    created = client.post(f"/api/pipelines/runs/{run['id']}/shares", json={"days": 3}, headers=alice)
    assert created.status_code == 201
    link = created.json()
    assert link["url"].startswith("https://testsphere.example/api/shared/") and link["active"]
    token = link["url"].rsplit("/", 1)[1]

    # Only the token's hash is stored
    row = get_store().get(REPORT_SHARES, link["id"])
    assert token not in str(row) and len(row["token_hash"]) == 64

    page = client.get(f"/api/shared/{token}")  # no Authorization header
    assert page.status_code == 200 and "shared read-only copy" in page.text and "Check did not hold" in page.text
    assert page.headers["referrer-policy"] == "no-referrer" and page.headers["x-robots-tag"] == "noindex"
    assert "default-src 'none'" in page.headers["content-security-policy"]
    pdf = client.get(f"/api/shared/{token}.pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")

    # The list never shows tokens; creating it was audited
    listed = client.get(f"/api/pipelines/runs/{run['id']}/shares", headers=alice).json()
    assert [s["id"] for s in listed] == [link["id"]] and "url" not in listed[0] and "token_hash" not in listed[0]
    assert any("Read-only link to the report of run" in e["message"] for e in get_store().find(AUDIT_EVENTS))


def test_revoked_expired_and_unknown_links_all_answer_the_same_404(monkeypatch):
    from datetime import UTC, datetime, timedelta

    from backend.database.session import get_store
    from backend.models import REPORT_SHARES

    client, alice, bob = _signed_in(monkeypatch)
    run = _seed_run(owner="alice")
    make = lambda: client.post(f"/api/pipelines/runs/{run['id']}/shares", json={}, headers=alice).json()  # noqa: E731

    revoked = make()
    assert client.delete(f"/api/pipelines/shares/{revoked['id']}", headers=bob).status_code == 404  # not bob's
    assert client.delete(f"/api/pipelines/shares/{revoked['id']}", headers=alice).status_code == 204
    expired = make()
    get_store().update(REPORT_SHARES, expired["id"], expires_at=(datetime.now(UTC) - timedelta(minutes=1)).isoformat())

    answers = [client.get(f"/api/shared/{link['url'].rsplit('/', 1)[1]}") for link in (revoked, expired)]
    answers.append(client.get("/api/shared/" + "x" * 43))
    assert {a.status_code for a in answers} == {404} and len({a.text for a in answers}) == 1
    assert "not available" in answers[0].text

    # Bob can neither list alice's links nor share her run
    assert client.get(f"/api/pipelines/runs/{run['id']}/shares", headers=bob).status_code == 404
    assert client.post(f"/api/pipelines/runs/{run['id']}/shares", json={}, headers=bob).status_code == 404


def test_a_link_lasts_at_most_30_days_and_dies_with_its_run(monkeypatch):
    from backend.database.session import get_store
    from backend.models import PIPELINE_RUNS

    client, alice, _ = _signed_in(monkeypatch)
    run = _seed_run(owner="alice")
    assert client.post(f"/api/pipelines/runs/{run['id']}/shares", json={"days": 31}, headers=alice).status_code == 422
    link = client.post(f"/api/pipelines/runs/{run['id']}/shares", json={"days": 30}, headers=alice).json()
    get_store().delete(PIPELINE_RUNS, run["id"])
    assert client.get(f"/api/shared/{link['url'].rsplit('/', 1)[1]}").status_code == 404
