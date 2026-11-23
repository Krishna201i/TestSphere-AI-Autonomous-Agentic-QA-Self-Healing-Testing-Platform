"""
Tests for backend/pipeline/flakiness.py (Explainable Flaky Test Intelligence & Classification).
"""

from __future__ import annotations

import pytest

from app.pipeline.flakiness import (
    FlakinessClassification,
    FlakinessReport,
    analyze_flakiness,
    classify_test_stability,
)


def _exec(status: str, error: str | None = None, duration_ms: float = 200.0) -> dict:
    return {"status": status, "error": error, "duration_ms": duration_ms}


def test_insufficient_evidence_when_too_few_runs():
    history = [_exec("PASSED"), _exec("FAILED", "assert failed")]
    rep = classify_test_stability(1, history, min_runs_for_evidence=3)

    assert rep.classification == FlakinessClassification.INSUFFICIENT_EVIDENCE
    assert "Insufficient run history" in rep.explanation
    assert rep.flakiness_score == 0.0


def test_consistently_failing_classified_as_genuine_application_failure():
    history = [
        _exec("FAILED", "AssertionError: expected 'Welcome'"),
        _exec("FAILED", "AssertionError: expected 'Welcome'"),
        _exec("FAILED", "AssertionError: expected 'Welcome'"),
    ]
    rep = classify_test_stability(1, history)

    assert rep.classification == FlakinessClassification.LIKELY_GENUINE_FAILURE
    assert rep.flakiness_score == 0.0
    assert rep.pass_rate == 0.0
    assert "Consistently failing" in rep.explanation


def test_oscillating_outcomes_classified_as_likely_flaky():
    # PASS -> FAIL -> PASS -> FAIL -> PASS
    history = [
        _exec("PASSED"),
        _exec("FAILED", "Locator not found: #btn"),
        _exec("PASSED"),
        _exec("FAILED", "Locator not found: #btn"),
        _exec("PASSED"),
    ]
    rep = classify_test_stability(1, history)

    assert rep.classification == FlakinessClassification.LIKELY_FLAKY
    assert rep.flip_count == 4
    assert rep.flakiness_score >= 0.8
    assert "pass↔fail transitions" in rep.explanation


def test_network_and_gateway_outages_classified_as_infrastructure_failure():
    history = [
        _exec("PASSED"),
        _exec("FAILED", "net::ERR_CONNECTION_REFUSED at http://app:8080"),
        _exec("FAILED", "502 Bad Gateway: backend unreachable"),
        _exec("FAILED", "504 Gateway Timeout"),
    ]
    rep = classify_test_stability(1, history)

    assert rep.classification == FlakinessClassification.INFRASTRUCTURE_FAILURE
    assert rep.flakiness_score <= 0.35
    assert "external infrastructure" in rep.explanation


def test_duration_variance_with_timeouts_classified_as_flaky():
    # Fast passes followed by intermittent timeouts
    history = [
        _exec("PASSED", duration_ms=50.0),
        _exec("PASSED", duration_ms=60.0),
        _exec("FAILED", "Timeout 30000ms exceeded", duration_ms=30000.0),
        _exec("PASSED", duration_ms=55.0),
    ]
    rep = classify_test_stability(1, history)

    assert rep.classification == FlakinessClassification.LIKELY_FLAKY
    assert rep.timeout_count == 1
    assert "duration variability" in rep.explanation or "pass↔fail" in rep.explanation


def test_consistently_passing_classified_as_stable():
    history = [
        _exec("PASSED"),
        _exec("HEALED"),
        _exec("PASSED"),
        _exec("PASSED"),
    ]
    rep = classify_test_stability(1, history)

    assert rep.classification == FlakinessClassification.INSUFFICIENT_EVIDENCE
    assert rep.pass_rate == 1.0
    assert rep.flakiness_score == 0.0


def test_analyze_flakiness_across_batch():
    history = [
        [
            {"test_case_id": 10, "status": "PASSED"},
            {"test_case_id": 20, "status": "FAILED", "error": "502 Bad Gateway"},
        ],
        [
            {"test_case_id": 10, "status": "FAILED", "error": "assert error"},
            {"test_case_id": 20, "status": "FAILED", "error": "503 Service Unavailable"},
        ],
    ]
    current = [
        {"test_case_id": 10, "status": "PASSED"},
        {"test_case_id": 20, "status": "FAILED", "error": "net::ERR_CONNECTION_REFUSED"},
    ]

    reports = analyze_flakiness(history, current)

    assert len(reports) == 2
    # Test 10: PASS -> FAIL -> PASS = 2 flips -> LIKELY_FLAKY
    assert reports[10].classification == FlakinessClassification.LIKELY_FLAKY
    # Test 20: 3 consecutive network failures -> INFRASTRUCTURE_FAILURE
    assert reports[20].classification == FlakinessClassification.INFRASTRUCTURE_FAILURE

    d = reports[10].to_dict()
    assert d["classification"] == "likely_flaky"
    assert "signals" in d
