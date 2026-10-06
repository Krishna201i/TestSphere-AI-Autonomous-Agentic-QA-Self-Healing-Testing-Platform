"""
TestSphere-AI — Day 9: Failure Analysis Agent Tests

Comprehensive pytest coverage for:
- Failure input validation (FailureContext schema)
- Failure classification (all 7 failure types)
- Historical context retrieval (with and without history)
- Previous/current context comparison
- Selector-change detection
- Element-not-found detection
- Element-not-interactable detection
- Assertion failure detection
- Timeout detection
- Navigation failure detection
- Unknown failure handling
- Confidence assignment (HIGH / MEDIUM / LOW)
- Recommended next action mapping
- LLM mock tests (ambiguous failures, invalid responses)
- Integration test (end-to-end selector change scenario)
"""

from __future__ import annotations

import json

import pytest
import pytest_asyncio

from agents.analyzer.analyzer import FailureAnalyzerAgent
from agents.analyzer.schemas import (
    FailureAnalysis,
    FailureContext,
    FailureEvidence,
    HistoricalContext,
    TestFailure,
)
from agents.llm.client import LLMClientSession
from agents.llm.config import LLMConfig
from agents.llm.providers.mock import MockLLMProvider
from agents.memory.context_comparator import ContextComparator
from agents.memory.in_memory_store import InMemoryStore
from agents.memory.memory_schemas import (
    ContextComparisonResult,
    ElementRecord,
    FailureInfo,
    TestExecutionRecord,
)
from agents.schemas.enums import (
    ChangeType,
    ConfidenceLevel,
    ExecutionStatus,
    FailureType,
    RecommendedAction,
)


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def store() -> InMemoryStore:
    """Fresh in-memory store for each test."""
    return InMemoryStore()


@pytest.fixture
def analyzer(store: InMemoryStore) -> FailureAnalyzerAgent:
    """Failure Analyzer without LLM (deterministic only)."""
    return FailureAnalyzerAgent(store)


@pytest.fixture
def llm_config() -> LLMConfig:
    """LLM config for mock provider."""
    return LLMConfig(provider="mock", model="mock-model")


@pytest.fixture
def mock_provider(llm_config: LLMConfig) -> MockLLMProvider:
    """Mock LLM provider."""
    return MockLLMProvider(llm_config)


@pytest.fixture
def llm_session(
    mock_provider: MockLLMProvider, llm_config: LLMConfig
) -> LLMClientSession:
    """LLM client session backed by mock provider."""
    return LLMClientSession(mock_provider, llm_config)


@pytest.fixture
def analyzer_with_llm(
    store: InMemoryStore, llm_session: LLMClientSession
) -> FailureAnalyzerAgent:
    """Failure Analyzer with LLM fallback enabled."""
    return FailureAnalyzerAgent(store, llm_client=llm_session)


@pytest.fixture
def previous_element() -> ElementRecord:
    """A previously recorded element (from a successful execution)."""
    return ElementRecord(
        element_id="login-btn",
        selector="#login-btn",
        text="Login",
        role="button",
        page_url="https://app.example.com/login",
        page_name="Login Page",
        attributes={"data-testid": "login-button", "type": "submit"},
        last_seen_timestamp="2026-09-01T10:00:00+00:00",
        last_successful_execution_id="exec-001",
    )


@pytest.fixture
def current_alternative_element() -> ElementRecord:
    """A current element that is an alternative to the previous one."""
    return ElementRecord(
        element_id="sign-in-btn",
        selector="#sign-in-btn",
        text="Login",
        role="button",
        page_url="https://app.example.com/login",
        page_name="Login Page",
        attributes={"data-testid": "sign-in-button", "type": "submit"},
        last_seen_timestamp="2026-09-10T10:00:00+00:00",
    )


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
    """A sample FAILED execution record."""
    return TestExecutionRecord(
        execution_id="exec-002",
        test_id="TC_LOGIN_001",
        test_name="Login with valid credentials",
        timestamp="2026-09-09T10:00:00+00:00",
        status=ExecutionStatus.FAILED,
        duration_ms=3000.0,
        failure_info=FailureInfo(
            error_message="Element #login-btn not found",
            failure_type=FailureType.ELEMENT_NOT_FOUND,
            failed_step=3,
            selector="#login-btn",
        ),
    )


# ═══════════════════════════════════════════════════════════════
# SECTION 1 — Failure Input Validation
# ═══════════════════════════════════════════════════════════════


class TestFailureContextValidation:
    """Tests for FailureContext schema validation."""

    def test_valid_failure_context(self):
        """A fully populated FailureContext is valid."""
        ctx = FailureContext(
            test_id="TC_001",
            execution_id="exec-001",
            failed_step=3,
            action="click",
            target_selector="#login-btn",
            error_message="Element not found",
        )
        assert ctx.test_id == "TC_001"
        assert ctx.execution_id == "exec-001"
        assert ctx.failed_step == 3
        assert ctx.action == "click"

    def test_minimal_failure_context(self):
        """FailureContext with only required fields is valid."""
        ctx = FailureContext(
            test_id="TC_001",
            execution_id="exec-001",
            failed_step=1,
            action="navigate",
        )
        assert ctx.target_selector == ""
        assert ctx.error_message == ""
        assert ctx.expected_result is None
        assert ctx.actual_result is None

    def test_empty_test_id_rejected(self):
        """Empty test_id is rejected."""
        with pytest.raises(Exception):
            FailureContext(
                test_id="",
                execution_id="exec-001",
                failed_step=1,
                action="click",
            )

    def test_empty_execution_id_rejected(self):
        """Empty execution_id is rejected."""
        with pytest.raises(Exception):
            FailureContext(
                test_id="TC_001",
                execution_id="",
                failed_step=1,
                action="click",
            )

    def test_zero_step_rejected(self):
        """Step 0 is rejected (1-based)."""
        with pytest.raises(Exception):
            FailureContext(
                test_id="TC_001",
                execution_id="exec-001",
                failed_step=0,
                action="click",
            )

    def test_empty_action_rejected(self):
        """Empty action is rejected."""
        with pytest.raises(Exception):
            FailureContext(
                test_id="TC_001",
                execution_id="exec-001",
                failed_step=1,
                action="",
            )

    def test_test_failure_is_alias(self):
        """TestFailure is a backward-compatible alias for FailureContext."""
        assert TestFailure is FailureContext

    def test_failure_context_with_current_element(
        self, current_alternative_element: ElementRecord
    ):
        """FailureContext can include a current element."""
        ctx = FailureContext(
            test_id="TC_001",
            execution_id="exec-001",
            failed_step=3,
            action="click",
            target_selector="#login-btn",
            error_message="Element not found",
            current_element=current_alternative_element,
        )
        assert ctx.current_element is not None
        assert ctx.current_element.selector == "#sign-in-btn"


