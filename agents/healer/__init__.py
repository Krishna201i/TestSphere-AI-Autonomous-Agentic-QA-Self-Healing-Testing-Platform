"""TestSphere-AI — Self-Healing Agent subpackage.

Components
----------
- SelfHealingAgent          — Abstract healer interface (Day 1)
- HealingCandidate          — Inter-member healing proposal (Day 1)
- HealingResult             — Validated healing outcome (Day 1)
- ScoredCandidate           — Internal scored candidate (Day 10)
- HealingRecommendation     — Structured recommendation (Day 10)
- HealingContext            — Healing input context (Day 10)
- CandidateGenerator        — Candidate generation engine (Day 10)
- CandidateScorer           — Deterministic scoring engine (Day 10)
- ScoringWeights            — Configurable scoring weights (Day 10)
- HealingDecisionEngine     — Decision pipeline orchestrator (Day 10)
- ConfidenceThresholds      — Configurable thresholds (Day 10)
- LLMEvaluationResult       — LLM evaluation result (Day 11)
- LLMHealingEvaluator       — LLM-assisted evaluator (Day 11)
- HealingResultFeedback     — Member 2 feedback schema (Day 12)
- HealingResultFeedbackProcessor — Feedback processor (Day 12)
"""

from agents.healer.candidate_generator import CandidateGenerator
from agents.healer.candidate_scorer import CandidateScorer, ScoringWeights
from agents.healer.healer import SelfHealingAgent
from agents.healer.healing_decision import (
    ConfidenceThresholds,
    HealingDecisionEngine,
)
from agents.healer.healing_feedback import (
    HealingResultFeedback,
    HealingResultFeedbackProcessor,
)
from agents.healer.healing_result_mapper import (
    healing_result_to_memory_update,
    prepare_healing_result,
    recommendation_to_healing_candidate,
)
from agents.healer.healing_schemas import (
    HealingContext,
    HealingRecommendation,
    LLMEvaluationResult,
    ScoredCandidate,
)
from agents.healer.llm_healing_evaluator import LLMHealingEvaluator
from agents.healer.schemas import HealingCandidate, HealingResult

__all__ = [
    # Day 1 — Interface and inter-member contracts
    "SelfHealingAgent",
    "HealingCandidate",
    "HealingResult",
    # Day 10 — Healing Decision Layer
    "ScoredCandidate",
    "HealingRecommendation",
    "HealingContext",
    "CandidateGenerator",
    "CandidateScorer",
    "ScoringWeights",
    "HealingDecisionEngine",
    "ConfidenceThresholds",
    # Day 10 — Member 2 interface helpers
    "recommendation_to_healing_candidate",
    "healing_result_to_memory_update",
    # Day 11 — AI-assisted evaluation
    "LLMEvaluationResult",
    "LLMHealingEvaluator",
    "prepare_healing_result",
    # Day 12 — Healing feedback loop
    "HealingResultFeedback",
    "HealingResultFeedbackProcessor",
]
