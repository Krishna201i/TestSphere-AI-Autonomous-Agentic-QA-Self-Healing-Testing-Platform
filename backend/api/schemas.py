"""
TestSphere-AI — Member 3 API Request and Response Schemas.

Pydantic models for validation and serialization across Member 3 CRUD endpoints.
Does not modify or duplicate any shared contracts.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.config import git_hosts
from backend.models.test_execution import TestExecutionStatus
from backend.notify import NOTIFY_CHOICES, check_slack_webhook
from backend.pipeline.deploy_config import check_hook_url
from ingestion.source import SourceError, validate_git_url

# ============================================================================
# Project Schemas
# ============================================================================


SCHEDULE_CHOICES = (15, 30, 60, 180, 360, 720, 1440, 10080)  # minutes; None = no schedule


def _check_http_url(value: str | None, what: str) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return ""  # explicit clear
    if not value.lower().startswith(("http://", "https://")):
        raise ValueError(f"{what} must start with http:// or https://")
    return value


class _ProjectPipelineFields(BaseModel):
    """What the automated pipeline needs to know about a project."""

    app_url: str | None = Field(None, max_length=1024, description="Live URL the pipeline tests")
    repo_url: str | None = Field(None, max_length=1024, description="Git repository to ingest (optional)")
    prompt: str | None = Field(None, max_length=500, description="What to test, in plain words (optional)")
    schedule_minutes: int | None = Field(None, description=f"Re-run interval in minutes, one of {SCHEDULE_CHOICES}")
    slack_webhook_url: str | None = Field(None, max_length=500, description="Slack incoming webhook for run alerts")
    notify_on: str | None = Field(None, description="'failures' (default) or 'always'")
    deploy_hook_url: str | None = Field(None, max_length=1000, description="Deploy hook (Render, Vercel, Netlify, ...)")
    rollback_hook_url: str | None = Field(None, max_length=1000, description="Hook that restores the previous version")
    health_url: str | None = Field(None, max_length=1024, description="URL checked after a deploy (default: app URL)")
    deploy_on_pass: bool | None = Field(None, description="Deploy and verify automatically after a passing run")

    @field_validator("deploy_hook_url")
    @classmethod
    def _deploy_hook(cls, v: str | None) -> str | None:
        return check_hook_url(v, "Deploy hook")

    @field_validator("rollback_hook_url")
    @classmethod
    def _rollback_hook(cls, v: str | None) -> str | None:
        return check_hook_url(v, "Rollback hook")

    @field_validator("health_url")
    @classmethod
    def _health_url(cls, v: str | None) -> str | None:
        return _check_http_url(v, "Health URL")

    @field_validator("slack_webhook_url")
    @classmethod
    def _slack(cls, v: str | None) -> str | None:
        return check_slack_webhook(v)

    @field_validator("notify_on")
    @classmethod
    def _notify_on(cls, v: str | None) -> str | None:
        if v in (None, ""):
            return v
        if v not in NOTIFY_CHOICES:
            raise ValueError(f"notify_on must be one of {NOTIFY_CHOICES}")
        return v

    @field_validator("app_url")
    @classmethod
    def _app_url(cls, v: str | None) -> str | None:
        return _check_http_url(v, "App URL")

    @field_validator("repo_url")
    @classmethod
    def _repo_url(cls, v: str | None) -> str | None:
        v = _check_http_url(v, "Repository URL")
        if v:
            try:
                validate_git_url(v, git_hosts())
            except SourceError as exc:
                raise ValueError(f"Repository URL: {exc}") from exc
        return v

    @field_validator("schedule_minutes")
    @classmethod
    def _schedule(cls, v: int | None) -> int | None:
        if v in (None, 0):
            return None
        if v not in SCHEDULE_CHOICES:
            raise ValueError(f"schedule_minutes must be one of {SCHEDULE_CHOICES}")
        return v


class ProjectCreate(_ProjectPipelineFields):
    """Payload to create a new testing project."""

    name: str = Field(..., min_length=1, max_length=255, description="Project name")
    description: str | None = Field(None, max_length=5000, description="Optional project description")


class ProjectUpdate(_ProjectPipelineFields):
    """Payload to update an existing project (send null/\"\" to clear a pipeline field)."""

    name: str | None = Field(None, min_length=1, max_length=255, description="Updated project name")
    description: str | None = Field(None, max_length=5000, description="Updated description")


class ProjectResponse(BaseModel):
    """Serialized representation of a Project."""

    id: int
    name: str
    description: str | None = None
    app_url: str | None = None
    repo_url: str | None = None
    prompt: str | None = None
    schedule_minutes: int | None = None
    next_run_at: datetime | None = None
    last_run_id: int | None = None
    last_run_status: str | None = None
    last_run_at: datetime | None = None
    webhook_secret: str | None = None
    slack_webhook_url: str | None = None
    notify_on: str | None = None
    deploy_hook_url: str | None = None
    rollback_hook_url: str | None = None
    health_url: str | None = None
    deploy_on_pass: bool | None = None
    last_deploy_id: int | None = None
    last_deploy_status: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ============================================================================
# Application Schemas
# ============================================================================


class ApplicationCreate(BaseModel):
    """Payload to create an application under a project."""

    project_id: int = Field(..., description="Foreign key to Project")
    name: str = Field(..., min_length=1, max_length=255, description="Application name")
    base_url: str = Field(..., min_length=1, max_length=1024, description="Base URL of application under test")
    description: str | None = Field(None, max_length=5000, description="Optional application description")


class ApplicationUpdate(BaseModel):
    """Payload to update an existing application."""

    name: str | None = Field(None, min_length=1, max_length=255, description="Updated name")
    base_url: str | None = Field(None, min_length=1, max_length=1024, description="Updated base URL")
    description: str | None = Field(None, max_length=5000, description="Updated description")


class ApplicationResponse(BaseModel):
    """Serialized representation of an Application."""

    id: int
    project_id: int
    name: str
    base_url: str
    description: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ============================================================================
# TestCase Schemas
# ============================================================================


class TestCaseCreate(BaseModel):
    """Payload to create a persisted test case."""

    application_id: int = Field(..., description="Foreign key to Application")
    external_id: str = Field(..., min_length=1, max_length=255, description="Correlation identifier")
    name: str = Field(..., min_length=1, max_length=255, description="Test case name")
    description: str | None = Field(None, description="Test case description")
    category: str | None = Field(None, max_length=64, description="Test category")
    priority: str | None = Field(None, max_length=32, description="Test priority")
    version: int = Field(1, ge=1, description="Test case version")


class TestCaseUpdate(BaseModel):
    """Payload to update an existing test case."""

    external_id: str | None = Field(None, min_length=1, max_length=255)
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    category: str | None = None
    priority: str | None = None
    version: int | None = Field(None, ge=1)
    quarantined: bool | None = Field(None, description="Still runs, but its failures no longer fail the run")


class TestCaseResponse(BaseModel):
    """Serialized representation of a TestCase."""

    id: int
    application_id: int
    external_id: str | None = None
    name: str
    description: str | None = None
    category: str | None = None
    priority: str | None = None
    version: int
    quarantined: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ============================================================================
# TestExecution Schemas
# ============================================================================


class TestExecutionCreate(BaseModel):
    """Payload to record a test execution instance."""

    test_case_id: int = Field(..., description="Foreign key to TestCase")
    status: TestExecutionStatus = Field(default=TestExecutionStatus.PENDING, description="Initial status")
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = Field(None, ge=0)
    error_message: str | None = None


class TestExecutionUpdate(BaseModel):
    """Payload to update execution status and results."""

    status: TestExecutionStatus | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = Field(None, ge=0)
    error_message: str | None = None


class TestExecutionResponse(BaseModel):
    """Serialized representation of a TestExecution."""

    id: int
    test_case_id: int
    status: str
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = None
    error_message: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ExecutionStepHealing(BaseModel):
    original_locator: str
    selected_locator: str | None = None
    strategy: str = ""
    confidence: float = 0.0
    candidates: list[dict[str, Any]] = Field(default_factory=list)


class ExecutionStep(BaseModel):
    """One engine step as recorded for the run view."""

    step_id: str
    description: str | None = None
    status: str
    duration_ms: int = 0
    locator: str | None = None
    error: str | None = None
    healing: ExecutionStepHealing | None = None
    console: list[str] = Field(default_factory=list)
    network_errors: list[str] = Field(default_factory=list)
    screenshot: str | None = None
    dom: str | None = None


class TestExecutionDetail(TestExecutionResponse):
    """An execution with its step results and artifact keys."""

    steps: list[ExecutionStep] = Field(default_factory=list)
    trace: str | None = None
    visual: dict[str, Any] | None = Field(None, description="Visual check: changed, ratio, current/diff/baseline keys")