# ═══════════════════════════════════════════════════════════════
# SECTION 2 — Failure Classification (Deterministic Rules)
# ═══════════════════════════════════════════════════════════════


class TestSelectorChangedDetection:
    """Tests for SELECTOR_CHANGED classification."""

    @pytest.mark.asyncio
    async def test_selector_changed_with_alternative(
        self,
        store: InMemoryStore,
        previous_element: ElementRecord,
        current_alternative_element: ElementRecord,
        passed_execution: TestExecutionRecord,
    ):
        """Detect SELECTOR_CHANGED when previous existed + alternative found."""
        store.store_execution(passed_execution)
        store.store_element(previous_element)

        analyzer = FailureAnalyzerAgent(store)
        failure = FailureContext(
            test_id="TC_LOGIN_001",
            execution_id="exec-002",
            failed_step=3,
            action="click",
            target_selector="#login-btn",
            error_message="Element #login-btn not found",
            current_element=current_alternative_element,
        )

        result = await analyzer.analyze(failure)

        assert result.failure_type == FailureType.SELECTOR_CHANGED
        assert result.confidence == ConfidenceLevel.HIGH
        assert result.recommended_action == RecommendedAction.SEARCH_FOR_REPLACEMENT_SELECTOR
        assert result.failed_target == "#login-btn"
        assert len(result.evidence) >= 2

    @pytest.mark.asyncio
    async def test_selector_changed_without_alternative(
        self,
        store: InMemoryStore,
        previous_element: ElementRecord,
        passed_execution: TestExecutionRecord,
    ):
        """Detect SELECTOR_CHANGED with MEDIUM confidence when no alternative."""
        store.store_execution(passed_execution)
        store.store_element(previous_element)

        analyzer = FailureAnalyzerAgent(store)
        failure = FailureContext(
            test_id="TC_LOGIN_001",
            execution_id="exec-002",
            failed_step=3,
            action="click",
            target_selector="#login-btn",
            error_message="Element #login-btn not found",
        )

        result = await analyzer.analyze(failure)

        assert result.failure_type == FailureType.SELECTOR_CHANGED
        assert result.confidence == ConfidenceLevel.MEDIUM

    @pytest.mark.asyncio
    async def test_selector_changed_includes_comparison_evidence(
        self,
        store: InMemoryStore,
        previous_element: ElementRecord,
        current_alternative_element: ElementRecord,
        passed_execution: TestExecutionRecord,
    ):
        """SELECTOR_CHANGED analysis includes context comparison evidence."""
        store.store_execution(passed_execution)
        store.store_element(previous_element)

        analyzer = FailureAnalyzerAgent(store)
        failure = FailureContext(
            test_id="TC_LOGIN_001",
            execution_id="exec-002",
            failed_step=3,
            action="click",
            target_selector="#login-btn",
            error_message="Element #login-btn not found",
            current_element=current_alternative_element,
        )

        result = await analyzer.analyze(failure)

        # Should have field_change evidence from context comparison
        evidence_types = [e.evidence_type for e in result.evidence]
        assert "selector_previously_existed" in evidence_types
        assert "alternative_element_found" in evidence_types
        assert "field_change" in evidence_types  # selector changed


class TestElementNotFoundDetection:
    """Tests for ELEMENT_NOT_FOUND classification."""

    @pytest.mark.asyncio
    async def test_element_not_found_no_history(
        self, analyzer: FailureAnalyzerAgent
    ):
        """Detect ELEMENT_NOT_FOUND when element was never seen before."""
        failure = FailureContext(
            test_id="TC_NEW_001",
            execution_id="exec-001",
            failed_step=2,
            action="click",
            target_selector="#unknown-btn",
            error_message="Element #unknown-btn not found",
        )

        result = await analyzer.analyze(failure)

        assert result.failure_type == FailureType.ELEMENT_NOT_FOUND
        assert result.recommended_action == RecommendedAction.INSPECT_CURRENT_UI

    @pytest.mark.asyncio
    async def test_element_completely_removed(
        self, analyzer: FailureAnalyzerAgent
    ):
        """Detect ELEMENT_NOT_FOUND for a completely removed element."""
        failure = FailureContext(
            test_id="TC_001",
            execution_id="exec-001",
            failed_step=1,
            action="click",
            target_selector="#removed-btn",
            error_message="No element matching selector #removed-btn",
        )

        result = await analyzer.analyze(failure)

        assert result.failure_type == FailureType.ELEMENT_NOT_FOUND


class TestElementNotInteractableDetection:
    """Tests for ELEMENT_NOT_INTERACTABLE classification."""

    @pytest.mark.asyncio
    async def test_element_not_interactable(
        self, analyzer: FailureAnalyzerAgent
    ):
        """Detect ELEMENT_NOT_INTERACTABLE when element exists but disabled."""
        failure = FailureContext(
            test_id="TC_001",
            execution_id="exec-001",
            failed_step=3,
            action="click",
            target_selector="#submit-btn",
            error_message="Element #submit-btn is not interactable — disabled",
        )

        result = await analyzer.analyze(failure)

        assert result.failure_type == FailureType.ELEMENT_NOT_INTERACTABLE
        assert result.confidence == ConfidenceLevel.HIGH
        assert result.recommended_action == RecommendedAction.CHECK_ELEMENT_STATE

    @pytest.mark.asyncio
    async def test_element_hidden(self, analyzer: FailureAnalyzerAgent):
        """Detect ELEMENT_NOT_INTERACTABLE when element is hidden."""
        failure = FailureContext(
            test_id="TC_001",
            execution_id="exec-001",
            failed_step=2,
            action="click",
            target_selector="#menu-item",
            error_message="Element is hidden and cannot be clicked",
        )

        result = await analyzer.analyze(failure)

        assert result.failure_type == FailureType.ELEMENT_NOT_INTERACTABLE

    @pytest.mark.asyncio
    async def test_element_obscured(self, analyzer: FailureAnalyzerAgent):
        """Detect ELEMENT_NOT_INTERACTABLE when element is obscured."""
        failure = FailureContext(
            test_id="TC_001",
            execution_id="exec-001",
            failed_step=2,
            action="click",
            target_selector="#button",
            error_message="Element is obscured by another element",
        )

        result = await analyzer.analyze(failure)

        assert result.failure_type == FailureType.ELEMENT_NOT_INTERACTABLE


