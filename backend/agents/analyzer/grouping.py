"""
TestSphere-AI — Failure Grouping & Root-Cause Clustering Module

Deterministic grouping of multiple test failures across test runs to identify
shared root causes and failure clusters without guessing or hallucinatory grouping.

Grouping Signals:
  1. Authentication failure / login redirect
  2. Identical broken selector on same page
  3. Network / backend gateway or connection failures
  4. Normalized exception signature
  5. Isolated singletons (unclustered failures preserved individually)

Principles:
  - Deterministic rules first (no unexplainable clustering).
  - Every individual failure is preserved inside its group.
  - No failure is ever dropped or concealed.
  - Do not claim a shared root cause without explicit supporting evidence.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from agents.analyzer.failure_classifier import FailureClassifier
from agents.analyzer.schemas import FailureContext
from agents.schemas.enums import FailureType, RecommendedAction

logger = logging.getLogger(__name__)


@dataclass
class FailureGroup:
    """A cluster of test failures sharing a verifiable root cause.

    Attributes
    ----------
    group_id:
        Deterministic identifier for the cluster.
    title:
        Human-readable title describing the shared failure.
    shared_failure_type:
        The failure category shared by the cluster.
    shared_root_cause:
        Evidence-based explanation of the shared cause.
    confidence:
        Confidence score between 0.0 and 1.0.
    grouping_signal:
        Signal used to identify the cluster (e.g. 'shared_selector', 'authentication_redirect').
    evidence_summary:
        List of verifiable evidence strings supporting the grouping.
    failures:
        All individual FailureContext objects in this group (no failures dropped).
    affected_test_ids:
        Unique IDs of test cases affected by this failure group.
    suggested_action:
        Actionable next step to resolve the cluster.
    """

    group_id: str
    title: str
    shared_failure_type: FailureType | str
    shared_root_cause: str
    confidence: float
    grouping_signal: str
    evidence_summary: list[str] = field(default_factory=list)
    failures: list[FailureContext] = field(default_factory=list)
    affected_test_ids: list[str] = field(default_factory=list)
    suggested_action: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert group to serializable dictionary."""
        return {
            "group_id": self.group_id,
            "title": self.title,
            "shared_failure_type": (
                self.shared_failure_type.value
                if isinstance(self.shared_failure_type, FailureType)
                else str(self.shared_failure_type)
            ),
            "shared_root_cause": self.shared_root_cause,
            "confidence": round(self.confidence, 4),
            "grouping_signal": self.grouping_signal,
            "evidence_summary": self.evidence_summary,
            "affected_test_ids": self.affected_test_ids,
            "failure_count": len(self.failures),
            "suggested_action": self.suggested_action,
        }


def normalize_error_message(message: str) -> str:
    """Normalize error message by removing transient numbers, timestamps, and memory addresses.

    Produces a stable signature for deterministic clustering.
    """
    if not message:
        return "empty_error"

    msg = message.strip().lower()

    # Normalize memory addresses
    msg = re.sub(r"0x[0-9a-fA-F]+", "<ADDR>", msg)
    # Normalize UUIDs
    msg = re.sub(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        "<UUID>",
        msg,
    )
    # Normalize timestamps (ISO 8601)
    msg = re.sub(r"\d{4}-\d{2}-\d{2}t\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:z|[+-]\d{2}:\d{2})?", "<TIMESTAMP>", msg)
    # Normalize timeout durations (e.g. 30000ms, 5000 ms)
    msg = re.sub(r"\d+\s*m?s", "<TIMEOUT>", msg)
    # Normalize line numbers (e.g. line 42, :123:45)
    msg = re.sub(r"(?:line\s+|:)\d+(?::\d+)?", "<LINE>", msg)
    # Normalize port numbers (e.g. port 8080)
    msg = re.sub(r"port\s+\d+", "port <PORT>", msg)
    # Collapse multiple whitespace
    msg = re.sub(r"\s+", " ", msg).strip()

    return msg


