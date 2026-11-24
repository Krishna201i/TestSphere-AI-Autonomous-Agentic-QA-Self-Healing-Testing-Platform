"""A quarantined test earns trust: verified on a broken page, then passing runs in a row."""

import json

from app.database.store import MemoryStore
from app.models import TEST_CASES
from app.pipeline import acceptance
from app.services.test_case_service import TestCaseService

STEPS = [{"step_number": 1, "action": "NAVIGATE", "value": "https://shop.test"},
         {"step_number": 2, "action": "ASSERT_CONTAINS_TEXT", "target": "body", "value": "Cart"}]


def make(db, **extra):
    row = db.insert(TEST_CASES, name="AI: cart", category="ai", quarantined=True,
                    description=json.dumps({"steps": STEPS}), **extra)
    return row


def verified(db, tc):
    return db.update(TEST_CASES, tc["id"], acceptance={"status": "verified", "steps_key": acceptance.steps_key(STEPS)})


def run(db, tc, status):
    return acceptance.graduate(db, [db.get(TEST_CASES, tc["id"])], [{"test_case_id": tc["id"], "status": status}])


def test_graduates_after_verified_and_two_passes_in_a_row():
    db = MemoryStore()
    tc = verified(db, make(db))
    assert run(db, tc, "PASSED") == []
    assert db.get(TEST_CASES, tc["id"])["quarantined"] is True
    assert [g["id"] for g in run(db, tc, "PASSED")] == [tc["id"]]
    assert db.get(TEST_CASES, tc["id"])["quarantined"] is False


def test_a_failure_resets_the_count():
    db = MemoryStore()
    tc = verified(db, make(db))
    run(db, tc, "PASSED")
    run(db, tc, "FAILED")
    assert run(db, tc, "PASSED") == []
    assert db.get(TEST_CASES, tc["id"])["quarantined"] is True


def test_passing_alone_is_not_enough_without_a_verified_verdict():
    db = MemoryStore()
    tc = make(db, acceptance={"status": "asserts_nothing", "steps_key": acceptance.steps_key(STEPS)})
    for _ in range(5):
        assert run(db, tc, "PASSED") == []
    assert db.get(TEST_CASES, tc["id"])["quarantined"] is True


def test_a_verdict_on_old_steps_does_not_count():
    db = MemoryStore()
    tc = make(db, acceptance={"status": "verified", "steps_key": "old-steps"})
    run(db, tc, "PASSED")
    assert run(db, tc, "PASSED") == []


def test_a_quarantine_set_by_a_person_is_never_lifted():
    db = MemoryStore()
    tc = make(db)
    TestCaseService.update_test_case(db, tc["id"], quarantined=True)
    verified(db, tc)
    for _ in range(3):
        assert run(db, tc, "PASSED") == []
    assert db.get(TEST_CASES, tc["id"])["quarantined"] is True
