"""
Tests for agents/orchestration/timeline.py (Agent Observability & Execution Timeline).
"""

from __future__ import annotations

from agents.orchestration.timeline import (
    AgentExecutionTimeline,
    TimelineStage,
    build_agent_timeline,
    sanitize_observability_data,
)
from agents.orchestration.workflow_schemas import (
    WorkflowEvent,
    WorkflowEventType,
    WorkflowStep,
)


def test_sanitize_observability_data_strips_credentials():
    raw = {
        "user": "alice",
        "password": "super-secret-password-123",
        "api_key": "ts_live_abcdef123456",
        "bearer_token": "bearer eyJhbGciOi...",
        "steps": [
            {"action": "fill", "target": "#password", "password": "hidden-pass"},
            {"action": "click", "target": "#submit"},
        ],
    }
    clean = sanitize_observability_data(raw)

    assert clean["user"] == "alice"
    assert clean["password"] == "[REDACTED]"
    assert clean["api_key"] == "[REDACTED]"
    assert clean["bearer_token"] == "[REDACTED]"
    assert clean["steps"][0]["password"] == "[REDACTED]"


def test_build_agent_timeline_for_successful_run():
    events = [
        WorkflowEvent(
            workflow_id="wf-1",
            timestamp="2026-11-23T10:00:00Z",
            event_type=WorkflowEventType.WORKFLOW_STARTED,
            step=WorkflowStep.PLANNING,
            message="Planning workflow initiated",
            metadata={"app_url": "https://shop.local"},
        ),
        WorkflowEvent(
            workflow_id="wf-1",
            timestamp="2026-11-23T10:00:01Z",
            event_type=WorkflowEventType.EXECUTION_RESULT_RECEIVED,
            step=WorkflowStep.EXECUTION_PENDING,
            message="Test executed",
            metadata={"step_count": 3, "result_status": "SUCCESS"},
        ),
        WorkflowEvent(
            workflow_id="wf-1",
            timestamp="2026-11-23T10:00:02Z",
            event_type=WorkflowEventType.WORKFLOW_COMPLETED,
            step=WorkflowStep.COMPLETED,
            message="Run completed successfully",
        ),
    ]

    timeline = build_agent_timeline(
        workflow_id="wf-1",
        execution_id=101,
        events=events,
        model_provider="mock",
        final_status="PASSED",
    )

    assert timeline.workflow_id == "wf-1"
    assert timeline.execution_id == 101
    assert timeline.final_status == "PASSED"
    assert len(timeline.stages) >= 2

    stage_ids = [s.stage_id for s in timeline.stages]
    assert "planning" in stage_ids
    assert "browser_execution" in stage_ids

    d = timeline.to_dict()
    assert d["workflow_id"] == "wf-1"
    assert isinstance(d["stages"], list)
    assert d["stages"][0]["stage_id"] == "planning"


def test_build_agent_timeline_for_healing_run():
    events = [
        WorkflowEvent(
            workflow_id="wf-heal",
            timestamp="2026-11-23T10:00:00Z",
            event_type=WorkflowEventType.WORKFLOW_STARTED,
            step=WorkflowStep.PLANNING,
            message="Autonomous QA started",
        ),
        WorkflowEvent(
            workflow_id="wf-heal",
            timestamp="2026-11-23T10:00:01Z",
            event_type=WorkflowEventType.EXECUTION_RESULT_RECEIVED,
            step=WorkflowStep.EXECUTION_PENDING,
            message="Execution failed on step 2",
            metadata={"result_status": "FAILED"},
        ),
        WorkflowEvent(
            workflow_id="wf-heal",
            timestamp="2026-11-23T10:00:02Z",
            event_type=WorkflowEventType.FAILURE_ANALYSIS_COMPLETED,
            step=WorkflowStep.ANALYZING_FAILURE,
            message="Diagnosed missing locator",
            metadata={"failure_type": "SELECTOR_CHANGED", "root_cause": "Button was renamed in checkout DOM"},
        ),
        WorkflowEvent(
            workflow_id="wf-heal",
            timestamp="2026-11-23T10:00:03Z",
            event_type=WorkflowEventType.HEALING_DECISION_CREATED,
            step=WorkflowStep.DECIDING_HEALING,
            message="Proposed replacement selector",
            metadata={"healed_selector": "button[data-testid='pay']", "confidence": 0.88},
        ),
        WorkflowEvent(
            workflow_id="wf-heal",
            timestamp="2026-11-23T10:00:04Z",
            event_type=WorkflowEventType.HEALING_RESULT_RECEIVED,
            step=WorkflowStep.HEALING_SUCCEEDED,
            message="Browser verification succeeded",
        ),
    ]

    timeline = build_agent_timeline(
        workflow_id="wf-heal",
        execution_id=202,
        events=events,
        model_provider="mock",
        final_status="HEALED",
    )

    stage_ids = [s.stage_id for s in timeline.stages]
    assert "failure_analysis" in stage_ids
    assert "healing_proposal" in stage_ids
    assert "browser_verification" in stage_ids

    heal_stage = next(s for s in timeline.stages if s.stage_id == "healing_proposal")
    assert any("button[data-testid='pay']" in ev for ev in heal_stage.evidence)
    assert any("0.88" in ev for ev in heal_stage.evidence)

    verif_stage = next(s for s in timeline.stages if s.stage_id == "browser_verification")
    assert verif_stage.status == "healed"


def test_empty_events_timeline_fallback():
    timeline = build_agent_timeline(
        workflow_id="wf-empty",
        execution_id=303,
        events=[],
        final_status="PASSED",
    )
    assert timeline.workflow_id == "wf-empty"
    assert len(timeline.stages) == 1
    assert timeline.stages[0].stage_id == "execution"
    assert timeline.stages[0].status == "passed"