class TestAssertionFailureDetection:
    """Tests for ASSERTION_FAILURE classification."""

    @pytest.mark.asyncio
    async def test_assertion_failure_with_state_mismatch(
        self, analyzer: FailureAnalyzerAgent
    ):
        """Detect ASSERTION_FAILURE when expected ≠ actual."""
        failure = FailureContext(
            test_id="TC_001",
            execution_id="exec-001",
            failed_step=5,
            action="assert",
            target_selector="#welcome-msg",
            expected_result="Welcome, John!",
            actual_result="Welcome, Guest!",
            error_message="Assertion failed: text mismatch",
        )

        result = await analyzer.analyze(failure)

        assert result.failure_type == FailureType.ASSERTION_FAILURE
        assert result.confidence == ConfidenceLevel.HIGH
        assert result.recommended_action == RecommendedAction.ANALYZE_APPLICATION_STATE
        assert result.expected_state == "Welcome, John!"
        assert result.actual_state == "Welcome, Guest!"

    @pytest.mark.asyncio
    async def test_assertion_failure_from_error_message(
        self, analyzer: FailureAnalyzerAgent
    ):
        """Detect ASSERTION_FAILURE from error message keywords."""
        failure = FailureContext(
            test_id="TC_001",
            execution_id="exec-001",
            failed_step=4,
            action="verify",
            error_message="Assertion error: expected element to be visible",
        )

        result = await analyzer.analyze(failure)

        assert result.failure_type == FailureType.ASSERTION_FAILURE


class TestTimeoutDetection:
    """Tests for TIMEOUT classification."""

    @pytest.mark.asyncio
    async def test_timeout_failure(self, analyzer: FailureAnalyzerAgent):
        """Detect TIMEOUT when operation timed out."""
        failure = FailureContext(
            test_id="TC_001",
            execution_id="exec-001",
            failed_step=2,
            action="wait",
            target_selector="#loading-spinner",
            error_message="Timeout: waiting for element exceeded 30s",
        )

        result = await analyzer.analyze(failure)

        assert result.failure_type == FailureType.TIMEOUT
        assert result.confidence == ConfidenceLevel.HIGH
        assert result.recommended_action == RecommendedAction.INVESTIGATE_TIMEOUT

    @pytest.mark.asyncio
    async def test_timed_out_variant(self, analyzer: FailureAnalyzerAgent):
        """Detect TIMEOUT with 'timed out' phrasing."""
        failure = FailureContext(
            test_id="TC_001",
            execution_id="exec-001",
            failed_step=1,
            action="navigate",
            error_message="Page load timed out after 60 seconds",
        )

        result = await analyzer.analyze(failure)

        assert result.failure_type == FailureType.TIMEOUT


class TestNavigationFailureDetection:
    """Tests for NAVIGATION_FAILURE classification."""

    @pytest.mark.asyncio
    async def test_navigation_failure(self, analyzer: FailureAnalyzerAgent):
        """Detect NAVIGATION_FAILURE when page navigation fails."""
        failure = FailureContext(
            test_id="TC_001",
            execution_id="exec-001",
            failed_step=1,
            action="navigate",
            error_message="Navigation to https://app.example.com/dashboard failed",
            current_page_url="https://app.example.com/login",
        )

        result = await analyzer.analyze(failure)

        assert result.failure_type == FailureType.NAVIGATION_FAILURE
        assert result.confidence == ConfidenceLevel.HIGH
        assert result.recommended_action == RecommendedAction.INVESTIGATE_NAVIGATION

    @pytest.mark.asyncio
    async def test_404_navigation(self, analyzer: FailureAnalyzerAgent):
        """Detect NAVIGATION_FAILURE for 404 errors."""
        failure = FailureContext(
            test_id="TC_001",
            execution_id="exec-001",
            failed_step=1,
            action="navigate",
            error_message="Page returned 404 Not Found",
        )

        result = await analyzer.analyze(failure)

        assert result.failure_type == FailureType.NAVIGATION_FAILURE

    @pytest.mark.asyncio
    async def test_net_error_navigation(self, analyzer: FailureAnalyzerAgent):
        """Detect NAVIGATION_FAILURE for net:: errors."""
        failure = FailureContext(
            test_id="TC_001",
            execution_id="exec-001",
            failed_step=1,
            action="navigate",
            error_message="net::ERR_NAME_NOT_RESOLVED",
        )

        result = await analyzer.analyze(failure)

        assert result.failure_type == FailureType.NAVIGATION_FAILURE


class TestUnknownFailure:
    """Tests for UNKNOWN failure classification."""

    @pytest.mark.asyncio
    async def test_unknown_failure(self, analyzer: FailureAnalyzerAgent):
        """Classify as UNKNOWN when no rules match."""
        failure = FailureContext(
            test_id="TC_001",
            execution_id="exec-001",
            failed_step=3,
            action="custom_action",
            error_message="Something unexpected happened internally",
        )

        result = await analyzer.analyze(failure)

        assert result.failure_type == FailureType.UNKNOWN
        assert result.confidence == ConfidenceLevel.LOW
        assert result.recommended_action == RecommendedAction.REQUIRE_FURTHER_ANALYSIS

    @pytest.mark.asyncio
    async def test_empty_error_message(self, analyzer: FailureAnalyzerAgent):
        """Empty error message results in UNKNOWN."""
        failure = FailureContext(
            test_id="TC_001",
            execution_id="exec-001",
            failed_step=1,
            action="click",
            error_message="",
        )

        result = await analyzer.analyze(failure)

        assert result.failure_type == FailureType.UNKNOWN
        assert result.confidence == ConfidenceLevel.LOW


