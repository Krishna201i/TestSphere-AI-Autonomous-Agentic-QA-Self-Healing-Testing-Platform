"""
TestSphere-AI — Authentication (Firebase Authentication).

The dashboard signs users in with Firebase (email/password or Google) and
sends the Firebase ID token as ``Authorization: Bearer <token>``.  The
``get_current_user`` dependency verifies it with firebase-admin.

With ``AUTH_REQUIRED=false`` (local development, tests) every request runs as
one local user and data is not partitioned.

Ownership: every stored document carries ``owner_uid``.  ``scope(user)`` gives
the equality filter that limits a query to the caller's documents, and
``ensure_owned`` turns someone else's document into a 404 (never a 403, so ids
of other users' data are not confirmed).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
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
    try:
        claims = verify_token(token.strip())
    except StoreUnavailableError as exc:
        # Server-side Firebase misconfiguration, not the user's fault
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=f"Sign-in is unavailable on this server: {exc}") from exc
    except Exception as exc:
        reason = (str(exc).splitlines() or [repr(exc)])[0][:200]
        logger.info("Rejected ID token: %s", reason)
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


def actor_for(user: User, requested: str | None) -> str:
    """Name recorded in the audit trail: the verified identity when signed in,
    otherwise whatever the local operator typed."""
    if user.local:
        return (requested or "").strip()[:64] or "dev_active"
    return user.label
