"""
TestSphere-AI — Core Data Contracts

Single-import access to all inter-member data contracts.

Usage:
    from agents.schemas.contracts import TestCase, TestFailure, HealingCandidate
"""

from agents.analyzer.schemas import (
    FailureAnalysis,
    FailureContext,
    FailureEvidence,
    HistoricalContext,
    TestFailure,
)
from agents.healer.healing_feedback import (
    HealingResultFeedback,
    HealingResultFeedbackProcessor,
)
from agents.healer.healing_schemas import (
    HealingContext,
    HealingRecommendation,
    ScoredCandidate,
)
from agents.healer.schemas import HealingCandidate, HealingResult
from agents.memory.healing_evidence import (
    HealingEvidenceRetriever,
    ReplacementStats,
    SelectorHistory,
)
from agents.memory.memory_schemas import (
    ContextComparisonResult,
    ElementRecord,
    FailureInfo,
    FieldChange,
    HealingRecord,
    TestExecutionRecord,
)
from agents.memory.pattern_detector import (
    HealingPattern,
    HealingPatternDetector,
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
    HealingPatternType,
    HealingStatus,
    RecommendedAction,
    TestAction,
    TestCategory,
    TestPriority,
    ValidationStatus,
)

__all__ = [
    # Planner contracts
    "ApplicationContext",
    "PageContext",
    "PageInfo",
    "ElementContext",
    "TestCase",
    "TestStep",
    "Assertion",
    "TestPlan",
    # Analyzer contracts
    "TestFailure",
    "FailureContext",
    "FailureEvidence",
    "HistoricalContext",
    "FailureAnalysis",
    # Healer contracts (Day 1)
    "HealingCandidate",
    "HealingResult",
    # Healer contracts (Day 10)
    "ScoredCandidate",
    "HealingRecommendation",
    "HealingContext",
    # Healer contracts (Day 12)
    "HealingResultFeedback",
    "HealingResultFeedbackProcessor",
    # Memory contracts (Day 8)
    "TestExecutionRecord",
    "FailureInfo",
    "ElementRecord",
    "HealingRecord",
    "ContextComparisonResult",
    "FieldChange",
    # Memory contracts (Day 12)
    "HealingEvidenceRetriever",
    "ReplacementStats",
    "SelectorHistory",
    "HealingPattern",
    "HealingPatternDetector",
    # Enums
    "FailureType",
    "HealingStatus",
    "HealingAction",
    "HealingPatternType",
    "CandidateSource",
    "TestCategory",
    "TestPriority",
    "TestAction",
    "AssertionType",
    "ExecutionStatus",
    "ChangeType",
    "ConfidenceLevel",
    "RecommendedAction",
    "ValidationStatus",
]
