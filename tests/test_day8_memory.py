"""
TestSphere-AI — Day 8: Historical Memory and Context Management Tests

Comprehensive pytest coverage for:
- Memory schemas (TestExecutionRecord, ElementRecord, HealingRecord)
- In-memory store (store, retrieve, edge cases)
- Context comparator (field diffs, attribute diffs, identical contexts)
"""

from __future__ import annotations

import pytest

from agents.memory.context_comparator import ContextComparator
from agents.memory.in_memory_store import InMemoryStore
from agents.memory.memory_schemas import (
    ContextComparisonResult,
    ElementRecord,
    FailureInfo,
    FieldChange,
    HealingRecord,
    TestExecutionRecord,
)
from agents.schemas.enums import (
    ChangeType,
    ExecutionStatus,
    FailureType,
)


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def store() -> InMemoryStore:
    """Fresh in-memory store for each test."""
    return InMemoryStore()


@pytest.fixture
def comparator() -> ContextComparator:
    """Fresh context comparator for each test."""
    return ContextComparator()


@pytest.fixture
def passed_execution() -> TestExecutionRecord:
    """A sample PASSED execution record."""
    return TestExecutionRecord(
        execution_id="exec-001",
        test_id="TC_LOGIN_001",
        test_name="Login with valid credentials",
        timestamp="2026-09-01T10:00:00+00:00",
        status=ExecutionStatus.PASSED,
        duration_ms=1500.0,
    )


@pytest.fixture
def failed_execution() -> TestExecutionRecord:
    """A sample FAILED execution record with failure info."""
    return TestExecutionRecord(
        execution_id="exec-002",
        test_id="TC_LOGIN_001",
        test_name="Login with valid credentials",
        timestamp="2026-09-02T10:00:00+00:00",
        status=ExecutionStatus.FAILED,
        duration_ms=3200.0,
        failure_info=FailureInfo(
            error_message="Element not found: #login-btn",
            failure_type=FailureType.ELEMENT_NOT_FOUND,
            failed_step=3,
            selector="#login-btn",
            page_url="/login",
        ),
    )


@pytest.fixture
def element_record() -> ElementRecord:
    """A sample element record."""
    return ElementRecord(
        element_id="elem-login-btn",
        selector="#login-btn",
        text="Login",
        role="button",
        page_url="/login",
        page_name="Login Page",
        attributes={"data-testid": "login-button", "aria-label": "Log in"},
        last_seen_timestamp="2026-09-01T10:00:00+00:00",
        last_successful_execution_id="exec-001",
    )


@pytest.fixture
def healing_record() -> HealingRecord:
    """A sample healing record."""
    return HealingRecord(
        healing_id="heal-001",
        test_id="TC_LOGIN_001",
        old_selector="#login-btn",
        new_selector="#sign-in-btn",
        healing_reason="Button ID was renamed in UI update",
        confidence=0.85,
        validation_result=True,
        timestamp="2026-09-02T12:00:00+00:00",
    )


# ═══════════════════════════════════════════════════════════════
# TASK 1: Schema Validation Tests
# ═══════════════════════════════════════════════════════════════


