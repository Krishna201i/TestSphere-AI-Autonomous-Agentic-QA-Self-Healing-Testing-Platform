"""
TestSphere-AI — Member 3 Configuration Module.

Reads configuration settings from environment variables with safe defaults.
Does not hardcode any sensitive information.
"""

import json
import os
from typing import Annotated

from dotenv import load_dotenv
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode

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


def _hosted() -> bool:
    """A public deployment: a hosting platform, or any APP_ENV but development."""
    return os.getenv("APP_ENV", "development") != "development" or any(os.getenv(m) for m in _CLOUD_MARKERS)


def _split_origins(raw: str) -> list[str]:
    """Comma-separated origins, or a JSON list (the format older versions required)."""
    raw = raw.strip()
    items = json.loads(raw) if raw.startswith("[") else raw.split(",")
    return [str(origin).strip().rstrip("/") for origin in items if str(origin).strip()]


def _default_cors_origins() -> list[str]:
    """The Vite dev servers locally; none when hosted, where the dashboard is
    served from the API's own origin.  CORS_ORIGINS (comma-separated) overrides."""
    if _hosted():
        return []
    return [f"http://{host}:{port}" for host in ("localhost", "127.0.0.1") for port in (3000, 5173)]


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

    # Other origins allowed to call the API from a browser (e.g. a dashboard on
    # Vercel). Auth is a bearer token, never a cookie, so credentials stay off.
    CORS_ORIGINS: Annotated[list[str], NoDecode] = Field(default_factory=_default_cors_origins)

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _parse_cors_origins(cls, value):
        return _split_origins(value) if isinstance(value, str) else value

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

    # Where pipeline runs execute: "inline" in the API process (one service,
    # fits a free host), or "worker": the API only queues them and
    # `python -m backend.worker` (a separate service) claims and runs them,
    # and runs the scheduler.  Queued runs then survive API restarts.
    PIPELINE_EXECUTION: str = Field(
        default_factory=lambda: os.getenv("PIPELINE_EXECUTION", "inline").strip().lower())
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
    # Check pinned dependency versions against OSV.dev (sends package names and versions, never code)
    DEPENDENCY_SCAN: bool = Field(default_factory=lambda: os.getenv("DEPENDENCY_SCAN", "true").lower() in ("true", "1"))

    # Whether tests and page analysis may target private/internal addresses
    # (localhost, 10.x, 169.254.x ...). Off on hosted servers (SSRF), on in local development.
    ALLOW_PRIVATE_TARGETS: bool = Field(default_factory=lambda: _default_allow_private_targets())

    # Test artifacts (screenshots, DOM snapshots, Playwright traces) kept per
    # execution: "local" (ARTIFACTS_DIR on this server) or "gcs" (a Cloud
    # Storage bucket, e.g. the Firebase project's <project>.appspot.com), which
    # survives redeploys and is shared with a separate worker.  Kept for
    # ARTIFACT_RETENTION_DAYS (0 = until the execution or account is deleted).
    ARTIFACT_STORE: str = Field(default_factory=lambda: os.getenv("ARTIFACT_STORE", "local").strip().lower())
    ARTIFACT_BUCKET: str = Field(default_factory=lambda: os.getenv("ARTIFACT_BUCKET", ""))
    ARTIFACTS_DIR: str = Field(default_factory=lambda: os.getenv("ARTIFACTS_DIR", "./data/artifacts"))
    ARTIFACT_TRACES: bool = Field(
        default_factory=lambda: os.getenv("ARTIFACT_TRACES", "true").lower() in ("true", "1"))
    ARTIFACT_RETENTION_DAYS: int = Field(default_factory=lambda: int(os.getenv("ARTIFACT_RETENTION_DAYS", "30")))

    # Verified deploy (loop stage 6): deploy hooks may only go to these hosts
    # (Render, Vercel and Netlify are always allowed), and a deployment must be
    # healthy DEPLOY_HEALTHY_CHECKS times in a row within DEPLOY_TIMEOUT_SECONDS.
    # Without a visible change on the health URL, the new version is assumed
    # live after DEPLOY_SETTLE_SECONDS.
    DEPLOY_HOOK_HOSTS: str = Field(default_factory=lambda: os.getenv("DEPLOY_HOOK_HOSTS", ""))
    DEPLOY_TIMEOUT_SECONDS: int = Field(default_factory=lambda: int(os.getenv("DEPLOY_TIMEOUT_SECONDS", "600")))
    DEPLOY_SETTLE_SECONDS: int = Field(default_factory=lambda: int(os.getenv("DEPLOY_SETTLE_SECONDS", "90")))
    DEPLOY_POLL_SECONDS: int = Field(default_factory=lambda: int(os.getenv("DEPLOY_POLL_SECONDS", "10")))
    DEPLOY_HEALTHY_CHECKS: int = Field(default_factory=lambda: int(os.getenv("DEPLOY_HEALTHY_CHECKS", "3")))

    # Fernet key that encrypts stored integration tokens (GitHub).  Required
    # on hosted servers; local development generates data/.token_key.
    TOKEN_ENCRYPTION_KEY: str = Field(default_factory=lambda: os.getenv("TOKEN_ENCRYPTION_KEY", ""))

    # The dashboard's public address, for links in notifications (Slack).
    # On Render it defaults to the service's own URL.
    DASHBOARD_URL: str = Field(default_factory=lambda: os.getenv("DASHBOARD_URL") or os.getenv("RENDER_EXTERNAL_URL", ""))

    # Shown on the dashboard's privacy notice: who users contact about their
    # data (e-mail or URL of the operator / grievance officer).
    PRIVACY_CONTACT: str = Field(default_factory=lambda: os.getenv("PRIVACY_CONTACT", ""))

    # Logging & error reporting (see backend/observability.py)
    LOG_LEVEL: str = Field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))
    SENTRY_DSN: str = Field(default_factory=lambda: os.getenv("SENTRY_DSN", ""))

    # Abuse limits: expensive actions (browser runs, scans, clones, LLM calls)
    # each signed-in user may start per minute; 0 disables the limit.
    RATE_LIMIT_RUNS_PER_MINUTE: int = Field(default_factory=lambda: int(os.getenv("RATE_LIMIT_RUNS_PER_MINUTE", "10")))

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


