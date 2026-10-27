"""Pipeline worker: queue-only API, atomic claims, heartbeats and stale-run reaping."""

import asyncio
import threading
from datetime import UTC, datetime, timedelta

import pytest

from backend import worker
from backend.config import settings, startup_safety_problem
from backend.models import PIPELINE_RUNS
from backend.pipeline import runner
from backend.services.project_service import ProjectService


@pytest.fixture
def worker_mode(monkeypatch):
    monkeypatch.setattr(settings, "PIPELINE_EXECUTION", "worker")


def queue_run(db):
    project = ProjectService.create_project(db, name="Shop", owner_uid="u1", app_url="https://shop.example")
    return runner.create_run(db, project, trigger="manual", actor="tester")


def test_in_worker_mode_the_api_only_queues(fresh_store, worker_mode, monkeypatch):
    executed = []

    async def fake_execute(run_id, *a, **k):
        executed.append(run_id)

    monkeypatch.setattr(runner, "execute_run", fake_execute)
    project = ProjectService.create_project(fresh_store, name="Shop", owner_uid="u1", app_url="https://shop.example")

    async def go():
        run = runner.start_run(fresh_store, project, trigger="manual", actor="tester")
        await asyncio.sleep(0)
        return run

    run = asyncio.run(go())
    assert executed == []
    assert fresh_store.get(PIPELINE_RUNS, run["id"])["status"] == "queued"


def test_a_restarting_api_leaves_the_workers_runs_alone(fresh_store, worker_mode):
    run = queue_run(fresh_store)
    assert runner.recover_interrupted(fresh_store) == 0
    assert fresh_store.get(PIPELINE_RUNS, run["id"])["status"] == "queued"


def test_claims_the_oldest_queued_run_once(fresh_store):
    first, second = queue_run(fresh_store), queue_run(fresh_store)
    claimed = worker.claim_next(fresh_store, "w1")
    assert claimed["id"] == first["id"]
    assert (claimed["status"], claimed["worker"]) == ("running", "w1")
    assert claimed["heartbeat_at"]
    assert worker.claim_next(fresh_store, "w2")["id"] == second["id"]
    assert worker.claim_next(fresh_store, "w3") is None


def test_concurrent_workers_never_take_the_same_run(fresh_store):
    runs = [queue_run(fresh_store) for _ in range(3)]
    taken, lock = [], threading.Lock()

    def drain(name):
        while (run := worker.claim_next(fresh_store, name)) is not None:
            with lock:
                taken.append(run["id"])

    threads = [threading.Thread(target=drain, args=(f"w{i}",)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(taken) == [r["id"] for r in runs]  # each exactly once


def test_runs_of_a_dead_worker_are_marked_interrupted_not_rerun(fresh_store):
    stale, fresh = queue_run(fresh_store), queue_run(fresh_store)
    old = (datetime.now(UTC) - timedelta(seconds=worker.STALE_SECONDS + 60)).isoformat()
    fresh_store.update(PIPELINE_RUNS, stale["id"], status="running", heartbeat_at=old)
    fresh_store.update(PIPELINE_RUNS, fresh["id"], status="running", heartbeat_at=datetime.now(UTC).isoformat())

    assert worker.reap_stale(fresh_store) == [stale["id"]]
    reaped = fresh_store.get(PIPELINE_RUNS, stale["id"])
    assert reaped["status"] == "error" and "worker" in reaped["error"]
    assert fresh_store.get(PIPELINE_RUNS, fresh["id"])["status"] == "running"


def test_the_worker_loop_executes_queued_runs(fresh_store, monkeypatch):
    run = queue_run(fresh_store)
    stop = asyncio.Event()

    async def fake_execute(run_id, *a, **k):
        fresh_store.update(PIPELINE_RUNS, run_id, status="passed")
        stop.set()
        return fresh_store.get(PIPELINE_RUNS, run_id)

    monkeypatch.setattr(runner, "execute_run", fake_execute)
    monkeypatch.setattr(worker, "POLL_SECONDS", 0.05)
    asyncio.run(asyncio.wait_for(worker.work(stop, fresh_store), timeout=5))
    done = fresh_store.get(PIPELINE_RUNS, run["id"])
    assert done["status"] == "passed" and done["worker"] == worker.worker_id()


def test_an_unknown_execution_mode_is_refused(monkeypatch):
    monkeypatch.setattr(settings, "PIPELINE_EXECUTION", "threads")
    assert "PIPELINE_EXECUTION" in startup_safety_problem()


def test_worker_mode_requires_a_shared_database(monkeypatch):
    monkeypatch.setattr(settings, "PIPELINE_EXECUTION", "worker")
    monkeypatch.setattr(settings, "DATABASE_BACKEND", "local")
    assert "share" in startup_safety_problem()
    monkeypatch.setattr(settings, "DATABASE_BACKEND", "firestore")
    assert startup_safety_problem() is None


def test_a_reaped_run_closes_its_stages_and_updates_the_project(fresh_store):
    from backend.models import PROJECTS

    run = queue_run(fresh_store)
    old = (datetime.now(UTC) - timedelta(seconds=worker.STALE_SECONDS + 60)).isoformat()
    stages = [dict(s) for s in run["stages"]]
    stages[0]["status"] = "running"
    fresh_store.update(PIPELINE_RUNS, run["id"], status="running", heartbeat_at=old, stages=stages)

    worker.reap_stale(fresh_store)

    reaped = fresh_store.get(PIPELINE_RUNS, run["id"])
    assert reaped["stages"][0]["status"] == "failed"
    assert not [s for s in reaped["stages"] if s["status"] in ("running", "pending")]
    assert fresh_store.get(PROJECTS, run["project_id"])["last_run_status"] == "error"


def test_an_idle_worker_polls_less_and_less(monkeypatch):
    monkeypatch.setattr(worker, "POLL_SECONDS", 5)
    monkeypatch.setattr(worker, "IDLE_POLL_SECONDS", 60)
    waits, wait = [], 5
    for _ in range(6):
        wait = worker.next_poll(wait)
        waits.append(wait)
    assert waits == [10, 20, 40, 60, 60, 60]
    # a day of idling: a few thousand queries instead of about 35,000
    assert 86_400 / 60 + 86_400 / worker.REAP_SECONDS < 2_000


def test_the_worker_waits_for_the_runs_deployment(fresh_store, monkeypatch):
    from backend.pipeline import deploy

    finished = []

    async def fake_execute(run_id, *a, **k):
        async def deployment():
            await asyncio.sleep(0.05)
            finished.append("deploy")

        task = asyncio.get_running_loop().create_task(deployment())
        deploy._tasks.add(task)
        task.add_done_callback(deploy._tasks.discard)
        return {"status": "passed"}

    monkeypatch.setattr(runner, "execute_run", fake_execute)
    queue_run(fresh_store)
    asyncio.run(worker.run_one(fresh_store, worker.claim_next(fresh_store, "w")))
    assert finished == ["deploy"]