class TestSchemaValidation:
    """Tests for memory schema creation and validation."""

    def test_create_valid_execution_record(self, passed_execution: TestExecutionRecord):
        """Valid execution record should be created successfully."""
        assert passed_execution.execution_id == "exec-001"
        assert passed_execution.test_id == "TC_LOGIN_001"
        assert passed_execution.status == ExecutionStatus.PASSED
        assert passed_execution.duration_ms == 1500.0
        assert passed_execution.failure_info is None

    def test_create_execution_with_failure_info(self, failed_execution: TestExecutionRecord):
        """Execution record with failure info should capture all details."""
        assert failed_execution.status == ExecutionStatus.FAILED
        assert failed_execution.failure_info is not None
        assert failed_execution.failure_info.error_message == "Element not found: #login-btn"
        assert failed_execution.failure_info.failure_type == FailureType.ELEMENT_NOT_FOUND
        assert failed_execution.failure_info.failed_step == 3
        assert failed_execution.failure_info.selector == "#login-btn"

    def test_create_valid_element_record(self, element_record: ElementRecord):
        """Valid element record should be created successfully."""
        assert element_record.element_id == "elem-login-btn"
        assert element_record.selector == "#login-btn"
        assert element_record.text == "Login"
        assert element_record.role == "button"
        assert element_record.attributes["data-testid"] == "login-button"

    def test_create_valid_healing_record(self, healing_record: HealingRecord):
        """Valid healing record should be created successfully."""
        assert healing_record.old_selector == "#login-btn"
        assert healing_record.new_selector == "#sign-in-btn"
        assert healing_record.confidence == 0.85
        assert healing_record.validation_result is True

    def test_invalid_execution_empty_id(self):
        """Execution record with empty execution_id should be rejected."""
        with pytest.raises(Exception):
            TestExecutionRecord(
                execution_id="",
                test_id="TC_001",
                test_name="Test",
                status=ExecutionStatus.PASSED,
            )

    def test_invalid_execution_empty_test_id(self):
        """Execution record with empty test_id should be rejected."""
        with pytest.raises(Exception):
            TestExecutionRecord(
                execution_id="exec-001",
                test_id="",
                test_name="Test",
                status=ExecutionStatus.PASSED,
            )

    def test_invalid_element_empty_selector(self):
        """Element record with empty selector should be rejected."""
        with pytest.raises(Exception):
            ElementRecord(
                element_id="elem-001",
                selector="",
            )

    def test_invalid_healing_confidence_out_of_range(self):
        """Healing record with confidence > 1.0 should be rejected."""
        with pytest.raises(Exception):
            HealingRecord(
                healing_id="heal-001",
                test_id="TC_001",
                old_selector="#old",
                new_selector="#new",
                confidence=1.5,
            )

    def test_invalid_failure_info_empty_message(self):
        """FailureInfo with empty error_message should be rejected."""
        with pytest.raises(Exception):
            FailureInfo(error_message="")

    def test_execution_record_default_timestamp(self):
        """Execution record should get a default timestamp if not provided."""
        record = TestExecutionRecord(
            execution_id="exec-auto",
            test_id="TC_001",
            test_name="Auto timestamp test",
            status=ExecutionStatus.PASSED,
        )
        assert record.timestamp is not None
        assert len(record.timestamp) > 0

    def test_execution_negative_duration_rejected(self):
        """Execution record with negative duration should be rejected."""
        with pytest.raises(Exception):
            TestExecutionRecord(
                execution_id="exec-neg",
                test_id="TC_001",
                test_name="Negative duration",
                status=ExecutionStatus.PASSED,
                duration_ms=-100.0,
            )


# ═══════════════════════════════════════════════════════════════
# TASK 3 & 4: Store and Retrieve Execution History
# ═══════════════════════════════════════════════════════════════


