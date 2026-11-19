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

import asyncio
import json
from collections import Counter
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from backend.auth import User, actor_for, get_current_user, scope
from backend.config import settings
from backend.database.session import get_db
from backend.database.store import Store
from backend.netguard import BlockedTargetError, PinnedTransport
from backend.ratelimit import limit_runs
from backend.services import domain_verify
from backend.services import security_service as store
from security import (
    ACTIVE_CHECK_IDS,
    EXPOSURE_CHECK_IDS,
    ActiveScanError,
    ActiveScanner,
    Finding,
    OutOfScopeError,
    PassiveScanner,
    ScanError,
    ScopePolicy,
)
from security import ai as security_ai
from security.remediation import propose, redact_headers
from security.scope import LOOPBACK_HOSTS

router = APIRouter(prefix="/security", tags=["Security Testing"])

DEFAULT_ACTOR = "dev_active"


class ScanRequest(BaseModel):
    url: str
    actor: str = DEFAULT_ACTOR
    active: bool = False  # also run the active (DAST) scanner, when the server allows it


class ActorRequest(BaseModel):
    actor: str = DEFAULT_ACTOR


def _configured_scope() -> ScopePolicy:
    extra = [h for h in settings.SECURITY_SCAN_ALLOWED_HOSTS.split(",") if h.strip()]
    return ScopePolicy.of(*LOOPBACK_HOSTS, *extra)


class _ScannerTransport(PinnedTransport):
    """The server's SSRF guard for the scanners: scope says which hosts may be
    tested, this says the addresses they resolve to must be public on a hosted
    server (loopback is in every scope, for local development, so without it any
    user could scan the server's own internal ports).  A refusal reads like any
    other out-of-scope target."""

    async def handle_async_request(self, request):
        try:
            return await super().handle_async_request(request)
        except BlockedTargetError as exc:
            raise OutOfScopeError(str(exc)) from exc


def get_scanner() -> PassiveScanner:
    """Build a passive scanner limited to the configured scope (overridable in tests)."""
    return PassiveScanner(_configured_scope(), transport=_ScannerTransport())


def get_active_scanner() -> ActiveScanner:
    """Build an active scanner limited to the configured scope (overridable in tests)."""
    from backend.services.xss_confirm import confirm_in_browser

    # Reflected XSS is confirmed by running the payload in the guarded browser
    return ActiveScanner(_configured_scope(), max_requests=settings.SECURITY_ACTIVE_MAX_REQUESTS,
                         transport=_ScannerTransport(), xss_confirmer=confirm_in_browser)


def active_scan_refusal(uid: str | None, url: str | None = None, db: Store | None = None) -> str | None:
    """Why *uid* may not run the active scanner (against *url*), or None when it may.

    The server must allow active scanning, the account must be listed, and
    (with *url* and *db*) the account must have proven it owns the host.
    """
    if not settings.SECURITY_ACTIVE_SCAN:
        return "Active scanning is turned off on this server"
    if not settings.AUTH_REQUIRED:
        return None
    allowed = {u.strip() for u in settings.SECURITY_ACTIVE_SCAN_USERS.split(",") if u.strip()}
    if uid not in allowed:
        return "Active scanning is not enabled for this account (SECURITY_ACTIVE_SCAN_USERS)"
    if url is not None and db is not None:
        return domain_verify.refusal(db, uid, url)
    return None


