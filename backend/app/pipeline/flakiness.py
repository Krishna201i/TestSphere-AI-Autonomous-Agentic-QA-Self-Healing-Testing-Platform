"""
TestSphere-AI — Intelligent Flaky Test Detection & Classification Module

Deterministic classification of test execution history into explainable stability categories:
  - Likely flaky test (pass <-> fail oscillations, high duration variance)
  - Likely genuine application failure (consistently failing without flips)
  - Infrastructure-related failure (network errors, gateway timeouts, browser crashes)
  - Insufficient evidence (< 3 completed runs or consistently passing)

Design Principles:
  - Explainable deterministic signals first.
  - Strict evidence requirements (never guess without completed run history).
  - Isolates infrastructure outages from test non-determinism.
  - Does not silently quarantine critical tests.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.models.test_execution import TestExecutionStatus

COMPLETED_STATUSES = frozenset({
    TestExecutionStatus.PASSED.value,
    TestExecutionStatus.HEALED.value,
    TestExecutionStatus.FAILED.value,
})

INFRASTRUCTURE_PATTERNS = [
    "econnrefused",
    "err_connection_refused",
    "502",
    "503",
    "504",
    "bad gateway",
    "service unavailable",
    "gateway timeout",
    "net::err_",
    "socket hang up",
    "target closed",
    "browser closed",
    "browser crashed",
    "protocol error",
    "connection reset",
]


class FlakinessClassification(str, Enum):
    """Categorization of test stability evidence."""

    LIKELY_FLAKY = "likely_flaky"
    LIKELY_GENUINE_FAILURE = "likely_genuine_failure"
    INFRASTRUCTURE_FAILURE = "infrastructure_failure"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


@dataclass
class FlakinessReport:
    """Comprehensive stability and flakiness assessment for a test case."""

    test_case_id: int | str
    classification: FlakinessClassification
    flakiness_score: float  # Normalized between 0.0 and 1.0
    flip_count: int
    total_runs: int
    pass_rate: float
    duration_mean_ms: float
    duration_stddev_ms: float
    timeout_count: int
    explanation: str
    signals: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "test_case_id": self.test_case_id,
            "classification": self.classification.value,
            "flakiness_score": round(self.flakiness_score, 4),
            "flip_count": self.flip_count,
            "total_runs": self.total_runs,
            "pass_rate": round(self.pass_rate, 4),
            "duration_mean_ms": round(self.duration_mean_ms, 2),
            "duration_stddev_ms": round(self.duration_stddev_ms, 2),
            "timeout_count": self.timeout_count,
            "explanation": self.explanation,
            "signals": self.signals,
        }


def _is_infrastructure_error(error_message: str | None) -> bool:
    if not error_message:
        return False
    lower = error_message.lower()
    return any(p in lower for p in INFRASTRUCTURE_PATTERNS)


def classify_test_stability(
    test_case_id: int | str,
    execution_history: list[dict[str, Any]],
    min_runs_for_evidence: int = 3,
    flaky_flips_threshold: int = 2,
) -> FlakinessReport:
    """Classify the stability of a single test case given its execution history.

    Parameters
    ----------
    test_case_id:
        Identifier of the test case.
    execution_history:
        List of execution dictionaries (oldest first).
    min_runs_for_evidence:
        Minimum completed runs required to diagnose flakiness (default 3).
    flaky_flips_threshold:
        Number of pass <-> fail transitions to qualify as flaky (default 2).
    """
    completed = [
        item for item in execution_history
        if item.get("status") in COMPLETED_STATUSES
    ]

    total = len(completed)
    if total < min_runs_for_evidence:
        return FlakinessReport(
            test_case_id=test_case_id,
            classification=FlakinessClassification.INSUFFICIENT_EVIDENCE,
            flakiness_score=0.0,
            flip_count=0,
            total_runs=total,
            pass_rate=1.0 if total == 0 else sum(1 for r in completed if r["status"] != TestExecutionStatus.FAILED.value) / total,
            duration_mean_ms=0.0,
            duration_stddev_ms=0.0,
            timeout_count=0,
            explanation=f"Insufficient run history ({total} completed runs; minimum {min_runs_for_evidence} required).",
            signals={"completed_count": total},
        )

    # Outcome booleans: True = passed/healed, False = failed
    outcomes = [r["status"] != TestExecutionStatus.FAILED.value for r in completed]
    passes = sum(1 for o in outcomes if o)
    pass_rate = passes / total

    # Count state flips
    flips = sum(1 for a, b in zip(outcomes, outcomes[1:], strict=False) if a != b)

    # Durations analysis
    durations = [float(r["duration_ms"]) for r in completed if r.get("duration_ms") is not None and r["duration_ms"] > 0]
    mean_dur = sum(durations) / len(durations) if durations else 0.0
    if len(durations) > 1:
        variance = sum((d - mean_dur) ** 2 for d in durations) / (len(durations) - 1)
        stddev_dur = math.sqrt(variance)
    else:
        stddev_dur = 0.0

    # Count timeout and infrastructure errors
    failures = [r for r in completed if r["status"] == TestExecutionStatus.FAILED.value]
    infra_failures = sum(1 for r in failures if _is_infrastructure_error(r.get("error") or r.get("error_message")))
    timeouts = sum(
        1 for r in failures
        if "timeout" in str(r.get("error") or r.get("error_message") or "").lower()
    )

    signals = {
        "total_completed": total,
        "passes": passes,
        "failures": len(failures),
        "flips": flips,
        "infra_failures": infra_failures,
        "timeouts": timeouts,
        "cv_duration": round(stddev_dur / mean_dur, 3) if mean_dur > 0 else 0.0,
    }

    # Classification rules (deterministic priority order)

    # 1. Infrastructure Outage: if majority of failures are network/infra
    if failures and infra_failures >= len(failures) * 0.6:
        score = min(0.35, 0.10 * infra_failures)
        return FlakinessReport(
            test_case_id=test_case_id,
            classification=FlakinessClassification.INFRASTRUCTURE_FAILURE,
            flakiness_score=score,
            flip_count=flips,
            total_runs=total,
            pass_rate=pass_rate,
            duration_mean_ms=mean_dur,
            duration_stddev_ms=stddev_dur,
            timeout_count=timeouts,
            explanation=(
                f"{infra_failures} of {len(failures)} failures caused by external infrastructure "
                f"or network instability (e.g. gateway errors, connection resets)."
            ),
            signals=signals,
        )

    # 2. Consistent genuine application failure: 0 passes, or 0 flips with latest FAILED
    if passes == 0:
        return FlakinessReport(
            test_case_id=test_case_id,
            classification=FlakinessClassification.LIKELY_GENUINE_FAILURE,
            flakiness_score=0.0,
            flip_count=flips,
            total_runs=total,
            pass_rate=0.0,
            duration_mean_ms=mean_dur,
            duration_stddev_ms=stddev_dur,
            timeout_count=timeouts,
            explanation=f"Consistently failing across all {total} observed executions (0% pass rate).",
            signals=signals,
        )

    # 3. Flaky test: pass <-> fail oscillations
    if flips >= flaky_flips_threshold:
        score = min(1.0, 0.50 + 0.15 * flips)
        return FlakinessReport(
            test_case_id=test_case_id,
            classification=FlakinessClassification.LIKELY_FLAKY,
            flakiness_score=score,
            flip_count=flips,
            total_runs=total,
            pass_rate=pass_rate,
            duration_mean_ms=mean_dur,
            duration_stddev_ms=stddev_dur,
            timeout_count=timeouts,
            explanation=(
                f"Observed {flips} pass↔fail transitions across {total} runs with {pass_rate:.1%} "
                f"pass rate, indicating non-deterministic execution."
            ),
            signals=signals,
        )

    # 4. Duration variability with intermittent timeouts
    cv = (stddev_dur / mean_dur) if mean_dur > 0 else 0.0
    if cv > 0.8 and timeouts >= 1 and passes > 0:
        score = min(0.85, 0.40 + 0.20 * timeouts)
        return FlakinessReport(
            test_case_id=test_case_id,
            classification=FlakinessClassification.LIKELY_FLAKY,
            flakiness_score=score,
            flip_count=flips,
            total_runs=total,
            pass_rate=pass_rate,
            duration_mean_ms=mean_dur,
            duration_stddev_ms=stddev_dur,
            timeout_count=timeouts,
            explanation=(
                f"High duration variability (CV={cv:.2f}) with intermittent timeouts "
                f"indicating timing-sensitive execution flakiness."
            ),
            signals=signals,
        )

    # 5. Stable pass (100% pass rate) or single isolated regression
    if pass_rate == 1.0:
        return FlakinessReport(
            test_case_id=test_case_id,
            classification=FlakinessClassification.INSUFFICIENT_EVIDENCE,
            flakiness_score=0.0,
            flip_count=flips,
            total_runs=total,
            pass_rate=1.0,
            duration_mean_ms=mean_dur,
            duration_stddev_ms=stddev_dur,
            timeout_count=timeouts,
            explanation=f"Consistently passing across {total} consecutive executions (100% pass rate).",
            signals=signals,
        )

    # Default: single flip (a fresh regression or fix, not flaky)
    return FlakinessReport(
        test_case_id=test_case_id,
        classification=FlakinessClassification.LIKELY_GENUINE_FAILURE if not outcomes[-1] else FlakinessClassification.INSUFFICIENT_EVIDENCE,
        flakiness_score=0.10,
        flip_count=flips,
        total_runs=total,
        pass_rate=pass_rate,
        duration_mean_ms=mean_dur,
        duration_stddev_ms=stddev_dur,
        timeout_count=timeouts,
        explanation=f"Single status transition observed ({flips} flip across {total} runs); consistent with new regression or fix.",
        signals=signals,
    )


def analyze_flakiness(
    history: list[list[dict[str, Any]]],
    current: list[dict[str, Any]],
    min_runs_for_evidence: int = 3,
    flaky_flips_threshold: int = 2,
) -> dict[int | str, FlakinessReport]:
    """Analyze flakiness across all test cases present in history and current run."""
    per_test_runs: dict[int | str, list[dict[str, Any]]] = {}

    for batch in [*history, current]:
        for item in batch:
            tc_id = item.get("test_case_id")
            if tc_id is not None:
                per_test_runs.setdefault(tc_id, []).append(item)

    reports: dict[int | str, FlakinessReport] = {}
    for tc_id, runs in per_test_runs.items():
        reports[tc_id] = classify_test_stability(
            test_case_id=tc_id,
            execution_history=runs,
            min_runs_for_evidence=min_runs_for_evidence,
            flaky_flips_threshold=flaky_flips_threshold,
        )

    return reports
