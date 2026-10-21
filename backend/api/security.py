"""
TestSphere-AI — Security Scan API Router.

Exposes the passive scanner (security/) to the dashboard.

Scope comes from server configuration only (``SECURITY_SCAN_ALLOWED_HOSTS``,
loopback by default).  Requests cannot widen it, so this endpoint cannot be
used to make the backend fetch arbitrary URLs (SSRF).
"""

from collections import Counter
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from backend.config import settings
from security import Finding, OutOfScopeError, PassiveScanner, ScanError, ScopePolicy
from security.remediation import propose, redact_headers
from security.scope import LOOPBACK_HOSTS

router = APIRouter(prefix="/security", tags=["Security Testing"])


class ScanRequest(BaseModel):
    url: str


def get_scanner() -> PassiveScanner:
    """Build a scanner limited to the configured scope (overridable in tests)."""
    extra = [h for h in settings.SECURITY_SCAN_ALLOWED_HOSTS.split(",") if h.strip()]
    return PassiveScanner(ScopePolicy.of(*LOOPBACK_HOSTS, *extra))


def _translate(exc: Exception) -> HTTPException:
    if isinstance(exc, OutOfScopeError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


@router.post("/scan", status_code=status.HTTP_200_OK)
async def scan(req: ScanRequest, scanner: PassiveScanner = Depends(get_scanner)) -> Dict[str, Any]:
    """Passively scan one authorized URL; findings are sorted most severe first.

    Each finding carries a ``remediation`` proposal built from the headers the
    target actually returned (also included, redacted, as ``response_headers``).
    """
    try:
        snap = await scanner.fetch(req.url)
    except (OutOfScopeError, ScanError) as exc:
        raise _translate(exc) from exc

    findings = scanner.analyze(snap)
    headers = [(k.decode("latin-1"), v.decode("latin-1")) for k, v in snap.headers.raw]
    return {
        "url": req.url,
        "final_url": snap.url,
        "status_code": snap.status,
        "summary": dict(Counter(f.severity.value for f in findings)),
        "response_headers": [list(h) for h in redact_headers(headers)],
        "findings": [
            f.model_dump(mode="json")
            | {"key": f.key, "remediation": propose(f, headers).model_dump()}
            for f in findings
        ],
    }


@router.post("/retest", status_code=status.HTTP_200_OK)
async def retest(finding: Finding, scanner: PassiveScanner = Depends(get_scanner)) -> Dict[str, Any]:
    """Re-run the scan behind a finding and report whether it still reproduces."""
    try:
        result = await scanner.retest(finding)
    except (OutOfScopeError, ScanError) as exc:
        raise _translate(exc) from exc
    return result.model_dump(mode="json") | {"key": result.key}
