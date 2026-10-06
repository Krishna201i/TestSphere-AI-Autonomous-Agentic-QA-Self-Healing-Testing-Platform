"""
TestSphere-AI — Member 3 Configuration Module.

Reads configuration settings from environment variables with safe defaults.
Does not hardcode any sensitive information.
"""

import os
from typing import List
from pydantic import Field
from pydantic_settings import BaseSettings


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

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


settings = Settings()
