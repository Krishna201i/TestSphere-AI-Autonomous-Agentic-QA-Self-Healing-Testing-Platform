"""
TestSphere-AI — Core Data Contracts

Single-import access to all inter-member data contracts.

Usage:
    from agents.schemas.contracts import TestCase, TestFailure, HealingCandidate
"""

from agents.analyzer.schemas import FailureAnalysis, TestFailure
from agents.healer.schemas import HealingCandidate, HealingResult
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
    FailureType,
    HealingStatus,
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
    "FailureAnalysis",
    # Healer contracts
    "HealingCandidate",
    "HealingResult",
    # Enums
    "FailureType",
    "HealingStatus",
    "TestCategory",
    "TestPriority",
    "TestAction",
    "AssertionType",
]
