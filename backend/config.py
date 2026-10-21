"""
TestSphere-AI — Member 3 Configuration Module.

Reads configuration settings from environment variables with safe defaults.
Does not hardcode any sensitive information.
"""

import os
from typing import List
from pydantic import Field
from pydantic_settings import BaseSettings


# Set by common hosting platforms; their servers are public, so local-path
# ingestion (reading the server's own disk) must be opted into explicitly there.
_CLOUD_MARKERS = ("RENDER", "DYNO", "RAILWAY_ENVIRONMENT", "FLY_APP_NAME", "K_SERVICE", "VERCEL")


def _default_allow_local_paths() -> bool:
    explicit = os.getenv("INGEST_ALLOW_LOCAL_PATHS")
    if explicit is not None:
        return explicit.lower() in ("true", "1")
    on_cloud = any(os.getenv(marker) for marker in _CLOUD_MARKERS)
    return os.getenv("APP_ENV", "development") == "development" and not on_cloud


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
    DATABASE_URL: str = Field(
        default_factory=lambda: os.getenv("DATABASE_URL", "sqlite:///./testsphere.db")
    )

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

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


settings = Settings()
