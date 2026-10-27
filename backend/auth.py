"""
TestSphere-AI — Authentication (Firebase Authentication).

The dashboard signs users in with Firebase (email/password or Google) and
sends the Firebase ID token as ``Authorization: Bearer <token>``.  The
``get_current_user`` dependency verifies it with firebase-admin.

With ``AUTH_REQUIRED=false`` (local development, tests) every request runs as
one local user and data is not partitioned.

Agents (the MCP server, scripts) that cannot renew an hour-long ID token
send a personal API token instead (``tsk_...``, made in Profile).  Only its
SHA-256 hash is stored; it acts as the user who made it until revoked.

Ownership: every stored document carries ``owner_uid``.  ``scope(user)`` gives
the equality filter that limits a query to the caller's documents, and
``ensure_owned`` turns someone else's document into a 404 (never a 403, so ids
of other users' data are not confirmed).
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import Header, HTTPException, status

from backend.config import settings
from backend.database.store import StoreUnavailableError, firebase_app

logger = logging.getLogger("testsphere.auth")


@dataclass(frozen=True)
class User:
    uid: str
    email: str | None = None
    name: str | None = None
    picture: str | None = None
    provider: str | None = None
    local: bool = False

    @property
    def label(self) -> str:
        """How this user appears in the audit trail."""
        return self.name or self.email or self.uid


LOCAL_USER = User(uid="local-dev", name="Local developer", provider="local", local=True)

API_TOKEN_PREFIX = "tsk_"
# last_used_at is refreshed at most this often (a write per request would add up)
_TOKEN_USE_RESOLUTION = timedelta(hours=1)


def new_api_token() -> str:
    return API_TOKEN_PREFIX + secrets.token_urlsafe(32)


def hash_api_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _user_for_api_token(token: str) -> User:
    """The user an API token belongs to (401 for an unknown or revoked one)."""
    from backend.database.session import get_store
    from backend.models import API_TOKENS, USERS

    db = get_store()
    row = db.find_one(API_TOKENS, token_hash=hash_api_token(token))
    if row is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="This API token is unknown or was revoked. Make a new one in Profile.",
                            headers={"WWW-Authenticate": "Bearer"})
    now = datetime.now(UTC)
    try:
        last = datetime.fromisoformat(row["last_used_at"]) if row.get("last_used_at") else None
    except ValueError:
        last = None
    if last is None or now - last > _TOKEN_USE_RESOLUTION:
        db.update(API_TOKENS, row["id"], last_used_at=now.isoformat())
    profile = db.find_one(USERS, uid=row["owner_uid"]) or {}
    return User(uid=row["owner_uid"], email=profile.get("email"), name=profile.get("display_name"),
                provider="api_token")


def verify_token(token: str) -> dict[str, Any]:
    """Decoded claims of a valid Firebase ID token (raises on anything else)."""
    from firebase_admin import auth

    app = firebase_app(settings.FIREBASE_CREDENTIALS or None, settings.FIREBASE_PROJECT_ID or None)
    # A little clock skew tolerance: a host clock a few seconds behind Google's
    # otherwise rejects brand-new tokens as "used too early".
    return auth.verify_id_token(token, app=app, clock_skew_seconds=30)


def get_current_user(authorization: str | None = Header(None)) -> User:
    """FastAPI dependency: the signed-in user (or the local user when sign-in is off)."""
    if not settings.AUTH_REQUIRED:
        return LOCAL_USER
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sign in required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if token.strip().startswith(API_TOKEN_PREFIX):
        return _user_for_api_token(token.strip())
    try:
        claims = verify_token(token.strip())
    except StoreUnavailableError as exc:
        # Server-side Firebase misconfiguration, not the user's fault
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=f"Sign-in is unavailable on this server: {exc}") from exc
    except Exception as exc:
        reason = (str(exc).splitlines() or [repr(exc)])[0][:200]
        logger.info("Rejected ID token: %s", reason)  # nosemgrep: python-logger-credential-disclosure - Firebase's reason, never the token
        detail = "Your session has expired or is invalid. Sign in again."
        if "audience" in reason.lower() or "aud" in reason.lower().split():
            # The dashboard's Firebase project differs from the backend's credentials
            detail = (f"This server checks sign-ins for Firebase project '{settings.FIREBASE_PROJECT_ID}', but your "
                      "token is from another project. Make FIREBASE_WEB_API_KEY and FIREBASE_CREDENTIALS come from "
                      "the same Firebase project.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    return User(
        uid=claims["uid"],
        email=claims.get("email"),
        name=claims.get("name"),
        picture=claims.get("picture"),
        provider=(claims.get("firebase") or {}).get("sign_in_provider"),
    )


def scope(user: User) -> dict[str, Any]:
    """Equality filter limiting a query to *user*'s documents (none for the local user)."""
    return {} if user.local else {"owner_uid": user.uid}


def owns(user: User, row: dict[str, Any] | None) -> bool:
    return row is not None and (user.local or row.get("owner_uid") == user.uid)


def ensure_owned(user: User, row: dict[str, Any] | None, what: str) -> dict[str, Any]:
    """*row* if *user* may see it, else 404 "<what> not found"."""
    if not owns(user, row):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{what} not found")
    return row  # type: ignore[return-value]


# Profile display names (users.display_name) by uid, so recording an action
# does not read the database each time: uid -> (name or None, expires at)
_DISPLAY_NAME_SECONDS = 600
_display_names: dict[str, tuple[str | None, float]] = {}
_display_lock = threading.Lock()


def remember_display_name(uid: str, name: str | None) -> None:
    """The profile's display name changed (or was read): use it from now on."""
    with _display_lock:
        _display_names[uid] = (name or None, time.monotonic() + _DISPLAY_NAME_SECONDS)


def _display_name(uid: str) -> str | None:
    with _display_lock:
        cached = _display_names.get(uid)
    if cached and cached[1] > time.monotonic():
        return cached[0]
    try:
        from backend.database.session import get_store
        from backend.models import USERS

        row = get_store().find_one(USERS, uid=uid)
    except Exception as exc:  # noqa: BLE001 - the token's name will do
        logger.debug("Display name of %s unavailable: %s", uid, exc)
        return None
    name = ((row or {}).get("display_name") or "").strip() or None
    remember_display_name(uid, name)
    return name


def actor_for(user: User, requested: str | None) -> str:
    """Name recorded in the audit trail: when signed in, the display name the
    user set in their profile (else their verified identity), otherwise
    whatever the local operator typed."""
    if user.local:
        return (requested or "").strip()[:64] or "dev_active"
    return _display_name(user.uid) or user.label
