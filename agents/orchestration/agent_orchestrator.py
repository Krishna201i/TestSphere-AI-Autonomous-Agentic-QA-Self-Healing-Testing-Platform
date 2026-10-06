"""
TestSphere-AI — AI Agent Orchestrator

Coordinates the autonomous QA workflow by connecting all existing
intelligence components through an explicit state machine.

Architecture::

    ApplicationContext
         ↓
    Test Planner → TestPlan
         ↓
    Execution Pending (Member 2 executes)
         ↓
    Execution Result
         ↓
    Failure Analyzer → FailureAnalysis
         ↓
    Candidate Generator → HealingCandidate[]
         ↓
    Candidate Scorer/Ranker → Ranked Candidates
         ↓
    Recovery Policy → RecoveryDecision  (Day 14)
         ↓
    Healing Decision Engine → HealingRecommendation
         ↓
    Member 2 Validation (browser)
         ↓
    Healing Result → Memory Feedback

Day 13: Foundation implementation.
Day 14: RecoveryPolicy integration, retry flow, explainable decisions.

IMPORTANT:
- The orchestrator coordinates, it does NOT execute browser actions.
- It does NOT replace component logic — it delegates to existing services.
- All state transitions are explicit and validated.
- The deterministic workflow works fully offline without a real LLM.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from agents.analyzer.analyzer import FailureAnalyzerAgent
from agents.analyzer.schemas import FailureContext
from agents.healer.healing_decision import HealingDecisionEngine
from agents.healer.healing_feedback import (
    HealingResultFeedback,
    HealingResultFeedbackProcessor,
)
from agents.healer.healing_schemas import HealingContext, HealingRecommendation
from agents.memory.memory_interface import MemoryStore
from agents.memory.memory_schemas import ElementRecord
from agents.orchestration.recovery_policy import (
    RecoveryAction,
    RecoveryDecision,
    RecoveryPolicy,
    RecoveryPolicyConfig,
)
from agents.orchestration.workflow_schemas import (
    VALID_TRANSITIONS,
    AgentState,
    ExecutionResult,
    ExecutionResultStatus,
    OrchestratorConfig,
    WorkflowEvent,
    WorkflowEventType,
    WorkflowStep,
)
from agents.planner.planner import TestPlannerAgent
from agents.planner.schemas import ApplicationContext, TestPlan
from agents.schemas.enums import (
    ConfidenceLevel,
    FailureType,
    HealingAction,
    HealingDecision,
    HealingStatus,
    ValidationStatus,
)

logger = logging.getLogger(__name__)


class AgentOrchestrator:
    """Coordinates the autonomous QA workflow.

    Connects existing intelligence components through an explicit
    state machine.  Each public method accepts the current state,
    delegates to the appropriate component, and returns the
    updated state with the next step.

    The orchestrator NEVER:
    - Executes browser actions
    - Invents selectors
    - Declares healing successful without Member 2 validation
    - Bypasses maximum healing attempt limits

    Parameters
    ----------
    memory_store:
        Historical memory for context retrieval and storage.
    failure_analyzer:
        Failure analysis agent (Day 9).
    healing_engine:
        Healing decision engine (Day 10/11/12).
    feedback_processor:
        Healing result feedback processor (Day 12).
    test_planner:
        Optional test planner agent (Day 5/7).
    config:
        Orchestrator configuration.
    recovery_policy:
        Optional autonomous recovery policy (Day 14).
        Created with conservative defaults if not provided.
    """

    def __init__(
        self,
        memory_store: MemoryStore,
        failure_analyzer: FailureAnalyzerAgent,
        healing_engine: HealingDecisionEngine,
        feedback_processor: HealingResultFeedbackProcessor,
        test_planner: Optional[TestPlannerAgent] = None,
        config: Optional[OrchestratorConfig] = None,
        recovery_policy: Optional[RecoveryPolicy] = None,
    ) -> None:
        self._memory = memory_store
        self._analyzer = failure_analyzer
        self._healing_engine = healing_engine
        self._feedback_processor = feedback_processor
        self._planner = test_planner
        self._config = config or OrchestratorConfig()
        if recovery_policy is not None:
            self._recovery_policy = recovery_policy
        else:
            self._recovery_policy = RecoveryPolicy(
                config=RecoveryPolicyConfig(
                    max_healing_attempts=self._config.max_healing_attempts,
                    max_retries=self._config.max_retries,
                    min_healing_confidence=self._config.minimum_confidence_for_healing,
                ),
            )

        # Active workflows indexed by workflow_id
        self._workflows: dict[str, AgentState] = {}

        logger.info(
            "AgentOrchestrator initialized — "
            "planner=%s, max_attempts=%d, recovery_policy=%s",
            test_planner is not None,
            self._config.max_healing_attempts,
            recovery_policy is not None,
        )

    # ══════════════════════════════════════════════════════════
    #  Public API
    # ══════════════════════════════════════════════════════════

    async def start_planning(
        self,
        context: ApplicationContext,
    ) -> AgentState:
        """Start a new workflow by generating a test plan.

        ApplicationContext → TestPlanner → TestPlan → EXECUTION_PENDING

        Parameters
        ----------
        context:
            Application context describing what to test.

        Returns
        -------
        AgentState
            Workflow state with test plan, ready for execution.

        Raises
        ------
        ValueError
            If no test planner is configured.
        """
        if self._planner is None:
            raise ValueError(
                "No test planner configured — "
                "cannot start planning workflow"
            )

        state = AgentState(
            current_step=WorkflowStep.PLANNING,
            max_healing_attempts=self._config.max_healing_attempts,
        )

        state = self._add_event(
            state,
            WorkflowEventType.WORKFLOW_STARTED,
            message=f"Workflow started for app '{context.app_name}'",
            metadata={"app_name": context.app_name, "app_url": context.app_url},
        )

        try:
            test_plan = await self._planner.generate_test_plan(
                context, max_tests=10,
            )
            state = state.model_copy(
                update={
                    "test_plan": test_plan,
                    "updated_at": _now(),
                },
            )

            state = self._add_event(
                state,
                WorkflowEventType.TEST_PLAN_GENERATED,
                message=(
                    f"Test plan generated with "
                    f"{len(test_plan.test_cases)} test cases"
                ),
                metadata={"test_case_count": len(test_plan.test_cases)},
            )

            state = self._transition(state, WorkflowStep.EXECUTION_PENDING)

        except Exception as exc:
            logger.error(
                "Planning failed: %s: %s", type(exc).__name__, exc,
            )
            state = state.model_copy(
                update={
                    "error_info": f"Planning failed: {exc}",
                    "status": "aborted",
                    "updated_at": _now(),
                },
            )
            state = self._transition(state, WorkflowStep.ABORTED)
            state = self._add_event(
                state,
                WorkflowEventType.WORKFLOW_ABORTED,
                message=f"Planning failed: {exc}",
            )

        self._workflows[state.workflow_id] = state
        return state

    async def submit_execution_result(
        self,
        state: AgentState,
        result: ExecutionResult,
    ) -> AgentState:
        """Process an execution result from Member 2.

        Routes to success flow or failure analysis flow.

        Parameters
        ----------
        state:
            Current workflow state (must be EXECUTION_PENDING).
        result:
            Structured execution result from the execution layer.

        Returns
        -------
        AgentState
            Updated workflow state after processing the result.

        Raises
        ------
        ValueError
            If state is not EXECUTION_PENDING or result is invalid.
        """
        # Validate current step
        if state.current_step != WorkflowStep.EXECUTION_PENDING:
            raise ValueError(
                f"Cannot submit execution result in step "
                f"'{state.current_step.value}' — "
                f"expected EXECUTION_PENDING"
            )

        # Validate workflow_id match
        if result.workflow_id != state.workflow_id:
            raise ValueError(
                f"Workflow ID mismatch: result has '{result.workflow_id}', "
                f"state has '{state.workflow_id}'"
            )

        state = state.model_copy(
            update={
                "execution_result": result,
                "updated_at": _now(),
            },
        )

        state = self._add_event(
            state,
            WorkflowEventType.EXECUTION_RESULT_RECEIVED,
            message=f"Execution result: {result.status.value}",
            metadata={
                "test_case_id": result.test_case_id,
                "status": result.status.value,
            },
        )

        if result.status == ExecutionResultStatus.SUCCESS:
            # SUCCESS → EXECUTION_SUCCESS → COMPLETED
            state = self._transition(state, WorkflowStep.EXECUTION_SUCCESS)
            state = state.model_copy(
                update={"status": "completed", "updated_at": _now()},
            )
            state = self._transition(state, WorkflowStep.COMPLETED)
            state = self._add_event(
                state,
                WorkflowEventType.WORKFLOW_COMPLETED,
                message="Test execution succeeded — no healing needed",
            )
        else:
            # FAILED → FAILURE_DETECTED → full analysis flow
            state = state.model_copy(
                update={
                    "failure_context": result.failure_context,
                    "updated_at": _now(),
                },
            )
            state = self._transition(state, WorkflowStep.FAILURE_DETECTED)
            state = await self._run_failure_flow(state)

        self._workflows[state.workflow_id] = state
        return state

    async def submit_healing_result(
        self,
        state: AgentState,
        feedback: HealingResultFeedback,
    ) -> AgentState:
        """Process a healing validation result from Member 2.

        Handles success (store + complete) or failure (retry or stop).

        Parameters
        ----------
        state:
            Current workflow state (must be HEALING_PENDING_VALIDATION).
        feedback:
            Structured healing feedback from Member 2.

        Returns
        -------
        AgentState
            Updated workflow state after processing the result.

        Raises
        ------
        ValueError
            If state is not HEALING_PENDING_VALIDATION or feedback
            is invalid.
        """
        # Validate current step
        if state.current_step != WorkflowStep.HEALING_PENDING_VALIDATION:
            raise ValueError(
                f"Cannot submit healing result in step "
                f"'{state.current_step.value}' — "
                f"expected HEALING_PENDING_VALIDATION"
            )

        state = self._add_event(
            state,
            WorkflowEventType.HEALING_RESULT_RECEIVED,
            message=(
                f"Healing result: {feedback.validation_status.value} "
                f"for selector '{feedback.attempted_selector}'"
            ),
            metadata={
                "attempted_selector": feedback.attempted_selector,
                "validation_status": feedback.validation_status.value,
                "healing_status": feedback.healing_status.value,
                "attempt": feedback.execution_attempt,
            },
        )

        # Store in memory via the feedback processor
        self._feedback_processor.process_feedback(feedback)

        state = self._add_event(
            state,
            WorkflowEventType.HEALING_HISTORY_UPDATED,
            message="Healing history updated in memory",
        )

        if feedback.validation_status == ValidationStatus.SUCCESS:
            # ── HEALED ────────────────────────────────────────
            state = state.model_copy(
                update={
                    "healing_result": _feedback_to_healing_result(feedback),
                    "status": "completed",
                    "updated_at": _now(),
                },
            )
            state = self._transition(state, WorkflowStep.HEALING_SUCCEEDED)
            state = self._transition(state, WorkflowStep.COMPLETED)
            state = self._add_event(
                state,
                WorkflowEventType.WORKFLOW_COMPLETED,
                message=(
                    f"Healing succeeded — selector "
                    f"'{feedback.attempted_selector}' validated"
                ),
            )

        elif feedback.validation_status == ValidationStatus.FAILURE:
            # ── FAILED — try next candidate or stop ───────────
            state = state.model_copy(
                update={
                    "healing_result": _feedback_to_healing_result(feedback),
                    "updated_at": _now(),
                },
            )

            # Add failed selector to attempted set
            attempted = set(state.attempted_selectors)
            attempted.add(feedback.attempted_selector)
            state = state.model_copy(
                update={"attempted_selectors": attempted},
            )

            # Check if we can try another candidate
            state = self._try_next_candidate(state)

        else:
            # ERROR / SKIPPED — treat as failure, do not retry
            state = state.model_copy(
                update={
                    "healing_result": _feedback_to_healing_result(feedback),
                    "error_info": (
                        f"Healing validation was "
                        f"{feedback.validation_status.value}"
                    ),
                    "status": "completed",
                    "updated_at": _now(),
                },
            )
            state = self._transition(state, WorkflowStep.HEALING_FAILED)
            state = self._transition(state, WorkflowStep.COMPLETED)

        self._workflows[state.workflow_id] = state
        return state

    def get_state(self, workflow_id: str) -> Optional[AgentState]:
        """Retrieve the current state for a workflow.

        Parameters
        ----------
        workflow_id:
            The workflow identifier.

        Returns
        -------
        Optional[AgentState]
            The current state, or None if not found.
        """
        return self._workflows.get(workflow_id)

    # ══════════════════════════════════════════════════════════
    #  Internal: Failure Analysis Flow
    # ══════════════════════════════════════════════════════════

    async def _run_failure_flow(self, state: AgentState) -> AgentState:
        """Execute the full failure analysis → healing pipeline.

        FAILURE_DETECTED
            → ANALYZING_FAILURE
            → GENERATING_CANDIDATES
            → RANKING_CANDIDATES
            → DECIDING_HEALING
            → HEALING_PENDING_VALIDATION / COMPLETED
        """
        # ── Step 1: Analyze failure ───────────────────────────
        state = self._transition(state, WorkflowStep.ANALYZING_FAILURE)

        if state.failure_context is None:
            state = state.model_copy(
                update={
                    "error_info": "No failure context available",
                    "status": "aborted",
                    "updated_at": _now(),
                },
            )
            state = self._transition(state, WorkflowStep.ABORTED)
            return state

        analysis = await self._analyzer.analyze(state.failure_context)
        state = state.model_copy(
            update={
                "failure_analysis": analysis,
                "updated_at": _now(),
            },
        )

        state = self._add_event(
            state,
            WorkflowEventType.FAILURE_ANALYSIS_COMPLETED,
            message=(
                f"Failure analyzed: {analysis.failure_type.value}, "
                f"confidence={analysis.confidence.value}"
            ),
            metadata={
                "failure_type": analysis.failure_type.value,
                "confidence": analysis.confidence.value,
                "recommended_action": analysis.recommended_action.value,
            },
        )

        # ── Step 2: Pre-candidate feasibility check (Day 14) ────
        # Check if the failure type is healable, retryable, or if
        # max healing attempts have been reached — BEFORE generating
        # candidates.  This avoids wasting effort on non-healable failures.

        # Rule 1: Max healing attempts → ABORT
        if state.healing_attempt_count >= self._config.max_healing_attempts:
            abort_decision = RecoveryDecision(
                workflow_id=state.workflow_id,
                test_case_id=(
                    state.current_test_case.test_id
                    if state.current_test_case else "unknown"
                ),
                failure_type=analysis.failure_type,
                decision=RecoveryAction.ABORT,
                confidence=1.0,
                reason=(
                    f"Maximum healing attempts "
                    f"({self._config.max_healing_attempts}) reached."
                ),
                evidence=[f"Healing attempts: {state.healing_attempt_count}"],
                attempt_number=state.healing_attempt_count,
                requires_validation=False,
                next_state="ABORTED",
            )
            state = state.model_copy(
                update={
                    "recovery_decision": abort_decision,
                    "status": "aborted",
                    "updated_at": _now(),
                },
            )
            state = self._add_event(
                state,
                WorkflowEventType.RECOVERY_DECISION_CREATED,
                message=f"Recovery decision: ABORT — {abort_decision.reason}",
                metadata={
                    "decision": "ABORT",
                    "evidence": abort_decision.evidence,
                },
            )
            state = self._transition(state, WorkflowStep.ABORTED)
            return state

        # Rule 2: Retryable failure → RETRY (if under retry limit)
        ft_policy = self._recovery_policy.get_failure_policy(
            analysis.failure_type
        )
        if (
            ft_policy.retryable
            and self._recovery_policy.config.allow_retry
            and state.retry_count < min(
                ft_policy.max_retries,
                self._recovery_policy.config.max_retries,
            )
        ):
            retry_decision = RecoveryDecision(
                workflow_id=state.workflow_id,
                test_case_id=(
                    state.current_test_case.test_id
                    if state.current_test_case else "unknown"
                ),
                failure_type=analysis.failure_type,
                decision=RecoveryAction.RETRY,
                confidence=0.9,
                reason=(
                    f"Transient failure ({analysis.failure_type.value}). "
                    f"Retrying ({state.retry_count + 1})."
                ),
                evidence=[
                    f"Failure type: {analysis.failure_type.value}",
                    f"Retry count: {state.retry_count}",
                ],
                retry_count=state.retry_count,
                requires_validation=False,
                next_state="RETRYING",
            )
            state = state.model_copy(
                update={
                    "recovery_decision": retry_decision,
                    "retry_count": state.retry_count + 1,
                    "updated_at": _now(),
                },
            )
            state = self._add_event(
                state,
                WorkflowEventType.RECOVERY_DECISION_CREATED,
                message=(
                    f"Recovery decision: RETRY — {retry_decision.reason}"
                ),
                metadata={
                    "decision": "RETRY",
                    "retry_count": state.retry_count,
                    "evidence": retry_decision.evidence,
                },
            )
            state = self._transition(state, WorkflowStep.RETRYING)
            state = self._add_event(
                state,
                WorkflowEventType.RETRY_INITIATED,
                message=(
                    f"Retry #{state.retry_count} initiated for "
                    f"transient failure ({analysis.failure_type.value})"
                ),
            )
            state = self._transition(state, WorkflowStep.EXECUTION_PENDING)
            return state

        # Rule 3: Non-healable failure type → DO_NOT_HEAL or escalate
        if not ft_policy.healable:
            # For retryable types whose retries are exhausted
            if ft_policy.retryable:
                noheal_decision = RecoveryDecision(
                    workflow_id=state.workflow_id,
                    failure_type=analysis.failure_type,
                    decision=RecoveryAction.REQUIRE_FURTHER_ANALYSIS,
                    confidence=0.7,
                    reason=(
                        f"Retries exhausted for {analysis.failure_type.value}. "
                        f"Require further analysis."
                    ),
                    evidence=[
                        f"Failure type: {analysis.failure_type.value}",
                        f"Retry count: {state.retry_count}",
                    ],
                    requires_validation=False,
                    next_state="COMPLETED",
                )
            else:
                noheal_decision = RecoveryDecision(
                    workflow_id=state.workflow_id,
                    failure_type=analysis.failure_type,
                    decision=RecoveryAction.DO_NOT_HEAL,
                    confidence=1.0,
                    reason=(
                        f"Failure type {analysis.failure_type.value} does "
                        f"not support automatic healing."
                    ),
                    evidence=[
                        f"Failure type: {analysis.failure_type.value}",
                    ],
                    requires_validation=False,
                    next_state="COMPLETED",
                )

            state = state.model_copy(
                update={
                    "recovery_decision": noheal_decision,
                    "status": "completed",
                    "updated_at": _now(),
                },
            )
            state = self._add_event(
                state,
                WorkflowEventType.RECOVERY_DECISION_CREATED,
                message=(
                    f"Recovery decision: {noheal_decision.decision.value} — "
                    f"{noheal_decision.reason}"
                ),
                metadata={
                    "decision": noheal_decision.decision.value,
                    "evidence": noheal_decision.evidence,
                },
            )
            state = self._transition(state, WorkflowStep.COMPLETED)
            state = self._add_event(
                state,
                WorkflowEventType.WORKFLOW_COMPLETED,
                message=(
                    f"Healing not attempted — "
                    f"type={analysis.failure_type.value}, "
                    f"decision={noheal_decision.decision.value}"
                ),
            )
            return state

        # ── Step 3: Generate candidates ───────────────────────
        state = self._transition(state, WorkflowStep.GENERATING_CANDIDATES)

        healing_context = HealingContext(
            failure_analysis=analysis,
            current_elements=self._get_current_elements(state),
            page_url=state.failure_context.current_page_url if state.failure_context else None,
            page_title=state.failure_context.current_page_title if state.failure_context else None,
        )

        # The HealingDecisionEngine handles the full pipeline:
        # generation → enrichment → scoring → ranking → decision
        recommendation = await self._healing_engine.generate_recommendation(
            healing_context,
        )

        state = state.model_copy(
            update={
                "healing_candidates": list(recommendation.candidates),
                "ranked_candidates": list(recommendation.candidates),
                "updated_at": _now(),
            },
        )

        state = self._add_event(
            state,
            WorkflowEventType.CANDIDATES_GENERATED,
            message=f"Generated {len(recommendation.candidates)} candidates",
            metadata={"candidate_count": len(recommendation.candidates)},
        )

        # ── Step 4: Ranking (done by engine) ──────────────────
        state = self._transition(state, WorkflowStep.RANKING_CANDIDATES)

        state = self._add_event(
            state,
            WorkflowEventType.CANDIDATES_RANKED,
            message=(
                f"Candidates ranked — "
                f"top: {recommendation.candidates[0].selector if recommendation.candidates else 'none'}"
            ),
        )

        # ── Step 5: Recovery Policy Decision (Day 14) ─────────
        state = self._transition(state, WorkflowStep.DECIDING_HEALING)

        recovery_decision = self._recovery_policy.evaluate(
            failure_analysis=analysis,
            ranked_candidates=list(recommendation.candidates),
            healing_attempt_count=state.healing_attempt_count,
            retry_count=state.retry_count,
            attempted_selectors=state.attempted_selectors,
            workflow_id=state.workflow_id,
            test_case_id=(
                state.current_test_case.test_id
                if state.current_test_case else "unknown"
            ),
        )

        state = state.model_copy(
            update={
                "recovery_decision": recovery_decision,
                "healing_decision": recommendation.decision,
                "healing_recommendation": recommendation,
                "updated_at": _now(),
            },
        )

        state = self._add_event(
            state,
            WorkflowEventType.RECOVERY_DECISION_CREATED,
            message=(
                f"Recovery decision: {recovery_decision.decision.value} — "
                f"{recovery_decision.reason}"
            ),
            metadata={
                "decision": recovery_decision.decision.value,
                "confidence": recovery_decision.confidence,
                "selected_candidate": (
                    recovery_decision.selected_candidate.selector
                    if recovery_decision.selected_candidate
                    else None
                ),
                "evidence": recovery_decision.evidence,
            },
        )

        # Backward compatibility: emit HEALING_DECISION_CREATED
        state = self._add_event(
            state,
            WorkflowEventType.HEALING_DECISION_CREATED,
            message=(
                f"Decision: {recommendation.decision.value}, "
                f"action: {recommendation.recommended_action.value}"
            ),
            metadata={
                "decision": recommendation.decision.value,
                "action": recommendation.recommended_action.value,
                "confidence": recommendation.confidence.value,
            },
        )

        # ── Step 6: Route based on RecoveryDecision ───────────
        if recovery_decision.decision == RecoveryAction.TRY_HEALING:
            candidate = recovery_decision.selected_candidate
            if candidate is not None:
                # Track the attempt
                attempted = set(state.attempted_selectors)
                attempted.add(candidate.selector)
                state = state.model_copy(
                    update={
                        "attempted_selectors": attempted,
                        "healing_attempt_count": state.healing_attempt_count + 1,
                        "updated_at": _now(),
                    },
                )

                # Update the recommendation's selected candidate
                if state.healing_recommendation is not None:
                    updated_rec = state.healing_recommendation.model_copy(
                        update={"selected_candidate": candidate},
                    )
                    state = state.model_copy(
                        update={"healing_recommendation": updated_rec},
                    )

                state = self._transition(
                    state, WorkflowStep.HEALING_PENDING_VALIDATION,
                )
                state = self._add_event(
                    state,
                    WorkflowEventType.HEALING_RECOMMENDATION_SENT,
                    message=(
                        f"Recommendation sent to Member 2: "
                        f"'{candidate.selector}' "
                        f"(attempt {state.healing_attempt_count})"
                    ),
                    metadata={
                        "selector": candidate.selector,
                        "confidence": candidate.confidence,
                        "attempt": state.healing_attempt_count,
                    },
                )
            else:
                # No selected candidate despite TRY action — treat as failed
                state = self._transition(state, WorkflowStep.HEALING_FAILED)
                state = state.model_copy(
                    update={"status": "completed", "updated_at": _now()},
                )
                state = self._transition(state, WorkflowStep.COMPLETED)

        elif recovery_decision.decision == RecoveryAction.ABORT:
            state = state.model_copy(
                update={"status": "aborted", "updated_at": _now()},
            )
            state = self._transition(state, WorkflowStep.ABORTED)
            state = self._add_event(
                state,
                WorkflowEventType.WORKFLOW_ABORTED,
                message=(
                    f"Workflow aborted — {recovery_decision.reason}"
                ),
            )

        elif recovery_decision.decision == RecoveryAction.DO_NOT_HEAL:
            state = state.model_copy(
                update={"status": "completed", "updated_at": _now()},
            )
            state = self._transition(state, WorkflowStep.COMPLETED)
            state = self._add_event(
                state,
                WorkflowEventType.WORKFLOW_COMPLETED,
                message="Healing not recommended — DO_NOT_HEAL",
            )

        else:
            # REQUIRE_FURTHER_ANALYSIS / RETRY (post-candidates)
            state = state.model_copy(
                update={"status": "completed", "updated_at": _now()},
            )
            state = self._transition(state, WorkflowStep.COMPLETED)
            state = self._add_event(
                state,
                WorkflowEventType.WORKFLOW_COMPLETED,
                message=(
                    f"Workflow completed — "
                    f"decision: {recovery_decision.decision.value}"
                ),
            )

        return state

    # ══════════════════════════════════════════════════════════
    #  Internal: Try Next Candidate (Retry Logic)
    # ══════════════════════════════════════════════════════════

    def _try_next_candidate(self, state: AgentState) -> AgentState:
        """Try the next ranked candidate, or stop if exhausted.

        Uses the RecoveryPolicy (Day 14) to decide whether to
        continue healing with the next candidate.

        Rules (enforced by RecoveryPolicy):
        1. healing_attempt_count must be < max_healing_attempts
        2. The candidate must not have been attempted before
        3. Candidate must meet minimum confidence threshold
        4. If no eligible candidate exists → ABORT
        """
        # Delegate continuation decision to RecoveryPolicy
        continuation = self._recovery_policy.evaluate_continuation(
            failure_analysis=state.failure_analysis,
            ranked_candidates=list(state.ranked_candidates),
            healing_attempt_count=state.healing_attempt_count,
            attempted_selectors=set(state.attempted_selectors),
            workflow_id=state.workflow_id,
            test_case_id=(
                state.current_test_case.test_id
                if state.current_test_case else "unknown"
            ),
        )

        state = state.model_copy(
            update={
                "recovery_decision": continuation,
                "updated_at": _now(),
            },
        )

        state = self._add_event(
            state,
            WorkflowEventType.RECOVERY_DECISION_CREATED,
            message=(
                f"Continuation decision: {continuation.decision.value} — "
                f"{continuation.reason}"
            ),
            metadata={
                "decision": continuation.decision.value,
                "evidence": continuation.evidence,
            },
        )

        if continuation.decision == RecoveryAction.TRY_HEALING:
            next_candidate = continuation.selected_candidate
            if next_candidate is not None:
                attempted = set(state.attempted_selectors)
                attempted.add(next_candidate.selector)
                state = state.model_copy(
                    update={
                        "attempted_selectors": attempted,
                        "healing_attempt_count": state.healing_attempt_count + 1,
                        "updated_at": _now(),
                    },
                )

                # Update the recommendation with the new selected candidate
                if state.healing_recommendation is not None:
                    updated_rec = state.healing_recommendation.model_copy(
                        update={"selected_candidate": next_candidate},
                    )
                    state = state.model_copy(
                        update={"healing_recommendation": updated_rec},
                    )

                # Stay in HEALING_PENDING_VALIDATION (valid self-transition)
                state = self._transition(
                    state, WorkflowStep.HEALING_PENDING_VALIDATION,
                )

                state = self._add_event(
                    state,
                    WorkflowEventType.HEALING_RECOMMENDATION_SENT,
                    message=(
                        f"Retry: recommendation sent to Member 2: "
                        f"'{next_candidate.selector}' "
                        f"(attempt {state.healing_attempt_count})"
                    ),
                    metadata={
                        "selector": next_candidate.selector,
                        "confidence": next_candidate.confidence,
                        "attempt": state.healing_attempt_count,
                    },
                )
            else:
                # Should not happen, but handle gracefully
                state = state.model_copy(
                    update={"status": "completed", "updated_at": _now()},
                )
                state = self._transition(state, WorkflowStep.HEALING_FAILED)
                state = self._transition(state, WorkflowStep.COMPLETED)
        else:
            state = state.model_copy(
                update={"status": "completed", "updated_at": _now()},
            )
            state = self._transition(state, WorkflowStep.HEALING_FAILED)
            state = self._transition(state, WorkflowStep.COMPLETED)
            state = self._add_event(
                state,
                WorkflowEventType.WORKFLOW_COMPLETED,
                message=(
                    f"Healing stopped — {continuation.reason}"
                ),
            )

        return state

    # ══════════════════════════════════════════════════════════
    #  Internal: Helpers
    # ══════════════════════════════════════════════════════════

    def _should_attempt_healing(
        self, analysis: "FailureAnalysis",
    ) -> bool:
        """Determine if healing should be attempted for this analysis.

        Legacy method retained for backward compatibility.
        Day 14: RecoveryPolicy is now the primary decision maker.

        Healing is NOT attempted when:
        - Failure type is UNKNOWN with LOW confidence
        - Failure type is ASSERTION_FAILURE
        - Failure type is NETWORK_ERROR
        - Failure type is APPLICATION_ERROR
        """
        non_healable = {
            FailureType.ASSERTION_FAILURE,
            FailureType.NETWORK_ERROR,
            FailureType.APPLICATION_ERROR,
        }
        if analysis.failure_type in non_healable:
            return False

        if (
            analysis.failure_type == FailureType.UNKNOWN
            and analysis.confidence == ConfidenceLevel.LOW
        ):
            return False

        return True

    def _get_current_elements(
        self, state: AgentState,
    ) -> list[ElementRecord]:
        """Extract current UI elements from the failure context.

        Returns an empty list if no current element is available.
        """
        elements: list[ElementRecord] = []
        if (
            state.failure_context is not None
            and state.failure_context.current_element is not None
        ):
            elements.append(state.failure_context.current_element)
        return elements

    # ══════════════════════════════════════════════════════════
    #  Internal: State Machine
    # ══════════════════════════════════════════════════════════

    @staticmethod
    def _transition(
        state: AgentState,
        target: WorkflowStep,
    ) -> AgentState:
        """Transition the workflow to a new step.

        Validates the transition against the explicit state machine.

        Parameters
        ----------
        state:
            Current workflow state.
        target:
            Target workflow step.

        Returns
        -------
        AgentState
            Updated state with the new step.

        Raises
        ------
        ValueError
            If the transition is invalid.
        """
        allowed = VALID_TRANSITIONS.get(state.current_step, frozenset())
        if target not in allowed:
            raise ValueError(
                f"Invalid state transition: "
                f"{state.current_step.value} → {target.value}. "
                f"Allowed: {[s.value for s in allowed]}"
            )

        return state.model_copy(
            update={
                "current_step": target,
                "updated_at": _now(),
            },
        )

    @staticmethod
    def _add_event(
        state: AgentState,
        event_type: WorkflowEventType,
        message: str = "",
        metadata: Optional[dict] = None,
    ) -> AgentState:
        """Append a structured event to the workflow history.

        Parameters
        ----------
        state:
            Current workflow state.
        event_type:
            Type of event to record.
        message:
            Human-readable event description.
        metadata:
            Optional structured metadata.

        Returns
        -------
        AgentState
            Updated state with the new event appended.
        """
        event = WorkflowEvent(
            workflow_id=state.workflow_id,
            event_type=event_type,
            step=state.current_step,
            message=message,
            metadata=metadata or {},
        )

        updated_events = list(state.events) + [event]
        return state.model_copy(
            update={"events": updated_events},
        )


# ── Module-level Helpers ──────────────────────────────────────


def _now() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _feedback_to_healing_result(
    feedback: HealingResultFeedback,
) -> "HealingResult":
    """Convert a HealingResultFeedback to a HealingResult."""
    from agents.healer.schemas import HealingResult

    return HealingResult(
        test_id=feedback.test_case_id,
        failed_step=1,
        old_selector=feedback.original_selector,
        new_selector=feedback.attempted_selector,
        status=feedback.healing_status,
        confidence=feedback.confidence,
        validated_by="execution_engine",
        validation_error=feedback.error_reason,
    )
