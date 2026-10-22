"""
TestSphere-AI — Current user profile.

``GET /me`` returns the signed-in user's profile (created on first sign-in
from the Firebase token) plus activity counts; ``PUT /me`` edits it;
``DELETE /me`` erases the account and everything it owns (right to erasure,
DPDP Act 2023 s.12 / GDPR art.17).
"""

import logging
from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from backend.auth import User, get_current_user, scope
from backend.database.session import get_db
from backend.database.store import Record, Store, now_iso
from backend.config import settings
from backend.models import (
    APPLICATIONS,
    AUDIT_EVENTS,
    BLUEPRINTS,
    PIPELINE_RUNS,
    PROJECTS,
    SECURITY_FINDINGS,
    TEST_CASES,
    TEST_EXECUTIONS,
    USERS,
)

logger = logging.getLogger("testsphere.me")

router = APIRouter(prefix="/me", tags=["Profile"])

# Every collection whose documents carry owner_uid
OWNED_COLLECTIONS = (PROJECTS, APPLICATIONS, TEST_CASES, TEST_EXECUTIONS, SECURITY_FINDINGS,
                     AUDIT_EVENTS, BLUEPRINTS, PIPELINE_RUNS)


class ProfileUpdate(BaseModel):
    display_name: Optional[str] = Field(None, max_length=80)
    organization: Optional[str] = Field(None, max_length=120)
    job_title: Optional[str] = Field(None, max_length=80)


class AccountDeletion(BaseModel):
    confirm: Literal["DELETE MY ACCOUNT"] = Field(..., description='Must be exactly "DELETE MY ACCOUNT"')


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


def _delete_sign_in_account(uid: str) -> bool:
    """Remove the Firebase Authentication user; False if that failed."""
    try:
        from firebase_admin import auth

        from backend.database.store import firebase_app

        auth.delete_user(uid, app=firebase_app(settings.FIREBASE_CREDENTIALS or None,
                                               settings.FIREBASE_PROJECT_ID or None))
        return True
    except Exception as exc:  # noqa: BLE001 - the data is gone either way; report what remains
        if type(exc).__name__ == "UserNotFoundError":
            return True
        logger.error("Could not delete Firebase user %s: %s", uid, exc)
        return False


@router.delete("")
def delete_me(payload: AccountDeletion, db: Store = Depends(get_db),
              user: User = Depends(get_current_user)) -> Dict[str, Any]:
    """Erase the signed-in user's data and sign-in account. Cannot be undone."""
    if user.local:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Sign-in is off on this server, so there is no personal account to delete.")
    deleted = {name: len(db.delete_where(name, owner_uid=user.uid)) for name in OWNED_COLLECTIONS}
    deleted[USERS] = len(db.delete_where(USERS, uid=user.uid))
    sign_in_deleted = _delete_sign_in_account(user.uid)
    logger.info("Account %s erased: %s documents, sign-in account %s",
                user.uid, sum(deleted.values()), "deleted" if sign_in_deleted else "NOT deleted")
    return {
        "deleted": deleted,
        "sign_in_account_deleted": sign_in_deleted,
        "detail": "Your data has been erased." + (
            "" if sign_in_deleted else " Your sign-in account could not be removed; contact the operator."),
    }
