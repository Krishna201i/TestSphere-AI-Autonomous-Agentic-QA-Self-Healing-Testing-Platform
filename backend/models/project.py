"""
TestSphere-AI — Project Database Model.

Represents a testing project within the TestSphere-AI platform.
"""

from datetime import datetime, timezone
from typing import TYPE_CHECKING, List, Optional
from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database.session import Base

if TYPE_CHECKING:
    from backend.models.application import Application


class Project(Base):
    """Project entity representing a testing project."""

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
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

    # Relationships: Project -> many Applications
    applications: Mapped[List["Application"]] = relationship(
        "Application",
        back_populates="project",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Project(id={self.id}, name='{self.name}')>"
