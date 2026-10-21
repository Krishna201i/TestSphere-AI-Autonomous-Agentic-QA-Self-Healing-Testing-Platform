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
from typing import Any, Dict, Optional

from fastapi import Header, HTTPException, status

from backend.config import settings
from backend.database.store import StoreUnavailableError, firebase_app

logger = logging.getLogger("testsphere.auth")


@dataclass(frozen=True)
class User:
    uid: str
    email: Optional[str] = None
    name: Optional[str] = None
    picture: Optional[str] = None
    provider: Optional[str] = None
    local: bool = False

    @property
    def label(self) -> str:
        """How this user appears in the audit trail."""
        return self.name or self.email or self.uid


LOCAL_USER = User(uid="local-dev", name="Local developer", provider="local", local=True)


def verify_token(token: str) -> Dict[str, Any]:
    """Decoded claims of a valid Firebase ID token (raises on anything else)."""
    from firebase_admin import auth

    app = firebase_app(settings.FIREBASE_CREDENTIALS or None, settings.FIREBASE_PROJECT_ID or None)
    return auth.verify_id_token(token, app=app)


def get_current_user(authorization: Optional[str] = Header(None)) -> User:
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
        logger.info("Rejected ID token: %s", (str(exc).splitlines() or [repr(exc)])[0][:200])
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Your session has expired or is invalid. Sign in again.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    return User(
        uid=claims["uid"],
        email=claims.get("email"),
        name=claims.get("name"),
        picture=claims.get("picture"),
        provider=(claims.get("firebase") or {}).get("sign_in_provider"),
    )


def scope(user: User) -> Dict[str, Any]:
    """Equality filter limiting a query to *user*'s documents (none for the local user)."""
    return {} if user.local else {"owner_uid": user.uid}


def owns(user: User, row: Optional[Dict[str, Any]]) -> bool:
    return row is not None and (user.local or row.get("owner_uid") == user.uid)


def ensure_owned(user: User, row: Optional[Dict[str, Any]], what: str) -> Dict[str, Any]:
    """*row* if *user* may see it, else 404 "<what> not found"."""
    if not owns(user, row):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{what} not found")
    return row  # type: ignore[return-value]


def actor_for(user: User, requested: Optional[str]) -> str:
    """Name recorded in the audit trail: the verified identity when signed in,
    otherwise whatever the local operator typed."""
    if user.local:
        return (requested or "").strip()[:64] or "dev_active"
    return user.label
