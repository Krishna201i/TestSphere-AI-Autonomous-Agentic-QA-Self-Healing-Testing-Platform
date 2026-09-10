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
from agents.healer.schemas import HealingCandidate, HealingResult
from agents.memory.memory_schemas import (
    ContextComparisonResult,
    ElementRecord,
    FailureInfo,
    FieldChange,
    HealingRecord,
    TestExecutionRecord,
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
    ChangeType,
    ConfidenceLevel,
    ExecutionStatus,
    FailureType,
    HealingStatus,
    RecommendedAction,
    TestAction,
    TestCategory,
    TestPriority,
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
    # Healer contracts
    "HealingCandidate",
    "HealingResult",
    # Memory contracts (Day 8)
    "TestExecutionRecord",
    "FailureInfo",
    "ElementRecord",
    "HealingRecord",
    "ContextComparisonResult",
    "FieldChange",
    # Enums
    "FailureType",
    "HealingStatus",
    "TestCategory",
    "TestPriority",
    "TestAction",
    "AssertionType",
    "ExecutionStatus",
    "ChangeType",
    "ConfidenceLevel",
    "RecommendedAction",
]
