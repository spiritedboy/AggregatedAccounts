"""add latest account and asset balance state tables

Revision ID: 20260810_0010
Revises: 20260810_0009
Create Date: 2026-08-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260810_0010"
down_revision: str | None = "20260810_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "latest_account_balances",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("exchange", sa.String(length=24), nullable=False),
        sa.Column("exchange_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tracking_period_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("total_equity_usd", sa.Numeric(30, 10), nullable=False),
        sa.Column("available_balance_usd", sa.Numeric(30, 10), nullable=False),
        sa.Column("margin_balance_usd", sa.Numeric(30, 10), nullable=False),
        sa.Column("unrealized_pnl_usd", sa.Numeric(30, 10), nullable=False),
        sa.Column("unvalued_asset_count", sa.Integer(), nullable=False),
        sa.Column("price_source", sa.String(length=80), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["exchange_account_id"], ["exchange_accounts.id"]),
        sa.ForeignKeyConstraint(["tracking_period_id"], ["tracking_periods.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("exchange_account_id"),
    )
    op.create_index(
        "ix_latest_account_balance_recorded",
        "latest_account_balances",
        ["recorded_at"],
    )
    op.create_table(
        "latest_asset_balances",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("exchange", sa.String(length=24), nullable=False),
        sa.Column("exchange_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tracking_period_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("asset", sa.String(length=40), nullable=False),
        sa.Column("account_type", sa.String(length=24), nullable=False),
        sa.Column("available", sa.Numeric(30, 10), nullable=False),
        sa.Column("locked", sa.Numeric(30, 10), nullable=False),
        sa.Column("value_usd", sa.Numeric(30, 10), nullable=True),
        sa.Column("price_source", sa.String(length=80), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["exchange_account_id"], ["exchange_accounts.id"]),
        sa.ForeignKeyConstraint(["tracking_period_id"], ["tracking_periods.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "exchange_account_id",
            "account_type",
            "asset",
            name="uq_latest_asset_balance",
        ),
    )
    op.create_index(
        "ix_latest_asset_balance_account",
        "latest_asset_balances",
        ["exchange_account_id"],
    )
    op.create_index(
        "ix_latest_asset_balance_recorded",
        "latest_asset_balances",
        ["recorded_at"],
    )

    op.execute(
        """
        INSERT INTO latest_account_balances (
            id, exchange, exchange_account_id, tracking_period_id,
            total_equity_usd, available_balance_usd, margin_balance_usd,
            unrealized_pnl_usd, unvalued_asset_count, price_source,
            recorded_at, created_at, updated_at
        )
        SELECT DISTINCT ON (exchange_account_id)
            id, exchange, exchange_account_id, tracking_period_id,
            total_equity_usd, available_balance_usd, margin_balance_usd,
            unrealized_pnl_usd, unvalued_asset_count, price_source,
            recorded_at, created_at, updated_at
        FROM account_balance_snapshots
        ORDER BY exchange_account_id, recorded_at DESC, id DESC
        """
    )
    op.execute(
        """
        INSERT INTO latest_asset_balances (
            id, exchange, exchange_account_id, tracking_period_id,
            asset, account_type, available, locked, value_usd, price_source,
            recorded_at, created_at, updated_at
        )
        SELECT
            snapshot.id, snapshot.exchange, snapshot.exchange_account_id,
            snapshot.tracking_period_id, snapshot.asset, snapshot.account_type,
            snapshot.available, snapshot.locked, snapshot.value_usd,
            snapshot.price_source, snapshot.recorded_at,
            snapshot.created_at, snapshot.updated_at
        FROM asset_balance_snapshots snapshot
        JOIN (
            SELECT exchange_account_id, max(recorded_at) AS recorded_at
            FROM asset_balance_snapshots
            GROUP BY exchange_account_id
        ) latest USING (exchange_account_id, recorded_at)
        """
    )


def downgrade() -> None:
    op.drop_index("ix_latest_asset_balance_recorded", table_name="latest_asset_balances")
    op.drop_index("ix_latest_asset_balance_account", table_name="latest_asset_balances")
    op.drop_table("latest_asset_balances")
    op.drop_index("ix_latest_account_balance_recorded", table_name="latest_account_balances")
    op.drop_table("latest_account_balances")
