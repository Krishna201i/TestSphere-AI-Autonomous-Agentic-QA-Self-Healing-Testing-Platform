"""
tests/engine/test_schemas.py
============================
Unit tests for engine/schemas.py — Member 2 scope.

Covers:
- Round-trip serialisation for every model
- ActionType / StepStatus / TestStatus enum values
- EngineConfig defaults
- RunOptions.merged() override logic
- TestResult convenience counts
- export_schemas() writes valid JSON files
"""

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from engine.schemas import (
    ActionType,
    BoundingBox,
    ElementFingerprint,
    EngineConfig,
    HealingCandidate,
    HealingReport,
    HealingSignals,
    RunOptions,
    Step,
    StepResult,
    StepStatus,
    Target,
    TestPlan,
    TestResult,
    TestStatus,
    export_schemas,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def minimal_target() -> Target:
    return Target(description="Login button", primary_locator="#login-btn")


@pytest.fixture()
def minimal_step(minimal_target: Target) -> Step:
    return Step(step_id="s1", action=ActionType.CLICK, target=minimal_target)


@pytest.fixture()
def minimal_plan(minimal_step: Step) -> TestPlan:
    return TestPlan(
        test_id="t1",
        name="Login flow",
        base_url="http://localhost:8080",
        steps=[minimal_step],
    )


@pytest.fixture()
def passed_step_result() -> StepResult:
    return StepResult(
        step_id="s1",
        status=StepStatus.PASSED,
        duration_ms=120,
        locator_used="#login-btn",
    )


@pytest.fixture()
def healed_step_result() -> StepResult:
    signals = HealingSignals(attribute=0.9, text=0.8, position=0.6, structure=0.7)
    candidate = HealingCandidate(locator="button.login", score=0.82, signals=signals)
    report = HealingReport(
        original_locator="#login-btn",
        candidates=[candidate],
        selected_locator="button.login",
        confidence=0.82,
        strategy_used="fingerprint",
    )
    return StepResult(
        step_id="s2",
        status=StepStatus.HEALED,
        duration_ms=350,
        locator_used="button.login",
        healing=report,
    )


@pytest.fixture()
def failed_step_result() -> StepResult:
    return StepResult(
        step_id="s3",
        status=StepStatus.FAILED,
        duration_ms=5001,
        error="Timeout waiting for #gone",
    )


@pytest.fixture()
def full_test_result(
    passed_step_result: StepResult,
    healed_step_result: StepResult,
    failed_step_result: StepResult,
) -> TestResult:
    return TestResult(
        test_id="t1",
        status=TestStatus.FAILED,
        started_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        duration_ms=6000,
        steps=[passed_step_result, healed_step_result, failed_step_result],
        artifacts_dir="artifacts/t1",
    )


# ---------------------------------------------------------------------------
# Enum sanity
# ---------------------------------------------------------------------------


def test_action_type_values() -> None:
    expected = {"goto", "click", "fill", "press", "select", "assert_text", "assert_visible", "wait_for"}
    assert {a.value for a in ActionType} == expected


def test_step_status_values() -> None:
    assert {s.value for s in StepStatus} == {"passed", "failed", "healed"}


def test_test_status_values() -> None:
    assert {s.value for s in TestStatus} == {"passed", "failed", "healed"}


# ---------------------------------------------------------------------------
# BoundingBox
# ---------------------------------------------------------------------------


def test_bounding_box_round_trip() -> None:
    bb = BoundingBox(x=10.5, y=20.0, width=100.0, height=50.0)
    assert BoundingBox.model_validate(bb.model_dump()) == bb


def test_bounding_box_immutable() -> None:
    bb = BoundingBox(x=0, y=0, width=10, height=10)
    with pytest.raises(Exception):  # frozen=True raises ValidationError or AttributeError
        bb.x = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ElementFingerprint
# ---------------------------------------------------------------------------


def test_fingerprint_defaults() -> None:
    fp = ElementFingerprint()
    assert fp.classes == []
    assert fp.attributes == {}
    assert fp.parent_chain == []
    assert fp.bounding_box is None


def test_fingerprint_round_trip() -> None:
    fp = ElementFingerprint(
        tag="button",
        id="login-btn",
        classes=["btn", "primary"],
        text="Log in",
        role="button",
        aria_label="Submit login form",
        attributes={"data-testid": "login"},
        parent_chain=["div#form.container", "form#login-form"],
        sibling_index=0,
        bounding_box=BoundingBox(x=100, y=200, width=80, height=36),
    )
    assert ElementFingerprint.model_validate(fp.model_dump()) == fp


# ---------------------------------------------------------------------------
# Target
# ---------------------------------------------------------------------------


def test_target_fallbacks_default(minimal_target: Target) -> None:
    assert minimal_target.fallback_locators == []
    assert minimal_target.fingerprint is None


def test_target_with_fallbacks() -> None:
    t = Target(
        description="Submit",
        primary_locator="[data-testid='submit']",
        fallback_locators=["button[type=submit]", "//button[text()='Submit']"],
    )
    assert len(t.fallback_locators) == 2


# ---------------------------------------------------------------------------
# Step
# ---------------------------------------------------------------------------


def test_step_defaults(minimal_step: Step) -> None:
    assert minimal_step.timeout_ms == 5_000
    assert minimal_step.value is None
    assert minimal_step.expected is None


def test_step_all_action_types() -> None:
    """Every ActionType must be valid in a Step (no enum exclusion)."""
    for action in ActionType:
        step = Step(step_id="x", action=action)
        assert step.action == action


# ---------------------------------------------------------------------------
# TestPlan
# ---------------------------------------------------------------------------


def test_plan_requires_steps() -> None:
    with pytest.raises(Exception):
        TestPlan(test_id="t", name="n", base_url="http://x", steps=[])


def test_plan_round_trip(minimal_plan: TestPlan) -> None:
    data = minimal_plan.model_dump()
    restored = TestPlan.model_validate(data)
    assert restored.test_id == minimal_plan.test_id
    assert len(restored.steps) == 1


# ---------------------------------------------------------------------------
# EngineConfig
# ---------------------------------------------------------------------------


def test_engine_config_defaults() -> None:
    cfg = EngineConfig()
    assert cfg.heal_threshold == 0.75
    assert cfg.default_timeout_ms == 5_000
    assert cfg.headless is True
    assert cfg.artifacts_dir == "artifacts"
    assert cfg.slow_mo_ms == 0
    assert cfg.tracing_enabled is False
    assert cfg.max_candidates == 20


def test_engine_config_rejects_bad_threshold() -> None:
    with pytest.raises(Exception):
        EngineConfig(heal_threshold=1.5)


# ---------------------------------------------------------------------------
# RunOptions.merged()
# ---------------------------------------------------------------------------


def test_run_options_merged_partial() -> None:
    base = EngineConfig()
    opts = RunOptions(headless=False, heal_threshold=0.9)
    merged = opts.merged(base)
    assert merged.headless is False
    assert merged.heal_threshold == 0.9
    # Unchanged fields stay at default
    assert merged.default_timeout_ms == 5_000


def test_run_options_merged_no_override() -> None:
    base = EngineConfig()
    opts = RunOptions()  # all None
    merged = opts.merged(base)
    assert merged == base


def test_run_options_merged_returns_new_config() -> None:
    base = EngineConfig()
    opts = RunOptions(slow_mo_ms=200)
    merged = opts.merged(base)
    assert merged is not base  # new object
    assert base.slow_mo_ms == 0  # original unchanged


# ---------------------------------------------------------------------------
# HealingSignals / HealingCandidate / HealingReport
# ---------------------------------------------------------------------------


def test_healing_signals_defaults() -> None:
    s = HealingSignals()
    assert s.attribute == 0.0
    assert s.text == 0.0
    assert s.position == 0.0
    assert s.structure == 0.0


def test_healing_report_defaults() -> None:
    r = HealingReport(original_locator="#x")
    assert r.candidates == []
    assert r.selected_locator is None
    assert r.confidence == 0.0
    assert r.strategy_used == ""


def test_healing_report_round_trip(healed_step_result: StepResult) -> None:
    report = healed_step_result.healing
    assert report is not None
    data = report.model_dump()
    restored = HealingReport.model_validate(data)
    assert restored.selected_locator == report.selected_locator
    assert len(restored.candidates) == 1
    assert restored.candidates[0].score == pytest.approx(0.82)


# ---------------------------------------------------------------------------
# StepResult
# ---------------------------------------------------------------------------


def test_step_result_passed(passed_step_result: StepResult) -> None:
    assert passed_step_result.status == StepStatus.PASSED
    assert passed_step_result.error is None
    assert passed_step_result.healing is None
    assert passed_step_result.console_logs == []
    assert passed_step_result.network_errors == []


def test_step_result_healed_has_report(healed_step_result: StepResult) -> None:
    assert healed_step_result.status == StepStatus.HEALED
    assert healed_step_result.healing is not None
    assert healed_step_result.healing.strategy_used == "fingerprint"


# ---------------------------------------------------------------------------
# TestResult counts
# ---------------------------------------------------------------------------


def test_test_result_counts(full_test_result: TestResult) -> None:
    assert full_test_result.passed_count == 1
    assert full_test_result.healed_count == 1
    assert full_test_result.failed_count == 1


def test_test_result_round_trip(full_test_result: TestResult) -> None:
    data = full_test_result.model_dump()
    restored = TestResult.model_validate(data)
    assert restored.test_id == "t1"
    assert restored.duration_ms == 6000
    assert len(restored.steps) == 3


# ---------------------------------------------------------------------------
# export_schemas()
# ---------------------------------------------------------------------------


def test_export_schemas_creates_files() -> None:
    expected_names = {
        "EngineConfig",
        "RunOptions",
        "TestPlan",
        "Step",
        "Target",
        "ElementFingerprint",
        "BoundingBox",
        "TestResult",
        "StepResult",
        "HealingReport",
        "HealingCandidate",
        "HealingSignals",
    }
    with tempfile.TemporaryDirectory() as tmp:
        export_schemas(tmp)
        written = {p.stem for p in Path(tmp).glob("*.json")}
        assert expected_names == written


def test_export_schemas_valid_json() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        export_schemas(tmp)
        for f in Path(tmp).glob("*.json"):
            data = json.loads(f.read_text(encoding="utf-8"))
            assert isinstance(data, dict)
            assert "properties" in data or "title" in data  # valid schema structure


def test_export_schemas_title_present() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        export_schemas(tmp)
        schema = json.loads((Path(tmp) / "TestPlan.json").read_text(encoding="utf-8"))
        assert schema.get("title") in ("TestPlan",)