class TestStoreExecution:
    """Tests for storing execution records."""

    def test_store_single_execution(
        self, store: InMemoryStore, passed_execution: TestExecutionRecord
    ):
        """Storing a single execution should be retrievable."""
        store.store_execution(passed_execution)
        history = store.get_execution_history("TC_LOGIN_001")
        assert len(history) == 1
        assert history[0].execution_id == "exec-001"

    def test_store_multiple_executions(self, store: InMemoryStore):
        """Multiple executions for the same test should all be stored."""
        for i in range(5):
            record = TestExecutionRecord(
                execution_id=f"exec-{i:03d}",
                test_id="TC_001",
                test_name="Multi test",
                timestamp=f"2026-09-0{i + 1}T10:00:00+00:00",
                status=ExecutionStatus.PASSED if i % 2 == 0 else ExecutionStatus.FAILED,
            )
            store.store_execution(record)
        history = store.get_execution_history("TC_001")
        assert len(history) == 5

    def test_store_execution_with_failure(
        self, store: InMemoryStore, failed_execution: TestExecutionRecord
    ):
        """Failed execution with failure info should be stored correctly."""
        store.store_execution(failed_execution)
        history = store.get_execution_history("TC_LOGIN_001")
        assert len(history) == 1
        assert history[0].failure_info is not None
        assert history[0].failure_info.error_message == "Element not found: #login-btn"

    def test_execution_history_sorted_newest_first(self, store: InMemoryStore):
        """Execution history should return newest records first."""
        old = TestExecutionRecord(
            execution_id="exec-old",
            test_id="TC_001",
            test_name="Test",
            timestamp="2026-09-01T10:00:00+00:00",
            status=ExecutionStatus.PASSED,
        )
        new = TestExecutionRecord(
            execution_id="exec-new",
            test_id="TC_001",
            test_name="Test",
            timestamp="2026-09-05T10:00:00+00:00",
            status=ExecutionStatus.PASSED,
        )
        store.store_execution(old)
        store.store_execution(new)
        history = store.get_execution_history("TC_001")
        assert history[0].execution_id == "exec-new"
        assert history[1].execution_id == "exec-old"

    def test_execution_history_respects_limit(self, store: InMemoryStore):
        """Limit parameter should cap the number of returned records."""
        for i in range(10):
            record = TestExecutionRecord(
                execution_id=f"exec-{i:03d}",
                test_id="TC_001",
                test_name="Test",
                timestamp=f"2026-09-{i + 1:02d}T10:00:00+00:00",
                status=ExecutionStatus.PASSED,
            )
            store.store_execution(record)
        history = store.get_execution_history("TC_001", limit=3)
        assert len(history) == 3


class TestRetrieveExecution:
    """Tests for retrieving execution history."""

    def test_empty_history_returns_empty_list(self, store: InMemoryStore):
        """Empty store should return empty list for any test_id."""
        history = store.get_execution_history("TC_NONEXISTENT")
        assert history == []

    def test_unknown_test_id_returns_empty(self, store: InMemoryStore, passed_execution: TestExecutionRecord):
        """Unknown test_id should return empty list, not error."""
        store.store_execution(passed_execution)
        history = store.get_execution_history("TC_UNKNOWN")
        assert history == []

    def test_get_latest_successful_execution(self, store: InMemoryStore):
        """Should return the most recent PASSED execution."""
        old_pass = TestExecutionRecord(
            execution_id="exec-pass-old",
            test_id="TC_001",
            test_name="Test",
            timestamp="2026-09-01T10:00:00+00:00",
            status=ExecutionStatus.PASSED,
        )
        new_pass = TestExecutionRecord(
            execution_id="exec-pass-new",
            test_id="TC_001",
            test_name="Test",
            timestamp="2026-09-05T10:00:00+00:00",
            status=ExecutionStatus.PASSED,
        )
        fail = TestExecutionRecord(
            execution_id="exec-fail",
            test_id="TC_001",
            test_name="Test",
            timestamp="2026-09-10T10:00:00+00:00",
            status=ExecutionStatus.FAILED,
            failure_info=FailureInfo(error_message="Failed"),
        )
        store.store_execution(old_pass)
        store.store_execution(fail)
        store.store_execution(new_pass)

        latest = store.get_latest_successful_execution("TC_001")
        assert latest is not None
        assert latest.execution_id == "exec-pass-new"

    def test_latest_successful_none_when_no_passes(self, store: InMemoryStore):
        """Should return None when there are no PASSED executions."""
        fail = TestExecutionRecord(
            execution_id="exec-fail",
            test_id="TC_001",
            test_name="Test",
            timestamp="2026-09-01T10:00:00+00:00",
            status=ExecutionStatus.FAILED,
            failure_info=FailureInfo(error_message="Failed"),
        )
        store.store_execution(fail)
        assert store.get_latest_successful_execution("TC_001") is None

    def test_latest_successful_none_for_unknown_test(self, store: InMemoryStore):
        """Should return None for unknown test_id."""
        assert store.get_latest_successful_execution("TC_UNKNOWN") is None