# ═══════════════════════════════════════════════════════════════
# SECTION 3 — Historical Context Retrieval
# ═══════════════════════════════════════════════════════════════


class TestHistoricalContextRetrieval:
    """Tests for historical context retrieval from memory."""

    @pytest.mark.asyncio
    async def test_no_historical_data(self, analyzer: FailureAnalyzerAgent):
        """Analyze gracefully when no historical data exists."""
        failure = FailureContext(
            test_id="TC_BRAND_NEW",
            execution_id="exec-001",
            failed_step=1,
            action="click",
            target_selector="#btn",
            error_message="Element #btn not found",
        )

        result = await analyzer.analyze(failure)

        assert result.historical_context is not None
        assert result.historical_context.previous_executions_count == 0
        assert result.historical_context.previous_successes_count == 0
        assert result.historical_context.previous_failures_count == 0
        assert result.historical_context.latest_successful_execution is None
        assert result.historical_context.previous_element is None

    @pytest.mark.asyncio
    async def test_with_previous_executions(
        self,
        store: InMemoryStore,
        passed_execution: TestExecutionRecord,
        failed_execution: TestExecutionRecord,
    ):
        """Historical context includes previous execution counts."""
        store.store_execution(passed_execution)
        store.store_execution(failed_execution)

        analyzer = FailureAnalyzerAgent(store)
        failure = FailureContext(
            test_id="TC_LOGIN_001",
            execution_id="exec-003",
            failed_step=3,
            action="click",
            target_selector="#login-btn",
            error_message="Element not found",
        )

        result = await analyzer.analyze(failure)

        ctx = result.historical_context
        assert ctx.previous_executions_count == 2
        assert ctx.previous_successes_count == 1
        assert ctx.previous_failures_count == 1
        assert ctx.latest_successful_execution is not None
        assert ctx.latest_successful_execution.execution_id == "exec-001"

    @pytest.mark.asyncio
    async def test_with_previous_element(
        self,
        store: InMemoryStore,
        previous_element: ElementRecord,
    ):
        """Historical context includes previous element record."""
        store.store_element(previous_element)

        analyzer = FailureAnalyzerAgent(store)
        failure = FailureContext(
            test_id="TC_LOGIN_001",
            execution_id="exec-002",
            failed_step=3,
            action="click",
            target_selector="#login-btn",
            error_message="Element not found",
        )

        result = await analyzer.analyze(failure)

        ctx = result.historical_context
        assert ctx.previous_element is not None
        assert ctx.previous_element.selector == "#login-btn"

    @pytest.mark.asyncio
    async def test_multiple_previous_executions(
        self, store: InMemoryStore
    ):
        """Correct latest successful execution is retrieved from multiple."""
        # Store multiple executions
        for i in range(5):
            status = ExecutionStatus.PASSED if i % 2 == 0 else ExecutionStatus.FAILED
            store.store_execution(
                TestExecutionRecord(
                    execution_id=f"exec-{i:03d}",
                    test_id="TC_MULTI_001",
                    test_name="Multi-execution test",
                    timestamp=f"2026-09-0{i+1}T10:00:00+00:00",
                    status=status,
                )
            )

        analyzer = FailureAnalyzerAgent(store)
        failure = FailureContext(
            test_id="TC_MULTI_001",
            execution_id="exec-010",
            failed_step=1,
            action="click",
            error_message="Something unexpected happened",
        )

        result = await analyzer.analyze(failure)

        ctx = result.historical_context
        assert ctx.previous_executions_count == 5
        assert ctx.previous_successes_count == 3  # indices 0, 2, 4
        assert ctx.previous_failures_count == 2   # indices 1, 3
        # Latest success should be exec-004 (timestamp 2026-09-05)
        assert ctx.latest_successful_execution is not None
        assert ctx.latest_successful_execution.execution_id == "exec-004"


# ═══════════════════════════════════════════════════════════════
# SECTION 4 — Context Comparison
# ═══════════════════════════════════════════════════════════════


class TestContextComparison:
    """Tests for previous/current context comparison in analysis."""

    @pytest.mark.asyncio
    async def test_comparison_included_when_both_elements_exist(
        self,
        store: InMemoryStore,
        previous_element: ElementRecord,
        current_alternative_element: ElementRecord,
        passed_execution: TestExecutionRecord,
    ):
        """Context comparison is included when both previous and current exist."""
        store.store_execution(passed_execution)
        store.store_element(previous_element)

        analyzer = FailureAnalyzerAgent(store)
        failure = FailureContext(
            test_id="TC_LOGIN_001",
            execution_id="exec-002",
            failed_step=3,
            action="click",
            target_selector="#login-btn",
            error_message="Element #login-btn not found",
            current_element=current_alternative_element,
        )

        result = await analyzer.analyze(failure)

        ctx = result.historical_context
        assert ctx.context_comparison is not None
        assert not ctx.context_comparison.is_identical
        # Selector should be different
        assert ctx.context_comparison.previous_selector == "#login-btn"
        assert ctx.context_comparison.current_selector == "#sign-in-btn"

    @pytest.mark.asyncio
    async def test_comparison_absent_without_previous_element(
        self, analyzer: FailureAnalyzerAgent, current_alternative_element: ElementRecord
    ):
        """No context comparison when previous element is absent."""
        failure = FailureContext(
            test_id="TC_NEW_001",
            execution_id="exec-001",
            failed_step=3,
            action="click",
            target_selector="#login-btn",
            error_message="Element not found",
            current_element=current_alternative_element,
        )

        result = await analyzer.analyze(failure)

        assert (
            result.historical_context.context_comparison is None
        )

    @pytest.mark.asyncio
    async def test_comparison_absent_without_current_element(
        self,
        store: InMemoryStore,
        previous_element: ElementRecord,
    ):
        """No context comparison when current element is absent."""
        store.store_element(previous_element)
        analyzer = FailureAnalyzerAgent(store)

        failure = FailureContext(
            test_id="TC_LOGIN_001",
            execution_id="exec-002",
            failed_step=3,
            action="click",
            target_selector="#login-btn",
            error_message="Element not found",
        )

        result = await analyzer.analyze(failure)

        assert (
            result.historical_context.context_comparison is None
        )


