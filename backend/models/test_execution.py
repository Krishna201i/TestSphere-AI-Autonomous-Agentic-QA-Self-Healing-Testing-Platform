"""
TestSphere-AI — Test execution status values.

Executions are stored as documents in the ``test_executions`` collection
(see backend/database/store.py); this module only defines their statuses.
"""

from enum import Enum


class TestExecutionStatus(str, Enum):
    """Lifecycle statuses for test execution runs."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    HEALED = "HEALED"
