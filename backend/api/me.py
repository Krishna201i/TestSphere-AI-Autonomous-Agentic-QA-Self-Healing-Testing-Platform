"""
TestSphere-AI — Current user profile.

``GET /me`` returns the signed-in user's profile (created on first sign-in
from the Firebase token) plus activity counts; ``PUT /me`` edits it;
``DELETE /me`` erases the account and everything it owns (right to erasure,
DPDP Act 2023 s.12 / GDPR art.17).
"""

import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from backend.artifacts import delete_owner_artifacts
from backend.auth import (
    API_TOKEN_PREFIX,
    User,
    ensure_owned,
    get_current_user,
    hash_api_token,
    new_api_token,
    remember_display_name,
    scope,
)
from backend.config import settings
from backend.database.session import get_db
from backend.database.store import Record, Store, now_iso
from backend.models import (
    AGENT_MEMORY,
    API_TOKENS,
    APPLICATIONS,
    AUDIT_EVENTS,
    BLUEPRINTS,
    DEPLOYMENTS,
    FIX_PATCHES,
    INTEGRATIONS,
    PIPELINE_RUNS,
    PROJECTS,
    RATE_LIMITS,
    SECURITY_FINDINGS,
    TEST_CASES,
    TEST_EXECUTIONS,
    USERS,
)

logger = logging.getLogger("testsphere.me")

router = APIRouter(prefix="/me", tags=["Profile"])

# Every collection whose documents carry owner_uid
OWNED_COLLECTIONS = (PROJECTS, APPLICATIONS, TEST_CASES, TEST_EXECUTIONS, SECURITY_FINDINGS,
                     AUDIT_EVENTS, BLUEPRINTS, PIPELINE_RUNS, FIX_PATCHES, DEPLOYMENTS, INTEGRATIONS,
                     AGENT_MEMORY, API_TOKENS, RATE_LIMITS)

MAX_API_TOKENS = 10


class ProfileUpdate(BaseModel):
    display_name: str | None = Field(None, max_length=80)
    organization: str | None = Field(None, max_length=120)
    job_title: str | None = Field(None, max_length=80)


class ApiTokenCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=60, description="What uses it, e.g. 'Claude Code MCP'")


class AccountDeletion(BaseModel):
    confirm: Literal["DELETE MY ACCOUNT"] = Field(..., description='Must be exactly "DELETE MY ACCOUNT"')


def _profile(db: Store, user: User) -> Record:
    row = db.find_one(USERS, uid=user.uid)
    if row is None:
        return db.insert(USERS, uid=user.uid, email=user.email, display_name=user.name or (user.email or "").split("@")[0] or None,
                         organization=None, job_title=None, photo_url=user.picture, provider=user.provider,
                         last_login_at=now_iso())
    changes: dict[str, Any] = {}
    if user.email and user.email != row.get("email"):
        changes["email"] = user.email
    if user.picture and user.picture != row.get("photo_url"):
        changes["photo_url"] = user.picture
    return db.update(USERS, row["id"], **changes) if changes else row


def _view(db: Store, user: User, row: Record) -> dict[str, Any]:
    owned = scope(user)
    # Counts are aggregations and the last run is one document: the history itself is not read
    last = db.find(PIPELINE_RUNS, order_by="id", descending=True, limit=1, **owned)
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
            "projects": db.count(PROJECTS, **owned),
            "pipeline_runs": db.count(PIPELINE_RUNS, **owned),
            "test_executions": db.count(TEST_EXECUTIONS, **owned),
            "open_findings": db.count(SECURITY_FINDINGS, status="open", **owned),
            "last_run": {k: last[0].get(k) for k in ("id", "status", "project_name", "finished_at")} if last else None,
        },
    }


@router.get("")
def get_me(db: Store = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    row = _profile(db, user)
    return _view(db, user, row)


@router.post("/login")
def record_login(db: Store = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    """Called by the dashboard right after sign-in: stamps last_login_at."""
    row = _profile(db, user)
    row = db.update(USERS, row["id"], last_login_at=now_iso())
    return _view(db, user, row)


@router.put("")
def update_me(payload: ProfileUpdate, db: Store = Depends(get_db), user: User = Depends(get_current_user)) -> dict[str, Any]:
    row = _profile(db, user)
    changes = {k: (v.strip() or None) for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    if changes:
        row = db.update(USERS, row["id"], **changes)
    remember_display_name(user.uid, row.get("display_name"))  # approvals, scans and runs show it from now on
    return _view(db, user, row)


# ── API tokens (for agents such as the MCP server) ────────────────────────


def _token_view(row: Record) -> dict[str, Any]:
    return {"id": row["id"], "name": row.get("name"), "prefix": row.get("prefix"),
            "created_at": row.get("created_at"), "last_used_at": row.get("last_used_at")}


def _require_account(user: User) -> None:
    if user.local:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="Sign-in is off on this server, so no token is needed: agents connect as you.")


@router.get("/tokens")
def list_api_tokens(db: Store = Depends(get_db), user: User = Depends(get_current_user)) -> list[dict[str, Any]]:
    _require_account(user)
    # At most MAX_API_TOKENS rows: sorted here, so Firestore needs no composite index
    return [_token_view(r) for r in sorted(db.find(API_TOKENS, owner_uid=user.uid), key=lambda r: r["id"])]


@router.post("/tokens", status_code=status.HTTP_201_CREATED)
def create_api_token(payload: ApiTokenCreate, db: Store = Depends(get_db),
                     user: User = Depends(get_current_user)) -> dict[str, Any]:
    """A token that acts as you until revoked; shown only in this response."""
    _require_account(user)
    if db.count(API_TOKENS, owner_uid=user.uid) >= MAX_API_TOKENS:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail=f"You already have {MAX_API_TOKENS} tokens. Revoke one you no longer use.")
    token = new_api_token()
    row = db.insert(API_TOKENS, owner_uid=user.uid, name=payload.name.strip(), token_hash=hash_api_token(token),
                    prefix=token[:len(API_TOKEN_PREFIX) + 6], last_used_at=None)
    return {**_token_view(row), "token": token}


@router.delete("/tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_api_token(token_id: int, db: Store = Depends(get_db), user: User = Depends(get_current_user)) -> None:
    _require_account(user)
    ensure_owned(user, db.get(API_TOKENS, token_id), "Token")
    db.delete(API_TOKENS, token_id)


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
              user: User = Depends(get_current_user)) -> dict[str, Any]:
    """Erase the signed-in user's data and sign-in account. Cannot be undone."""
    if user.local:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Sign-in is off on this server, so there is no personal account to delete.")
    deleted = {name: len(db.delete_where(name, owner_uid=user.uid)) for name in OWNED_COLLECTIONS}
    deleted[USERS] = len(db.delete_where(USERS, uid=user.uid))
    if deleted[AGENT_MEMORY]:
        from backend.orchestration.orchestrator import forget_healing_memory

        forget_healing_memory()  # the running healer's copy of the erased records
    deleted["artifacts"] = delete_owner_artifacts(user.uid)
    sign_in_deleted = _delete_sign_in_account(user.uid)
    logger.info("Account %s erased: %s documents, sign-in account %s",
                user.uid, sum(deleted.values()), "deleted" if sign_in_deleted else "NOT deleted")
    return {
        "deleted": deleted,
        "sign_in_account_deleted": sign_in_deleted,
        "detail": "Your data has been erased." + (
            "" if sign_in_deleted else " Your sign-in account could not be removed; contact the operator."),
    }