# ═══════════════════════════════════════════════════════════════
# Element History Tests
# ═══════════════════════════════════════════════════════════════


class TestElementHistory:
    """Tests for storing and retrieving element records."""

    def test_store_element(self, store: InMemoryStore, element_record: ElementRecord):
        """Storing an element should be retrievable."""
        store.store_element(element_record)
        history = store.get_element_history("elem-login-btn")
        assert len(history) == 1
        assert history[0].selector == "#login-btn"

    def test_store_multiple_element_versions(self, store: InMemoryStore):
        """Multiple versions of the same element should all be stored."""
        v1 = ElementRecord(
            element_id="elem-btn",
            selector="#login-btn",
            text="Login",
            last_seen_timestamp="2026-09-01T10:00:00+00:00",
        )
        v2 = ElementRecord(
            element_id="elem-btn",
            selector="#sign-in-btn",
            text="Sign In",
            last_seen_timestamp="2026-09-05T10:00:00+00:00",
        )
        store.store_element(v1)
        store.store_element(v2)
        history = store.get_element_history("elem-btn")
        assert len(history) == 2
        # Newest first
        assert history[0].selector == "#sign-in-btn"
        assert history[1].selector == "#login-btn"

    def test_get_element_by_selector(self, store: InMemoryStore, element_record: ElementRecord):
        """Should find an element by its selector."""
        store.store_element(element_record)
        found = store.get_element_by_selector("#login-btn")
        assert found is not None
        assert found.element_id == "elem-login-btn"

    def test_get_element_by_selector_with_page(self, store: InMemoryStore):
        """Should narrow search by page_url when provided."""
        elem1 = ElementRecord(
            element_id="elem-1",
            selector=".submit-btn",
            page_url="/login",
            last_seen_timestamp="2026-09-01T10:00:00+00:00",
        )
        elem2 = ElementRecord(
            element_id="elem-2",
            selector=".submit-btn",
            page_url="/register",
            last_seen_timestamp="2026-09-01T10:00:00+00:00",
        )
        store.store_element(elem1)
        store.store_element(elem2)

        found = store.get_element_by_selector(".submit-btn", page_url="/register")
        assert found is not None
        assert found.element_id == "elem-2"

    def test_get_element_by_selector_not_found(self, store: InMemoryStore):
        """Unknown selector should return None."""
        assert store.get_element_by_selector("#nonexistent") is None

    def test_element_history_empty(self, store: InMemoryStore):
        """Empty store should return empty list for any element_id."""
        assert store.get_element_history("elem-unknown") == []


# ═══════════════════════════════════════════════════════════════
# Failure History Tests
# ═══════════════════════════════════════════════════════════════


class TestFailureHistory:
    """Tests for retrieving failure-only history."""

    def test_get_failure_history(self, store: InMemoryStore):
        """Should return only FAILED/ERROR executions."""
        passed = TestExecutionRecord(
            execution_id="exec-pass",
            test_id="TC_001",
            test_name="Test",
            timestamp="2026-09-01T10:00:00+00:00",
            status=ExecutionStatus.PASSED,
        )
        failed = TestExecutionRecord(
            execution_id="exec-fail",
            test_id="TC_001",
            test_name="Test",
            timestamp="2026-09-02T10:00:00+00:00",
            status=ExecutionStatus.FAILED,
            failure_info=FailureInfo(error_message="Element not found"),
        )
        error = TestExecutionRecord(
            execution_id="exec-err",
            test_id="TC_001",
            test_name="Test",
            timestamp="2026-09-03T10:00:00+00:00",
            status=ExecutionStatus.ERROR,
            failure_info=FailureInfo(error_message="Timeout"),
        )
        store.store_execution(passed)
        store.store_execution(failed)
        store.store_execution(error)

        failures = store.get_failure_history("TC_001")
        assert len(failures) == 2
        assert all(
            f.status in (ExecutionStatus.FAILED, ExecutionStatus.ERROR)
            for f in failures
        )

    def test_failure_history_empty_when_all_passed(self, store: InMemoryStore):
        """Should return empty list when all executions passed."""
        passed = TestExecutionRecord(
            execution_id="exec-pass",
            test_id="TC_001",
            test_name="Test",
            timestamp="2026-09-01T10:00:00+00:00",
            status=ExecutionStatus.PASSED,
        )
        store.store_execution(passed)
        assert store.get_failure_history("TC_001") == []