class FailureGroupingEngine:
    """Deterministic failure grouping and root-cause analysis engine."""

    def __init__(self, classifier: FailureClassifier | None = None) -> None:
        self.classifier = classifier or FailureClassifier()

    def group_failures(self, failures: list[FailureContext]) -> list[FailureGroup]:
        """Group a collection of test failures into evidence-backed clusters.

        Parameters
        ----------
        failures:
            List of failed test contexts to group.

        Returns
        -------
        list[FailureGroup]
            Grouped failures sorted by impact (size descending, then confidence descending).
        """
        if not failures:
            return []

        remaining: list[FailureContext] = list(failures)
        groups: list[FailureGroup] = []

        # 1. Cluster Authentication & Session Gate Failures
        auth_group, remaining = self._cluster_auth_failures(remaining)
        if auth_group:
            groups.append(auth_group)

        # 2. Cluster Network & Infrastructure / Gateway Failures
        network_groups, remaining = self._cluster_network_failures(remaining)
        groups.extend(network_groups)

        # 3. Cluster Shared Selector & Page Failures
        selector_groups, remaining = self._cluster_shared_selectors(remaining)
        groups.extend(selector_groups)

        # 4. Cluster Normalized Exception Signatures (for 2+ matching failures)
        signature_groups, remaining = self._cluster_by_signature(remaining)
        groups.extend(signature_groups)

        # 5. Create Singletons for remaining isolated failures
        for fc in remaining:
            groups.append(self._create_singleton_group(fc))

        # Sort groups: largest affected group first, then highest confidence
        groups.sort(key=lambda g: (len(g.failures), g.confidence), reverse=True)
        return groups

    def _cluster_auth_failures(
        self, failures: list[FailureContext]
    ) -> tuple[FailureGroup | None, list[FailureContext]]:
        """Identify and group failures stemming from authentication / session gates."""
        auth_hits: list[FailureContext] = []
        rest: list[FailureContext] = []

        auth_patterns = [
            "login", "sign-in", "signin", "unauthorized", "401", "403",
            "forbidden", "session expired", "token expired", "redirected to /login"
        ]

        for fc in failures:
            err = (fc.error_message or "").lower()
            page = (fc.current_page_url or "").lower()
            title = (fc.current_page_title or "").lower()

            is_auth = (
                any(p in err for p in ["401", "403", "unauthorized", "session expired", "token expired"])
                or ("/login" in page and "login" not in (fc.target_selector or "").lower() and fc.failed_step > 1)
                or "login" in title and fc.failed_step > 1
            )
            if is_auth:
                auth_hits.append(fc)
            else:
                rest.append(fc)

        # Only form a group if 2 or more tests were hit (or if single test with clear 401/403)
        if len(auth_hits) >= 2 or (len(auth_hits) == 1 and any(c in auth_hits[0].error_message for c in ["401", "403"])):
            test_ids = sorted({fc.test_id for fc in auth_hits})
            group = FailureGroup(
                group_id="fg-auth-gate",
                title=f"Authentication / Session Failure ({len(auth_hits)} tests affected)",
                shared_failure_type=FailureType.NAVIGATION_FAILURE,
                shared_root_cause=(
                    f"Authentication failure or session expiration redirected {len(auth_hits)} "
                    f"test execution(s) to login page."
                ),
                confidence=0.92,
                grouping_signal="authentication_redirect",
                evidence_summary=[
                    f"{len(auth_hits)} tests failed at or were redirected to login screen",
                    f"Sample error: '{auth_hits[0].error_message[:120]}'",
                ],
                failures=auth_hits,
                affected_test_ids=test_ids,
                suggested_action="Verify test authentication credentials, session cookie expiration, or login setup fixture.",
            )
            return group, rest

        return None, failures

    def _cluster_network_failures(
        self, failures: list[FailureContext]
    ) -> tuple[list[FailureGroup], list[FailureContext]]:
        """Identify network, gateway, and timeout failures."""
        net_hits: list[FailureContext] = []
        rest: list[FailureContext] = []

        net_signatures = [
            "econnrefused", "502", "503", "504", "bad gateway", "service unavailable",
            "gateway timeout", "err_connection_refused", "net::err_name_not_resolved"
        ]

        for fc in failures:
            err = (fc.error_message or "").lower()
            if any(sig in err for sig in net_signatures):
                net_hits.append(fc)
            else:
                rest.append(fc)

        if len(net_hits) >= 2 or (len(net_hits) == 1 and any(c in net_hits[0].error_message.lower() for c in ["502", "503", "504", "econnrefused"])):
            test_ids = sorted({fc.test_id for fc in net_hits})
            group = FailureGroup(
                group_id="fg-net-infrastructure",
                title=f"Backend Infrastructure / Service Unavailable ({len(net_hits)} tests affected)",
                shared_failure_type=FailureType.NETWORK_ERROR,
                shared_root_cause=f"Backend server outage, connection refusal, or gateway failure across {len(net_hits)} tests.",
                confidence=0.90,
                grouping_signal="network_infrastructure",
                evidence_summary=[
                    f"Network/gateway error signature found across {len(net_hits)} execution(s)",
                    f"Primary error: '{net_hits[0].error_message[:120]}'",
                ],
                failures=net_hits,
                affected_test_ids=test_ids,
                suggested_action="Check backend application service health, database connectivity, and mock API servers.",
            )
            return [group], rest

        return [], failures

    def _cluster_shared_selectors(
        self, failures: list[FailureContext]
    ) -> tuple[list[FailureGroup], list[FailureContext]]:
        """Group failures that share an identical broken selector and target page."""
        selector_map: dict[str, list[FailureContext]] = {}
        for fc in failures:
            sel = (fc.target_selector or "").strip()
            if sel:
                # Key by normalized selector and path
                page = (fc.current_page_url or "").split("?")[0].rstrip("/")
                key = f"{page}::{sel}"
                selector_map.setdefault(key, []).append(fc)

        groups: list[FailureGroup] = []
        claimed_execution_ids: set[str] = set()

        for key, group_fcs in selector_map.items():
            if len(group_fcs) >= 2:
                for fc in group_fcs:
                    claimed_execution_ids.add(fc.execution_id)

                page, sel = key.split("::", 1)
                test_ids = sorted({fc.test_id for fc in group_fcs})
                short_hash = hashlib.md5(key.encode()).hexdigest()[:8]
                groups.append(
                    FailureGroup(
                        group_id=f"fg-sel-{short_hash}",
                        title=f"Shared Selector Failure '{sel}' ({len(group_fcs)} tests)",
                        shared_failure_type=FailureType.SELECTOR_CHANGED,
                        shared_root_cause=f"DOM change or missing element for locator '{sel}' on page '{page or 'current page'}'.",
                        confidence=0.88,
                        grouping_signal="shared_selector_on_page",
                        evidence_summary=[
                            f"Selector '{sel}' failed across {len(group_fcs)} distinct test executions",
                            f"Target page URL: '{page or 'N/A'}'",
                        ],
                        failures=group_fcs,
                        affected_test_ids=test_ids,
                        suggested_action=f"Inspect updated DOM for '{sel}' or approve self-healed replacement locator.",
                    )
                )

        remaining = [fc for fc in failures if fc.execution_id not in claimed_execution_ids]
        return groups, remaining

    def _cluster_by_signature(
        self, failures: list[FailureContext]
    ) -> tuple[list[FailureGroup], list[FailureContext]]:
        """Group 2 or more failures sharing the same normalized error signature."""
        sig_map: dict[str, list[FailureContext]] = {}
        for fc in failures:
            sig = normalize_error_message(fc.error_message)
            sig_map.setdefault(sig, []).append(fc)

        groups: list[FailureGroup] = []
        claimed_ids: set[str] = set()

        for sig, group_fcs in sig_map.items():
            if len(group_fcs) >= 2:
                for fc in group_fcs:
                    claimed_ids.add(fc.execution_id)

                # Classify representative failure
                rep = group_fcs[0]
                cls_res = self.classifier.classify(rep.error_message)
                short_hash = hashlib.md5(sig.encode()).hexdigest()[:8]
                test_ids = sorted({fc.test_id for fc in group_fcs})

                groups.append(
                    FailureGroup(
                        group_id=f"fg-sig-{short_hash}",
                        title=f"Common Error Pattern: {cls_res.failure_type.value} ({len(group_fcs)} tests)",
                        shared_failure_type=cls_res.failure_type,
                        shared_root_cause=f"Shared error signature across {len(group_fcs)} tests: '{sig[:100]}'",
                        confidence=round(cls_res.confidence * 0.95, 4),
                        grouping_signal="normalized_exception",
                        evidence_summary=[
                            f"Normalized signature: '{sig[:120]}'",
                            f"Matched classification: {cls_res.failure_type.value} ({cls_res.confidence:.2%})",
                        ],
                        failures=group_fcs,
                        affected_test_ids=test_ids,
                        suggested_action="Review application stack trace and recent source code commits affecting this path.",
                    )
                )

        remaining = [fc for fc in failures if fc.execution_id not in claimed_ids]
        return groups, remaining

    def _create_singleton_group(self, fc: FailureContext) -> FailureGroup:
        """Create an individual group for an isolated failure."""
        cls_res = self.classifier.classify(fc.error_message)
        short_hash = hashlib.md5(f"{fc.test_id}:{fc.execution_id}".encode()).hexdigest()[:8]
        return FailureGroup(
            group_id=f"fg-single-{short_hash}",
            title=f"Isolated Failure: {fc.test_id} ({cls_res.failure_type.value})",
            shared_failure_type=cls_res.failure_type,
            shared_root_cause=f"Specific failure in {fc.test_id}: {cls_res.explanation}",
            confidence=round(cls_res.confidence, 4),
            grouping_signal="singleton",
            evidence_summary=[
                f"Error: '{fc.error_message[:120]}'",
                f"Action: '{fc.action}', Selector: '{fc.target_selector or 'None'}'",
            ],
            failures=[fc],
            affected_test_ids=[fc.test_id],
            suggested_action="Review individual test step and locator expectations.",
        )
