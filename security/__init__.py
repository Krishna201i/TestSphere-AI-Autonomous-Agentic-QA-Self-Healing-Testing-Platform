"""TestSphere-AI — security testing (Attacker Agent, module 5.3).

Scope-checked scanning: ``passive_scanner`` (safe, always on) and
``active_scanner`` (DAST, opt-in, against your own apps).
"""

from security.active_scanner import ACTIVE_CHECK_IDS, ActiveScanError, ActiveScanner
from security.ai import AIInsight, triage as ai_triage
from security.findings import (
    Finding,
    FindingSource,
    FindingStatus,
    RetestResult,
    Severity,
    dedupe,
)
from security.passive_scanner import PassiveScanner, ScanError
from security.scope import OutOfScopeError, ScopePolicy

__all__ = [
    "Finding", "FindingSource", "FindingStatus", "RetestResult", "Severity", "dedupe",
    "PassiveScanner", "ScanError", "ActiveScanner", "ActiveScanError", "ACTIVE_CHECK_IDS",
    "OutOfScopeError", "ScopePolicy",
    "AIInsight", "ai_triage",
]
