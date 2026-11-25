"""workspace size and activity

Phase 13 storage accounting: track how much disk a cloned workspace occupies and when it was last
touched, so SaaS quotas and TTL cleanup work without walking every directory on every request.

Both columns are nullable so existing Phase 8/10 rows upgrade without a backfill.

Revision ID: 0002_workspace_size_and_activity
Revises: 0001_initial_schema
Create Date: 2026-11-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_workspace_size_and_activity"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Column-existence guards keep this additive revision safe even if the table was created by a
    # newer ``create_all`` bootstrap (which already includes both columns).
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("workspaces")}
    with op.batch_alter_table("workspaces") as batch:
        if "size_bytes" not in existing:
            batch.add_column(sa.Column("size_bytes", sa.Integer(), nullable=True, server_default="0"))
        if "last_accessed_at" not in existing:
            batch.add_column(sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("workspaces")}
    with op.batch_alter_table("workspaces") as batch:
        if "last_accessed_at" in existing:
            batch.drop_column("last_accessed_at")
        if "size_bytes" in existing:
            batch.drop_column("size_bytes")
