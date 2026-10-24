"""
Run evidence: step results and artifacts (screenshots, DOM snapshots,
traces) saved per execution, served only to their owner.
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from backend import auth
from backend.artifacts import (
    LocalArtifactStore,
    execution_prefix,
    persist_run_artifacts,
)
from backend.config import settings
from backend.database.session import get_store
from backend.main import app
from backend.models import TEST_EXECUTIONS
from backend.orchestration.orchestrator import PlatformWorkflowOrchestrator
from backend.services.application_service import ApplicationService
from backend.services.project_service import ProjectService
from backend.services.test_case_service import TestCaseService
from backend.services.test_execution_service import TestExecutionService
from engine.schemas import (
    HealingCandidate,
    HealingReport,
    HealingSignals,
    StepResult,
    StepStatus,
    TestStatus,
)
from engine.schemas import TestResult as EngineTestResult

TOKENS = {"token-alice": {"uid": "alice", "email": "a@example.com", "firebase": {"sign_in_provider": "password"}},
          "token-bob": {"uid": "bob", "email": "b@example.com", "firebase": {"sign_in_provider": "password"}}}


def engine_result(tmp_path, *, with_files=True):
    run_dir = tmp_path / "artifacts" / "TC-1"
    shot = run_dir / "click-login" / "screenshot.png"
    dom = run_dir / "click-login" / "dom.html"
    if with_files:
        shot.parent.mkdir(parents=True)
        shot.write_bytes(b"\x89PNG fake")
        dom.write_text("<html><script>alert(1)</script></html>")
        (run_dir / "_trace.zip").write_bytes(b"PK trace")
    signals = HealingSignals(attribute=0.9, text=0.8, position=0.5, structure=0.7)
    return EngineTestResult(
        test_id="TC-1", status=TestStatus.HEALED, started_at=datetime.now(UTC), duration_ms=300,
        artifacts_dir=str(run_dir),
        steps=[
            StepResult(step_id="open", status=StepStatus.PASSED, duration_ms=100),
            StepResult(
                step_id="click-login", status=StepStatus.HEALED, duration_ms=200, locator_used="#login-btn",
                screenshot_path=str(shot), dom_snapshot_path=str(dom), console_logs=["warn: x"],
                healing=HealingReport(
                    original_locator='[data-testid="login"]', selected_locator="#login-btn", confidence=0.87,
                    strategy_used="fingerprint",
                    candidates=[HealingCandidate(locator=f"#c{i}", score=0.9 - i / 10, signals=signals) for i in range(5)],
                ),
            ),
        ],
    )


def test_persist_keeps_step_evidence_and_stores_files(tmp_path, fresh_artifacts):
    evidence = persist_run_artifacts(engine_result(tmp_path), "alice", 12, {"click-login": "click Login button"})

    open_step, login = evidence["steps"]
    assert open_step["screenshot"] is None and open_step["status"] == "passed"
    assert login["description"] == "click Login button"
    assert login["healing"]["original_locator"] == '[data-testid="login"]'
    assert login["healing"]["selected_locator"] == "#login-btn"
    assert login["healing"]["confidence"] == 0.87
    assert len(login["healing"]["candidates"]) == 3  # top three only
    assert login["screenshot"] == "alice/executions/12/click-login/screenshot.png"
    assert evidence["trace"] == "alice/executions/12/trace.zip"
    assert fresh_artifacts.get(login["screenshot"]) == (b"\x89PNG fake", "image/png")


def test_missing_files_are_skipped_not_fatal(tmp_path):
    evidence = persist_run_artifacts(engine_result(tmp_path, with_files=False), "alice", 3)
    assert [s["screenshot"] for s in evidence["steps"]] == [None, None]
    assert evidence["trace"] is None


def test_keys_cannot_escape_the_local_store(tmp_path):
    store = LocalArtifactStore(str(tmp_path / "store"))
    store.put("alice/executions/1/a.png", b"x", "image/png")
    assert store.get("alice/executions/1/a.png") == (b"x", "image/png")
    with pytest.raises(ValueError):
        store.get("../../etc/passwd")
    assert execution_prefix("../evil", 5) == "evil/executions/5/"
    assert store.delete_prefix("alice/") == 1
    assert store.get("alice/executions/1/a.png") is None


class TestOrchestratorRecordsEvidence:
    @pytest.mark.asyncio
    async def test_execution_record_gets_steps_and_trace(self, tmp_path):
        db = get_store()
        project = ProjectService.create_project(db, name="P")
        application = ApplicationService.create_application(db, project.id, name="A", base_url="https://a.example")
        tc = TestCaseService.create_test_case(db, application.id, external_id="TC-1", name="Login")
        execution = TestExecutionService.create_execution(db, tc.id)

        with patch("backend.orchestration.orchestrator.run_test", new=AsyncMock(return_value=engine_result(tmp_path))):
            await PlatformWorkflowOrchestrator().execute_test_run(db=db, execution_id=execution.id)

        saved = db.get(TEST_EXECUTIONS, execution.id)
        assert saved.status == "HEALED"
        assert [s["step_id"] for s in saved["steps"]] == ["open", "click-login"]
        assert saved["steps"][1]["healing"]["selected_locator"] == "#login-btn"
        assert saved["trace"].endswith("/trace.zip")


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    monkeypatch.setattr(auth, "verify_token", lambda token: TOKENS[token])
    return TestClient(app)


def _seed_execution(owner, fresh_artifacts):
    db = get_store()
    prefix = execution_prefix(owner, 1)
    fresh_artifacts.put(f"{prefix}s1/screenshot.png", b"PNG", "image/png")
    fresh_artifacts.put(f"{prefix}s1/dom.html", b"<script>alert(1)</script>", "text/html")
    fresh_artifacts.put(f"{prefix}trace.zip", b"PK", "application/zip")
    fresh_artifacts.put(f"{owner}/executions/99/secret.png", b"other", "image/png")
    return db.insert(TEST_EXECUTIONS, test_case_id=1, status="FAILED", owner_uid=owner,
                     steps=[{"step_id": "s1", "status": "failed", "screenshot": f"{prefix}s1/screenshot.png",
                             "dom": f"{prefix}s1/dom.html"}],
                     trace=f"{prefix}trace.zip")


def test_owner_sees_steps_and_gets_artifacts(client, fresh_artifacts):
    ex = _seed_execution("alice", fresh_artifacts)
    alice = {"Authorization": "Bearer token-alice"}

    detail = client.get(f"/api/test-executions/{ex.id}", headers=alice).json()
    assert detail["steps"][0]["screenshot"].endswith("screenshot.png")
    assert detail["trace"].endswith("trace.zip")

    shot = client.get(f"/api/test-executions/{ex.id}/artifact", params={"key": detail["steps"][0]["screenshot"]}, headers=alice)
    assert shot.status_code == 200 and shot.content == b"PNG"
    assert shot.headers["content-type"] == "image/png"
    assert shot.headers["content-disposition"].startswith("inline")

    # Someone else's HTML is never rendered on this origin
    dom = client.get(f"/api/test-executions/{ex.id}/artifact", params={"key": detail["steps"][0]["dom"]}, headers=alice)
    assert dom.headers["content-type"].startswith("text/plain")
    assert dom.headers["content-disposition"].startswith("attachment")
    assert dom.headers["content-security-policy"] == "sandbox"

    trace = client.get(f"/api/test-executions/{ex.id}/artifact", params={"key": detail["trace"]}, headers=alice)
    assert trace.status_code == 200 and trace.headers["content-disposition"].startswith("attachment")


def test_only_recorded_keys_of_own_executions_are_served(client, fresh_artifacts):
    ex = _seed_execution("alice", fresh_artifacts)
    url = f"/api/test-executions/{ex.id}/artifact"
    alice, bob = {"Authorization": "Bearer token-alice"}, {"Authorization": "Bearer token-bob"}

    # A real file of the same owner that is not recorded on this execution
    assert client.get(url, params={"key": "alice/executions/99/secret.png"}, headers=alice).status_code == 404
    assert client.get(url, params={"key": "../../etc/passwd"}, headers=alice).status_code == 404
    # Another user's execution does not exist for them
    assert client.get(url, params={"key": ex["trace"]}, headers=bob).status_code == 404
    assert client.get(f"/api/test-executions/{ex.id}", headers=bob).status_code == 404


def test_expired_artifacts_say_so(client, fresh_artifacts):
    ex = _seed_execution("alice", fresh_artifacts)
    fresh_artifacts.delete_prefix("alice/")
    resp = client.get(f"/api/test-executions/{ex.id}/artifact", params={"key": ex["trace"]},
                      headers={"Authorization": "Bearer token-alice"})
    assert resp.status_code == 404 and "expired" in resp.json()["detail"]


def test_deleting_an_execution_or_account_removes_its_artifacts(client, fresh_artifacts, monkeypatch):
    from backend.api import me

    ex = _seed_execution("alice", fresh_artifacts)
    alice = {"Authorization": "Bearer token-alice"}
    assert client.delete(f"/api/test-executions/{ex.id}", headers=alice).status_code == 204
    assert not any(k.startswith(execution_prefix("alice", ex.id)) for k in fresh_artifacts.files)
    assert "alice/executions/99/secret.png" in fresh_artifacts.files

    monkeypatch.setattr(me, "_delete_sign_in_account", lambda uid: True)
    fresh_artifacts.put("bob/executions/1/x.png", b"b", "image/png")
    resp = client.request("DELETE", "/api/me", json={"confirm": "DELETE MY ACCOUNT"}, headers=alice)
    assert resp.json()["deleted"]["artifacts"] == 1
    assert list(fresh_artifacts.files) == ["bob/executions/1/x.png"]


def test_local_retention_removes_only_old_files(tmp_path, monkeypatch):
    import os
    import time

    from backend import artifacts

    store = LocalArtifactStore(str(tmp_path / "store"))
    store.put("alice/executions/1/old.png", b"x", "image/png")
    store.put("alice/executions/2/new.png", b"y", "image/png")
    old = tmp_path / "store" / "alice" / "executions" / "1" / "old.png"
    stamp = time.time() - 40 * 86400
    os.utime(old, (stamp, stamp))

    artifacts.set_artifact_store(store)
    monkeypatch.setattr(settings, "ARTIFACT_RETENTION_DAYS", 30)
    assert artifacts.expire_old_artifacts(force=True) == 1
    assert store.get("alice/executions/1/old.png") is None
    assert store.get("alice/executions/2/new.png") is not None
    assert artifacts.expire_old_artifacts() is None  # not again within the window

    monkeypatch.setattr(settings, "ARTIFACT_RETENTION_DAYS", 0)
    assert artifacts.expire_old_artifacts(force=True) is None  # kept until deleted


def test_step_descriptions_read_like_sentences_and_hide_typed_values():
    from backend.orchestration.orchestrator import describe_step
    from engine.schemas import ActionType, Step, Target

    assert describe_step(Step(step_id="a", action=ActionType.GOTO, value="https://shop.example/")) == "Open https://shop.example/"
    click = Step(step_id="b", action=ActionType.CLICK, target=Target(description='"Log in" button', primary_locator="#login"))
    assert describe_step(click) == 'Click "Log in" button'
    secret = Step(step_id="c", action=ActionType.FILL, value="hunter2",
                  target=Target(description="Password field", primary_locator="#pw"))
    assert describe_step(secret) == "Type into Password field (7 characters)"
    check = Step(step_id="d", action=ActionType.ASSERT_TEXT, expected="Welcome",
                 target=Target(description="Assertion target for element_contains_text", primary_locator="h1"))
    assert describe_step(check) == 'Check the text of h1 contains "Welcome"'
