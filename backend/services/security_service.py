"""
TestSphere-AI — Security finding persistence and the audit trail.
"""

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from backend.models.security import AuditEvent, SecurityFinding


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: Optional[datetime]) -> Optional[str]:
    """ISO 8601 in UTC; SQLite returns naive datetimes, which are stored as UTC."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def record_audit(
    db: Session, *, actor: str, kind: str, message: str, level: str = "info", ref: Optional[str] = None,
) -> AuditEvent:
    event = AuditEvent(actor=actor, kind=kind, message=message, level=level, ref=ref, at=_now())
    db.add(event)
    db.commit()
    return event


def list_audit(db: Session, limit: int = 200) -> List[Dict[str, Any]]:
    rows = db.query(AuditEvent).order_by(AuditEvent.at.desc(), AuditEvent.id.desc()).limit(limit).all()
    return [
        {"id": r.id, "at": _iso(r.at), "actor": r.actor, "kind": r.kind, "level": r.level, "message": r.message, "ref": r.ref}
        for r in rows
    ]


def serialize(row: SecurityFinding) -> Dict[str, Any]:
    """Stored finding JSON plus its tracked lifecycle fields."""
    return json.loads(row.data) | {
        "key": row.key,
        "status": row.status,
        "retest_result": row.retest_result,
        "retested_at": _iso(row.retested_at),
        "approved_by": row.approved_by,
        "approved_at": _iso(row.approved_at),
        "first_seen": _iso(row.first_seen),
        "last_seen": _iso(row.last_seen),
    }


def get_finding(db: Session, key: str) -> Optional[SecurityFinding]:
    return db.query(SecurityFinding).filter(SecurityFinding.key == key).first()


def list_findings(db: Session, target_url: Optional[str] = None) -> List[SecurityFinding]:
    query = db.query(SecurityFinding)
    if target_url:
        query = query.filter(SecurityFinding.target_url == target_url)
    return query.order_by(SecurityFinding.last_seen.desc()).all()


def save_scan(db: Session, target_url: str, findings: List[Dict[str, Any]]) -> Dict[str, List[SecurityFinding]]:
    """Upsert this scan's findings for *target_url*.

    - New findings are inserted as open.
    - A previously resolved finding that shows up again is a regression:
      reopened, approval and retest cleared.
    - Open findings for this target that no longer appear are resolved —
      the scan itself is a retest that passed.
    """
    now = _now()
    seen = {f["key"] for f in findings}
    current, reopened, resolved = [], [], []

    for f in findings:
        data = json.dumps({k: v for k, v in f.items() if k != "key"})
        row = get_finding(db, f["key"])
        if row is None:
            row = SecurityFinding(
                key=f["key"], target_url=target_url, check_id=f["check_id"], severity=f["severity"],
                title=f["title"], data=data, status="open", first_seen=now, last_seen=now,
            )
            db.add(row)
        else:
            if row.status == "resolved":
                row.status = "open"
                row.retest_result = None
                row.retested_at = None
                row.approved_by = None
                row.approved_at = None
                reopened.append(row)
            row.severity, row.title, row.data, row.last_seen = f["severity"], f["title"], data, now
        current.append(row)

    for row in list_findings(db, target_url):
        if row.key not in seen and row.status == "open":
            row.status, row.retest_result, row.retested_at = "resolved", "pass", now
            resolved.append(row)

    db.commit()
    return {"current": current, "reopened": reopened, "resolved": resolved}


def approve(db: Session, row: SecurityFinding, actor: str) -> SecurityFinding:
    row.approved_by = actor
    row.approved_at = _now()
    db.commit()
    return row


def save_retest(db: Session, row: SecurityFinding, result: str, status: str) -> SecurityFinding:
    row.retest_result = result
    row.status = status
    row.retested_at = _now()
    db.commit()
    return row
