"""align sync-job indexes with latest-row query ordering

Revision ID: 20260810_0009
Revises: 20260810_0008
Create Date: 2026-08-10
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260810_0009"
down_revision: str | None = "20260810_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            "ix_sync_job_account_started",
            table_name="sync_jobs",
            postgresql_concurrently=True,
        )
        op.drop_index(
            "ix_sync_job_account_status_started",
            table_name="sync_jobs",
            postgresql_concurrently=True,
        )
        op.create_index(
            "ix_sync_job_account_started",
            "sync_jobs",
            ["exchange_account_id", sa.text("started_at DESC"), sa.text("id DESC")],
            postgresql_concurrently=True,
        )
        op.create_index(
            "ix_sync_job_account_status_started",
            "sync_jobs",
            [
                "exchange_account_id",
                "status",
                sa.text("started_at DESC"),
                sa.text("id DESC"),
            ],
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            "ix_sync_job_account_started",
            table_name="sync_jobs",
            postgresql_concurrently=True,
        )
        op.drop_index(
            "ix_sync_job_account_status_started",
            table_name="sync_jobs",
            postgresql_concurrently=True,
        )
        op.create_index(
            "ix_sync_job_account_started",
            "sync_jobs",
            ["exchange_account_id", "started_at", "id"],
            postgresql_concurrently=True,
        )
        op.create_index(
            "ix_sync_job_account_status_started",
            "sync_jobs",
            ["exchange_account_id", "status", "started_at", "id"],
            postgresql_concurrently=True,
        )
