"""Visual baselines: created by the first passing run, compared later, replaced only when a person accepts a change."""

import pytest
from fastapi.testclient import TestClient

from backend import artifacts
from backend.config import settings
from backend.main import app
from backend.models import APPLICATIONS, TEST_CASES, TEST_EXECUTIONS


@pytest.fixture
def store():
    mem = artifacts.MemoryArtifactStore()
    artifacts.set_artifact_store(mem)
    yield mem
    artifacts.set_artifact_store(None)


def shot(tmp_path, name, data):
    path = tmp_path / name
    path.write_bytes(data)
    return str(path)


def test_first_pass_creates_the_baseline_and_later_changes_are_flagged(store, tmp_path):
    first = artifacts.record_visual({"current": shot(tmp_path, "a.png", b"PNG-A")}, "ann", 1, 7, None, passed=True)
    assert first == {"baseline_created": True, "changed": False, "current": "ann/executions/1/visual/current.png"}
    assert artifacts.load_baseline("ann", 7) == b"PNG-A"

    small = artifacts.record_visual({"current": shot(tmp_path, "b.png", b"PNG-B"), "ratio": 0.001}, "ann", 2, 7,
                                    b"PNG-A", passed=True)
    assert small["changed"] is False  # under VISUAL_DIFF_THRESHOLD: noise
    big = artifacts.record_visual({"current": shot(tmp_path, "c.png", b"PNG-C"), "ratio": settings.VISUAL_DIFF_THRESHOLD * 5,
                                   "diff": shot(tmp_path, "d.png", b"DIFF")}, "ann", 3, 7, b"PNG-A", passed=True)
    assert big["changed"] is True and big["diff"] == "ann/executions/3/visual/diff.png"
    assert artifacts.load_baseline("ann", 7) == b"PNG-A"  # a change never replaces the baseline by itself

    assert artifacts.record_visual({"current": shot(tmp_path, "e.png", b"X")}, "bob", 4, 8, None, passed=False) is None
    assert artifacts.load_baseline("bob", 8) is None  # a failed run never becomes a baseline


def test_accepting_a_change_makes_it_the_baseline(store, tmp_path, fresh_store):
    app_row = fresh_store.insert(APPLICATIONS, name="Shop", base_url="http://shop.test/", owner_uid="local-dev", project_id=None)
    tc = fresh_store.insert(TEST_CASES, application_id=app_row["id"], name="Smoke", owner_uid="local-dev")
    store.put(artifacts.baseline_key("local-dev", tc["id"]), b"OLD", "image/png")  # from an earlier run
    visual = artifacts.record_visual({"current": shot(tmp_path, "n.png", b"NEW"), "ratio": 0.5}, "local-dev", 1, tc["id"],
                                     b"OLD", passed=True)
    ex = fresh_store.insert(TEST_EXECUTIONS, test_case_id=tc["id"], status="PASSED", owner_uid="local-dev", visual=visual)
    client = TestClient(app)

    detail = client.get(f"/api/test-executions/{ex['id']}").json()
    assert detail["visual"]["changed"] is True
    baseline = artifacts.baseline_key("local-dev", tc["id"])
    assert detail["visual"]["baseline"] == baseline  # the dashboard shows it next to the new screenshot
    img = client.get(f"/api/test-executions/{ex['id']}/artifact", params={"key": baseline})
    assert img.status_code == 200 and img.content == b"OLD"

    resp = client.post(f"/api/test-executions/{ex['id']}/accept-visual")
    assert resp.status_code == 200 and resp.json()["visual"]["changed"] is False
    assert artifacts.load_baseline("local-dev", tc["id"]) == b"NEW"
    assert any(e["kind"] == "visual" for e in client.get("/api/audit").json())

    plain = fresh_store.insert(TEST_EXECUTIONS, test_case_id=tc["id"], status="FAILED", owner_uid="local-dev")
    assert client.post(f"/api/test-executions/{plain['id']}/accept-visual").status_code == 422


def test_a_run_never_puts_back_a_baseline_accepted_while_it_ran(store, tmp_path):
    artifacts.record_visual({"current": shot(tmp_path, "a.png", b"OLD")}, "ann", 1, 7, None, passed=True)
    compared = artifacts.load_baseline("ann", 7)  # what a run loads at its start
    store.put(artifacts.baseline_key("ann", 7), b"ACCEPTED", "image/png")  # a person accepts a change meanwhile

    artifacts.record_visual({"current": shot(tmp_path, "b.png", b"NEW"), "ratio": 0.5}, "ann", 2, 7, compared,
                            passed=True)
    assert artifacts.load_baseline("ann", 7) == b"ACCEPTED"

    # nor does the first run of a test overwrite one accepted while it ran
    store.put(artifacts.baseline_key("ann", 9), b"ACCEPTED", "image/png")
    assert artifacts.record_visual({"current": shot(tmp_path, "c.png", b"FIRST")}, "ann", 3, 9, None,
                                   passed=True) is None
    assert artifacts.load_baseline("ann", 9) == b"ACCEPTED"
