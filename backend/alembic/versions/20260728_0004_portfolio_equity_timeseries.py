"""add five-minute portfolio equity time series

Revision ID: 20260728_0004
Revises: 20260727_0003
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260728_0004"
down_revision: str | None = "20260727_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


AGGREGATE_INTERVALS = {
    "portfolio_equity_30m": ("30 minutes", "5 minutes"),
    "portfolio_equity_2h": ("2 hours", "15 minutes"),
    "portfolio_equity_6h": ("6 hours", "30 minutes"),
    "portfolio_equity_12h": ("12 hours", "1 hour"),
}


def _create_continuous_aggregate(name: str, bucket: str, schedule: str) -> None:
    op.execute(
        sa.text(
            f"""
            CREATE MATERIALIZED VIEW {name}
            WITH (timescaledb.continuous) AS
            SELECT
                time_bucket(INTERVAL '{bucket}', bucket_time) AS bucket_time,
                last(total_equity_usd, bucket_time) AS total_equity_usd,
                last(available_balance_usd, bucket_time) AS available_balance_usd,
                last(margin_balance_usd, bucket_time) AS margin_balance_usd,
                last(unrealized_pnl_usd, bucket_time) AS unrealized_pnl_usd,
                last(unvalued_asset_count, bucket_time) AS unvalued_asset_count,
                last(account_count, bucket_time) AS account_count,
                last(stale_account_count, bucket_time) AS stale_account_count,
                max(source_latest_at) AS source_latest_at
            FROM portfolio_equity_points
            GROUP BY time_bucket(INTERVAL '{bucket}', bucket_time)
            WITH NO DATA
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            ALTER MATERIALIZED VIEW {name}
            SET (timescaledb.materialized_only = false)
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            SELECT add_continuous_aggregate_policy(
                '{name}',
                start_offset => INTERVAL '2 years',
                end_offset => INTERVAL '{bucket}',
                schedule_interval => INTERVAL '{schedule}',
                if_not_exists => true
            )
            """
        )
    )


def upgrade() -> None:
    op.create_table(
        "portfolio_equity_points",
        sa.Column("bucket_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "total_equity_usd",
            sa.Numeric(precision=30, scale=10),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "available_balance_usd",
            sa.Numeric(precision=30, scale=10),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "margin_balance_usd",
            sa.Numeric(precision=30, scale=10),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "unrealized_pnl_usd",
            sa.Numeric(precision=30, scale=10),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "unvalued_asset_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("account_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "stale_account_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("source_latest_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("bucket_time"),
    )

    if op.get_bind().dialect.name != "postgresql":
        return

    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
    op.execute(
        """
        SELECT create_hypertable(
            'portfolio_equity_points',
            by_range('bucket_time', INTERVAL '7 days'),
            if_not_exists => true
        )
        """
    )
    for name, (bucket, schedule) in AGGREGATE_INTERVALS.items():
        _create_continuous_aggregate(name, bucket, schedule)


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for name in reversed(AGGREGATE_INTERVALS):
            op.execute(f"DROP MATERIALIZED VIEW IF EXISTS {name}")
    op.drop_table("portfolio_equity_points")
