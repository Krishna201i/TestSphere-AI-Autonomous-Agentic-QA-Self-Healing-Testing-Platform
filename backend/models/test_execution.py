"""
TestSphere-AI — TestExecution Database Model.

Represents an execution run of a TestCase within the platform.
Uses a local database-safe enum representation supporting lifecycle states:
PENDING, RUNNING, PASSED, FAILED.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Optional
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database.session import Base

if TYPE_CHECKING:
    from backend.models.test_case import TestCase


class TestExecutionStatus(str, Enum):
    """Lifecycle statuses for test execution runs in the database."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PASSED = "PASSED"
    FAILED = "FAILED"


class TestExecution(Base):
    """TestExecution entity representing a single execution instance of a test case."""

    __tablename__ = "test_executions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    test_case_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("test_cases.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default=TestExecutionStatus.PENDING.value,
        nullable=False,
        doc="Execution lifecycle status: PENDING, RUNNING, PASSED, FAILED",
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    duration_ms: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
    )
    error_message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships: TestExecution -> TestCase (many-to-one)
    test_case: Mapped["TestCase"] = relationship(
        "TestCase",
        back_populates="test_executions",
    )

    def __repr__(self) -> str:
        return f"<TestExecution(id={self.id}, test_case_id={self.test_case_id}, status='{self.status}')>"
