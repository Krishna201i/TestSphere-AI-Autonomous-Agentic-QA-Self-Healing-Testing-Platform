"""
Unit tests for agents/analyzer/grouping.py (Deterministic Failure Grouping & Root-Cause Clustering).
"""

from __future__ import annotations

import pytest

from agents.analyzer.grouping import (
    FailureGroup,
    FailureGroupingEngine,
    normalize_error_message,
)
from agents.analyzer.schemas import FailureContext
from agents.schemas.enums import FailureType


def _make_failure(
    test_id: str,
    execution_id: str,
    error_message: str,
    target_selector: str = "",
    current_page_url: str = "https://app.local",
    failed_step: int = 1,
) -> FailureContext:
    return FailureContext(
        test_id=test_id,
        execution_id=execution_id,
        failed_step=failed_step,
        action="click" if target_selector else "navigate",
        target_selector=target_selector,
        error_message=error_message,
        current_page_url=current_page_url,
    )


def test_normalize_error_message_strips_transient_tokens():
    raw1 = "Timeout 30000ms exceeded at line 142 in file.js: 0x7fff5fbff820 session a1b2c3d4-e5f6-7890-1234-56789abcdef0"
    raw2 = "Timeout 5000ms exceeded at line 89 in file.js: 0xdeadbeef session 12345678-1234-1234-1234-123456789abc"

    norm1 = normalize_error_message(raw1)
    norm2 = normalize_error_message(raw2)

    assert norm1 == norm2
    assert "<TIMEOUT>" in norm1
    assert "<LINE>" in norm1
    assert "<ADDR>" in norm1
    assert "<UUID>" in norm1


def test_empty_failures_returns_empty_list():
    engine = FailureGroupingEngine()
    assert engine.group_failures([]) == []


def test_cluster_authentication_failures():
    engine = FailureGroupingEngine()
    f1 = _make_failure("TC-1", "exec-1", "User session expired; redirected to /login", failed_step=2, current_page_url="https://app.local/login")
    f2 = _make_failure("TC-2", "exec-2", "HTTP 401 Unauthorized for /api/user/profile", failed_step=3, current_page_url="https://app.local/login")
    f3 = _make_failure("TC-3", "exec-3", "Element not found #search-bar", target_selector="#search-bar", current_page_url="https://app.local/products")

    groups = engine.group_failures([f1, f2, f3])
    auth_groups = [g for g in groups if g.grouping_signal == "authentication_redirect"]

    assert len(auth_groups) == 1
    auth_grp = auth_groups[0]
    assert len(auth_grp.failures) == 2
    assert set(auth_grp.affected_test_ids) == {"TC-1", "TC-2"}
    assert "Authentication" in auth_grp.title
    assert auth_grp.confidence >= 0.90


def test_cluster_network_failures():
    engine = FailureGroupingEngine()
    f1 = _make_failure("TC-A", "exec-A", "net::ERR_CONNECTION_REFUSED at http://app.local:8080/api")
    f2 = _make_failure("TC-B", "exec-B", "502 Bad Gateway: backend service is down")

    groups = engine.group_failures([f1, f2])
    net_groups = [g for g in groups if g.grouping_signal == "network_infrastructure"]

    assert len(net_groups) == 1
    grp = net_groups[0]
    assert len(grp.failures) == 2
    assert grp.shared_failure_type == FailureType.NETWORK_ERROR
    assert "Backend Infrastructure" in grp.title


def test_cluster_shared_selectors_on_same_page():
    engine = FailureGroupingEngine()
    f1 = _make_failure("TC-10", "exec-10", "Timed out waiting for locator('#checkout-pay')", target_selector="#checkout-pay", current_page_url="https://app.local/checkout")
    f2 = _make_failure("TC-11", "exec-11", "Unable to click #checkout-pay button", target_selector="#checkout-pay", current_page_url="https://app.local/checkout")
    f3 = _make_failure("TC-12", "exec-12", "Unable to click #checkout-pay button", target_selector="#checkout-pay", current_page_url="https://app.local/settings")

    groups = engine.group_failures([f1, f2, f3])
    sel_groups = [g for g in groups if g.grouping_signal == "shared_selector_on_page"]

    assert len(sel_groups) == 1
    grp = sel_groups[0]
    assert len(grp.failures) == 2
    assert set(grp.affected_test_ids) == {"TC-10", "TC-11"}
    assert "#checkout-pay" in grp.title
    assert grp.shared_failure_type == FailureType.SELECTOR_CHANGED


def test_cluster_by_normalized_signature():
    engine = FailureGroupingEngine()
    f1 = _make_failure("TC-21", "exec-21", "Element is hidden or obscured by modal 0x1234 at line 50")
    f2 = _make_failure("TC-22", "exec-22", "Element is hidden or obscured by modal 0x5678 at line 99")

    groups = engine.group_failures([f1, f2])
    sig_groups = [g for g in groups if g.grouping_signal == "normalized_exception"]

    assert len(sig_groups) == 1
    grp = sig_groups[0]
    assert len(grp.failures) == 2
    assert set(grp.affected_test_ids) == {"TC-21", "TC-22"}


def test_isolated_singletons_preserved_and_serialized():
    engine = FailureGroupingEngine()
    f_single = _make_failure("TC-UNIQUE", "exec-unique", "Custom assertion failed: expected 5 items, found 3", target_selector="#list")

    groups = engine.group_failures([f_single])
    assert len(groups) == 1
    grp = groups[0]
    assert grp.grouping_signal == "singleton"
    assert grp.affected_test_ids == ["TC-UNIQUE"]
    assert len(grp.failures) == 1

    d = grp.to_dict()
    assert d["group_id"].startswith("fg-single-")
    assert d["failure_count"] == 1
    assert d["affected_test_ids"] == ["TC-UNIQUE"]


def test_no_failures_dropped_across_mixed_clusters():
    engine = FailureGroupingEngine()
    failures = [
        # Auth cluster (2)
        _make_failure("TC-1", "e-1", "401 Unauthorized for user", current_page_url="https://app.local/login", failed_step=2),
        _make_failure("TC-2", "e-2", "Redirected to /login unexpectedly", current_page_url="https://app.local/login", failed_step=3),
        # Selector cluster (2)
        _make_failure("TC-3", "e-3", "Locator not found: button.submit", target_selector="button.submit", current_page_url="https://app.local/form"),
        _make_failure("TC-4", "e-4", "Locator not found: button.submit", target_selector="button.submit", current_page_url="https://app.local/form"),
        # Singleton (1)
        _make_failure("TC-5", "e-5", "AssertionError: expected 'Active' but got 'Pending'", current_page_url="https://app.local/status"),
    ]

    groups = engine.group_failures(failures)
    total_grouped = sum(len(g.failures) for g in groups)
    assert total_grouped == len(failures)

    all_affected = []
    for g in groups:
        all_affected.extend(g.affected_test_ids)
    assert set(all_affected) == {"TC-1", "TC-2", "TC-3", "TC-4", "TC-5"}