# ═══════════════════════════════════════════════════════════════
# SECTION 5 — Confidence Assignment
# ═══════════════════════════════════════════════════════════════


class TestConfidenceAssignment:
    """Tests for confidence level assignment."""

    @pytest.mark.asyncio
    async def test_high_confidence_selector_change(
        self,
        store: InMemoryStore,
        previous_element: ElementRecord,
        current_alternative_element: ElementRecord,
        passed_execution: TestExecutionRecord,
    ):
        """HIGH confidence when previous + not found + alternative."""
        store.store_execution(passed_execution)
        store.store_element(previous_element)

        analyzer = FailureAnalyzerAgent(store)
        failure = FailureContext(
            test_id="TC_LOGIN_001",
            execution_id="exec-002",
            failed_step=3,
            action="click",
            target_selector="#login-btn",
            error_message="Element #login-btn not found",
            current_element=current_alternative_element,
        )

        result = await analyzer.analyze(failure)
        assert result.confidence == ConfidenceLevel.HIGH

    @pytest.mark.asyncio
    async def test_medium_confidence_selector_no_alternative(
        self,
        store: InMemoryStore,
        previous_element: ElementRecord,
        passed_execution: TestExecutionRecord,
    ):
        """MEDIUM confidence when previous + not found + no alternative."""
        store.store_execution(passed_execution)
        store.store_element(previous_element)

        analyzer = FailureAnalyzerAgent(store)
        failure = FailureContext(
            test_id="TC_LOGIN_001",
            execution_id="exec-002",
            failed_step=3,
            action="click",
            target_selector="#login-btn",
            error_message="Element #login-btn not found",
        )

        result = await analyzer.analyze(failure)
        assert result.confidence == ConfidenceLevel.MEDIUM

    @pytest.mark.asyncio
    async def test_low_confidence_unknown(
        self, analyzer: FailureAnalyzerAgent
    ):
        """LOW confidence when failure cannot be classified."""
        failure = FailureContext(
            test_id="TC_001",
            execution_id="exec-001",
            failed_step=1,
            action="custom",
            error_message="Internal unexpected error",
        )

        result = await analyzer.analyze(failure)
        assert result.confidence == ConfidenceLevel.LOW


# ═══════════════════════════════════════════════════════════════
# SECTION 6 — Recommended Next Action
# ═══════════════════════════════════════════════════════════════


class TestRecommendedAction:
    """Tests for recommended next action mapping."""

    @pytest.mark.asyncio
    async def test_selector_changed_recommends_search(
        self,
        store: InMemoryStore,
        previous_element: ElementRecord,
        current_alternative_element: ElementRecord,
        passed_execution: TestExecutionRecord,
    ):
        """SELECTOR_CHANGED → SEARCH_FOR_REPLACEMENT_SELECTOR."""
        store.store_execution(passed_execution)
        store.store_element(previous_element)

        analyzer = FailureAnalyzerAgent(store)
        failure = FailureContext(
            test_id="TC_LOGIN_001",
            execution_id="exec-002",
            failed_step=3,
            action="click",
            target_selector="#login-btn",
            error_message="Element not found",
            current_element=current_alternative_element,
        )

        result = await analyzer.analyze(failure)
        assert result.recommended_action == RecommendedAction.SEARCH_FOR_REPLACEMENT_SELECTOR

    @pytest.mark.asyncio
    async def test_element_not_found_recommends_inspect(
        self, analyzer: FailureAnalyzerAgent
    ):
        """ELEMENT_NOT_FOUND → INSPECT_CURRENT_UI."""
        failure = FailureContext(
            test_id="TC_001",
            execution_id="exec-001",
            failed_step=1,
            action="click",
            target_selector="#btn",
            error_message="Element not found",
        )

        result = await analyzer.analyze(failure)
        assert result.recommended_action == RecommendedAction.INSPECT_CURRENT_UI

    @pytest.mark.asyncio
    async def test_not_interactable_recommends_check_state(
        self, analyzer: FailureAnalyzerAgent
    ):
        """ELEMENT_NOT_INTERACTABLE → CHECK_ELEMENT_STATE."""
        failure = FailureContext(
            test_id="TC_001",
            execution_id="exec-001",
            failed_step=2,
            action="click",
            target_selector="#btn",
            error_message="Element is not interactable",
        )

        result = await analyzer.analyze(failure)
        assert result.recommended_action == RecommendedAction.CHECK_ELEMENT_STATE

    @pytest.mark.asyncio
    async def test_assertion_recommends_analyze_state(
        self, analyzer: FailureAnalyzerAgent
    ):
        """ASSERTION_FAILURE → ANALYZE_APPLICATION_STATE."""
        failure = FailureContext(
            test_id="TC_001",
            execution_id="exec-001",
            failed_step=5,
            action="assert",
            expected_result="visible",
            actual_result="hidden",
            error_message="Assertion failed",
        )

        result = await analyzer.analyze(failure)
        assert result.recommended_action == RecommendedAction.ANALYZE_APPLICATION_STATE

    @pytest.mark.asyncio
    async def test_timeout_recommends_investigate(
        self, analyzer: FailureAnalyzerAgent
    ):
        """TIMEOUT → INVESTIGATE_TIMEOUT."""
        failure = FailureContext(
            test_id="TC_001",
            execution_id="exec-001",
            failed_step=1,
            action="wait",
            error_message="Timeout exceeded",
        )

        result = await analyzer.analyze(failure)
        assert result.recommended_action == RecommendedAction.INVESTIGATE_TIMEOUT

    @pytest.mark.asyncio
    async def test_navigation_recommends_investigate(
        self, analyzer: FailureAnalyzerAgent
    ):
        """NAVIGATION_FAILURE → INVESTIGATE_NAVIGATION."""
        failure = FailureContext(
            test_id="TC_001",
            execution_id="exec-001",
            failed_step=1,
            action="navigate",
            error_message="Navigation failed",
        )

        result = await analyzer.analyze(failure)
        assert result.recommended_action == RecommendedAction.INVESTIGATE_NAVIGATION

    @pytest.mark.asyncio
    async def test_unknown_recommends_further_analysis(
        self, analyzer: FailureAnalyzerAgent
    ):
        """UNKNOWN → REQUIRE_FURTHER_ANALYSIS."""
        failure = FailureContext(
            test_id="TC_001",
            execution_id="exec-001",
            failed_step=1,
            action="custom",
            error_message="Mysterious failure",
        )

        result = await analyzer.analyze(failure)
        assert result.recommended_action == RecommendedAction.REQUIRE_FURTHER_ANALYSIS


