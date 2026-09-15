"""TestSphere-AI — Agent Orchestration subpackage.

Components
----------
- AgentController      — Abstract orchestration interface (Day 1)
- AgentOrchestrator    — Autonomous workflow orchestrator (Day 13)
- AgentState           — Workflow state object (Day 13)
- WorkflowStep         — Explicit workflow state machine (Day 13)
- ExecutionResult      — Structured execution result (Day 13)
- WorkflowEvent        — Audit log event (Day 13)
- OrchestratorConfig   — Orchestrator configuration (Day 13)
"""

from agents.orchestration.agent_controller import AgentController
from agents.orchestration.agent_orchestrator import AgentOrchestrator
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

__all__ = [
    # Day 1
    "AgentController",
    # Day 13 — Orchestrator
    "AgentOrchestrator",
    # Day 13 — Schemas
    "AgentState",
    "WorkflowStep",
    "WorkflowEventType",
    "ExecutionResult",
    "ExecutionResultStatus",
    "WorkflowEvent",
    "OrchestratorConfig",
    "VALID_TRANSITIONS",
]
