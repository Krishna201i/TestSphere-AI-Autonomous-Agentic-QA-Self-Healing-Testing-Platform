"""
TestSphere-AI — Memory Store Interface

Abstract base class defining the storage-independent API for the
Historical Memory and Context Management Layer.

Any storage backend (in-memory, SQLite, PostgreSQL, vector DB)
must implement this interface.  The rest of the system programs
against this ABC, never against a concrete backend.

Day 8: Foundation interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from agents.memory.memory_schemas import (
    ElementRecord,
    HealingRecord,
    TestExecutionRecord,
)


class MemoryStore(ABC):
    """Abstract Memory Store interface.

    Defines all operations that the Historical Memory layer
    exposes to the rest of TestSphere-AI.  Concrete implementations
    handle persistence details.

    Design Principles
    -----------------
    - Storage-independent: no assumptions about backend
    - Validate before storing: reject invalid data
    - Return newest-first: most-recent records first
    - Fail gracefully: unknown IDs return empty results, not errors
    """

    # ── Execution History ─────────────────────────────────────

    @abstractmethod
    def store_execution(self, record: TestExecutionRecord) -> None:
        """Store a test execution record.

        Parameters
        ----------
        record:
            A validated ``TestExecutionRecord`` to persist.

        Raises
        ------
        ValueError
            If the record fails validation.
        """
        ...

    @abstractmethod
    def get_execution_history(
        self,
        test_id: str,
        *,
        limit: int = 50,
    ) -> list[TestExecutionRecord]:
        """Retrieve execution history for a test, most recent first.

        Parameters
        ----------
        test_id:
            The test case ID to look up.
        limit:
            Maximum number of records to return.

        Returns
        -------
        list[TestExecutionRecord]
            Execution records, newest first.  Empty if unknown test.
        """
        ...

    @abstractmethod
    def get_latest_successful_execution(
        self,
        test_id: str,
    ) -> Optional[TestExecutionRecord]:
        """Retrieve the most recent successful execution for a test.

        Parameters
        ----------
        test_id:
            The test case ID to look up.

        Returns
        -------
        Optional[TestExecutionRecord]
            The latest ``PASSED`` execution, or ``None`` if none exists.
        """
        ...

    # ── Element History ───────────────────────────────────────

    @abstractmethod
    def store_element(self, record: ElementRecord) -> None:
        """Store or update an element record.

        If an element with the same ``element_id`` already exists,
        the record is updated (new version appended).

        Parameters
        ----------
        record:
            A validated ``ElementRecord`` to persist.

        Raises
        ------
        ValueError
            If the record fails validation.
        """
        ...

    @abstractmethod
    def get_element_history(
        self,
        element_id: str,
    ) -> list[ElementRecord]:
        """Retrieve all recorded states of an element, most recent first.

        Parameters
        ----------
        element_id:
            The element identifier to look up.

        Returns
        -------
        list[ElementRecord]
            Element snapshots, newest first.  Empty if unknown.
        """
        ...

    @abstractmethod
    def get_element_by_selector(
        self,
        selector: str,
        page_url: Optional[str] = None,
    ) -> Optional[ElementRecord]:
        """Retrieve the latest element record matching a selector.

        Parameters
        ----------
        selector:
            The CSS/XPath selector to search for.
        page_url:
            Optional page URL to narrow the search.

        Returns
        -------
        Optional[ElementRecord]
            The most recent matching record, or ``None``.
        """
        ...

    # ── Failure History ───────────────────────────────────────

    @abstractmethod
    def get_failure_history(
        self,
        test_id: str,
        *,
        limit: int = 50,
    ) -> list[TestExecutionRecord]:
        """Retrieve only failed executions for a test.

        Parameters
        ----------
        test_id:
            The test case ID to look up.
        limit:
            Maximum number of records to return.

        Returns
        -------
        list[TestExecutionRecord]
            Failed execution records, newest first.
        """
        ...

    # ── Healing History ───────────────────────────────────────

    @abstractmethod
    def store_healing_record(self, record: HealingRecord) -> None:
        """Store a healing attempt record.

        Parameters
        ----------
        record:
            A validated ``HealingRecord`` to persist.

        Raises
        ------
        ValueError
            If the record fails validation.
        """
        ...

    @abstractmethod
    def get_healing_history(
        self,
        selector: str,
        *,
        limit: int = 20,
    ) -> list[HealingRecord]:
        """Retrieve healing history for a selector, most recent first.

        Parameters
        ----------
        selector:
            The original selector to look up.
        limit:
            Maximum number of records to return.

        Returns
        -------
        list[HealingRecord]
            Healing records, newest first.
        """
        ...

    # ── Aggregated Context ────────────────────────────────────

    @abstractmethod
    def get_test_context(self, test_id: str) -> dict[str, Any]:
        """Retrieve aggregated historical context for a test.

        Returns a summary dictionary containing execution history,
        latest success, and failure history.  Designed for consumption
        by the future Failure Analyzer and Self-Healing Agent.

        Parameters
        ----------
        test_id:
            The test case ID to look up.

        Returns
        -------
        dict[str, Any]
            Aggregated context with keys:
            ``execution_count``, ``pass_count``, ``fail_count``,
            ``latest_execution``, ``latest_success``,
            ``recent_failures``.
        """
        ...

    # ── Maintenance ───────────────────────────────────────────

    @abstractmethod
    def clear(self) -> None:
        """Clear all stored data.

        Primarily used for testing and reset scenarios.
        """
        ...
