"""
TestSphere-AI — Agent Observability & Execution Timeline Module

Builds a structured, human-readable execution timeline of autonomous agent decisions
from workflow events without exposing private prompts, passwords, or credentials.

Lifecycle Stages:
  1. Codebase / Target Inspection
  2. Test Planning
  3. Browser Execution
  4. Failure Detection & Diagnosis
  5. Failure Analysis
  6. Healing Proposal
  7. Browser Verification
  8. Human Review / Audit
  9. Final Test Report

Principles:
  - Transparent & explainable agent decisions.
  - Zero leakage of raw prompts, auth headers, or user passwords.
  - Computes stage durations, retries, and evidence breakdown.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from agents.orchestration.workflow_schemas import WorkflowEvent, WorkflowEventType, WorkflowStep


_SENSITIVE_KEY_PATTERNS = re.compile(r"(?:password|token|secret|auth|api_key|cookie|bearer)", re.IGNORECASE)


def sanitize_observability_data(data: Any) -> Any:
    """Recursively scrub sensitive keys and long prompt strings from observability records."""
    if isinstance(data, dict):
        clean: dict[str, Any] = {}
        for k, v in data.items():
            if _SENSITIVE_KEY_PATTERNS.search(str(k)):
                clean[k] = "[REDACTED]"
            elif isinstance(k, str) and "prompt" in k.lower():
                clean[k] = "[PROMPT_OMITTED]"
            else:
                clean[k] = sanitize_observability_data(v)
        return clean
    if isinstance(data, list):
        return [sanitize_observability_data(x) for x in data]
    if isinstance(data, str) and len(data) > 300 and ("system prompt" in data.lower() or "user instructions:" in data.lower()):
        return "[PROMPT_OMITTED]"
    return data


@dataclass
class TimelineStage:
    """A distinct stage in the autonomous QA agent decision pipeline."""

    stage_id: str
    stage_name: str
    status: str  # "success", "failed", "healed", "skipped", "in_progress"
    started_at: str
    completed_at: str | None = None
    duration_ms: float | None = None
    retry_count: int = 0
    decision_summary: str = ""
    evidence: list[str] = field(default_factory=list)
    failure_explanation: str | None = None
    model_provider: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage_id": self.stage_id,
            "stage_name": self.stage_name,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_ms": round(self.duration_ms, 2) if self.duration_ms is not None else None,
            "retry_count": self.retry_count,
            "decision_summary": self.decision_summary,
            "evidence": sanitize_observability_data(self.evidence),
            "failure_explanation": self.failure_explanation,
            "model_provider": self.model_provider,
        }


@dataclass
class AgentExecutionTimeline:
    """Structured end-to-end timeline of autonomous agent decisions."""

    workflow_id: str
    execution_id: int | str
    stages: list[TimelineStage] = field(default_factory=list)
    total_duration_ms: float = 0.0
    final_status: str = "UNKNOWN"

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "execution_id": self.execution_id,
            "stages": [s.to_dict() for s in self.stages],
            "total_duration_ms": round(self.total_duration_ms, 2),
            "final_status": self.final_status,
        }


def _parse_ts(ts_str: str | None) -> datetime | None:
    if not ts_str:
        return None
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def build_agent_timeline(
    workflow_id: str,
    execution_id: int | str,
    events: list[WorkflowEvent | dict[str, Any]],
    model_provider: str | None = None,
    final_status: str = "COMPLETED",
) -> AgentExecutionTimeline:
    """Reconstruct an explainable agent execution timeline from workflow events."""
    parsed_events: list[dict[str, Any]] = []
    for ev in events:
        if isinstance(ev, WorkflowEvent):
            parsed_events.append(ev.model_dump())
        elif isinstance(ev, dict):
            parsed_events.append(ev)

    stages_by_id: dict[str, TimelineStage] = {}
    stage_order: list[str] = []

    def get_or_create(stage_id: str, stage_name: str, started_at: str) -> TimelineStage:
        if stage_id not in stages_by_id:
            st = TimelineStage(
                stage_id=stage_id,
                stage_name=stage_name,
                status="in_progress",
                started_at=started_at,
                model_provider=model_provider,
            )
            stages_by_id[stage_id] = st
            stage_order.append(stage_id)
        return stages_by_id[stage_id]

    retry_count = 0

    for ev in parsed_events:
        ev_type = ev.get("event_type")
        step = ev.get("step")
        msg = ev.get("message", "")
        ts = ev.get("timestamp") or datetime.utcnow().isoformat()
        meta = ev.get("metadata") or {}

        # 1. Workflow Start
        if ev_type == WorkflowEventType.WORKFLOW_STARTED.value or step == WorkflowStep.PLANNING.value:
            st = get_or_create("planning", "Test Planning & Ingestion", ts)
            st.decision_summary = msg or "Test plan configured"
            if "app_url" in meta:
                st.evidence.append(f"Target application URL: {meta['app_url']}")

        # 2. Execution Pending / Running
        elif ev_type == WorkflowEventType.EXECUTION_RESULT_RECEIVED.value or step == WorkflowStep.EXECUTION_PENDING.value:
            st = get_or_create("browser_execution", "Browser Automation Execution", ts)
            if "step_count" in meta:
                st.evidence.append(f"Executed test plan with {meta['step_count']} step(s)")
            if ev_type == WorkflowEventType.EXECUTION_RESULT_RECEIVED.value:
                res_status = meta.get("result_status") or "SUCCESS"
                st.status = "success" if res_status == "SUCCESS" else "failed"
                st.completed_at = ts
                st.decision_summary = f"Execution result received: {res_status}"

        # 3. Retrying
        elif ev_type == WorkflowEventType.RETRY_INITIATED.value or step == WorkflowStep.RETRYING.value:
            retry_count += 1
            st = get_or_create("browser_execution", "Browser Automation Execution", ts)
            st.retry_count = retry_count
            st.evidence.append(f"Retry attempt {retry_count} triggered for transient recovery")

        # 4. Failure Analysis
        elif (
            ev_type == WorkflowEventType.FAILURE_ANALYSIS_COMPLETED.value
            or step in (WorkflowStep.FAILURE_DETECTED.value, WorkflowStep.ANALYZING_FAILURE.value)
        ):
            st = get_or_create("failure_analysis", "Failure Diagnosis & Classification", ts)
            if msg:
                st.decision_summary = msg
            if "failure_type" in meta:
                st.evidence.append(f"Classified failure category: {meta['failure_type']}")
            if "root_cause" in meta:
                st.failure_explanation = meta["root_cause"]
                st.evidence.append(f"Diagnosed root cause: {meta['root_cause']}")
            st.status = "completed"
            st.completed_at = ts

        # 5. Healing Proposal
        elif (
            ev_type in (WorkflowEventType.HEALING_DECISION_CREATED.value, WorkflowEventType.CANDIDATES_RANKED.value)
            or step in (WorkflowStep.GENERATING_CANDIDATES.value, WorkflowStep.RANKING_CANDIDATES.value, WorkflowStep.DECIDING_HEALING.value)
        ):
            st = get_or_create("healing_proposal", "Self-Healing Candidate Selection", ts)
            if "candidate" in meta or "healed_selector" in meta:
                cand = meta.get("healed_selector") or meta.get("candidate")
                st.evidence.append(f"Proposed replacement locator: {cand}")
            if "confidence" in meta:
                st.evidence.append(f"Candidate confidence score: {meta['confidence']}")
            if msg:
                st.decision_summary = msg
            st.status = "completed"
            st.completed_at = ts

        # 6. Browser Verification
        elif (
            ev_type == WorkflowEventType.HEALING_RESULT_RECEIVED.value
            or step in (WorkflowStep.HEALING_PENDING_VALIDATION.value, WorkflowStep.HEALING_SUCCEEDED.value, WorkflowStep.HEALING_FAILED.value)
        ):
            st = get_or_create("browser_verification", "Healing Browser Verification", ts)
            if step == WorkflowStep.HEALING_SUCCEEDED.value:
                st.status = "healed"
                st.decision_summary = "Replacement selector verified successfully in browser"
            elif step == WorkflowStep.HEALING_FAILED.value:
                st.status = "failed"
                st.decision_summary = "Healing candidate validation failed or exhausted"
            st.completed_at = ts

        # 7. Workflow Completed / Aborted
        elif ev_type in (WorkflowEventType.WORKFLOW_COMPLETED.value, WorkflowEventType.WORKFLOW_ABORTED.value):
            st = get_or_create("final_report", "Final Test Report & Audit", ts)
            st.status = "success" if ev_type == WorkflowEventType.WORKFLOW_COMPLETED.value else "failed"
            st.decision_summary = msg or ("Workflow completed" if st.status == "success" else "Workflow aborted")
            st.completed_at = ts

    # If no stages recorded (empty event log), generate basic completed stage
    if not stage_order:
        now_str = datetime.utcnow().isoformat()
        stages_by_id["execution"] = TimelineStage(
            stage_id="execution",
            stage_name="Test Execution",
            status=final_status.lower(),
            started_at=now_str,
            completed_at=now_str,
            decision_summary=f"Execution completed with status {final_status}",
        )
        stage_order.append("execution")

    # Compute durations for stages where start and completion timestamps exist
    stages_list: list[TimelineStage] = []
    total_dur_ms = 0.0

    for sid in stage_order:
        stage = stages_by_id[sid]
        start_dt = _parse_ts(stage.started_at)
        comp_dt = _parse_ts(stage.completed_at)
        if start_dt and comp_dt:
            diff_ms = max(0.0, (comp_dt - start_dt).total_seconds() * 1000.0)
            stage.duration_ms = diff_ms
            total_dur_ms += diff_ms
        stages_list.append(stage)

    return AgentExecutionTimeline(
        workflow_id=workflow_id,
        execution_id=execution_id,
        stages=stages_list,
        total_duration_ms=total_dur_ms,
        final_status=final_status,
    )
