"""
TestSphere-AI — Integrations API: connect GitHub with a personal token.

The token is checked with GitHub, encrypted (backend/secretbox.py) and
stored per user; it is never sent back to the browser.  It is used to open
pull requests from fix patches and to set commit statuses on pushed commits.
"""

from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from backend.auth import User, get_current_user
from backend.config import git_hosts
from backend.database.session import get_db
from backend.database.store import Store, now_iso
from backend.github import GitHubClient, GitHubError
from backend.models import INTEGRATIONS
from backend.secretbox import SecretBoxError, decrypt, encrypt
from backend.services.security_service import record_audit
from ingestion.source import GitAuth

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


# ── Git credentials for private repositories ───────────────────────────────

# The user name each host expects with a token (Basic auth over https)
TOKEN_USERS = {"github.com": "x-access-token", "gitlab.com": "oauth2", "bitbucket.org": "x-token-auth"}


class GitCredential(BaseModel):
    host: str = Field(..., min_length=3, max_length=255, description="Git host, e.g. gitlab.com")
    username: str | None = Field(None, max_length=255,
                                 description="Leave empty for a token (Bitbucket app passwords need your user name)")
    token: str = Field(..., min_length=8, max_length=512, description="Personal/project access token or app password")


def git_auth(db: Store, uid: str | None, url: str | None) -> GitAuth | None:
    """Credentials of *uid* for the host of *url*: a saved Git credential, else the connected GitHub token."""
    host = (urlsplit(url or "").hostname or "").lower()
    if not host:
        return None
    row = db.find_one(INTEGRATIONS, owner_uid=uid, provider="git", host=host)
    try:
        if row:
            return GitAuth(row["username"], decrypt(row["token"]))
    except SecretBoxError:
        pass
    if host == "github.com":
        token = github_token(db, uid)
        return GitAuth(TOKEN_USERS[host], token) if token else None
    return None


def _git_public(row) -> dict[str, Any]:
    return {"host": row["host"], "username": row["username"], "added_at": row.get("connected_at")}


@router.get("/git-credentials")
def list_git_credentials(db: Store = Depends(get_db), user: User = Depends(get_current_user)) -> list[dict[str, Any]]:
    """Hosts with saved credentials (tokens are never returned)."""
    return [_git_public(r) for r in db.find(INTEGRATIONS, owner_uid=user.uid, provider="git")]


@router.put("/git-credentials")
def save_git_credential(payload: GitCredential, db: Store = Depends(get_db),
                        user: User = Depends(get_current_user)) -> dict[str, Any]:
    """Save (or replace) the credential used to fetch private repositories from one host."""
    host = payload.host.strip().lower().removeprefix("https://").split("/", 1)[0]
    if host not in git_hosts():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=f"{host} is not an allowed Git host ({', '.join(sorted(git_hosts()))}).")
    username = (payload.username or "").strip() or TOKEN_USERS.get(host, "git")
    if ":" in username or any(c in payload.token for c in "\r\n"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid user name or token.")
    try:
        sealed = encrypt(payload.token.strip())
    except SecretBoxError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    fields = {"username": username, "token": sealed, "connected_at": now_iso()}
    row = db.find_one(INTEGRATIONS, owner_uid=user.uid, provider="git", host=host)
    row = db.update(INTEGRATIONS, row["id"], **fields) if row else \
        db.insert(INTEGRATIONS, provider="git", host=host, owner_uid=user.uid, **fields)
    record_audit(db, actor=user.name or user.uid, kind="integration", owner_uid=user.uid,
                 message=f"Git credential saved for {host}")
    return _git_public(row)


@router.delete("/git-credentials/{host}", status_code=status.HTTP_204_NO_CONTENT)
def delete_git_credential(host: str, db: Store = Depends(get_db), user: User = Depends(get_current_user)) -> None:
    if db.delete_where(INTEGRATIONS, owner_uid=user.uid, provider="git", host=host.lower()):
        record_audit(db, actor=user.name or user.uid, kind="integration", owner_uid=user.uid,
                     message=f"Git credential removed for {host}")
