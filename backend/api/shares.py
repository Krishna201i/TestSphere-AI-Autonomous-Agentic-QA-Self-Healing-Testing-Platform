"""
TestSphere-AI — Read-only links to one run's report.

The owner of a finished run creates a link to send to someone without an
account (a teacher, a client).  The link holder sees that run's report and
nothing else: the same self-contained document as the PDF (summary, stages,
failures with diagnosis and screenshot, all tests), as HTML or PDF.  No page
HTML, traces, other runs or anything else of the account.

* The token is 256 random bits; only its SHA-256 is stored, so a database
  leak does not leak working links.  The full link is shown once.
* A link expires (7 days by default, at most 30) and can be revoked.
* Expired, revoked and unknown links answer the same 404.
* Creating and revoking links is recorded in the audit trail.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from backend.api.pipelines import (
    REPORT_CSP,
    _finished_run,
    report_html_response,
    report_pdf_response,
)
from backend.auth import User, actor_for, ensure_owned, get_current_user
from backend.config import settings
from backend.database.session import get_db
from backend.database.store import Record, Store, now_iso
from backend.models import PIPELINE_RUNS, REPORT_SHARES
from backend.services.security_service import record_audit

router = APIRouter(prefix="/pipelines", tags=["Report sharing"])
public_router = APIRouter(prefix="/shared", tags=["Shared reports (public)"])

DEFAULT_DAYS = 7
MAX_DAYS = 30
MAX_ACTIVE_PER_RUN = 10


class ShareCreate(BaseModel):
    days: int = Field(DEFAULT_DAYS, ge=1, le=MAX_DAYS, description="Days until the link stops working")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _active(row: Record, now: datetime | None = None) -> bool:
    expires = datetime.fromisoformat(row["expires_at"])
    return not row.get("revoked") and expires > (now or datetime.now(UTC))


def _public(row: Record) -> dict[str, Any]:
    return {"id": row["id"], "run_id": row["run_id"], "created_at": row["created_at"], "expires_at": row["expires_at"],
            "revoked": bool(row.get("revoked")), "active": _active(row), "created_by": row.get("created_by")}


@router.post("/runs/{run_id}/shares", status_code=status.HTTP_201_CREATED)
def create_share(run_id: int, payload: ShareCreate, request: Request, db: Store = Depends(get_db),
                 user: User = Depends(get_current_user)) -> dict[str, Any]:
    """A new read-only link to this run's report. The link is shown only in this answer."""
    run = _finished_run(db, user, run_id)
    if sum(1 for r in db.find(REPORT_SHARES, run_id=run_id) if _active(r)) >= MAX_ACTIVE_PER_RUN:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail=f"This run already has {MAX_ACTIVE_PER_RUN} active links; revoke one first.")
    token = secrets.token_urlsafe(32)
    actor = actor_for(user, None)
    row = db.insert(REPORT_SHARES, token_hash=_hash(token), run_id=run_id, owner_uid=run.get("owner_uid"),
                    created_at=now_iso(), created_by=actor,
                    expires_at=(datetime.now(UTC) + timedelta(days=payload.days)).isoformat(), revoked=False)
    record_audit(db, actor=actor, kind="share", ref=str(run_id), owner_uid=run.get("owner_uid"),
                 message=f"Read-only link to the report of run #{run_id} created (expires in {payload.days} days)")
    base = (settings.DASHBOARD_URL or str(request.base_url)).rstrip("/")
    return {**_public(row), "url": f"{base}/api/shared/{token}", "pdf_url": f"{base}/api/shared/{token}.pdf"}


@router.get("/runs/{run_id}/shares")
def list_shares(run_id: int, db: Store = Depends(get_db), user: User = Depends(get_current_user)) -> list[dict[str, Any]]:
    """The run's links (never their tokens)."""
    ensure_owned(user, db.get(PIPELINE_RUNS, run_id), "Pipeline run")
    return [_public(r) for r in db.find(REPORT_SHARES, run_id=run_id, order_by="id", descending=True)]


@router.delete("/shares/{share_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_share(share_id: int, db: Store = Depends(get_db), user: User = Depends(get_current_user)) -> None:
    row = ensure_owned(user, db.get(REPORT_SHARES, share_id), "Link")
    if not row.get("revoked"):
        db.update(REPORT_SHARES, share_id, revoked=True, revoked_at=now_iso())
        record_audit(db, actor=actor_for(user, None), kind="share", ref=str(row["run_id"]), owner_uid=row.get("owner_uid"),
                     message=f"Read-only link to the report of run #{row['run_id']} revoked")


_GONE = ("<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='robots' content='noindex'>"
         "<title>Link not available</title></head><body style='font-family:sans-serif;max-width:560px;margin:15vh auto;"
         "padding:0 16px;color:#1f2328'><h1 style='font-size:20px'>This report link is not available</h1>"
         "<p>It may have expired or been revoked. Ask the person who sent it for a new link.</p></body></html>")


def _shared_run(db: Store, token: str) -> Record | None:
    row = db.find_one(REPORT_SHARES, token_hash=_hash(token)) if 20 <= len(token) <= 100 else None
    if row is None or not _active(row):
        return None
    run = db.get(PIPELINE_RUNS, row["run_id"])
    # The run must still exist and belong to whoever made the link
    return run if run and run.get("owner_uid") == row.get("owner_uid") else None


def _not_available() -> Response:
    return Response(content=_GONE, status_code=status.HTTP_404_NOT_FOUND, media_type="text/html; charset=utf-8",
                    headers={"Content-Security-Policy": REPORT_CSP, "X-Robots-Tag": "noindex", "Cache-Control": "no-store"})


@public_router.get("/{token}.pdf", include_in_schema=False)
async def shared_report_pdf(token: str, db: Store = Depends(get_db)) -> Response:
    run = _shared_run(db, token)
    return await report_pdf_response(db, run, shared=True) if run else _not_available()


@public_router.get("/{token}", include_in_schema=False)
def shared_report(token: str, db: Store = Depends(get_db)) -> Response:
    run = _shared_run(db, token)
    if not run:
        return _not_available()
    response = report_html_response(db, run, shared=True)
    response.headers["Referrer-Policy"] = "no-referrer"  # the token never leaves in a Referer header
    return response
