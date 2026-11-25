"""initial schema

Baseline for the Phase 8 + Phase 10 tables. Databases created by the older
``Base.metadata.create_all()`` bootstrap already contain these tables but no ``alembic_version``
row; ``app.db.engine.run_migrations`` stamps this revision before upgrading, so both legacy and
fresh databases converge on the same schema.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-11-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("github_id", sa.String(length=64), nullable=True),
        sa.Column("username", sa.String(length=200), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=True),
        sa.Column("avatar_url", sa.String(length=500), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("github_id"),
    )

    op.create_table(
        "workspaces",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("local_path", sa.Text(), nullable=False),
        sa.Column("repo_url", sa.String(length=500), nullable=True),
        sa.Column("branch", sa.String(length=200), nullable=True),
        sa.Column("last_health_score", sa.Integer(), nullable=True),
        sa.Column("last_scanned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "local_path", name="uq_workspaces_user_path"),
    )
    op.create_index("ix_workspaces_user_id", "workspaces", ["user_id"])
    op.create_index("ix_workspaces_user_created", "workspaces", ["user_id", "created_at"])

    op.create_table(
        "rollback_batches",
        sa.Column("apply_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("root_path", sa.Text(), nullable=False),
        sa.Column("entries_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("apply_id"),
    )
    op.create_index("ix_rollback_batches_user_id", "rollback_batches", ["user_id"])
    op.create_index("ix_rollback_user_created", "rollback_batches", ["user_id", "created_at"])

    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("root_path", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("files_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_events_user_id", "audit_events", ["user_id"])
    op.create_index("ix_audit_user_timestamp", "audit_events", ["user_id", "timestamp"])

    op.create_table(
        "saved_blueprints",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("workspace_path", sa.Text(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("stack", sa.String(length=40), nullable=False),
        sa.Column("blueprint_json", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "workspace_path", name="uq_blueprints_user_path"),
    )
    op.create_index("ix_saved_blueprints_user_id", "saved_blueprints", ["user_id"])

    op.create_table(
        "user_settings",
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("settings_json", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )

    op.create_table(
        "architecture_decision_records",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=64), nullable=False),
        sa.Column("workspace_path", sa.Text(), nullable=False),
        sa.Column("decision_type", sa.String(length=40), nullable=False),
        sa.Column("subject", sa.String(length=300), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("recommended_route", sa.String(length=60), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("state_json", sa.Text(), nullable=False),
        sa.Column("answers_json", sa.Text(), nullable=False),
        sa.Column("feedback_status", sa.String(length=20), nullable=False),
        sa.Column("override_route", sa.String(length=60), nullable=True),
        sa.Column("feedback_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("feedback_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_adr_user_id", "architecture_decision_records", ["user_id"])
    op.create_index("ix_adr_user_created", "architecture_decision_records", ["user_id", "created_at"])
    op.create_index("ix_adr_user_workspace", "architecture_decision_records", ["user_id", "workspace_path"])


def downgrade() -> None:
    op.drop_index("ix_adr_user_workspace", table_name="architecture_decision_records")
    op.drop_index("ix_adr_user_created", table_name="architecture_decision_records")
    op.drop_index("ix_adr_user_id", table_name="architecture_decision_records")
    op.drop_table("architecture_decision_records")

    op.drop_table("user_settings")

    op.drop_index("ix_saved_blueprints_user_id", table_name="saved_blueprints")
    op.drop_table("saved_blueprints")

    op.drop_index("ix_audit_user_timestamp", table_name="audit_events")
    op.drop_index("ix_audit_events_user_id", table_name="audit_events")
    op.drop_table("audit_events")

    op.drop_index("ix_rollback_user_created", table_name="rollback_batches")
    op.drop_index("ix_rollback_batches_user_id", table_name="rollback_batches")
    op.drop_table("rollback_batches")

    op.drop_index("ix_workspaces_user_created", table_name="workspaces")
    op.drop_index("ix_workspaces_user_id", table_name="workspaces")
    op.drop_table("workspaces")

    op.drop_table("users")
