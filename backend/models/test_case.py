"""
TestSphere-AI — TestCase Database Model.

Persistence model for test cases generated or stored in the platform.
Correlates with Member 1's TestCase contract via external_id.
"""

from datetime import datetime, timezone
from typing import TYPE_CHECKING, List, Optional
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database.session import Base

if TYPE_CHECKING:
    from backend.models.application import Application
    from backend.models.test_execution import TestExecution


class TestCase(Base):
    """TestCase entity representing a test case persistence record."""

    __tablename__ = "test_cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    application_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("applications.id", ondelete="CASCADE"),
        nullable=False,
    )
    external_id: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        index=True,
        doc="Correlation ID matching Member 1 TestCase.id (e.g., tc-001)",
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        doc="Category string corresponding to TestCategory enum values without modifying contract",
    )
    priority: Mapped[Optional[str]] = mapped_column(
        String(32),
        nullable=True,
        doc="Priority string corresponding to TestPriority enum values without modifying contract",
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships: TestCase -> Application (many-to-one)
    application: Mapped["Application"] = relationship(
        "Application",
        back_populates="test_cases",
    )

    # Relationships: TestCase -> many TestExecutions
    test_executions: Mapped[List["TestExecution"]] = relationship(
        "TestExecution",
        back_populates="test_case",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<TestCase(id={self.id}, name='{self.name}', external_id='{self.external_id}')>"
