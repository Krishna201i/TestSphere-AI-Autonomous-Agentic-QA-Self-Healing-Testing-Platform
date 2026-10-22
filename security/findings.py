"""
security/findings.py
====================
The unified ``Finding`` record shared by QA and security results.

Fields follow Appendix B of the synopsis: severity, component, evidence,
root cause, confidence and retest result, plus what is needed to deduplicate
and track a finding through the remediate → retest loop.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, Field


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"

    @property
    def rank(self) -> int:
        """Lower = more severe; use as a sort key."""
        return list(Severity).index(self)


class FindingSource(str, Enum):
    SECURITY = "security"
    QA = "qa"


class FindingStatus(str, Enum):
    OPEN = "open"
    RESOLVED = "resolved"


class RetestResult(str, Enum):
    PASS = "pass"  # issue no longer reproduces
    FAIL = "fail"  # issue still present


class Finding(BaseModel):
    """One validated issue, from either the QA or the security side."""

    check_id: str = Field(..., description="Stable id of the check that produced it, e.g. SEC-HDR-CSP")
    source: FindingSource
    title: str
    severity: Severity
    component: str = Field(..., description="Where it lives: URL, URL + cookie name, locator, …")
    target_url: str = Field("", description="What was scanned/tested to find it; retests re-run against this")
    evidence: list[str] = Field(default_factory=list, description="Observed facts backing the finding")
    root_cause: str = ""
    recommendation: str = ""
    confidence: float = Field(1.0, ge=0.0, le=1.0)
    status: FindingStatus = FindingStatus.OPEN
    retest_result: RetestResult | None = None
    detected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def key(self) -> str:
        """Deduplication key: same check on the same component = same finding."""
        return hashlib.sha1(f"{self.check_id}|{self.component}".encode()).hexdigest()[:16]


def dedupe(findings: list[Finding]) -> list[Finding]:
    """Drop repeat findings (by ``key``), keeping the first, sorted most severe first."""
    unique: dict[str, Finding] = {}
    for f in findings:
        unique.setdefault(f.key, f)
    return sorted(unique.values(), key=lambda f: (f.severity.rank, f.check_id, f.component))
