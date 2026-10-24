"""
TestSphere-AI — Integrations API: connect GitHub with a personal token.

The token is checked with GitHub, encrypted (backend/secretbox.py) and
stored per user; it is never sent back to the browser.  It is used to open
pull requests from fix patches and to set commit statuses on pushed commits.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from backend.auth import User, get_current_user
from backend.database.session import get_db
from backend.database.store import Store, now_iso
from backend.github import GitHubClient, GitHubError
from backend.models import INTEGRATIONS
from backend.secretbox import SecretBoxError, decrypt, encrypt
from backend.services.security_service import record_audit

router = APIRouter(prefix="/integrations", tags=["Integrations"])


class GitHubConnect(BaseModel):
    token: str = Field(..., min_length=20, max_length=255, description="Fine-grained personal access token")


def _row(db: Store, uid: str | None):
    return db.find_one(INTEGRATIONS, owner_uid=uid, provider="github")


def github_token(db: Store, uid: str | None) -> str | None:
    """The user's GitHub token, or None when not connected (or unreadable)."""
    row = _row(db, uid)
    if not row:
        return None
    try:
        return decrypt(row["token"])
    except SecretBoxError:
        return None


def _public(row) -> dict[str, Any]:
    return {"provider": "github", "connected": True, "login": row["login"], "name": row.get("name"),
            "avatar_url": row.get("avatar_url"), "connected_at": row.get("connected_at")}


@router.get("")
def list_integrations(db: Store = Depends(get_db), user: User = Depends(get_current_user)) -> list[dict[str, Any]]:
    row = _row(db, user.uid)
    return [_public(row)] if row else [{"provider": "github", "connected": False}]


@router.put("/github")
async def connect_github(payload: GitHubConnect, db: Store = Depends(get_db),
                         user: User = Depends(get_current_user)) -> dict[str, Any]:
    token = payload.token.strip()

    def check() -> dict[str, Any]:
        with GitHubClient(token) as gh:
            return gh.user()

    try:
        account = await asyncio.to_thread(check)
        sealed = encrypt(token)
    except GitHubError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except SecretBoxError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    fields = {"login": account["login"], "name": account.get("name"), "avatar_url": account.get("avatar_url"),
              "token": sealed, "connected_at": now_iso()}
    row = _row(db, user.uid)
    row = db.update(INTEGRATIONS, row["id"], **fields) if row else \
        db.insert(INTEGRATIONS, provider="github", owner_uid=user.uid, **fields)
    record_audit(db, actor=user.name or user.uid, kind="integration", owner_uid=user.uid,
                 message=f"GitHub connected as {account['login']}")
    return _public(row)


@router.delete("/github", status_code=status.HTTP_204_NO_CONTENT)
def disconnect_github(db: Store = Depends(get_db), user: User = Depends(get_current_user)) -> None:
    removed = db.delete_where(INTEGRATIONS, owner_uid=user.uid, provider="github")
    if removed:
        record_audit(db, actor=user.name or user.uid, kind="integration", owner_uid=user.uid,
                     message="GitHub disconnected")
