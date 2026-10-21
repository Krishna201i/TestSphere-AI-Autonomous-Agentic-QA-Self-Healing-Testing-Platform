"""
TestSphere-AI — Member 3 Configuration Module.

Reads configuration settings from environment variables with safe defaults.
Does not hardcode any sensitive information.
"""

import json
import os
from typing import List

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings

# Load .env into the process environment first: several defaults below are
# derived from other variables via os.getenv (e.g. DATABASE_BACKEND from
# FIREBASE_CREDENTIALS), which pydantic-settings' own .env loading does not
# cover.  Real environment variables still take precedence.
load_dotenv()


def _default_database_backend() -> str:
    explicit = os.getenv("DATABASE_BACKEND")
    if explicit:
        return explicit.strip().lower()
    if os.getenv("FIREBASE_CREDENTIALS") or os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or os.getenv("FIRESTORE_EMULATOR_HOST"):
        return "firestore"
    return "local"


# Set by common hosting platforms; their servers are public, so local-path
# ingestion (reading the server's own disk) must be opted into explicitly there.
_CLOUD_MARKERS = ("RENDER", "DYNO", "RAILWAY_ENVIRONMENT", "FLY_APP_NAME", "K_SERVICE", "VERCEL")


def _default_allow_local_paths() -> bool:
    explicit = os.getenv("INGEST_ALLOW_LOCAL_PATHS")
    if explicit is not None:
        return explicit.lower() in ("true", "1")
    on_cloud = any(os.getenv(marker) for marker in _CLOUD_MARKERS)
    return os.getenv("APP_ENV", "development") == "development" and not on_cloud


def _default_allow_private_targets() -> bool:
    explicit = os.getenv("ALLOW_PRIVATE_TARGETS")
    if explicit is not None:
        return explicit.lower() in ("true", "1")
    on_cloud = any(os.getenv(marker) for marker in _CLOUD_MARKERS)
    return os.getenv("APP_ENV", "development") == "development" and not on_cloud


def _default_auth_required() -> bool:
    """Sign-in is required once Firebase is configured, unless explicitly turned off."""
    explicit = os.getenv("AUTH_REQUIRED")
    if explicit is not None:
        return explicit.lower() in ("true", "1")
    return bool(os.getenv("FIREBASE_CREDENTIALS") or os.getenv("GOOGLE_APPLICATION_CREDENTIALS"))


def _default_firebase_project_id() -> str:
    """FIREBASE_PROJECT_ID, else the project_id inside the service-account JSON."""
    explicit = os.getenv("FIREBASE_PROJECT_ID")
    if explicit:
        return explicit
    raw = (os.getenv("FIREBASE_CREDENTIALS") or "").strip()
    try:
        if raw.startswith("{"):
            return json.loads(raw).get("project_id", "")
        if raw and os.path.isfile(raw):
            with open(raw, encoding="utf-8") as fh:
                return json.load(fh).get("project_id", "")
    except (OSError, ValueError):
        pass
    return ""


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Application settings
    APP_NAME: str = "TestSphere-AI Backend"
    APP_ENV: str = Field(default_factory=lambda: os.getenv("APP_ENV", "development"))
    API_V1_PREFIX: str = "/api/v1"
    DEBUG: bool = Field(default_factory=lambda: os.getenv("DEBUG", "false").lower() in ("true", "1"))

    # Server settings
    HOST: str = Field(default_factory=lambda: os.getenv("BACKEND_HOST", "127.0.0.1"))
    PORT: int = Field(default_factory=lambda: int(os.getenv("BACKEND_PORT", "8000")))

    # CORS settings
    CORS_ORIGINS: List[str] = ["*"]

    # Database settings (SQLite default for local development)
    # Storage: "firestore" (production), "local" (JSON file, offline dev) or
    # "memory" (tests).  Defaults to firestore when Firebase credentials or the
    # emulator are configured, otherwise local.
    DATABASE_BACKEND: str = Field(default_factory=lambda: _default_database_backend())
    LOCAL_DB_PATH: str = Field(default_factory=lambda: os.getenv("LOCAL_DB_PATH", "./data/local_db.json"))
    # Service-account JSON (the whole key file contents) or a path to it
    FIREBASE_CREDENTIALS: str = Field(default_factory=lambda: os.getenv("FIREBASE_CREDENTIALS", ""))
    FIREBASE_PROJECT_ID: str = Field(default_factory=lambda: _default_firebase_project_id())

    # Sign-in (Firebase Authentication).  When required, every API call needs
    # a Firebase ID token and users only see their own data; when off, the
    # API runs as a single local user (development).
    AUTH_REQUIRED: bool = Field(default_factory=lambda: _default_auth_required())
    # Public web-app config handed to the dashboard so it can show the login
    # page (Firebase console → Project settings → General → Your apps).
    FIREBASE_WEB_API_KEY: str = Field(default_factory=lambda: os.getenv("FIREBASE_WEB_API_KEY", ""))
    FIREBASE_AUTH_DOMAIN: str = Field(default_factory=lambda: os.getenv("FIREBASE_AUTH_DOMAIN", ""))

    # Automated pipeline: scheduled re-runs are checked every
    # SCHEDULER_INTERVAL_SECONDS while the server is awake.  CRON_SECRET lets an
    # external cron wake a sleeping host and trigger due runs (POST /api/scheduler/tick).
    SCHEDULER_ENABLED: bool = Field(
        default_factory=lambda: os.getenv("SCHEDULER_ENABLED", "true").lower() in ("true", "1")
    )
    SCHEDULER_INTERVAL_SECONDS: int = Field(default_factory=lambda: int(os.getenv("SCHEDULER_INTERVAL_SECONDS", "60")))
    CRON_SECRET: str = Field(default_factory=lambda: os.getenv("CRON_SECRET", ""))

    # Security scanning: comma-separated extra hosts the passive scanner may
    # contact (loopback is always allowed). Only list hosts you own.
    SECURITY_SCAN_ALLOWED_HOSTS: str = Field(
        default_factory=lambda: os.getenv("SECURITY_SCAN_ALLOWED_HOSTS", "")
    )

    # Agent healing memory: "database" persists it (survives restarts),
    # "memory" keeps it in-process only (tests).
    AGENT_MEMORY_BACKEND: str = Field(
        default_factory=lambda: os.getenv("AGENT_MEMORY_BACKEND", "database")
    )

    # Codebase ingestion: where clones go, which Git hosts may be cloned, and
    # whether local folder paths are accepted (development only by default).
    INGEST_WORKSPACE: str = Field(default_factory=lambda: os.getenv("INGEST_WORKSPACE", "./data/repos"))
    INGEST_GIT_HOSTS: str = Field(
        default_factory=lambda: os.getenv("INGEST_GIT_HOSTS", "github.com,gitlab.com,bitbucket.org")
    )
    INGEST_ALLOW_LOCAL_PATHS: bool = Field(default_factory=lambda: _default_allow_local_paths())

    # Whether tests and page analysis may target private/internal addresses
    # (localhost, 10.x, 169.254.x ...). Off on hosted servers (SSRF), on in local development.
    ALLOW_PRIVATE_TARGETS: bool = Field(default_factory=lambda: _default_allow_private_targets())

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


settings = Settings()
