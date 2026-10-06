"""
TestSphere-AI — Application Database Model.

Represents a web application under test associated with a Project.
"""

from datetime import datetime, timezone
from typing import TYPE_CHECKING, List, Optional
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database.session import Base

if TYPE_CHECKING:
    from backend.models.project import Project
    from backend.models.test_case import TestCase


class Application(Base):
    """Application entity representing a web application to be tested."""

    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    base_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
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

    # Relationships: Application -> Project (many-to-one)
    project: Mapped["Project"] = relationship(
        "Project",
        back_populates="applications",
    )

    # Relationships: Application -> many TestCases
    test_cases: Mapped[List["TestCase"]] = relationship(
        "TestCase",
        back_populates="application",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Application(id={self.id}, name='{self.name}', project_id={self.project_id})>"
