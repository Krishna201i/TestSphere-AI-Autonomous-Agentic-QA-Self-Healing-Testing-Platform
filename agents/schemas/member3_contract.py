"""
TestSphere-AI — Member 1 ↔ Member 3 Contract

Formal data contracts, API surface models, and streaming serialization
helpers between Member 1 (AI Agent & Intelligence Layer) and Member 3
(Platform Backend, Dashboard, and Reporting Service).

Data Flow Overview:
──────────────────
Member 3 ───────────────── ApplicationContext / Config ─────────────► Member 1
Member 3 ◄──────────────── TestPlan / TestCases ─────────────────── Member 1
Member 3 ◄──────────────── AgentState / Status Updates ──────────── Member 1
Member 3 ◄──────────────── WorkflowEvent (SSE / WebSocket) ──────── Member 1
Member 3 ◄──────────────── FailureAnalysis Summary ──────────────── Member 1
Member 3 ◄──────────────── HealingRecommendation & Results ──────── Member 1
Member 3 ◄──────────────── RecoveryDecision & Confidence ───────── Member 1

Member 3 triggers pipeline execution via the AgentOrchestrator and
subscribes to workflow events and state snapshots for real-time
dashboard visualization, test management, and reporting.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field

from agents.analyzer.schemas import (
    FailureAnalysis,
    FailureContext,
    FailureEvidence,
    HistoricalContext,
    TestFailure,
)
from agents.healer.healing_feedback import HealingResultFeedback
from agents.healer.healing_schemas import (
    HealingContext,
    HealingRecommendation,
    ScoredCandidate,
)
from agents.orchestration.recovery_policy import (
    RecoveryAction,
    RecoveryDecision,
    RecoveryPolicyConfig,
)
from agents.orchestration.workflow_schemas import (
    AgentState,
    ExecutionResult,
    ExecutionResultStatus,
    OrchestratorConfig,
    WorkflowEvent,
    WorkflowEventType,
    WorkflowStep,
)
from agents.planner.schemas import (
    ApplicationContext,
    Assertion,
    ElementContext,
    PageContext,
    PageInfo,
    TestCase,
    TestPlan,
    TestStep,
)
from agents.schemas.enums import (
    AssertionType,
    CandidateSource,
    ChangeType,
    ConfidenceLevel,
    ExecutionStatus,
    FailureType,
    HealingAction,
    HealingDecision,
    HealingPatternType,
    HealingStatus,
    RecommendedAction,
    TestAction,
    TestCategory,
    TestPriority,
    ValidationStatus,
)

__all__ = [
    # Core orchestration & state models exposed to Member 3
    "AgentState",
    "WorkflowStep",
    "WorkflowEvent",
    "WorkflowEventType",
    "OrchestratorConfig",
    "RecoveryDecision",
    "RecoveryAction",
    "RecoveryPolicyConfig",
    # Test planning models exposed to Member 3
    "ApplicationContext",
    "TestPlan",
    "TestCase",
    "TestStep",
    "Assertion",
    # Analysis & Healing models exposed to Member 3
    "FailureAnalysis",
    "HealingRecommendation",
    "ScoredCandidate",
    "HealingResultFeedback",
    # Dashboard API View Models
    "DashboardWorkflowSummary",
    "DashboardEventMessage",
    # Helpers
    "format_sse_event",
    "format_websocket_message",
    "build_dashboard_summary",
    "MEMBER3_SAMPLE_WORKFLOW_SUMMARY_JSON",
    "MEMBER3_SAMPLE_SSE_EVENT",
]

# ---------------------------------------------------------------------------
# Member 3 Specific Dashboard Views
# ---------------------------------------------------------------------------


class DashboardWorkflowSummary(BaseModel):
    """Clean JSON-serializable summary of a pipeline run for Member 3 dashboard."""

    workflow_id: str = Field(..., description="Unique workflow run ID")
    current_step: WorkflowStep = Field(..., description="Current pipeline step")
    is_terminal: bool = Field(..., description="True if pipeline completed or aborted")
    total_test_cases: int = Field(default=0, description="Total planned test cases")
    passed_tests: int = Field(default=0, description="Number of passing tests")
    failed_tests: int = Field(default=0, description="Number of failed tests")
    healed_tests: int = Field(default=0, description="Number of successfully healed tests")
    healing_attempts: int = Field(default=0, description="Total healing attempts made")
    retry_count: int = Field(default=0, description="Total retries executed")
    latest_decision: Optional[RecoveryAction] = Field(
        default=None, description="Latest recovery policy action"
    )
    latest_failure_type: Optional[FailureType] = Field(
        default=None, description="Type of the last encountered failure"
    )
    event_count: int = Field(default=0, description="Number of events logged")
    error_message: Optional[str] = Field(
        default=None, description="Workflow error message if failed/aborted"
    )


class DashboardEventMessage(BaseModel):
    """Payload sent over SSE / WebSocket to Member 3 frontends."""

    event_type: WorkflowEventType = Field(..., description="Type of workflow event")
    timestamp: str = Field(..., description="ISO 8601 timestamp")
    workflow_id: str = Field(..., description="Associated workflow ID")
    step: WorkflowStep = Field(..., description="Pipeline step when event occurred")
    message: str = Field(default="", description="Human-readable event message")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Event payload")


# ---------------------------------------------------------------------------
# Streaming Helpers (SSE & WebSocket)
# ---------------------------------------------------------------------------


def format_sse_event(event: WorkflowEvent) -> str:
    """Format a WorkflowEvent into a standard Server-Sent Events (SSE) stream chunk.

    Parameters
    ----------
    event:
        WorkflowEvent from Member 1 orchestrator event stream.

    Returns
    -------
    str:
        SSE formatted block: "event: <type>\\ndata: <json>\\n\\n"
    """
    event_payload = {
        "event_type": event.event_type.value,
        "timestamp": event.timestamp,
        "workflow_id": event.workflow_id,
        "step": event.step.value,
        "message": event.message,
        "metadata": event.metadata,
    }
    json_str = json.dumps(event_payload)
    return f"event: {event.event_type.value}\ndata: {json_str}\n\n"


def format_websocket_message(event: WorkflowEvent) -> str:
    """Format a WorkflowEvent into a JSON string for WebSocket distribution.

    Parameters
    ----------
    event:
        WorkflowEvent instance.

    Returns
    -------
    str:
        Serialized JSON string.
    """
    event_msg = DashboardEventMessage(
        event_type=event.event_type,
        timestamp=event.timestamp,
        workflow_id=event.workflow_id,
        step=event.step,
        message=event.message,
        metadata=event.metadata,
    )
    return event_msg.model_dump_json()


def build_dashboard_summary(state: AgentState) -> DashboardWorkflowSummary:
    """Build a high-level summary suitable for Member 3 dashboard cards.

    Parameters
    ----------
    state:
        The current AgentState from the orchestrator.

    Returns
    -------
    DashboardWorkflowSummary:
        High-level metrics and current status.
    """
    passed = 0
    failed = 0
    if state.execution_result is not None:
        if state.execution_result.status == ExecutionResultStatus.SUCCESS:
            passed = 1
        elif state.execution_result.status == ExecutionResultStatus.FAILED:
            failed = 1

    latest_failure_type = None
    if state.failure_analysis:
        latest_failure_type = state.failure_analysis.failure_type

    latest_decision = None
    if state.recovery_decision:
        latest_decision = state.recovery_decision.decision

    total_tests = len(state.test_plan.test_cases) if state.test_plan else 0
    healed_count = (
        1
        if (
            state.healing_result
            and state.healing_result.status == HealingStatus.VALIDATED_SUCCESS
        )
        else 0
    )

    return DashboardWorkflowSummary(
        workflow_id=state.workflow_id,
        current_step=state.current_step,
        is_terminal=state.current_step in (WorkflowStep.COMPLETED, WorkflowStep.ABORTED),
        total_test_cases=total_tests,
        passed_tests=passed,
        failed_tests=failed,
        healed_tests=healed_count,
        healing_attempts=state.healing_attempt_count,
        retry_count=state.retry_count,
        latest_decision=latest_decision,
        latest_failure_type=latest_failure_type,
        event_count=len(state.events),
        error_message=state.error_info,
    )


# ---------------------------------------------------------------------------
# Sample Payloads Documenting Member 3 API Contracts
# ---------------------------------------------------------------------------

MEMBER3_SAMPLE_WORKFLOW_SUMMARY_JSON = """{
  "workflow_id": "wf-dashboard-001",
  "current_step": "COMPLETED",
  "is_terminal": true,
  "total_test_cases": 5,
  "passed_tests": 4,
  "failed_tests": 1,
  "healed_tests": 1,
  "healing_attempts": 1,
  "retry_count": 0,
  "latest_decision": "TRY_HEALING",
  "latest_failure_type": "SELECTOR_CHANGED",
  "event_count": 8,
  "error_message": null
}"""

MEMBER3_SAMPLE_SSE_EVENT = """event: candidate_scored
data: {"event_id": "evt-001", "event_type": "candidate_scored", "timestamp": "2026-09-18T12:00:00Z", "workflow_id": "wf-001", "step": "ranking_candidates", "data": {"candidate": "button[data-testid='login-submit']", "score": 0.95, "rank": 1}}

"""