# ═══════════════════════════════════════════════════════════════
# SECTION 7 — Evidence Validation
# ═══════════════════════════════════════════════════════════════


class TestEvidenceStructure:
    """Tests for evidence structure in analysis results."""

    @pytest.mark.asyncio
    async def test_evidence_is_structured(
        self, analyzer: FailureAnalyzerAgent
    ):
        """Evidence items are FailureEvidence instances with proper fields."""
        failure = FailureContext(
            test_id="TC_001",
            execution_id="exec-001",
            failed_step=2,
            action="click",
            target_selector="#btn",
            error_message="Element is not interactable",
        )

        result = await analyzer.analyze(failure)

        assert len(result.evidence) >= 1
        for ev in result.evidence:
            assert isinstance(ev, FailureEvidence)
            assert ev.evidence_type
            assert ev.description

    def test_failure_evidence_validation(self):
        """FailureEvidence rejects empty fields."""
        with pytest.raises(Exception):
            FailureEvidence(evidence_type="", description="valid")

        with pytest.raises(Exception):
            FailureEvidence(evidence_type="valid", description="")

    def test_failure_evidence_with_details(self):
        """FailureEvidence can carry structured details."""
        ev = FailureEvidence(
            evidence_type="selector_missing",
            description="Previous selector no longer exists",
            details={"old_selector": "#login-btn", "page": "/login"},
        )
        assert ev.details["old_selector"] == "#login-btn"


# ═══════════════════════════════════════════════════════════════
# SECTION 8 — FailureAnalysis Schema Validation
# ═══════════════════════════════════════════════════════════════


class TestFailureAnalysisSchema:
    """Tests for FailureAnalysis output schema."""

    def test_valid_failure_analysis(self):
        """A fully populated FailureAnalysis is valid."""
        analysis = FailureAnalysis(
            test_id="TC_001",
            execution_id="exec-001",
            failure_type=FailureType.SELECTOR_CHANGED,
            root_cause="Selector changed from #login-btn to #sign-in-btn",
            confidence=ConfidenceLevel.HIGH,
            failed_step=3,
            failed_target="#login-btn",
            expected_state="visible",
            actual_state="not found",
            recommended_action=RecommendedAction.SEARCH_FOR_REPLACEMENT_SELECTOR,
        )
        assert analysis.test_id == "TC_001"
        assert analysis.failure_type == FailureType.SELECTOR_CHANGED
        assert analysis.confidence == ConfidenceLevel.HIGH

    def test_analysis_consumable_by_self_healing_agent(self):
        """FailureAnalysis provides all fields needed by future Self-Healing Agent."""
        analysis = FailureAnalysis(
            test_id="TC_001",
            execution_id="exec-001",
            failure_type=FailureType.SELECTOR_CHANGED,
            root_cause="Selector changed",
            confidence=ConfidenceLevel.HIGH,
            failed_step=3,
            failed_target="#login-btn",
            recommended_action=RecommendedAction.SEARCH_FOR_REPLACEMENT_SELECTOR,
            historical_context=HistoricalContext(
                previous_executions_count=5,
                previous_successes_count=4,
                previous_failures_count=1,
                previous_element=ElementRecord(
                    element_id="login-btn",
                    selector="#login-btn",
                    text="Login",
                    role="button",
                ),
            ),
            evidence=[
                FailureEvidence(
                    evidence_type="selector_previously_existed",
                    description="Selector was previously successful",
                ),
            ],
        )

        # Self-Healing Agent can access all needed fields
        assert analysis.failure_type is not None
        assert analysis.failed_target is not None
        assert analysis.historical_context is not None
        assert analysis.historical_context.previous_element is not None
        assert analysis.evidence is not None
        assert analysis.confidence is not None
        assert analysis.recommended_action is not None


# ═══════════════════════════════════════════════════════════════
# SECTION 9 — LLM Mock Tests
# ═══════════════════════════════════════════════════════════════


