"""TestSphere-AI — Memory subpackage.

Provides the Historical Memory and Context Management Layer.

Components
----------
- HealingMemory       — Legacy healing memory ABC (Day 1)
- MemoryStore         — Storage-independent memory interface (Day 8)
- InMemoryStore       — In-memory MemoryStore backend (Day 8)
- ContextComparator   — Element context comparison engine (Day 8)
- Memory schemas      — TestExecutionRecord, ElementRecord, etc. (Day 8)
"""

from agents.memory.context_comparator import ContextComparator
from agents.memory.healing_history import HealingMemory
from agents.memory.in_memory_store import InMemoryStore
from agents.memory.memory_interface import MemoryStore
from agents.memory.memory_schemas import (
    ContextComparisonResult,
    ElementRecord,
    FailureInfo,
    FieldChange,
    HealingRecord,
    TestExecutionRecord,
)

__all__ = [
    # Legacy (Day 1)
    "HealingMemory",
    # Day 8 — Interface and implementation
    "MemoryStore",
    "InMemoryStore",
    "ContextComparator",
    # Day 8 — Schemas
    "TestExecutionRecord",
    "FailureInfo",
    "ElementRecord",
    "HealingRecord",
    "ContextComparisonResult",
    "FieldChange",
]
