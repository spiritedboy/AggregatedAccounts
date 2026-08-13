"""add indexes for snapshot, sync status, and position history queries

Revision ID: 20260810_0008
Revises: 20260805_0007
Create Date: 2026-08-10
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260810_0008"
down_revision: str | None = "20260805_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # PostgreSQL cannot build indexes concurrently inside Alembic's normal
    # migration transaction. The autocommit block keeps production reads and
    # the one-minute sync loop available while the existing rows are indexed.
    with op.get_context().autocommit_block():
        for statement in (
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_sync_job_account_started "
            "ON sync_jobs (exchange_account_id, started_at, id)",
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_sync_job_account_status_started "
            "ON sync_jobs (exchange_account_id, status, started_at, id)",
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_position_snapshot_recorded "
            "ON position_snapshots (recorded_at)",
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_position_snapshot_account_recorded "
            "ON position_snapshots (exchange_account_id, recorded_at)",
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_closed_position_close_time "
            "ON closed_positions (close_time)",
        ):
            op.execute(statement)


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for index_name, table_name in (
            ("ix_closed_position_close_time", "closed_positions"),
            ("ix_position_snapshot_account_recorded", "position_snapshots"),
            ("ix_position_snapshot_recorded", "position_snapshots"),
            ("ix_sync_job_account_status_started", "sync_jobs"),
            ("ix_sync_job_account_started", "sync_jobs"),
        ):
            op.drop_index(
                index_name,
                table_name=table_name,
                postgresql_concurrently=True,
            )