settings = Settings()


def git_hosts() -> frozenset[str]:
    """Git hosts repositories may be fetched from (INGEST_GIT_HOSTS)."""
    return frozenset(h.strip().lower() for h in settings.INGEST_GIT_HOSTS.split(",") if h.strip())


def pipeline_problem() -> str | None:
    if settings.PIPELINE_EXECUTION not in ("inline", "worker"):
        return f"PIPELINE_EXECUTION must be 'inline' or 'worker', not {settings.PIPELINE_EXECUTION!r}."
    if settings.PIPELINE_EXECUTION == "worker" and settings.DATABASE_BACKEND != "firestore":
        return (f"PIPELINE_EXECUTION=worker needs a database the API and the worker share (Firestore), "
                f"but DATABASE_BACKEND is {settings.DATABASE_BACKEND!r}: queued runs would never be seen.")
    return None


def startup_safety_problem() -> str | None:
    """Why this server must not start as configured, or None.

    Sign-in defaults to off when no Firebase credentials are set.  On a public
    server that would silently put every visitor in one shared account with
    all its data, so it has to be chosen explicitly (AUTH_REQUIRED=false).
    """
    if _hosted() and not settings.AUTH_REQUIRED and os.getenv("AUTH_REQUIRED") is None:
        return ("Sign-in is off on a public server because no Firebase credentials are set: every visitor "
                "would share one account and all of its data. Set FIREBASE_CREDENTIALS (sign-in then turns "
                "on), or set AUTH_REQUIRED=false to run without sign-in on purpose.")
    return pipeline_problem()
