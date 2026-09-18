"""
TestSphere-AI — Member 1 ↔ Member 2 Contract

Formal data contracts, type definitions, and serialization helpers
between Member 1 (AI Agent & Intelligence Layer) and Member 2
(Execution Engine / Browser Automation).

Data Flow Overview:
──────────────────
Member 1 ─────────────────── TestCase / TestPlan ──────────────────► Member 2
Member 1 ◄───────────────── ExecutionResult ─────────────────────── Member 2
Member 1 ─────────────── HealingRecommendation ────────────────────► Member 2
Member 1 ◄────────────── HealingResultFeedback ──────────────────── Member 2

1. Member 1 outputs TestPlan / TestCase to Member 2 for test execution.
2. Member 2 executes tests in browser and sends back ExecutionResult.
3. On failure, Member 1 analyzes failure, scores candidates, and outputs
   HealingRecommendation (with replacement selector, confidence, rationale).
4. Member 2 attempts validation using the recommended selector in the browser
   and reports back HealingResultFeedback (with validation status).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel

from agents.analyzer.schemas import (
    FailureAnalysis,
    FailureContext,
    TestFailure,
)
from agents.healer.healing_feedback import HealingResultFeedback
from agents.healer.healing_schemas import (
    HealingContext,
    HealingRecommendation,
    ScoredCandidate,
)
from agents.orchestration.workflow_schemas import (
    ExecutionResult,
    ExecutionResultStatus,
)
from agents.planner.schemas import (
    ApplicationContext,
    Assertion,
    ElementContext,
    PageContext,
    TestCase,
    TestPlan,
    TestStep,
)
from agents.schemas.enums import (
    AssertionType,
    CandidateSource,
    ConfidenceLevel,
    ExecutionStatus,
    FailureType,
    HealingAction,
    HealingDecision,
    HealingStatus,
    RecommendedAction,
    TestAction,
    TestCategory,
    TestPriority,
    ValidationStatus,
)

__all__ = [
    # Contracts sent from Member 1 to Member 2
    "TestCase",
    "TestPlan",
    "TestStep",
    "Assertion",
    "HealingRecommendation",
    "ScoredCandidate",
    # Contracts received by Member 1 from Member 2
    "ExecutionResult",
    "ExecutionResultStatus",
    "HealingResultFeedback",
    "ValidationStatus",
    "FailureContext",
    "TestFailure",
    # Contract serialization & validation helpers
    "serialize_for_member2",
    "parse_member2_execution_result",
    "parse_member2_feedback",
    "MEMBER2_SAMPLE_EXECUTION_RESULT_JSON",
    "MEMBER2_SAMPLE_FEEDBACK_JSON",
    "MEMBER2_SAMPLE_HEALING_RECOMMENDATION_JSON",
]

# ---------------------------------------------------------------------------
# Contract Verification & Helper Utilities
# ---------------------------------------------------------------------------


def serialize_for_member2(model: BaseModel) -> str:
    """Serialize any Member 1 model to a standard JSON string for Member 2.

    Parameters
    ----------
    model:
        Pydantic model instance (TestCase, HealingRecommendation, etc.)

    Returns
    -------
    str:
        JSON string formatted with standard ISO datetime serialization.
    """
    return model.model_dump_json(indent=2)


def parse_member2_execution_result(
    payload: Union[str, Dict[str, Any]]
) -> ExecutionResult:
    """Parse and validate an ExecutionResult received from Member 2.

    Parameters
    ----------
    payload:
        JSON string or dictionary conforming to the ExecutionResult schema.

    Returns
    -------
    ExecutionResult:
        Validated Pydantic model.
    """
    if isinstance(payload, str):
        return ExecutionResult.model_validate_json(payload)
    return ExecutionResult.model_validate(payload)


def parse_member2_feedback(
    payload: Union[str, Dict[str, Any]]
) -> HealingResultFeedback:
    """Parse and validate a HealingResultFeedback received from Member 2.

    Parameters
    ----------
    payload:
        JSON string or dictionary conforming to HealingResultFeedback schema.

    Returns
    -------
    HealingResultFeedback:
        Validated Pydantic model.
    """
    if isinstance(payload, str):
        return HealingResultFeedback.model_validate_json(payload)
    return HealingResultFeedback.model_validate(payload)


# ---------------------------------------------------------------------------
# Sample JSON Payloads Documenting Inter-Member Communication
# ---------------------------------------------------------------------------

MEMBER2_SAMPLE_EXECUTION_RESULT_JSON = """{
  "workflow_id": "wf-e2e-001",
  "test_case_id": "tc-login-01",
  "status": "FAILED",
  "failure_context": {
    "test_id": "tc-login-01",
    "execution_id": "exec-001",
    "failed_step": 2,
    "action": "click",
    "target_selector": "#submit-btn",
    "error_message": "Element not found: #submit-btn",
    "current_element": {
      "element_id": "el-btn-01",
      "selector": "button[data-testid='login-submit']",
      "text": "Sign In",
      "role": "button",
      "page_url": "https://app.example.com/login",
      "attributes": {
        "class": "btn btn-primary",
        "data-testid": "login-submit"
      }
    }
  },
  "metadata": {
    "browser": "chromium",
    "duration_ms": 1240
  }
}"""

MEMBER2_SAMPLE_FEEDBACK_JSON = """{
  "test_case_id": "tc-login-01",
  "original_selector": "#submit-btn",
  "attempted_selector": "button[data-testid='login-submit']",
  "healing_status": "VALIDATED_SUCCESS",
  "validation_status": "SUCCESS",
  "confidence": 0.95,
  "execution_attempt": 1,
  "target_element_text": "Sign In",
  "error_message": null,
  "validation_time_ms": 150.0,
  "strategy_used": "historical_pattern"
}"""

MEMBER2_SAMPLE_HEALING_RECOMMENDATION_JSON = """{
  "test_id": "tc-login-01",
  "execution_id": "exec-001",
  "failed_step": 2,
  "original_selector": "#submit-btn",
  "failure_type": "SELECTOR_CHANGED",
  "confidence": "HIGH",
  "recommended_action": "TRY_REPLACEMENT_SELECTOR",
  "decision": "RECOMMEND_HEALING",
  "selected_candidate": {
    "selector": "button[data-testid='login-submit']",
    "confidence": 0.95,
    "source": "CURRENT_DOM"
  },
  "candidates": [
    {
      "selector": "button[data-testid='login-submit']",
      "confidence": 0.95,
      "source": "CURRENT_DOM"
    }
  ],
  "evidence": [
    "Exact match on data-testid attribute"
  ],
  "requires_validation": true
}"""
