"""TestSphere-AI — security testing (Attacker Agent, module 5.3).

Passive, scope-checked scanning for now; see ``passive_scanner``.
"""

from security.findings import Finding, FindingSource, FindingStatus, RetestResult, Severity, dedupe
from security.passive_scanner import PassiveScanner, ScanError
from security.scope import OutOfScopeError, ScopePolicy

__all__ = [
    "Finding", "FindingSource", "FindingStatus", "RetestResult", "Severity", "dedupe",
    "PassiveScanner", "ScanError", "OutOfScopeError", "ScopePolicy",
]
