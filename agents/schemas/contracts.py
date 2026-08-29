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
    PageInfo,
    TestCase,
    TestStep,
)
from agents.schemas.enums import (
    FailureType,
    HealingStatus,
    TestCategory,
    TestPriority,
)

__all__ = [
    # Planner contracts
    "ApplicationContext",
    "PageInfo",
    "TestCase",
    "TestStep",
    "Assertion",
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
]