# ═══════════════════════════════════════════════════════════════
# Healing Record Tests
# ═══════════════════════════════════════════════════════════════


class TestHealingRecords:
    """Tests for storing and retrieving healing records."""

    def test_store_healing_record(self, store: InMemoryStore, healing_record: HealingRecord):
        """Storing a healing record should be retrievable."""
        store.store_healing_record(healing_record)
        history = store.get_healing_history("#login-btn")
        assert len(history) == 1
        assert history[0].new_selector == "#sign-in-btn"

    def test_healing_history_empty(self, store: InMemoryStore):
        """Unknown selector should return empty healing history."""
        assert store.get_healing_history("#unknown") == []

    def test_multiple_healing_records(self, store: InMemoryStore):
        """Multiple healing records for same selector should all be stored."""
        for i in range(3):
            record = HealingRecord(
                healing_id=f"heal-{i:03d}",
                test_id="TC_001",
                old_selector="#btn",
                new_selector=f"#btn-v{i}",
                confidence=0.7 + i * 0.1,
                timestamp=f"2026-09-0{i + 1}T10:00:00+00:00",
            )
            store.store_healing_record(record)
        history = store.get_healing_history("#btn")
        assert len(history) == 3
        # Newest first
        assert history[0].healing_id == "heal-002"


# ═══════════════════════════════════════════════════════════════
# Aggregated Context Tests
# ═══════════════════════════════════════════════════════════════


class TestAggregatedContext:
    """Tests for get_test_context aggregation."""

    def test_get_test_context(self, store: InMemoryStore):
        """Should aggregate execution statistics correctly."""
        for i in range(4):
            record = TestExecutionRecord(
                execution_id=f"exec-{i:03d}",
                test_id="TC_001",
                test_name="Test",
                timestamp=f"2026-09-0{i + 1}T10:00:00+00:00",
                status=ExecutionStatus.PASSED if i < 3 else ExecutionStatus.FAILED,
                failure_info=(
                    FailureInfo(error_message="Failed") if i == 3 else None
                ),
            )
            store.store_execution(record)

        ctx = store.get_test_context("TC_001")
        assert ctx["test_id"] == "TC_001"
        assert ctx["execution_count"] == 4
        assert ctx["pass_count"] == 3
        assert ctx["fail_count"] == 1
        assert ctx["latest_execution"] is not None
        assert ctx["latest_success"] is not None
        assert len(ctx["recent_failures"]) == 1

    def test_get_test_context_unknown_test(self, store: InMemoryStore):
        """Unknown test should return zero counts."""
        ctx = store.get_test_context("TC_UNKNOWN")
        assert ctx["execution_count"] == 0
        assert ctx["pass_count"] == 0
        assert ctx["fail_count"] == 0
        assert ctx["latest_execution"] is None
        assert ctx["latest_success"] is None
        assert ctx["recent_failures"] == []


# ═══════════════════════════════════════════════════════════════
# Store Maintenance Tests
# ═══════════════════════════════════════════════════════════════


class TestStoreMaintenance:
    """Tests for store clear and maintenance."""

    def test_clear_removes_all_data(
        self,
        store: InMemoryStore,
        passed_execution: TestExecutionRecord,
        element_record: ElementRecord,
        healing_record: HealingRecord,
    ):
        """Clear should remove all executions, elements, and healing records."""
        store.store_execution(passed_execution)
        store.store_element(element_record)
        store.store_healing_record(healing_record)

        store.clear()

        assert store.get_execution_history("TC_LOGIN_001") == []
        assert store.get_element_history("elem-login-btn") == []
        assert store.get_healing_history("#login-btn") == []


