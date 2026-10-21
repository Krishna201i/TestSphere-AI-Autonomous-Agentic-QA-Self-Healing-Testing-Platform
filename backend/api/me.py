"""
TestSphere-AI — Current user profile.

``GET /me`` returns the signed-in user's profile (created on first sign-in
from the Firebase token) plus activity counts; ``PUT /me`` edits it.
"""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from backend.auth import User, get_current_user, scope
from backend.database.session import get_db
from backend.database.store import Record, Store, now_iso
from backend.models import PIPELINE_RUNS, PROJECTS, SECURITY_FINDINGS, TEST_EXECUTIONS, USERS

router = APIRouter(prefix="/me", tags=["Profile"])


class ProfileUpdate(BaseModel):
    display_name: Optional[str] = Field(None, max_length=80)
    organization: Optional[str] = Field(None, max_length=120)
    job_title: Optional[str] = Field(None, max_length=80)


def _profile(db: Store, user: User) -> Record:
    row = db.find_one(USERS, uid=user.uid)
    if row is None:
        return db.insert(USERS, uid=user.uid, email=user.email, display_name=user.name or (user.email or "").split("@")[0] or None,
                         organization=None, job_title=None, photo_url=user.picture, provider=user.provider,
                         last_login_at=now_iso())
    changes: Dict[str, Any] = {}
    if user.email and user.email != row.get("email"):
        changes["email"] = user.email
    if user.picture and user.picture != row.get("photo_url"):
        changes["photo_url"] = user.picture
    return db.update(USERS, row["id"], **changes) if changes else row


def _view(db: Store, user: User, row: Record) -> Dict[str, Any]:
    owned = scope(user)
    runs = db.find(PIPELINE_RUNS, order_by="id", descending=True, **owned)
    return {
        "uid": row["uid"],
        "email": row.get("email"),
        "display_name": row.get("display_name"),
        "organization": row.get("organization"),
        "job_title": row.get("job_title"),
        "photo_url": row.get("photo_url"),
        "provider": row.get("provider"),
        "local": user.local,
        "member_since": row.get("created_at"),
        "last_login_at": row.get("last_login_at"),
        "stats": {
            "projects": len(db.find(PROJECTS, **owned)),
            "pipeline_runs": len(runs),
            "test_executions": len(db.find(TEST_EXECUTIONS, **owned)),
            "open_findings": len(db.find(SECURITY_FINDINGS, status="open", **owned)),
            "last_run": {k: runs[0].get(k) for k in ("id", "status", "project_name", "finished_at")} if runs else None,
        },
    }


@router.get("")
def get_me(db: Store = Depends(get_db), user: User = Depends(get_current_user)) -> Dict[str, Any]:
    row = _profile(db, user)
    return _view(db, user, row)


@router.post("/login")
def record_login(db: Store = Depends(get_db), user: User = Depends(get_current_user)) -> Dict[str, Any]:
    """Called by the dashboard right after sign-in: stamps last_login_at."""
    row = _profile(db, user)
    row = db.update(USERS, row["id"], last_login_at=now_iso())
    return _view(db, user, row)


@router.put("")
def update_me(payload: ProfileUpdate, db: Store = Depends(get_db), user: User = Depends(get_current_user)) -> Dict[str, Any]:
    row = _profile(db, user)
    changes = {k: (v.strip() or None) for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    if changes:
        row = db.update(USERS, row["id"], **changes)
    return _view(db, user, row)
