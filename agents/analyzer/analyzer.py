"""
TestSphere-AI — Failure Analyzer Agent

Concrete implementation of the Failure Analysis Agent.

The analyzer diagnoses test failures using:
1. Current failure information (structured FailureContext)
2. Previous execution history (via MemoryStore)
3. Previous successful element context (via MemoryStore)
4. Context comparison (via ContextComparator)
5. Deterministic rule-based classification
6. Optional LLM fallback for ambiguous cases

Architecture::

    Failed Test
         ↓
    FailureAnalyzerAgent.analyze()
         ↓
    Retrieve Historical Context
         ↓
    Compare Previous and Current Context
         ↓
    Deterministic Rule-Based Classification
         ↓
    Is evidence sufficient?
       /       \\
     YES        NO (+ LLM available)
      ↓          ↓
    Return     LLMClient → Structured Result
    Analysis

IMPORTANT: The analyzer does NOT perform self-healing.
It diagnoses failures and produces structured information
that the future Self-Healing Agent can consume.

Day 1: Placeholder ABC.
Day 9: Full concrete implementation.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from agents.analyzer.schemas import (
    FailureAnalysis,
    FailureContext,
    FailureEvidence,
    HistoricalContext,
)
from agents.memory.context_comparator import ContextComparator
from agents.memory.memory_interface import MemoryStore
from agents.memory.memory_schemas import (
    ContextComparisonResult,
    ElementRecord,
)
from agents.schemas.enums import (
    ChangeType,
    ConfidenceLevel,
    FailureType,
    RecommendedAction,
)

logger = logging.getLogger(__name__)


# ── Recommended Action Mapping ────────────────────────────────

_ACTION_MAP: dict[FailureType, RecommendedAction] = {
    FailureType.SELECTOR_CHANGED: RecommendedAction.SEARCH_FOR_REPLACEMENT_SELECTOR,
    FailureType.ELEMENT_NOT_FOUND: RecommendedAction.INSPECT_CURRENT_UI,
    FailureType.ELEMENT_NOT_INTERACTABLE: RecommendedAction.CHECK_ELEMENT_STATE,
    FailureType.ASSERTION_FAILURE: RecommendedAction.ANALYZE_APPLICATION_STATE,
    FailureType.TIMEOUT: RecommendedAction.INVESTIGATE_TIMEOUT,
    FailureType.NAVIGATION_FAILURE: RecommendedAction.INVESTIGATE_NAVIGATION,
    FailureType.NETWORK_ERROR: RecommendedAction.REQUIRE_FURTHER_ANALYSIS,
    FailureType.APPLICATION_ERROR: RecommendedAction.REQUIRE_FURTHER_ANALYSIS,
    FailureType.UNKNOWN: RecommendedAction.REQUIRE_FURTHER_ANALYSIS,
}


class FailureAnalyzerAgent:
    """Concrete Failure Analysis Agent.

    Analyzes test failures and produces structured ``FailureAnalysis``
    results.  Uses the Historical Memory layer for context and the
    Context Comparator for element change detection.

    Parameters
    ----------
    memory_store:
        The memory store to query for historical context.
    llm_client:
        Optional LLM client session for ambiguous cases.
        If ``None``, only deterministic rules are used.

    Usage
    -----
    >>> from agents.memory import InMemoryStore
    >>> store = InMemoryStore()
    >>> analyzer = FailureAnalyzerAgent(store)
    >>> analysis = await analyzer.analyze(failure_context)
    """

    def __init__(
        self,
        memory_store: MemoryStore,
        llm_client: object | None = None,
    ) -> None:
        self._memory = memory_store
        self._llm_client = llm_client
        self._comparator = ContextComparator()
        logger.info(
            "FailureAnalyzerAgent initialized — llm_available=%s",
            llm_client is not None,
        )

    # ── Public API ────────────────────────────────────────────

    async def analyze(self, failure: FailureContext) -> FailureAnalysis:
        """Analyze a test failure and produce a structured diagnosis.

        Parameters
        ----------
        failure:
            Structured failure context from the execution engine.

        Returns
        -------
        FailureAnalysis
            Structured analysis including failure type, root cause,
            confidence, evidence, and recommended action.
        """
        logger.info(
            "Analyzing failure — test_id=%s, execution_id=%s, step=%d",
            failure.test_id,
            failure.execution_id,
            failure.failed_step,
        )

        # 1. Retrieve historical context
        historical = self._retrieve_historical_context(failure)

        # 2. Compare previous and current element contexts
        comparison = self._compare_contexts(failure, historical)
        if comparison is not None:
            historical = historical.model_copy(
                update={"context_comparison": comparison}
            )

        # 3. Deterministic rule-based classification
        failure_type, confidence, evidence, root_cause = (
            self._classify_deterministic(failure, historical)
        )

        # 4. Optional LLM fallback for ambiguous cases
        if confidence == ConfidenceLevel.LOW and self._llm_client is not None:
            logger.info(
                "Confidence is LOW — attempting LLM analysis for "
                "test_id=%s",
                failure.test_id,
            )
            llm_result = await self._analyze_with_llm(
                failure, historical, evidence
            )
            if llm_result is not None:
                failure_type = llm_result["failure_type"]
                confidence = llm_result["confidence"]
                root_cause = llm_result["root_cause"]
                evidence.append(
                    FailureEvidence(
                        evidence_type="llm_analysis",
                        description="LLM provided analysis for ambiguous failure",
                        details={"source": "llm"},
                    )
                )

        # 5. Determine recommended action
        recommended = _ACTION_MAP.get(
            failure_type, RecommendedAction.REQUIRE_FURTHER_ANALYSIS
        )

        analysis = FailureAnalysis(
            test_id=failure.test_id,
            execution_id=failure.execution_id,
            failure_type=failure_type,
            root_cause=root_cause,
            confidence=confidence,
            failed_step=failure.failed_step,
            failed_target=failure.target_selector,
            expected_state=failure.expected_result,
            actual_state=failure.actual_result,
            evidence=evidence,
            historical_context=historical,
            recommended_action=recommended,
        )

        logger.info(
            "Analysis complete — type=%s, confidence=%s, action=%s",
            failure_type.value,
            confidence.value,
            recommended.value,
        )

        return analysis

    # ── Historical Context Retrieval ──────────────────────────

    def _retrieve_historical_context(
        self, failure: FailureContext
    ) -> HistoricalContext:
        """Retrieve historical context from the memory store.

        Gracefully handles cases where no history exists.
        """
        test_context = self._memory.get_test_context(failure.test_id)

        # Retrieve element history for the failed target
        previous_element: Optional[ElementRecord] = None
        if failure.target_selector:
            previous_element = self._memory.get_element_by_selector(
                failure.target_selector
            )

        latest_success = test_context.get("latest_success")

        return HistoricalContext(
            previous_executions_count=test_context.get("execution_count", 0),
            previous_successes_count=test_context.get("pass_count", 0),
            previous_failures_count=test_context.get("fail_count", 0),
            latest_successful_execution=latest_success,
            previous_element=previous_element,
        )

    # ── Context Comparison ────────────────────────────────────

    def _compare_contexts(
        self,
        failure: FailureContext,
        historical: HistoricalContext,
    ) -> Optional[ContextComparisonResult]:
        """Compare previous and current element contexts.

        Returns ``None`` if either context is unavailable.
        """
        if historical.previous_element is None:
            return None
        if failure.current_element is None:
            return None

        return self._comparator.compare_elements(
            previous=historical.previous_element,
            current=failure.current_element,
        )

    # ── Deterministic Classification ──────────────────────────

    def _classify_deterministic(
        self,
        failure: FailureContext,
        historical: HistoricalContext,
    ) -> tuple[FailureType, ConfidenceLevel, list[FailureEvidence], str]:
        """Apply deterministic rules to classify the failure.

        Returns a tuple of (failure_type, confidence, evidence, root_cause).
        """
        evidence: list[FailureEvidence] = []

        # Rule 1: SELECTOR_CHANGED
        result = self._check_selector_changed(failure, historical, evidence)
        if result is not None:
            return result

        # Rule 2: ELEMENT_NOT_INTERACTABLE
        result = self._check_element_not_interactable(failure, evidence)
        if result is not None:
            return result

        # Rule 3: ASSERTION_FAILED
        result = self._check_assertion_failed(failure, evidence)
        if result is not None:
            return result

        # Rule 4: TIMEOUT
        result = self._check_timeout(failure, evidence)
        if result is not None:
            return result

        # Rule 5: NAVIGATION_FAILED
        result = self._check_navigation_failed(failure, evidence)
        if result is not None:
            return result

        # Rule 6: ELEMENT_NOT_FOUND (less specific, checked after selector_changed)
        result = self._check_element_not_found(failure, historical, evidence)
        if result is not None:
            return result

        # Fallback: UNKNOWN
        evidence.append(
            FailureEvidence(
                evidence_type="insufficient_evidence",
                description="Available evidence is insufficient to determine the cause",
                details={
                    "error_message": failure.error_message,
                    "action": failure.action,
                },
            )
        )
        return (
            FailureType.UNKNOWN,
            ConfidenceLevel.LOW,
            evidence,
            "Available evidence is insufficient to determine the failure cause",
        )

    # ── Individual Rule Checks ────────────────────────────────

    def _check_selector_changed(
        self,
        failure: FailureContext,
        historical: HistoricalContext,
        evidence: list[FailureEvidence],
    ) -> Optional[tuple[FailureType, ConfidenceLevel, list[FailureEvidence], str]]:
        """Check if the failure is due to a selector change.

        Conditions:
        - Previous element existed in history for this selector
        - Current selector not found (error indicates not found)
        - An alternative element is available in current UI
        """
        has_previous = historical.previous_element is not None
        has_current_alt = failure.current_element is not None
        error_lower = failure.error_message.lower()
        not_found_signal = (
            "not found" in error_lower
            or "no element" in error_lower
            or "element_not_found" in error_lower
        )

        if has_previous and not_found_signal and has_current_alt:
            # Strong evidence: previous existed + current missing + alternative found
            evidence.append(
                FailureEvidence(
                    evidence_type="selector_previously_existed",
                    description=(
                        f"Selector '{failure.target_selector}' was previously "
                        f"successful"
                    ),
                    details={
                        "previous_selector": historical.previous_element.selector,
                        "previous_text": historical.previous_element.text,
                        "previous_role": historical.previous_element.role,
                    },
                )
            )
            evidence.append(
                FailureEvidence(
                    evidence_type="alternative_element_found",
                    description=(
                        f"Alternative element found with selector "
                        f"'{failure.current_element.selector}'"
                    ),
                    details={
                        "current_selector": failure.current_element.selector,
                        "current_text": failure.current_element.text,
                        "current_role": failure.current_element.role,
                    },
                )
            )

            # Add comparison evidence if available
            if historical.context_comparison is not None:
                for change in historical.context_comparison.changes:
                    evidence.append(
                        FailureEvidence(
                            evidence_type="field_change",
                            description=(
                                f"Field '{change.field_name}' changed: "
                                f"'{change.old_value}' → '{change.new_value}'"
                            ),
                            details={
                                "field": change.field_name,
                                "old_value": str(change.old_value),
                                "new_value": str(change.new_value),
                                "change_type": change.change_type.value,
                            },
                        )
                    )

            return (
                FailureType.SELECTOR_CHANGED,
                ConfidenceLevel.HIGH,
                evidence,
                (
                    f"The selector '{failure.target_selector}' no longer "
                    f"identifies the expected element. An alternative element "
                    f"with selector '{failure.current_element.selector}' was found."
                ),
            )

        if has_previous and not_found_signal and not has_current_alt:
            # Medium evidence: previous existed + current missing, no alternative
            evidence.append(
                FailureEvidence(
                    evidence_type="selector_previously_existed",
                    description=(
                        f"Selector '{failure.target_selector}' was previously "
                        f"successful but is now missing"
                    ),
                    details={
                        "previous_selector": historical.previous_element.selector,
                    },
                )
            )
            evidence.append(
                FailureEvidence(
                    evidence_type="no_alternative_found",
                    description="No alternative element was found in the current UI",
                    details={},
                )
            )
            return (
                FailureType.SELECTOR_CHANGED,
                ConfidenceLevel.MEDIUM,
                evidence,
                (
                    f"The selector '{failure.target_selector}' was previously "
                    f"valid but can no longer be found. No alternative element "
                    f"was located."
                ),
            )

        return None

    def _check_element_not_found(
        self,
        failure: FailureContext,
        historical: HistoricalContext,
        evidence: list[FailureEvidence],
    ) -> Optional[tuple[FailureType, ConfidenceLevel, list[FailureEvidence], str]]:
        """Check if the element simply cannot be found."""
        error_lower = failure.error_message.lower()
        not_found = (
            "not found" in error_lower
            or "no element" in error_lower
            or "element_not_found" in error_lower
        )

        if not_found:
            confidence = ConfidenceLevel.HIGH
            if historical.previous_element is None:
                confidence = ConfidenceLevel.MEDIUM

            evidence.append(
                FailureEvidence(
                    evidence_type="element_not_found",
                    description=(
                        f"Target element '{failure.target_selector}' "
                        f"cannot be located"
                    ),
                    details={
                        "selector": failure.target_selector,
                        "error": failure.error_message,
                    },
                )
            )
            return (
                FailureType.ELEMENT_NOT_FOUND,
                confidence,
                evidence,
                f"The target element '{failure.target_selector}' cannot currently be located",
            )

        return None

    def _check_element_not_interactable(
        self,
        failure: FailureContext,
        evidence: list[FailureEvidence],
    ) -> Optional[tuple[FailureType, ConfidenceLevel, list[FailureEvidence], str]]:
        """Check if the element exists but is not interactable."""
        error_lower = failure.error_message.lower()
        not_interactable = (
            "not interactable" in error_lower
            or "not clickable" in error_lower
            or "disabled" in error_lower
            or "hidden" in error_lower
            or "obscured" in error_lower
        )

        if not_interactable:
            evidence.append(
                FailureEvidence(
                    evidence_type="element_not_interactable",
                    description=(
                        f"Element '{failure.target_selector}' exists but "
                        f"cannot be interacted with"
                    ),
                    details={
                        "selector": failure.target_selector,
                        "error": failure.error_message,
                    },
                )
            )
            return (
                FailureType.ELEMENT_NOT_INTERACTABLE,
                ConfidenceLevel.HIGH,
                evidence,
                (
                    f"The element '{failure.target_selector}' exists but "
                    f"cannot currently be interacted with"
                ),
            )

        return None

    def _check_assertion_failed(
        self,
        failure: FailureContext,
        evidence: list[FailureEvidence],
    ) -> Optional[tuple[FailureType, ConfidenceLevel, list[FailureEvidence], str]]:
        """Check if this is an assertion failure."""
        error_lower = failure.error_message.lower()

        # Only match explicit assertion keywords — NOT generic "expected"
        is_assertion_keyword = (
            "assertion" in error_lower
            or "assert failed" in error_lower
            or "assert error" in error_lower
            or "mismatch" in error_lower
        )

        # Also check if expected ≠ actual (explicit state mismatch)
        has_state_mismatch = (
            failure.expected_result is not None
            and failure.actual_result is not None
            and failure.expected_result != failure.actual_result
        )

        if is_assertion_keyword or has_state_mismatch:
            evidence.append(
                FailureEvidence(
                    evidence_type="assertion_failed",
                    description="Expected application state does not match observed state",
                    details={
                        "expected": failure.expected_result or "",
                        "actual": failure.actual_result or "",
                        "error": failure.error_message,
                    },
                )
            )
            confidence = ConfidenceLevel.HIGH if has_state_mismatch else ConfidenceLevel.MEDIUM
            return (
                FailureType.ASSERTION_FAILURE,
                confidence,
                evidence,
                (
                    f"The expected application state does not match the "
                    f"observed state. Expected: '{failure.expected_result}', "
                    f"Actual: '{failure.actual_result}'"
                ),
            )

        return None

    def _check_timeout(
        self,
        failure: FailureContext,
        evidence: list[FailureEvidence],
    ) -> Optional[tuple[FailureType, ConfidenceLevel, list[FailureEvidence], str]]:
        """Check if this is a timeout failure."""
        error_lower = failure.error_message.lower()
        is_timeout = (
            "timeout" in error_lower
            or "timed out" in error_lower
            or "exceeded" in error_lower
        )

        if is_timeout:
            evidence.append(
                FailureEvidence(
                    evidence_type="timeout",
                    description="Operation did not complete within the allowed time",
                    details={
                        "error": failure.error_message,
                        "action": failure.action,
                    },
                )
            )
            return (
                FailureType.TIMEOUT,
                ConfidenceLevel.HIGH,
                evidence,
                f"An expected operation did not complete within the allowed time",
            )

        return None

    def _check_navigation_failed(
        self,
        failure: FailureContext,
        evidence: list[FailureEvidence],
    ) -> Optional[tuple[FailureType, ConfidenceLevel, list[FailureEvidence], str]]:
        """Check if this is a navigation failure."""
        error_lower = failure.error_message.lower()
        is_nav = (
            "navigation" in error_lower
            or "navigate" in error_lower
            or "page load" in error_lower
            or "404" in error_lower
            or "net::" in error_lower
        )

        if is_nav:
            evidence.append(
                FailureEvidence(
                    evidence_type="navigation_failed",
                    description="Expected navigation did not occur successfully",
                    details={
                        "error": failure.error_message,
                        "page_url": failure.current_page_url or "",
                    },
                )
            )
            return (
                FailureType.NAVIGATION_FAILURE,
                ConfidenceLevel.HIGH,
                evidence,
                f"The expected navigation did not occur successfully",
            )

        return None

    # ── LLM Fallback ─────────────────────────────────────────

    async def _analyze_with_llm(
        self,
        failure: FailureContext,
        historical: HistoricalContext,
        evidence: list[FailureEvidence],
    ) -> Optional[dict]:
        """Use the LLM to analyze an ambiguous failure.

        The LLM receives concise structured evidence and must return
        only the required structured analysis fields.

        Returns ``None`` if the LLM response cannot be parsed or validated.
        """
        if self._llm_client is None:
            return None

        # Build concise prompt with structured evidence
        prompt_data = {
            "task": "Analyze this test failure and classify it.",
            "failure": {
                "test_id": failure.test_id,
                "action": failure.action,
                "target_selector": failure.target_selector,
                "error_message": failure.error_message,
                "expected": failure.expected_result,
                "actual": failure.actual_result,
            },
            "historical": {
                "previous_executions": historical.previous_executions_count,
                "previous_successes": historical.previous_successes_count,
                "has_previous_element": historical.previous_element is not None,
            },
            "current_evidence": [
                {"type": e.evidence_type, "description": e.description}
                for e in evidence
            ],
            "valid_failure_types": [ft.value for ft in FailureType],
            "valid_confidence_levels": [cl.value for cl in ConfidenceLevel],
            "required_response_format": {
                "failure_type": "one of valid_failure_types",
                "confidence": "one of valid_confidence_levels",
                "root_cause": "concise explanation string",
            },
        }

        from agents.llm.schemas import LLMRequest

        try:
            request = LLMRequest(
                prompt=json.dumps(prompt_data, indent=2),
                system_instruction=(
                    "You are a test failure analysis engine. "
                    "Respond ONLY with a JSON object containing: "
                    "failure_type, confidence, root_cause. "
                    "Do not include any other text."
                ),
                response_format="json",
                temperature=0.1,
            )

            response_data = await self._llm_client.generate_json(request)

            # Validate the response
            ft_str = response_data.get("failure_type", "")
            conf_str = response_data.get("confidence", "")
            root_cause = response_data.get("root_cause", "")

            # Validate failure_type
            try:
                failure_type = FailureType(ft_str)
            except ValueError:
                logger.warning(
                    "LLM returned invalid failure_type: %s", ft_str
                )
                return None

            # Validate confidence
            try:
                confidence = ConfidenceLevel(conf_str)
            except ValueError:
                logger.warning(
                    "LLM returned invalid confidence: %s", conf_str
                )
                return None

            if not root_cause or not isinstance(root_cause, str):
                logger.warning("LLM returned empty or invalid root_cause")
                return None

            return {
                "failure_type": failure_type,
                "confidence": confidence,
                "root_cause": root_cause,
            }

        except Exception as exc:
            logger.warning(
                "LLM analysis failed: %s: %s", type(exc).__name__, exc
            )
            return None
