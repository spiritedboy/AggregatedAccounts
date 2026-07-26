"""add asset balances and persistent completeness details

Revision ID: 20260727_0003
Revises: 20260726_0002
Create Date: 2026-07-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260727_0003"
down_revision: str | None = "20260726_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    account_columns = {
        column["name"] for column in inspector.get_columns("exchange_accounts")
    }
    if "data_completeness_details" not in account_columns:
        op.add_column(
            "exchange_accounts",
            sa.Column(
                "data_completeness_details",
                postgresql.JSON(astext_type=sa.Text()),
                server_default=sa.text("'{}'::json"),
                nullable=False,
            ),
        )
    if "asset_balance_snapshots" not in inspector.get_table_names():
        op.create_table(
            "asset_balance_snapshots",
            sa.Column("asset", sa.String(length=40), nullable=False),
            sa.Column(
                "account_type",
                sa.String(length=24),
                server_default="SPOT",
                nullable=False,
            ),
            sa.Column("available", sa.Numeric(precision=30, scale=10), nullable=False),
            sa.Column("locked", sa.Numeric(precision=30, scale=10), nullable=False),
            sa.Column("value_usd", sa.Numeric(precision=30, scale=10), nullable=True),
            sa.Column(
                "price_source",
                sa.String(length=80),
                server_default="EXCHANGE_API",
                nullable=False,
            ),
            sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
            sa.Column("exchange", sa.String(length=24), nullable=False),
            sa.Column(
                "exchange_account_id",
                postgresql.UUID(as_uuid=True),
                nullable=False,
            ),
            sa.Column(
                "tracking_period_id",
                postgresql.UUID(as_uuid=True),
                nullable=False,
            ),
            sa.Column("source_record_id", sa.String(length=160), nullable=False),
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
            sa.ForeignKeyConstraint(
                ["exchange_account_id"], ["exchange_accounts.id"]
            ),
            sa.ForeignKeyConstraint(["tracking_period_id"], ["tracking_periods.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "exchange_account_id",
                "tracking_period_id",
                "source_record_id",
                name="uq_asset_balance_source",
            ),
        )
        op.create_index(
            "ix_asset_balance_latest",
            "asset_balance_snapshots",
            ["exchange_account_id", "recorded_at"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "asset_balance_snapshots" in inspector.get_table_names():
        index_names = {
            index["name"]
            for index in inspector.get_indexes("asset_balance_snapshots")
        }
        if "ix_asset_balance_latest" in index_names:
            op.drop_index(
                "ix_asset_balance_latest",
                table_name="asset_balance_snapshots",
            )
        op.drop_table("asset_balance_snapshots")
    account_columns = {
        column["name"] for column in inspector.get_columns("exchange_accounts")
    }
    if "data_completeness_details" in account_columns:
        op.drop_column("exchange_accounts", "data_completeness_details")