# ═══════════════════════════════════════════════════════════════
# TASK 5: Context Comparison Tests
# ═══════════════════════════════════════════════════════════════


class TestContextComparator:
    """Tests for element context comparison."""

    def test_identical_elements(self, comparator: ContextComparator):
        """Comparing identical elements should report is_identical=True."""
        elem = ElementRecord(
            element_id="elem-btn",
            selector="#login-btn",
            text="Login",
            role="button",
            page_url="/login",
            page_name="Login Page",
            attributes={"data-testid": "login"},
        )
        result = comparator.compare_elements(elem, elem)
        assert result.is_identical is True
        assert len(result.changes) == 0
        assert result.element_id == "elem-btn"

    def test_changed_selector(self, comparator: ContextComparator):
        """Changed selector should be detected."""
        prev = ElementRecord(
            element_id="elem-btn",
            selector="#login-btn",
            text="Login",
            role="button",
        )
        curr = ElementRecord(
            element_id="elem-btn",
            selector="#sign-in-btn",
            text="Login",
            role="button",
        )
        result = comparator.compare_elements(prev, curr)
        assert result.is_identical is False
        selector_changes = [c for c in result.changes if c.field_name == "selector"]
        assert len(selector_changes) == 1
        assert selector_changes[0].old_value == "#login-btn"
        assert selector_changes[0].new_value == "#sign-in-btn"
        assert selector_changes[0].change_type == ChangeType.MODIFIED

    def test_changed_text(self, comparator: ContextComparator):
        """Changed text should be detected."""
        prev = ElementRecord(
            element_id="elem-btn",
            selector="#btn",
            text="Login",
        )
        curr = ElementRecord(
            element_id="elem-btn",
            selector="#btn",
            text="Sign In",
        )
        result = comparator.compare_elements(prev, curr)
        assert result.is_identical is False
        text_changes = [c for c in result.changes if c.field_name == "text"]
        assert len(text_changes) == 1
        assert text_changes[0].old_value == "Login"
        assert text_changes[0].new_value == "Sign In"
        assert text_changes[0].change_type == ChangeType.MODIFIED

    def test_changed_role(self, comparator: ContextComparator):
        """Changed role should be detected."""
        prev = ElementRecord(
            element_id="elem-btn",
            selector="#btn",
            role="button",
        )
        curr = ElementRecord(
            element_id="elem-btn",
            selector="#btn",
            role="link",
        )
        result = comparator.compare_elements(prev, curr)
        assert result.is_identical is False
        role_changes = [c for c in result.changes if c.field_name == "role"]
        assert len(role_changes) == 1
        assert role_changes[0].change_type == ChangeType.MODIFIED

    def test_changed_page_url(self, comparator: ContextComparator):
        """Changed page_url should be detected."""
        prev = ElementRecord(
            element_id="elem-btn",
            selector="#btn",
            page_url="/login",
        )
        curr = ElementRecord(
            element_id="elem-btn",
            selector="#btn",
            page_url="/auth/login",
        )
        result = comparator.compare_elements(prev, curr)
        assert result.is_identical is False
        page_changes = [c for c in result.changes if c.field_name == "page_url"]
        assert len(page_changes) == 1

    def test_added_field(self, comparator: ContextComparator):
        """Field that was None and is now set should be ADDED."""
        prev = ElementRecord(
            element_id="elem-btn",
            selector="#btn",
            text=None,
        )
        curr = ElementRecord(
            element_id="elem-btn",
            selector="#btn",
            text="Login",
        )
        result = comparator.compare_elements(prev, curr)
        assert result.is_identical is False
        text_changes = [c for c in result.changes if c.field_name == "text"]
        assert len(text_changes) == 1
        assert text_changes[0].change_type == ChangeType.ADDED

    def test_removed_field(self, comparator: ContextComparator):
        """Field that was set and is now None should be REMOVED."""
        prev = ElementRecord(
            element_id="elem-btn",
            selector="#btn",
            role="button",
        )
        curr = ElementRecord(
            element_id="elem-btn",
            selector="#btn",
            role=None,
        )
        result = comparator.compare_elements(prev, curr)
        assert result.is_identical is False
        role_changes = [c for c in result.changes if c.field_name == "role"]
        assert len(role_changes) == 1
        assert role_changes[0].change_type == ChangeType.REMOVED

    def test_attribute_added(self, comparator: ContextComparator):
        """New attribute should be detected as ADDED."""
        prev = ElementRecord(
            element_id="elem-btn",
            selector="#btn",
            attributes={},
        )
        curr = ElementRecord(
            element_id="elem-btn",
            selector="#btn",
            attributes={"data-testid": "login"},
        )
        result = comparator.compare_elements(prev, curr)
        assert result.is_identical is False
        attr_changes = [c for c in result.changes if c.field_name.startswith("attributes.")]
        assert len(attr_changes) == 1
        assert attr_changes[0].change_type == ChangeType.ADDED
        assert attr_changes[0].new_value == "login"

    def test_attribute_removed(self, comparator: ContextComparator):
        """Removed attribute should be detected as REMOVED."""
        prev = ElementRecord(
            element_id="elem-btn",
            selector="#btn",
            attributes={"data-testid": "login"},
        )
        curr = ElementRecord(
            element_id="elem-btn",
            selector="#btn",
            attributes={},
        )
        result = comparator.compare_elements(prev, curr)
        assert result.is_identical is False
        attr_changes = [c for c in result.changes if c.field_name.startswith("attributes.")]
        assert len(attr_changes) == 1
        assert attr_changes[0].change_type == ChangeType.REMOVED

    def test_attribute_modified(self, comparator: ContextComparator):
        """Modified attribute should be detected as MODIFIED."""
        prev = ElementRecord(
            element_id="elem-btn",
            selector="#btn",
            attributes={"aria-label": "Log in"},
        )
        curr = ElementRecord(
            element_id="elem-btn",
            selector="#btn",
            attributes={"aria-label": "Sign in"},
        )
        result = comparator.compare_elements(prev, curr)
        assert result.is_identical is False
        attr_changes = [c for c in result.changes if c.field_name == "attributes.aria-label"]
        assert len(attr_changes) == 1
        assert attr_changes[0].change_type == ChangeType.MODIFIED

    def test_multiple_changes(self, comparator: ContextComparator):
        """Multiple simultaneous changes should all be detected."""
        prev = ElementRecord(
            element_id="elem-btn",
            selector="#login-btn",
            text="Login",
            role="button",
            page_url="/login",
            attributes={"data-testid": "login-button"},
        )
        curr = ElementRecord(
            element_id="elem-btn",
            selector="#sign-in-btn",
            text="Sign In",
            role="button",
            page_url="/auth/login",
            attributes={"data-testid": "signin-button", "aria-label": "Sign in"},
        )
        result = comparator.compare_elements(prev, curr)
        assert result.is_identical is False
        # selector, text, page_url changed + data-testid modified + aria-label added
        assert len(result.changes) >= 4

        changed_fields = {c.field_name for c in result.changes}
        assert "selector" in changed_fields
        assert "text" in changed_fields
        assert "page_url" in changed_fields

    def test_comparison_result_has_selectors(self, comparator: ContextComparator):
        """Comparison result should include both previous and current selectors."""
        prev = ElementRecord(
            element_id="elem-btn",
            selector="#login-btn",
        )
        curr = ElementRecord(
            element_id="elem-btn",
            selector="#sign-in-btn",
        )
        result = comparator.compare_elements(prev, curr)
        assert result.previous_selector == "#login-btn"
        assert result.current_selector == "#sign-in-btn"

    def test_compare_attributes_directly(self, comparator: ContextComparator):
        """compare_attributes should detect added, removed, and modified keys."""
        old_attrs = {"id": "btn1", "class": "primary", "data-old": "yes"}
        new_attrs = {"id": "btn1", "class": "secondary", "data-new": "yes"}

        changes = comparator.compare_attributes(old_attrs, new_attrs)
        change_map = {c.field_name: c for c in changes}

        # 'class' was modified
        assert "attributes.class" in change_map
        assert change_map["attributes.class"].change_type == ChangeType.MODIFIED

        # 'data-old' was removed
        assert "attributes.data-old" in change_map
        assert change_map["attributes.data-old"].change_type == ChangeType.REMOVED

        # 'data-new' was added
        assert "attributes.data-new" in change_map
        assert change_map["attributes.data-new"].change_type == ChangeType.ADDED

        # 'id' was unchanged — should not appear
        assert "attributes.id" not in change_map


