"""
TestSphere-AI — In-Memory Store

Concrete ``MemoryStore`` implementation backed by Python dicts.
No external dependencies, no database, no network — suitable
for testing, development, and offline execution.

Day 8: Initial storage backend.
"""

from __future__ import annotations

from typing import Any, Optional

from agents.memory.memory_interface import MemoryStore
from agents.memory.memory_schemas import (
    ElementRecord,
    HealingRecord,
    TestExecutionRecord,
)
from agents.schemas.enums import ExecutionStatus


class InMemoryStore(MemoryStore):
    """In-memory implementation of the ``MemoryStore`` interface.

    Data is stored in plain Python dictionaries and lost when the
    process exits.  This is intentional — the in-memory backend is
    designed for tests and local development.

    Storage layout
    --------------
    - ``_executions``: ``{test_id: [TestExecutionRecord, ...]}``
    - ``_elements``: ``{element_id: [ElementRecord, ...]}``
    - ``_healing``: ``{old_selector: [HealingRecord, ...]}``
    """

    def __init__(self) -> None:
        self._executions: dict[str, list[TestExecutionRecord]] = {}
        self._elements: dict[str, list[ElementRecord]] = {}
        self._healing: dict[str, list[HealingRecord]] = {}

    # ── Execution History ─────────────────────────────────────

    def store_execution(self, record: TestExecutionRecord) -> None:
        """Store a test execution record.

        Validates that required fields are present before storing.
        """
        self._validate_execution(record)

        if record.test_id not in self._executions:
            self._executions[record.test_id] = []
        self._executions[record.test_id].append(record)

    def get_execution_history(
        self,
        test_id: str,
        *,
        limit: int = 50,
    ) -> list[TestExecutionRecord]:
        """Retrieve execution history, most recent first."""
        records = self._executions.get(test_id, [])
        # Sort by timestamp descending (newest first)
        sorted_records = sorted(records, key=lambda r: r.timestamp, reverse=True)
        return sorted_records[:limit]

    def get_latest_successful_execution(
        self,
        test_id: str,
    ) -> Optional[TestExecutionRecord]:
        """Retrieve the most recent PASSED execution for a test."""
        records = self._executions.get(test_id, [])
        passed = [r for r in records if r.status == ExecutionStatus.PASSED]
        if not passed:
            return None
        return max(passed, key=lambda r: r.timestamp)

    # ── Element History ───────────────────────────────────────

    def store_element(self, record: ElementRecord) -> None:
        """Store or append an element record."""
        self._validate_element(record)

        if record.element_id not in self._elements:
            self._elements[record.element_id] = []
        self._elements[record.element_id].append(record)

    def get_element_history(
        self,
        element_id: str,
    ) -> list[ElementRecord]:
        """Retrieve all element snapshots, most recent first."""
        records = self._elements.get(element_id, [])
        return sorted(records, key=lambda r: r.last_seen_timestamp, reverse=True)

    def get_element_by_selector(
        self,
        selector: str,
        page_url: Optional[str] = None,
    ) -> Optional[ElementRecord]:
        """Find the latest element record matching a selector."""
        candidates: list[ElementRecord] = []
        for records in self._elements.values():
            for record in records:
                if record.selector == selector:
                    if page_url is None or record.page_url == page_url:
                        candidates.append(record)
        if not candidates:
            return None
        return max(candidates, key=lambda r: r.last_seen_timestamp)

    # ── Failure History ───────────────────────────────────────

    def get_failure_history(
        self,
        test_id: str,
        *,
        limit: int = 50,
    ) -> list[TestExecutionRecord]:
        """Retrieve only FAILED / ERROR executions for a test."""
        records = self._executions.get(test_id, [])
        failures = [
            r
            for r in records
            if r.status in (ExecutionStatus.FAILED, ExecutionStatus.ERROR)
        ]
        sorted_failures = sorted(failures, key=lambda r: r.timestamp, reverse=True)
        return sorted_failures[:limit]

    # ── Healing History ───────────────────────────────────────

    def store_healing_record(self, record: HealingRecord) -> None:
        """Store a healing attempt record."""
        self._validate_healing(record)

        key = record.old_selector
        if key not in self._healing:
            self._healing[key] = []
        self._healing[key].append(record)

    def get_healing_history(
        self,
        selector: str,
        *,
        limit: int = 20,
    ) -> list[HealingRecord]:
        """Retrieve healing history for a selector, most recent first."""
        records = self._healing.get(selector, [])
        sorted_records = sorted(records, key=lambda r: r.timestamp, reverse=True)
        return sorted_records[:limit]

    # ── Aggregated Context ────────────────────────────────────

    def get_test_context(self, test_id: str) -> dict[str, Any]:
        """Return an aggregated summary of historical context for a test."""
        all_records = self._executions.get(test_id, [])
        pass_count = sum(
            1 for r in all_records if r.status == ExecutionStatus.PASSED
        )
        fail_count = sum(
            1 for r in all_records
            if r.status in (ExecutionStatus.FAILED, ExecutionStatus.ERROR)
        )
        sorted_all = sorted(all_records, key=lambda r: r.timestamp, reverse=True)
        latest_execution = sorted_all[0] if sorted_all else None
        latest_success = self.get_latest_successful_execution(test_id)
        recent_failures = self.get_failure_history(test_id, limit=5)

        return {
            "test_id": test_id,
            "execution_count": len(all_records),
            "pass_count": pass_count,
            "fail_count": fail_count,
            "latest_execution": latest_execution,
            "latest_success": latest_success,
            "recent_failures": recent_failures,
        }

    # ── Maintenance ───────────────────────────────────────────

    def clear(self) -> None:
        """Clear all stored data."""
        self._executions.clear()
        self._elements.clear()
        self._healing.clear()

    # ── Private Validation Helpers ────────────────────────────

    @staticmethod
    def _validate_execution(record: TestExecutionRecord) -> None:
        """Validate an execution record before storage."""
        if not record.execution_id or not record.execution_id.strip():
            raise ValueError("execution_id must not be empty")
        if not record.test_id or not record.test_id.strip():
            raise ValueError("test_id must not be empty")
        if not record.test_name or not record.test_name.strip():
            raise ValueError("test_name must not be empty")

    @staticmethod
    def _validate_element(record: ElementRecord) -> None:
        """Validate an element record before storage."""
        if not record.element_id or not record.element_id.strip():
            raise ValueError("element_id must not be empty")
        if not record.selector or not record.selector.strip():
            raise ValueError("selector must not be empty")

    @staticmethod
    def _validate_healing(record: HealingRecord) -> None:
        """Validate a healing record before storage."""
        if not record.healing_id or not record.healing_id.strip():
            raise ValueError("healing_id must not be empty")
        if not record.old_selector or not record.old_selector.strip():
            raise ValueError("old_selector must not be empty")
        if not record.new_selector or not record.new_selector.strip():
            raise ValueError("new_selector must not be empty")