class TestLLMMockAnalysis:
    """Tests for optional LLM analysis with MockLLMProvider."""

    @pytest.mark.asyncio
    async def test_llm_used_for_ambiguous_failure(
        self,
        store: InMemoryStore,
        mock_provider: MockLLMProvider,
        llm_session: LLMClientSession,
    ):
        """LLM is consulted when deterministic rules give LOW confidence."""
        # Register a valid JSON response for the LLM
        mock_provider.register_response(
            "analyze this test failure",
            json.dumps({
                "failure_type": "APPLICATION_ERROR",
                "confidence": "MEDIUM",
                "root_cause": "Application returned unexpected internal error",
            }),
        )

        analyzer = FailureAnalyzerAgent(store, llm_client=llm_session)
        failure = FailureContext(
            test_id="TC_001",
            execution_id="exec-001",
            failed_step=3,
            action="custom_action",
            error_message="Something unexpected happened internally",
        )

        result = await analyzer.analyze(failure)

        # LLM should have upgraded the analysis
        assert result.failure_type == FailureType.APPLICATION_ERROR
        assert result.confidence == ConfidenceLevel.MEDIUM
        # Should have LLM evidence
        evidence_types = [e.evidence_type for e in result.evidence]
        assert "llm_analysis" in evidence_types

    @pytest.mark.asyncio
    async def test_llm_ambiguous_selector_failure(
        self,
        store: InMemoryStore,
        mock_provider: MockLLMProvider,
        llm_session: LLMClientSession,
    ):
        """LLM analyzes an ambiguous selector failure."""
        mock_provider.register_response(
            "analyze this test failure",
            json.dumps({
                "failure_type": "SELECTOR_CHANGED",
                "confidence": "MEDIUM",
                "root_cause": "Selector likely changed due to UI redesign",
            }),
        )

        analyzer = FailureAnalyzerAgent(store, llm_client=llm_session)
        failure = FailureContext(
            test_id="TC_001",
            execution_id="exec-001",
            failed_step=2,
            action="click",
            error_message="Unexpected DOM state",
        )

        result = await analyzer.analyze(failure)

        assert result.failure_type == FailureType.SELECTOR_CHANGED
        assert result.confidence == ConfidenceLevel.MEDIUM

    @pytest.mark.asyncio
    async def test_llm_unknown_failure_analysis(
        self,
        store: InMemoryStore,
        mock_provider: MockLLMProvider,
        llm_session: LLMClientSession,
    ):
        """LLM may return UNKNOWN with a root cause explanation."""
        mock_provider.register_response(
            "analyze this test failure",
            json.dumps({
                "failure_type": "UNKNOWN",
                "confidence": "LOW",
                "root_cause": "Insufficient information to determine failure cause",
            }),
        )

        analyzer = FailureAnalyzerAgent(store, llm_client=llm_session)
        failure = FailureContext(
            test_id="TC_001",
            execution_id="exec-001",
            failed_step=1,
            action="custom",
            error_message="Weird error",
        )

        result = await analyzer.analyze(failure)

        assert result.failure_type == FailureType.UNKNOWN

    @pytest.mark.asyncio
    async def test_invalid_llm_response_rejected(
        self,
        store: InMemoryStore,
        mock_provider: MockLLMProvider,
        llm_session: LLMClientSession,
    ):
        """Invalid LLM response is rejected; deterministic result used."""
        mock_provider.register_response(
            "analyze this test failure",
            json.dumps({
                "failure_type": "INVALID_TYPE_NOT_IN_ENUM",
                "confidence": "SUPER_HIGH",
                "root_cause": "This is invalid",
            }),
        )

        analyzer = FailureAnalyzerAgent(store, llm_client=llm_session)
        failure = FailureContext(
            test_id="TC_001",
            execution_id="exec-001",
            failed_step=1,
            action="custom",
            error_message="Something broke",
        )

        result = await analyzer.analyze(failure)

        # Should fall back to deterministic result (UNKNOWN/LOW)
        assert result.failure_type == FailureType.UNKNOWN
        assert result.confidence == ConfidenceLevel.LOW

    @pytest.mark.asyncio
    async def test_valid_structured_llm_response(
        self,
        store: InMemoryStore,
        mock_provider: MockLLMProvider,
        llm_session: LLMClientSession,
    ):
        """Valid structured LLM response is properly consumed."""
        mock_provider.register_response(
            "analyze this test failure",
            json.dumps({
                "failure_type": "NETWORK_ERROR",
                "confidence": "HIGH",
                "root_cause": "Backend API returned 503 Service Unavailable",
            }),
        )

        analyzer = FailureAnalyzerAgent(store, llm_client=llm_session)
        failure = FailureContext(
            test_id="TC_001",
            execution_id="exec-001",
            failed_step=4,
            action="verify_data",
            error_message="Unexpected response from backend",
        )

        result = await analyzer.analyze(failure)

        assert result.failure_type == FailureType.NETWORK_ERROR
        assert result.confidence == ConfidenceLevel.HIGH
        assert "503" in result.root_cause

    @pytest.mark.asyncio
    async def test_no_llm_when_confidence_is_high(
        self,
        store: InMemoryStore,
        mock_provider: MockLLMProvider,
        llm_session: LLMClientSession,
    ):
        """LLM is NOT consulted when deterministic classification is confident."""
        analyzer = FailureAnalyzerAgent(store, llm_client=llm_session)
        failure = FailureContext(
            test_id="TC_001",
            execution_id="exec-001",
            failed_step=2,
            action="click",
            target_selector="#btn",
            error_message="Element is not interactable — disabled",
        )

        result = await analyzer.analyze(failure)

        # HIGH confidence from deterministic rule — LLM should not be called
        assert result.failure_type == FailureType.ELEMENT_NOT_INTERACTABLE
        assert result.confidence == ConfidenceLevel.HIGH
        assert mock_provider.call_count == 0

    @pytest.mark.asyncio
    async def test_no_llm_when_not_configured(
        self, analyzer: FailureAnalyzerAgent
    ):
        """When no LLM client is configured, UNKNOWN stays UNKNOWN."""
        failure = FailureContext(
            test_id="TC_001",
            execution_id="exec-001",
            failed_step=1,
            action="custom",
            error_message="Internal unexpected error",
        )

        result = await analyzer.analyze(failure)

        assert result.failure_type == FailureType.UNKNOWN
        assert result.confidence == ConfidenceLevel.LOW


# ═══════════════════════════════════════════════════════════════
# SECTION 10 — Integration Test
# ═══════════════════════════════════════════════════════════════