def checks_run(active: bool, probed: bool = True) -> Callable[[str], bool]:
    """Which finding kinds a page scan checked: the passive ones always, the
    active ones only when the active scanner ran, exposed files only when they
    were probed for; dependency findings never (they come from the repository)."""
    return lambda check_id: (not check_id.startswith("SEC-DEP-")
                             and (active or check_id not in ACTIVE_CHECK_IDS)
                             and (probed or check_id not in EXPOSURE_CHECK_IDS))


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
    active_scanner: ActiveScanner = Depends(get_active_scanner),
    db: Store = Depends(get_db),
    user: User = Depends(limit_runs),
) -> dict[str, Any]:
    """Scan one authorized URL; findings are sorted most severe first.

    Always passive (headers, cookies, TLS, …).  When ``active`` is set and the
    server has ``SECURITY_ACTIVE_SCAN`` on, it also runs the DAST scanner
    (reflected XSS, SQL injection, open redirect) against the same URL.

    Each finding carries a ``remediation`` proposal built from the headers the
    target actually returned (also included, redacted, as ``response_headers``),
    plus its tracked state (approval, retest) from earlier scans.
    """
    actor = await asyncio.to_thread(actor_for, user, req.actor)
    if req.active and not settings.SECURITY_ACTIVE_SCAN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Active scanning is turned off on this server. Set SECURITY_ACTIVE_SCAN=true to "
                                   "enable it, and only for hosts you are authorized to test.")
    if req.active and (refusal := await asyncio.to_thread(active_scan_refusal, user.uid, req.url, db)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"{refusal}.")
    try:
        snap = await scanner.fetch(req.url, probe_files=True)
        active_findings: list[Finding] = []
        if req.active:
            active_findings = await active_scanner.scan(req.url)
    except (OutOfScopeError, ScanError, ActiveScanError) as exc:
        await asyncio.to_thread(store.record_audit, db, actor=actor, kind="scan", level="error",
                                message=f"Scan refused/failed for {req.url}: {exc}", owner_uid=user.uid)
        raise _translate(exc) from exc
    # Saving reads and writes each finding: in a thread, so other requests are not held up
    result = await asyncio.to_thread(scan_result, db, scanner, snap, req.url, actor=actor,
                                     owner_uid=None if user.local else user.uid, extra_findings=active_findings,
                                     active=bool(req.active))
    # Best-effort AI triage: reasons only over findings already produced in
    # scope, never contacts the target, and leaves the result untouched on any
    # failure.  analyze() re-runs on the already-fetched snapshot (cheap, no I/O).
    if security_ai.enabled():
        await _attach_ai(result, req.url, scanner.analyze(snap) + active_findings,
                         db=db, owner_uid=None if user.local else user.uid)
    return result


async def _attach_ai(result: dict[str, Any], url: str, findings: list[Finding], *,
                     db: Store | None = None, owner_uid: str | None = None) -> None:
    """Annotate each returned finding with the model's triage, in place, and
    keep it on the stored finding (with *db*)."""
    insights = await security_ai.triage(url, findings)
    if not insights:
        return
    if db is not None:
        await asyncio.to_thread(store.save_ai_insights, db,
                                {key: insight.model_dump() for key, insight in insights.items()}, owner_uid)
    for row in result["findings"]:
        insight = insights.get(row.get("key"))
        if insight:
            row["ai"] = insight.model_dump()
    # Surface the model's ordering without touching severity: most urgent first,
    # then fall back to the existing (severity) order for anything unranked.
    ranked = {row["key"]: row["ai"]["priority"] for row in result["findings"] if row.get("ai", {}).get("priority")}
    if ranked:
        result["findings"].sort(key=lambda r: ranked.get(r.get("key"), 10_000))
        result["ai_triage"] = True


