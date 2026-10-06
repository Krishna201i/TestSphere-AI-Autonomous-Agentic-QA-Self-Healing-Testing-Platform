"""
TestSphere-AI — Orchestration Workflow Schemas

Data contracts for the autonomous AI Agent Orchestrator.

Defines the structured state, events, and configuration for the
orchestration workflow that coordinates all intelligence components.

Day 13: Foundation implementation.
Day 14: Added RETRYING step, retry tracking, recovery decision
        tracking, and expanded configuration.

Schemas
-------
- WorkflowStep          — Explicit workflow state machine states
- WorkflowEventType     — Structured event types for audit logging
- ExecutionResult       — Structured input from the execution layer
- WorkflowEvent         — A single event in the workflow history
- AgentState            — Complete workflow state object
- OrchestratorConfig    — Configuration for orchestrator behavior
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

from agents.analyzer.schemas import FailureAnalysis, FailureContext
from agents.healer.healing_schemas import HealingRecommendation, ScoredCandidate
from agents.healer.schemas import HealingResult
from agents.planner.schemas import TestCase, TestPlan
from agents.schemas.enums import HealingAction, HealingDecision


# ── Workflow Step (State Machine States) ──────────────────────


class WorkflowStep(str, Enum):
    """Explicit states in the autonomous QA workflow.

    The orchestrator transitions between these states according
    to strict rules.  No ad-hoc or unnamed states are allowed.

    Definitions
    -----------
    PLANNING:
        Generating a test plan from ApplicationContext.
    EXECUTION_PENDING:
        Test plan generated; waiting for execution results.
    EXECUTION_SUCCESS:
        Test execution succeeded; no healing needed.
    FAILURE_DETECTED:
        Test execution failed; entering analysis flow.
    ANALYZING_FAILURE:
        Failure analysis in progress.
    GENERATING_CANDIDATES:
        Candidate replacement selectors being generated.
    RANKING_CANDIDATES:
        Candidates being scored and ranked.
    DECIDING_HEALING:
        Healing decision being made from ranked candidates.
    RETRYING:
        Transient failure detected; retrying execution (Day 14).
    HEALING_PENDING_VALIDATION:
        Healing recommendation sent to Member 2; awaiting result.
    HEALING_SUCCEEDED:
        Member 2 validated the healing as successful.
    HEALING_FAILED:
        Healing exhausted all attempts or was not possible.
    COMPLETED:
        Workflow finished (successfully or after controlled stop).
    ABORTED:
        Workflow aborted due to an unrecoverable error.
    """

    PLANNING = "PLANNING"
    EXECUTION_PENDING = "EXECUTION_PENDING"
    EXECUTION_SUCCESS = "EXECUTION_SUCCESS"
    FAILURE_DETECTED = "FAILURE_DETECTED"
    ANALYZING_FAILURE = "ANALYZING_FAILURE"
    GENERATING_CANDIDATES = "GENERATING_CANDIDATES"
    RANKING_CANDIDATES = "RANKING_CANDIDATES"
    DECIDING_HEALING = "DECIDING_HEALING"
    RETRYING = "RETRYING"
    HEALING_PENDING_VALIDATION = "HEALING_PENDING_VALIDATION"
    HEALING_SUCCEEDED = "HEALING_SUCCEEDED"
    HEALING_FAILED = "HEALING_FAILED"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


# ── Valid State Transitions ───────────────────────────────────

VALID_TRANSITIONS: dict[WorkflowStep, frozenset[WorkflowStep]] = {
    WorkflowStep.PLANNING: frozenset({
        WorkflowStep.EXECUTION_PENDING,
        WorkflowStep.ABORTED,
    }),
    WorkflowStep.EXECUTION_PENDING: frozenset({
        WorkflowStep.EXECUTION_SUCCESS,
        WorkflowStep.FAILURE_DETECTED,
    }),
    WorkflowStep.EXECUTION_SUCCESS: frozenset({
        WorkflowStep.COMPLETED,
    }),
    WorkflowStep.FAILURE_DETECTED: frozenset({
        WorkflowStep.ANALYZING_FAILURE,
    }),
    WorkflowStep.ANALYZING_FAILURE: frozenset({
        WorkflowStep.GENERATING_CANDIDATES,
        WorkflowStep.RETRYING,
        WorkflowStep.COMPLETED,
        WorkflowStep.ABORTED,
    }),
    WorkflowStep.GENERATING_CANDIDATES: frozenset({
        WorkflowStep.RANKING_CANDIDATES,
        WorkflowStep.HEALING_FAILED,
    }),
    WorkflowStep.RANKING_CANDIDATES: frozenset({
        WorkflowStep.DECIDING_HEALING,
    }),
    WorkflowStep.DECIDING_HEALING: frozenset({
        WorkflowStep.HEALING_PENDING_VALIDATION,
        WorkflowStep.COMPLETED,
        WorkflowStep.HEALING_FAILED,
        WorkflowStep.ABORTED,
    }),
    WorkflowStep.RETRYING: frozenset({
        WorkflowStep.EXECUTION_PENDING,
    }),
    WorkflowStep.HEALING_PENDING_VALIDATION: frozenset({
        WorkflowStep.HEALING_SUCCEEDED,
        WorkflowStep.HEALING_FAILED,
        # Retry with next candidate stays in HEALING_PENDING_VALIDATION
        WorkflowStep.HEALING_PENDING_VALIDATION,
        # Abort if recovery policy says stop
        WorkflowStep.ABORTED,
    }),
    WorkflowStep.HEALING_SUCCEEDED: frozenset({
        WorkflowStep.COMPLETED,
    }),
    WorkflowStep.HEALING_FAILED: frozenset({
        WorkflowStep.COMPLETED,
    }),
    # Terminal states — no further transitions
    WorkflowStep.COMPLETED: frozenset(),
    WorkflowStep.ABORTED: frozenset(),
}


# ── Workflow Event Types ──────────────────────────────────────


class WorkflowEventType(str, Enum):
    """Structured event types for workflow audit logging.

    Each event is appended to the workflow history for
    debugging and explainability of the autonomous process.
    """

    WORKFLOW_STARTED = "WORKFLOW_STARTED"
    TEST_PLAN_GENERATED = "TEST_PLAN_GENERATED"
    EXECUTION_RESULT_RECEIVED = "EXECUTION_RESULT_RECEIVED"
    FAILURE_ANALYSIS_COMPLETED = "FAILURE_ANALYSIS_COMPLETED"
    CANDIDATES_GENERATED = "CANDIDATES_GENERATED"
    CANDIDATES_RANKED = "CANDIDATES_RANKED"
    HEALING_DECISION_CREATED = "HEALING_DECISION_CREATED"
    HEALING_RECOMMENDATION_SENT = "HEALING_RECOMMENDATION_SENT"
    HEALING_RESULT_RECEIVED = "HEALING_RESULT_RECEIVED"
    HEALING_HISTORY_UPDATED = "HEALING_HISTORY_UPDATED"
    WORKFLOW_COMPLETED = "WORKFLOW_COMPLETED"
    WORKFLOW_ABORTED = "WORKFLOW_ABORTED"
    STATE_TRANSITION = "STATE_TRANSITION"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    RECOVERY_DECISION_CREATED = "RECOVERY_DECISION_CREATED"
    RETRY_INITIATED = "RETRY_INITIATED"


# ── Execution Result (from Member 2) ─────────────────────────


class ExecutionResultStatus(str, Enum):
    """Status of a test execution result from Member 2."""

    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class ExecutionResult(BaseModel):
    """Structured execution result from the execution layer.

    This is the contract for how Member 2 reports test execution
    outcomes back to the orchestrator.
    """

    workflow_id: str = Field(
        ..., min_length=1,
        description="Workflow ID this result belongs to",
    )
    test_case_id: str = Field(
        ..., min_length=1,
        description="ID of the test case that was executed",
    )
    status: ExecutionResultStatus = Field(
        ...,
        description="Execution outcome: SUCCESS or FAILED",
    )
    failure_context: Optional[FailureContext] = Field(
        default=None,
        description=(
            "Structured failure context (required when status is FAILED)"
        ),
    )

    @field_validator("failure_context")
    @classmethod
    def _validate_failure_context(
        cls, v: Optional[FailureContext], info: Any,
    ) -> Optional[FailureContext]:
        """Ensure failure_context is provided when status is FAILED."""
        # Access the status value from the data being validated
        status = info.data.get("status")
        if status == ExecutionResultStatus.FAILED and v is None:
            raise ValueError(
                "failure_context is required when status is FAILED"
            )
        return v


# ── Workflow Event ────────────────────────────────────────────


class WorkflowEvent(BaseModel):
    """A single event in the workflow audit log.

    Contains useful metadata for debugging the autonomous
    workflow and making it explainable.
    """

    workflow_id: str = Field(
        ..., min_length=1,
        description="Workflow this event belongs to",
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO 8601 timestamp of the event",
    )
    event_type: WorkflowEventType = Field(
        ...,
        description="Type of workflow event",
    )
    step: WorkflowStep = Field(
        ...,
        description="Workflow step when this event occurred",
    )
    message: str = Field(
        default="",
        description="Human-readable event description",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional structured metadata",
    )


# ── Agent State ───────────────────────────────────────────────


class AgentState(BaseModel):
    """Complete state object for the autonomous QA workflow.

    This model makes it possible to understand exactly where
    the workflow currently is, what has been attempted, and
    what the next step should be.

    All fields are strictly typed — no unstructured dictionaries
    for core workflow data.
    """

    model_config = {"arbitrary_types_allowed": True}

    # ── Identity ──────────────────────────────────────────
    workflow_id: str = Field(
        default_factory=lambda: f"wf_{uuid.uuid4().hex[:12]}",
        min_length=1,
        description="Unique workflow identifier",
    )

    # ── Test Planning ─────────────────────────────────────
    test_plan: Optional[TestPlan] = Field(
        default=None,
        description="Generated test plan (set after PLANNING)",
    )
    current_test_case: Optional[TestCase] = Field(
        default=None,
        description="Current test case being processed",
    )

    # ── Execution ─────────────────────────────────────────
    execution_result: Optional[ExecutionResult] = Field(
        default=None,
        description="Execution result from Member 2",
    )
    failure_context: Optional[FailureContext] = Field(
        default=None,
        description="Failure context extracted from execution result",
    )

    # ── Analysis ──────────────────────────────────────────
    failure_analysis: Optional[FailureAnalysis] = Field(
        default=None,
        description="Failure analysis from the Failure Analyzer",
    )

    # ── Healing Pipeline ──────────────────────────────────
    healing_candidates: list[ScoredCandidate] = Field(
        default_factory=list,
        description="Generated healing candidates (unranked)",
    )
    ranked_candidates: list[ScoredCandidate] = Field(
        default_factory=list,
        description="Candidates after scoring and ranking",
    )
    healing_decision: Optional[HealingDecision] = Field(
        default=None,
        description="Final healing decision enum value",
    )
    healing_recommendation: Optional[HealingRecommendation] = Field(
        default=None,
        description="Structured healing recommendation for Member 2",
    )
    healing_result: Optional[HealingResult] = Field(
        default=None,
        description="Most recent healing result from Member 2",
    )

    # ── Workflow Control ──────────────────────────────────
    current_step: WorkflowStep = Field(
        default=WorkflowStep.PLANNING,
        description="Current workflow state",
    )
    status: str = Field(
        default="active",
        description="High-level status: 'active', 'completed', 'aborted'",
    )

    # ── Healing Attempt Tracking ──────────────────────────
    attempted_selectors: set[str] = Field(
        default_factory=set,
        description="Set of candidate selectors already attempted (to avoid repeats)",
    )
    healing_attempt_count: int = Field(
        default=0, ge=0,
        description="Number of healing attempts made so far",
    )
    max_healing_attempts: int = Field(
        default=3, ge=1,
        description="Maximum allowed healing attempts",
    )

    # ── Retry Tracking (Day 14) ──────────────────────────
    retry_count: int = Field(
        default=0, ge=0,
        description="Number of retries attempted for transient failures",
    )
    max_retries: int = Field(
        default=2, ge=0,
        description="Maximum allowed retries for transient failures",
    )

    # ── Recovery Decision (Day 14) ────────────────────────
    recovery_decision: Optional[Any] = Field(
        default=None,
        description=(
            "Most recent RecoveryDecision from the RecoveryPolicy. "
            "Stored for explainability and debugging."
        ),
    )

    # ── Event History ─────────────────────────────────────
    events: list[WorkflowEvent] = Field(
        default_factory=list,
        description="Ordered workflow event log for debugging",
    )

    # ── Error Info ────────────────────────────────────────
    error_info: Optional[str] = Field(
        default=None,
        description="Error information if workflow encountered a problem",
    )

    # ── Timestamps ────────────────────────────────────────
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO 8601 timestamp of workflow creation",
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="ISO 8601 timestamp of last update",
    )


# ── Orchestrator Configuration ────────────────────────────────


class OrchestratorConfig(BaseModel):
    """Configuration for the AgentOrchestrator.

    Centralizes configurable parameters so they are not
    hard-coded throughout the codebase.

    Day 14: Added max_retries and min_healing_confidence.
    """

    max_healing_attempts: int = Field(
        default=3, ge=1,
        description=(
            "Maximum number of healing attempts per workflow. "
            "After this limit, healing is marked as failed."
        ),
    )
    minimum_confidence_for_healing: float = Field(
        default=0.30, ge=0.0, le=1.0,
        description=(
            "Minimum confidence threshold below which healing "
            "is not attempted. (Legacy — RecoveryPolicyConfig "
            "provides finer-grained control.)"
        ),
    )
    max_retries: int = Field(
        default=2, ge=0,
        description=(
            "Maximum retries for transient failures before "
            "escalating to further analysis."
        ),
    )