# ═══════════════════════════════════════════════════════════════
# Invalid Data Rejection Tests
# ═══════════════════════════════════════════════════════════════


class TestInvalidDataRejection:
    """Tests for store-level validation of invalid data."""

    def test_store_rejects_whitespace_execution_id(self, store: InMemoryStore):
        """Store should reject execution records with whitespace-only IDs."""
        record = TestExecutionRecord(
            execution_id="   ",
            test_id="TC_001",
            test_name="Test",
            status=ExecutionStatus.PASSED,
        )
        with pytest.raises(ValueError, match="execution_id"):
            store.store_execution(record)

    def test_store_rejects_whitespace_test_id(self, store: InMemoryStore):
        """Store should reject execution records with whitespace-only test_id."""
        record = TestExecutionRecord(
            execution_id="exec-001",
            test_id="   ",
            test_name="Test",
            status=ExecutionStatus.PASSED,
        )
        with pytest.raises(ValueError, match="test_id"):
            store.store_execution(record)

    def test_store_rejects_whitespace_element_id(self, store: InMemoryStore):
        """Store should reject element records with whitespace-only element_id."""
        record = ElementRecord(
            element_id="   ",
            selector="#btn",
        )
        with pytest.raises(ValueError, match="element_id"):
            store.store_element(record)

    def test_store_rejects_whitespace_selector(self, store: InMemoryStore):
        """Store should reject element records with whitespace-only selector."""
        record = ElementRecord(
            element_id="elem-001",
            selector="   ",
        )
        with pytest.raises(ValueError, match="selector"):
            store.store_element(record)

    def test_store_rejects_whitespace_healing_id(self, store: InMemoryStore):
        """Store should reject healing records with whitespace-only healing_id."""
        record = HealingRecord(
            healing_id="   ",
            test_id="TC_001",
            old_selector="#old",
            new_selector="#new",
            confidence=0.8,
        )
        with pytest.raises(ValueError, match="healing_id"):
            store.store_healing_record(record)


# ═══════════════════════════════════════════════════════════════
# Import Verification Tests
# ═══════════════════════════════════════════════════════════════


class TestImports:
    """Verify all Day 8 components are importable from expected locations."""

    def test_import_from_memory_package(self):
        """All Day 8 classes should be importable from agents.memory."""
        from agents.memory import (  # noqa: F401
            ContextComparator,
            ContextComparisonResult,
            ElementRecord,
            FailureInfo,
            FieldChange,
            HealingRecord,
            InMemoryStore,
            MemoryStore,
            TestExecutionRecord,
        )

    def test_import_from_contracts(self):
        """Memory schemas should be importable from agents.schemas.contracts."""
        from agents.schemas.contracts import (  # noqa: F401
            ContextComparisonResult,
            ElementRecord,
            FailureInfo,
            FieldChange,
            HealingRecord,
            TestExecutionRecord,
        )

    def test_import_enums(self):
        """New enums should be importable from agents.schemas."""
        from agents.schemas import ChangeType, ExecutionStatus  # noqa: F401

    def test_legacy_healing_memory_still_importable(self):
        """Legacy HealingMemory ABC should still be importable."""
        from agents.memory import HealingMemory  # noqa: F401
