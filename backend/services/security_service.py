"""
TestSphere-AI — Security finding persistence and the audit trail.
"""

import json
from typing import Any, Dict, List, Optional

from backend.database.store import Record, Store, now_iso
from backend.models import AUDIT_EVENTS, SECURITY_FINDINGS


def record_audit(
    db: Store, *, actor: str, kind: str, message: str, level: str = "info", ref: Optional[str] = None,
    owner_uid: Optional[str] = None,
) -> Record:
    return db.insert(AUDIT_EVENTS, at=now_iso(), actor=actor, kind=kind, message=message, level=level, ref=ref,
                     owner_uid=owner_uid)


def list_audit(db: Store, limit: int = 200, **filters: Any) -> List[Dict[str, Any]]:
    rows = db.find(AUDIT_EVENTS, order_by="id", descending=True, limit=limit, **filters)
    return [
        {"id": r["id"], "at": r["at"], "actor": r["actor"], "kind": r["kind"], "level": r["level"],
         "message": r["message"], "ref": r.get("ref")}
        for r in rows
    ]


def serialize(row: Record) -> Dict[str, Any]:
    """Stored finding JSON plus its tracked lifecycle fields."""
    return json.loads(row["data"]) | {
        "key": row["key"],
        "status": row["status"],
        "retest_result": row.get("retest_result"),
        "retested_at": row.get("retested_at"),
        "approved_by": row.get("approved_by"),
        "approved_at": row.get("approved_at"),
        "first_seen": row["first_seen"],
        "last_seen": row["last_seen"],
    }


def get_finding(db: Store, key: str, **filters: Any) -> Optional[Record]:
    return db.find_one(SECURITY_FINDINGS, key=key, **filters)


def list_findings(db: Store, target_url: Optional[str] = None, **filters: Any) -> List[Record]:
    if target_url:
        filters["target_url"] = target_url
    return db.find(SECURITY_FINDINGS, order_by="last_seen", descending=True, **filters)


def save_scan(
    db: Store, target_url: str, findings: List[Dict[str, Any]], owner_uid: Optional[str] = None,
) -> Dict[str, List[Record]]:
    """Upsert this scan's findings for *target_url*.

    - New findings are inserted as open.
    - A previously resolved finding that shows up again is a regression:
      reopened, approval and retest cleared.
    - Open findings for this target that no longer appear are resolved —
      the scan itself is a retest that passed.

    With *owner_uid*, only that user's findings are matched (each user tracks
    their own lifecycle for the same target).
    """
    owner = {"owner_uid": owner_uid} if owner_uid else {}
    now = now_iso()
    seen = {f["key"] for f in findings}
    current, reopened, resolved = [], [], []

    for f in findings:
        data = json.dumps({k: v for k, v in f.items() if k != "key"})
        row = get_finding(db, f["key"], **owner)
        if row is None:
            row = db.insert(
                SECURITY_FINDINGS, key=f["key"], target_url=target_url, check_id=f["check_id"],
                severity=f["severity"], title=f["title"], data=data, status="open",
                retest_result=None, retested_at=None, approved_by=None, approved_at=None,
                first_seen=now, last_seen=now, owner_uid=owner_uid,
            )
        else:
            changes: Dict[str, Any] = {"severity": f["severity"], "title": f["title"], "data": data, "last_seen": now}
            if row["status"] == "resolved":
                changes.update(status="open", retest_result=None, retested_at=None, approved_by=None, approved_at=None)
            was_resolved = row["status"] == "resolved"
            row = db.update(SECURITY_FINDINGS, row["id"], **changes)
            if was_resolved:
                reopened.append(row)
        current.append(row)

    for row in db.find(SECURITY_FINDINGS, target_url=target_url, **owner):
        if row["key"] not in seen and row["status"] == "open":
            resolved.append(db.update(SECURITY_FINDINGS, row["id"], status="resolved", retest_result="pass", retested_at=now))

    return {"current": current, "reopened": reopened, "resolved": resolved}


def approve(db: Store, row: Record, actor: str) -> Record:
    return db.update(SECURITY_FINDINGS, row["id"], approved_by=actor, approved_at=now_iso())


def save_retest(db: Store, row: Record, result: str, status: str) -> Record:
    return db.update(SECURITY_FINDINGS, row["id"], retest_result=result, status=status, retested_at=now_iso())
