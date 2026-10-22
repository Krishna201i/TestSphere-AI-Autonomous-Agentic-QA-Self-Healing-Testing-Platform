"""
TestSphere-AI — Security Scan API Router.

Exposes the passive scanner (security/) to the dashboard and persists
findings, approvals and retests with an audit trail.

Scope comes from server configuration only (``SECURITY_SCAN_ALLOWED_HOSTS``,
loopback by default).  Requests cannot widen it, so this endpoint cannot be
used to make the backend fetch arbitrary URLs (SSRF).

When sign-in is required, findings are per user and the audit actor is the
verified identity; with sign-in off, ``actor`` is whatever the client sends.
"""

import json
from collections import Counter
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from backend.auth import User, actor_for, get_current_user, scope
from backend.ratelimit import limit_runs
from backend.config import settings
from backend.database.session import get_db
from backend.database.store import Store
from backend.services import security_service as store
from security import Finding, OutOfScopeError, PassiveScanner, ScanError, ScopePolicy
from security.remediation import propose, redact_headers
from security.scope import LOOPBACK_HOSTS

router = APIRouter(prefix="/security", tags=["Security Testing"])

DEFAULT_ACTOR = "dev_active"


class ScanRequest(BaseModel):
    url: str
    actor: str = DEFAULT_ACTOR


class ActorRequest(BaseModel):
    actor: str = DEFAULT_ACTOR


def get_scanner() -> PassiveScanner:
    """Build a scanner limited to the configured scope (overridable in tests)."""
    extra = [h for h in settings.SECURITY_SCAN_ALLOWED_HOSTS.split(",") if h.strip()]
    return PassiveScanner(ScopePolicy.of(*LOOPBACK_HOSTS, *extra))


def _translate(exc: Exception) -> HTTPException:
    if isinstance(exc, OutOfScopeError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


def _finding_or_404(db: Store, key: str, user: User):
    row = store.get_finding(db, key, **scope(user))
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Finding {key} not found")
    return row


@router.post("/scan", status_code=status.HTTP_200_OK)
async def scan(
    req: ScanRequest,
    scanner: PassiveScanner = Depends(get_scanner),
    db: Store = Depends(get_db),
    user: User = Depends(limit_runs),
) -> Dict[str, Any]:
    """Passively scan one authorized URL; findings are sorted most severe first.

    Each finding carries a ``remediation`` proposal built from the headers the
    target actually returned (also included, redacted, as ``response_headers``),
    plus its tracked state (approval, retest) from earlier scans.
    """
    actor = actor_for(user, req.actor)
    try:
        snap = await scanner.fetch(req.url)
    except (OutOfScopeError, ScanError) as exc:
        store.record_audit(db, actor=actor, kind="scan", level="error", message=f"Scan refused/failed for {req.url}: {exc}",
                           owner_uid=user.uid)
        raise _translate(exc) from exc
    return scan_result(db, scanner, snap, req.url, actor=actor, owner_uid=None if user.local else user.uid)


def scan_result(db: Store, scanner: PassiveScanner, snap, url: str, *, actor: str, owner_uid: Optional[str]) -> Dict[str, Any]:
    """Analyze a fetched page, persist the findings and audit the scan (also used by the pipeline)."""
    findings = scanner.analyze(snap)
    headers = [(k.decode("latin-1"), v.decode("latin-1")) for k, v in snap.headers.raw]
    payload = [
        f.model_dump(mode="json") | {"key": f.key, "remediation": propose(f, headers).model_dump()}
        for f in findings
    ]
    saved = store.save_scan(db, url, payload, owner_uid=owner_uid)

    store.record_audit(
        db, actor=actor, kind="scan", level="warn" if findings else "success",
        message=f"Passive scan of {url}: {len(findings)} finding(s)", owner_uid=owner_uid,
    )
    for row in saved["resolved"]:
        store.record_audit(db, actor="scanner", kind="retest", level="success", ref=row.key,
                           message=f"{row.check_id} no longer reproduces on {row.target_url} — resolved", owner_uid=owner_uid)
    for row in saved["reopened"]:
        store.record_audit(db, actor="scanner", kind="scan", level="error", ref=row.key,
                           message=f"Regression: {row.check_id} reappeared on {row.target_url} — reopened", owner_uid=owner_uid)

    return {
        "url": url,
        "final_url": snap.url,
        "status_code": snap.status,
        "summary": dict(Counter(f.severity.value for f in findings)),
        "response_headers": [list(h) for h in redact_headers(headers)],
        "findings": [store.serialize(row) for row in saved["current"]],
        "resolved": [store.serialize(row) for row in saved["resolved"]],
        "reopened": [store.serialize(row) for row in saved["reopened"]],
    }


@router.get("/findings", status_code=status.HTTP_200_OK)
def list_findings(
    target_url: Optional[str] = None, db: Store = Depends(get_db), user: User = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    """The caller's tracked findings (optionally for one target), most recently seen first."""
    return [store.serialize(row) for row in store.list_findings(db, target_url, **scope(user))]


@router.post("/findings/{key}/approve", status_code=status.HTTP_200_OK)
def approve_finding(
    key: str, req: ActorRequest, db: Store = Depends(get_db), user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """Record a human approval of the finding's fix proposal."""
    actor = actor_for(user, req.actor)
    row = store.approve(db, _finding_or_404(db, key, user), actor)
    store.record_audit(db, actor=actor, kind="approval", level="success", ref=key,
                       message=f"{actor} approved the fix for {row.check_id} ({row.title})", owner_uid=user.uid)
    return store.serialize(row)


async def _retest(row, scanner: PassiveScanner, db: Store, actor: str, owner_uid: Optional[str]) -> Dict[str, Any]:
    finding = Finding.model_validate(json.loads(row.data))
    store.record_audit(db, actor=actor, kind="retest", ref=row.key, message=f"Retest started for {row.check_id} on {row.target_url}",
                       owner_uid=owner_uid)
    try:
        result = await scanner.retest(finding)
    except (OutOfScopeError, ScanError) as exc:
        store.record_audit(db, actor=actor, kind="retest", level="error", ref=row.key, message=f"Retest failed for {row.check_id}: {exc}",
                           owner_uid=owner_uid)
        raise _translate(exc) from exc
    row = store.save_retest(db, row, result.retest_result.value, result.status.value)
    store.record_audit(
        db, actor=actor, kind="retest", ref=row.key,
        level="success" if result.retest_result.value == "pass" else "warn",
        message=f"{row.check_id}: retest {result.retest_result.value.upper()} — {result.status.value}",
        owner_uid=owner_uid,
    )
    return store.serialize(row)


@router.post("/findings/{key}/retest", status_code=status.HTTP_200_OK)
async def retest_finding(
    key: str,
    req: ActorRequest,
    scanner: PassiveScanner = Depends(get_scanner),
    db: Store = Depends(get_db),
    user: User = Depends(limit_runs),
) -> Dict[str, Any]:
    """Re-run the check behind a tracked finding and store the result."""
    return await _retest(_finding_or_404(db, key, user), scanner, db, actor_for(user, req.actor), user.uid)


@router.post("/retest", status_code=status.HTTP_200_OK)
async def retest(
    finding: Finding, scanner: PassiveScanner = Depends(get_scanner), _user: User = Depends(limit_runs),
) -> Dict[str, Any]:
    """Stateless retest of a finding passed in the body (not stored)."""
    try:
        result = await scanner.retest(finding)
    except (OutOfScopeError, ScanError) as exc:
        raise _translate(exc) from exc
    return result.model_dump(mode="json") | {"key": result.key}
