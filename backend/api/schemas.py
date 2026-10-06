"""
TestSphere-AI — Member 3 API Request and Response Schemas.

Pydantic models for validation and serialization across Member 3 CRUD endpoints.
Does not modify or duplicate any shared contracts.
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field

from backend.models.test_execution import TestExecutionStatus


# ============================================================================
# Project Schemas
# ============================================================================


class ProjectCreate(BaseModel):
    """Payload to create a new testing project."""

    name: str = Field(..., min_length=1, max_length=255, description="Project name")
    description: Optional[str] = Field(None, description="Optional project description")


class ProjectUpdate(BaseModel):
    """Payload to update an existing project."""

    name: Optional[str] = Field(None, min_length=1, max_length=255, description="Updated project name")
    description: Optional[str] = Field(None, description="Updated description")


class ProjectResponse(BaseModel):
    """Serialized representation of a Project."""

    id: int
    name: str
    description: Optional[str] = None
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
    description: Optional[str] = Field(None, description="Optional application description")


class ApplicationUpdate(BaseModel):
    """Payload to update an existing application."""

    name: Optional[str] = Field(None, min_length=1, max_length=255, description="Updated name")
    base_url: Optional[str] = Field(None, min_length=1, max_length=1024, description="Updated base URL")
    description: Optional[str] = Field(None, description="Updated description")


class ApplicationResponse(BaseModel):
    """Serialized representation of an Application."""

    id: int
    project_id: int
    name: str
    base_url: str
    description: Optional[str] = None
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
    description: Optional[str] = Field(None, description="Test case description")
    category: Optional[str] = Field(None, max_length=64, description="Test category")
    priority: Optional[str] = Field(None, max_length=32, description="Test priority")
    version: int = Field(1, ge=1, description="Test case version")


class TestCaseUpdate(BaseModel):
    """Payload to update an existing test case."""

    external_id: Optional[str] = Field(None, min_length=1, max_length=255)
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    category: Optional[str] = None
    priority: Optional[str] = None
    version: Optional[int] = Field(None, ge=1)


class TestCaseResponse(BaseModel):
    """Serialized representation of a TestCase."""

    id: int
    application_id: int
    external_id: Optional[str] = None
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    priority: Optional[str] = None
    version: int
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
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_ms: Optional[int] = Field(None, ge=0)
    error_message: Optional[str] = None


class TestExecutionUpdate(BaseModel):
    """Payload to update execution status and results."""

    status: Optional[TestExecutionStatus] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_ms: Optional[int] = Field(None, ge=0)
    error_message: Optional[str] = None


class TestExecutionResponse(BaseModel):
    """Serialized representation of a TestExecution."""

    id: int
    test_case_id: int
    status: str
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    error_message: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
