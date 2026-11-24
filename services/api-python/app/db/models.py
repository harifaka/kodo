"""SQLAlchemy 2.0 tables for Kodo's persistent SaaS foundation.

The schema is intentionally portable between SQLite (local mode) and PostgreSQL (SaaS / managed
Postgres): JSON payloads are stored as text so the same migrations-free ``create_all`` bootstrap
works on both engines.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    github_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    username: Mapped[str] = mapped_column(String(200), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Workspace(Base):
    __tablename__ = "workspaces"
    __table_args__ = (
        UniqueConstraint("user_id", "local_path", name="uq_workspaces_user_path"),
        Index("ix_workspaces_user_created", "user_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    local_path: Mapped[str] = mapped_column(Text, nullable=False)
    repo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    branch: Mapped[str | None] = mapped_column(String(200), nullable=True)
    last_health_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RollbackBatch(Base):
    """Persisted rollback snapshot — the SaaS replacement for the in-memory deque."""

    __tablename__ = "rollback_batches"
    __table_args__ = (Index("ix_rollback_user_created", "user_id", "created_at"),)

    apply_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    root_path: Mapped[str] = mapped_column(Text, nullable=False)
    entries_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_user_timestamp", "user_id", "timestamp"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    root_path: Mapped[str] = mapped_column(Text, nullable=False, default="")
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    files_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="success")


class SavedBlueprint(Base):
    __tablename__ = "saved_blueprints"
    __table_args__ = (UniqueConstraint("user_id", "workspace_path", name="uq_blueprints_user_path"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    workspace_path: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    stack: Mapped[str] = mapped_column(String(40), nullable=False)
    blueprint_json: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class UserSettings(Base):
    __tablename__ = "user_settings"

    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    settings_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ArchitectureDecisionRecord(Base):
    """Phase 10 ADR: one advisory System 1 decision plus the human feedback on it.

    Records are strictly tenant-scoped. ``state_json`` keeps the compact deterministic state that was
    sent to Laya and ``answers_json`` the full typed answer distribution, so every route Kodo took
    stays inspectable and exportable for local calibration.
    """

    __tablename__ = "architecture_decision_records"
    __table_args__ = (
        Index("ix_adr_user_created", "user_id", "created_at"),
        Index("ix_adr_user_workspace", "user_id", "workspace_path"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    workspace_path: Mapped[str] = mapped_column(Text, nullable=False, default="")
    decision_type: Mapped[str] = mapped_column(String(40), nullable=False)
    subject: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    model: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    recommended_route: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    state_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    answers_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    feedback_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    override_route: Mapped[str | None] = mapped_column(String(60), nullable=True)
    feedback_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    feedback_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


__all__ = [
    "ArchitectureDecisionRecord",
    "AuditEvent",
    "Base",
    "RollbackBatch",
    "SavedBlueprint",
    "User",
    "UserSettings",
    "Workspace",
    "utcnow",
]