class TestIntegrationEndToEnd:
    """End-to-end integration test for the full failure analysis flow.

    Scenario:
    1. Previous successful execution with #login-btn (Login, button)
    2. Store element in memory
    3. Current failure: #login-btn not found
    4. Alternative: #sign-in-btn (Login, button)
    5. Expected: SELECTOR_CHANGED, HIGH, SEARCH_FOR_REPLACEMENT_SELECTOR
    """

    @pytest.mark.asyncio
    async def test_full_selector_change_flow(self):
        """Complete end-to-end: previous success → memory → failure → analysis."""
        # ── Setup memory with historical data ──
        store = InMemoryStore()

        # Store a previous successful execution
        previous_execution = TestExecutionRecord(
            execution_id="exec-001",
            test_id="TC_LOGIN_001",
            test_name="Login with valid credentials",
            timestamp="2026-09-01T10:00:00+00:00",
            status=ExecutionStatus.PASSED,
            duration_ms=1500.0,
        )
        store.store_execution(previous_execution)

        # Store the previous element state
        previous_element = ElementRecord(
            element_id="login-btn",
            selector="#login-btn",
            text="Login",
            role="button",
            page_url="https://app.example.com/login",
            page_name="Login Page",
            attributes={"data-testid": "login-button", "type": "submit"},
            last_seen_timestamp="2026-09-01T10:00:00+00:00",
            last_successful_execution_id="exec-001",
        )
        store.store_element(previous_element)

        # ── Create the analyzer ──
        analyzer = FailureAnalyzerAgent(store)

        # ── Current failure ──
        current_alternative = ElementRecord(
            element_id="sign-in-btn",
            selector="#sign-in-btn",
            text="Login",
            role="button",
            page_url="https://app.example.com/login",
            page_name="Login Page",
            attributes={"data-testid": "sign-in-button", "type": "submit"},
            last_seen_timestamp="2026-09-10T10:00:00+00:00",
        )

        failure = FailureContext(
            test_id="TC_LOGIN_001",
            execution_id="exec-010",
            failed_step=3,
            action="click",
            target_selector="#login-btn",
            expected_result="Login button clicked",
            actual_result="Element not found",
            error_message="Element #login-btn not found on page",
            current_page_url="https://app.example.com/login",
            current_page_title="Login Page",
            current_element=current_alternative,
        )

        # ── Analyze ──
        result = await analyzer.analyze(failure)

        # ── Verify the complete analysis ──

        # Failure type
        assert result.failure_type == FailureType.SELECTOR_CHANGED

        # Confidence
        assert result.confidence == ConfidenceLevel.HIGH

        # Recommended action
        assert result.recommended_action == RecommendedAction.SEARCH_FOR_REPLACEMENT_SELECTOR

        # Failed target
        assert result.failed_target == "#login-btn"

        # Root cause mentions the selector change
        assert "#login-btn" in result.root_cause
        assert "#sign-in-btn" in result.root_cause

        # Expected/actual state preserved
        assert result.expected_state == "Login button clicked"
        assert result.actual_state == "Element not found"

        # Evidence is present and structured
        assert len(result.evidence) >= 2
        evidence_types = [e.evidence_type for e in result.evidence]
        assert "selector_previously_existed" in evidence_types
        assert "alternative_element_found" in evidence_types

        # Historical context
        ctx = result.historical_context
        assert ctx is not None
        assert ctx.previous_executions_count == 1
        assert ctx.previous_successes_count == 1
        assert ctx.latest_successful_execution is not None
        assert ctx.latest_successful_execution.execution_id == "exec-001"
        assert ctx.previous_element is not None
        assert ctx.previous_element.selector == "#login-btn"

        # Context comparison
        assert ctx.context_comparison is not None
        assert not ctx.context_comparison.is_identical
        assert ctx.context_comparison.previous_selector == "#login-btn"
        assert ctx.context_comparison.current_selector == "#sign-in-btn"

        # The analysis does NOT perform any healing
        # (verified by the fact that we only got a FailureAnalysis back,
        #  no selectors were modified, no browser actions executed)

    @pytest.mark.asyncio
    async def test_full_flow_no_history(self):
        """End-to-end flow with no historical data — graceful degradation."""
        store = InMemoryStore()
        analyzer = FailureAnalyzerAgent(store)

        failure = FailureContext(
            test_id="TC_BRAND_NEW",
            execution_id="exec-001",
            failed_step=1,
            action="click",
            target_selector="#new-btn",
            error_message="Element #new-btn not found",
        )

        result = await analyzer.analyze(failure)

        # Should still produce a valid analysis
        assert result.failure_type == FailureType.ELEMENT_NOT_FOUND
        assert result.confidence in (ConfidenceLevel.HIGH, ConfidenceLevel.MEDIUM)
        assert result.test_id == "TC_BRAND_NEW"
        assert result.execution_id == "exec-001"

        # Historical context should be empty
        ctx = result.historical_context
        assert ctx.previous_executions_count == 0
        assert ctx.previous_element is None
        assert ctx.context_comparison is None

    @pytest.mark.asyncio
    async def test_full_flow_with_llm_fallback(self):
        """End-to-end flow using LLM for ambiguous failure."""
        store = InMemoryStore()
        config = LLMConfig(provider="mock", model="mock-model")
        provider = MockLLMProvider(config)

        provider.register_response(
            "analyze this test failure",
            json.dumps({
                "failure_type": "APPLICATION_ERROR",
                "confidence": "MEDIUM",
                "root_cause": "Application returned an unexpected error state",
            }),
        )

        session = LLMClientSession(provider, config)
        analyzer = FailureAnalyzerAgent(store, llm_client=session)

        failure = FailureContext(
            test_id="TC_001",
            execution_id="exec-001",
            failed_step=3,
            action="verify_state",
            error_message="Unexpected application behavior",
        )

        result = await analyzer.analyze(failure)

        # LLM should have provided the classification
        assert result.failure_type == FailureType.APPLICATION_ERROR
        assert result.confidence == ConfidenceLevel.MEDIUM
        assert provider.call_count == 1


# ═══════════════════════════════════════════════════════════════
# SECTION 11 — Enum Validation
# ═══════════════════════════════════════════════════════════════


class TestEnumCompleteness:
    """Verify Day 9 enums are complete and consistent."""

    def test_failure_type_has_selector_changed(self):
        """SELECTOR_CHANGED is in FailureType enum."""
        assert FailureType.SELECTOR_CHANGED == "SELECTOR_CHANGED"

    def test_confidence_levels(self):
        """All three confidence levels exist."""
        assert ConfidenceLevel.HIGH == "HIGH"
        assert ConfidenceLevel.MEDIUM == "MEDIUM"
        assert ConfidenceLevel.LOW == "LOW"

    def test_recommended_actions(self):
        """All recommended actions exist."""
        assert RecommendedAction.SEARCH_FOR_REPLACEMENT_SELECTOR.value
        assert RecommendedAction.INSPECT_CURRENT_UI.value
        assert RecommendedAction.CHECK_ELEMENT_STATE.value
        assert RecommendedAction.ANALYZE_APPLICATION_STATE.value
        assert RecommendedAction.INVESTIGATE_TIMEOUT.value
        assert RecommendedAction.INVESTIGATE_NAVIGATION.value
        assert RecommendedAction.REQUIRE_FURTHER_ANALYSIS.value

    def test_every_failure_type_has_recommended_action(self):
        """Every FailureType maps to a RecommendedAction."""
        from agents.analyzer.analyzer import _ACTION_MAP

        for ft in FailureType:
            assert ft in _ACTION_MAP, (
                f"FailureType.{ft.name} has no recommended action mapping"
            )
