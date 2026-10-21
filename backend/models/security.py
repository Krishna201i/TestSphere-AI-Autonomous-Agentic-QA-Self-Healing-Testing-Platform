"""
TestSphere-AI — Security Finding & Audit Event Models.

Findings persist across scans (one row per check + component, see
``Finding.key``) together with who approved the fix and the latest retest.
Audit events record every scan, approval, retest and QA run so the
approval trail survives browser resets and is shared by all viewers.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.database.session import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SecurityFinding(Base):
    """Latest known state of one security finding."""

    __tablename__ = "security_findings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    target_url: Mapped[str] = mapped_column(Text, nullable=False)
    check_id: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[str] = mapped_column(Text, nullable=False, doc="Full finding + remediation as JSON")
    status: Mapped[str] = mapped_column(String(16), default="open", nullable=False)
    retest_result: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    retested_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, nullable=False)


class AuditEvent(Base):
    """Append-only record of an action taken on the platform."""

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True, nullable=False)
    actor: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    level: Mapped[str] = mapped_column(String(16), default="info", nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    ref: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, doc="Finding key, execution id, …")