def scan_result(db: Store, scanner: PassiveScanner, snap, url: str, *, actor: str, owner_uid: str | None,
                extra_findings: list[Finding] | None = None, active: bool = False,
                probed: bool = True) -> dict[str, Any]:
    """Analyze a fetched page, persist the findings and audit the scan (also used by the pipeline).

    *extra_findings* are findings produced elsewhere (e.g. the active scanner)
    that are persisted and retested alongside the passive ones.  *active* says
    the active scanner ran: only then may its earlier findings be resolved by
    their absence.
    """
    findings = scanner.analyze(snap) + list(extra_findings or [])
    headers = [(k.decode("latin-1"), v.decode("latin-1")) for k, v in snap.headers.raw]
    payload = [
        f.model_dump(mode="json") | {"key": f.key, "remediation": propose(f, headers).model_dump()}
        for f in findings
    ]
    saved = store.save_scan(db, url, payload, owner_uid=owner_uid, checked=checks_run(active, probed))

    store.record_audit(
        db, actor=actor, kind="scan", level="warn" if findings else "success",
        message=f"{'Active and passive' if active else 'Passive'} scan of {url}: {len(findings)} finding(s)",
        owner_uid=owner_uid,
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
    target_url: str | None = None, db: Store = Depends(get_db), user: User = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """The caller's tracked findings (optionally for one target), most recently seen first."""
    return [store.serialize(row) for row in store.list_findings(db, target_url, **scope(user))]


@router.post("/findings/{key}/approve", status_code=status.HTTP_200_OK)
def approve_finding(
    key: str, req: ActorRequest, db: Store = Depends(get_db), user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Record a human approval of the finding's fix proposal."""
    actor = actor_for(user, req.actor)
    row = store.approve(db, _finding_or_404(db, key, user), actor)
    store.record_audit(db, actor=actor, kind="approval", level="success", ref=key,
                       message=f"{actor} approved the fix for {row.check_id} ({row.title})", owner_uid=user.uid)
    return store.serialize(row)


async def _retest(row, scanner: PassiveScanner, db: Store, actor: str, owner_uid: str | None,
                  active_scanner: ActiveScanner | None = None) -> dict[str, Any]:
    if row.check_id.startswith("SEC-DEP-"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="A vulnerable dependency is retested by ingesting the repository again "
                                   "(it is checked on every push, or run the pipeline).")
    if row.check_id in ACTIVE_CHECK_IDS and not settings.SECURITY_ACTIVE_SCAN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Active scanning is turned off on this server, so this finding cannot be retested. "
                                   "Set SECURITY_ACTIVE_SCAN=true to enable it.")
    if row.check_id in ACTIVE_CHECK_IDS and (
            refusal := await asyncio.to_thread(active_scan_refusal, owner_uid, row.target_url, db)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail=f"{refusal}, so this finding cannot be retested.")
    retester = active_scanner if row.check_id in ACTIVE_CHECK_IDS else scanner
    finding = Finding.model_validate(json.loads(row.data))
    await asyncio.to_thread(store.record_audit, db, actor=actor, kind="retest", ref=row.key,
                            message=f"Retest started for {row.check_id} on {row.target_url}", owner_uid=owner_uid)
    try:
        result = await retester.retest(finding)
    except (OutOfScopeError, ScanError, ActiveScanError) as exc:
        await asyncio.to_thread(store.record_audit, db, actor=actor, kind="retest", level="error", ref=row.key,
                                message=f"Retest failed for {row.check_id}: {exc}", owner_uid=owner_uid)
        raise _translate(exc) from exc
    row = await asyncio.to_thread(store.save_retest, db, row, result.retest_result.value, result.status.value)
    await asyncio.to_thread(
        store.record_audit, db, actor=actor, kind="retest", ref=row.key,
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
    active_scanner: ActiveScanner = Depends(get_active_scanner),
    db: Store = Depends(get_db),
    user: User = Depends(limit_runs),
) -> dict[str, Any]:
    """Re-run the check behind a tracked finding and store the result."""
    row = await asyncio.to_thread(_finding_or_404, db, key, user)
    actor = await asyncio.to_thread(actor_for, user, req.actor)
    return await _retest(row, scanner, db, actor, user.uid,
                         active_scanner=active_scanner)


@router.post("/retest", status_code=status.HTTP_200_OK)
async def retest(
    finding: Finding,
    scanner: PassiveScanner = Depends(get_scanner),
    active_scanner: ActiveScanner = Depends(get_active_scanner),
    db: Store = Depends(get_db),
    user: User = Depends(limit_runs),
) -> dict[str, Any]:
    """Stateless retest of a finding passed in the body (not stored).

    Each finding is retested by the check that produced it: an XSS or SQL
    injection finding needs the active scanner (with the same permission as a
    scan), and passing one to the passive scanner wrongly came back "pass".
    """
    if finding.check_id.startswith("SEC-DEP-"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="A vulnerable dependency is retested by ingesting the repository again.")
    retester = scanner
    if finding.check_id in ACTIVE_CHECK_IDS:
        if refusal := await asyncio.to_thread(active_scan_refusal, user.uid,
                                              finding.target_url or finding.component, db):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail=f"{refusal}, so this finding cannot be retested.")
        retester = active_scanner
    try:
        result = await retester.retest(finding)
    except (OutOfScopeError, ScanError, ActiveScanError) as exc:
        raise _translate(exc) from exc
    return result.model_dump(mode="json") | {"key": result.key}
