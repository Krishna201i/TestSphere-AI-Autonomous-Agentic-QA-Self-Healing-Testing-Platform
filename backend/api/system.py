"""
TestSphere-AI — System Info API Router.

Tells the dashboard what this backend is and how it is configured, so the UI
can show which server it is talking to and why a feature might be refused.
Never returns secrets.

Before sign-in the dashboard only needs the sign-in configuration, so that is
all an anonymous caller gets; the rest (commit, LLM model, scan scope, browser
path...) maps out the deployment and is shown to signed-in users only.
"""

import subprocess
import time
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, Header, HTTPException

from agents.llm.config import LLMConfig
from backend.auth import get_current_user
from backend.config import settings
from security.scope import LOOPBACK_HOSTS

router = APIRouter(prefix="/system", tags=["System"])

API_VERSION = 3  # bump when the dashboard needs new endpoints


@lru_cache(maxsize=1)
def _git_commit() -> str | None:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=3)
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


_browser_cache: dict[str, Any] = {"at": 0.0, "value": None}


def _browser_status() -> dict[str, Any]:
    """Chromium availability, cached for a minute (probing starts the Playwright driver)."""
    if time.monotonic() - _browser_cache["at"] > 60 or _browser_cache["value"] is None:
        from engine.browser import chromium_status

        _browser_cache.update(at=time.monotonic(), value=chromium_status())
    return _browser_cache["value"]


def _signed_in(authorization: str | None) -> bool:
    """Whether the caller may see deployment details (no 401: an anonymous or
    expired session still needs the sign-in configuration)."""
    try:
        get_current_user(authorization)
        return True
    except HTTPException:
        return False


def _auth_config() -> dict[str, Any]:
    # Public Firebase web config (not secret) so the dashboard can render sign-in
    return {
        "required": settings.AUTH_REQUIRED,
        "provider": "firebase" if settings.AUTH_REQUIRED else "local",
        "firebase": {
            "apiKey": settings.FIREBASE_WEB_API_KEY,
            "authDomain": settings.FIREBASE_AUTH_DOMAIN
            or (f"{settings.FIREBASE_PROJECT_ID}.firebaseapp.com" if settings.FIREBASE_PROJECT_ID else ""),
            "projectId": settings.FIREBASE_PROJECT_ID,
        } if settings.AUTH_REQUIRED else None,
    }


def _privacy_facts() -> dict[str, Any]:
    """What the privacy notice must disclose (shown before sign-in)."""
    provider = LLMConfig.from_env().provider
    return {
        "contact": settings.PRIVACY_CONTACT or None,
        # where page content goes for AI planning/healing: a third-party API, this machine, or nowhere
        "ai_processing": {"api": "cloud", "local": "local"}.get(provider, "none"),
        "error_reporting": bool(settings.SENTRY_DSN),
    }


@router.get("")
def system_info(authorization: str | None = Header(None)) -> dict[str, Any]:
    public = {"service": settings.APP_NAME, "api_version": API_VERSION, "auth": _auth_config(),
              "privacy": _privacy_facts()}
    if not _signed_in(authorization):
        return public
    llm = LLMConfig.from_env()
    extra = [h.strip() for h in settings.SECURITY_SCAN_ALLOWED_HOSTS.split(",") if h.strip()]
    return {
        **public,
        "environment": settings.APP_ENV,
        "commit": _git_commit(),
        "database": settings.DATABASE_BACKEND,
        "llm": {"provider": llm.provider, "model": llm.model, "configured": llm.is_configured},
        "scan_scope": sorted(LOOPBACK_HOSTS) + extra,
        "memory_backend": settings.AGENT_MEMORY_BACKEND,
        "ingestion": {
            "git_hosts": [h.strip() for h in settings.INGEST_GIT_HOSTS.split(",") if h.strip()],
            "local_paths": settings.INGEST_ALLOW_LOCAL_PATHS,
        },
        "scheduler": {"enabled": settings.SCHEDULER_ENABLED, "external_tick": bool(settings.CRON_SECRET)},
        "browser": _browser_status(),
    }
