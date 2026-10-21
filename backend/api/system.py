"""
TestSphere-AI — System Info API Router.

Tells the dashboard what this backend is and how it is configured, so the UI
can show which server it is talking to and why a feature might be refused.
Never returns secrets.
"""

import subprocess
from functools import lru_cache
from typing import Any, Dict

from fastapi import APIRouter

from agents.llm.config import LLMConfig
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


@router.get("")
def system_info() -> Dict[str, Any]:
    llm = LLMConfig.from_env()
    extra = [h.strip() for h in settings.SECURITY_SCAN_ALLOWED_HOSTS.split(",") if h.strip()]
    return {
        "service": settings.APP_NAME,
        "api_version": API_VERSION,
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
        # Public Firebase web config (not secret) so the dashboard can render sign-in
        "auth": {
            "required": settings.AUTH_REQUIRED,
            "provider": "firebase" if settings.AUTH_REQUIRED else "local",
            "firebase": {
                "apiKey": settings.FIREBASE_WEB_API_KEY,
                "authDomain": settings.FIREBASE_AUTH_DOMAIN
                or (f"{settings.FIREBASE_PROJECT_ID}.firebaseapp.com" if settings.FIREBASE_PROJECT_ID else ""),
                "projectId": settings.FIREBASE_PROJECT_ID,
            } if settings.AUTH_REQUIRED else None,
        },
        "scheduler": {"enabled": settings.SCHEDULER_ENABLED, "external_tick": bool(settings.CRON_SECRET)},
    }
