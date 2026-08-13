"""add PnL analytics read model

Revision ID: 20260813_0011
Revises: 20260810_0010
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260813_0011"
down_revision: str | None = "20260810_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pnl_analytics_summaries",
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("daily", sa.JSON(), nullable=False),
        sa.Column("weekly", sa.JSON(), nullable=False),
        sa.Column("monthly", sa.JSON(), nullable=False),
        sa.Column("by_side", sa.JSON(), nullable=False),
        sa.Column("trade_quality", sa.JSON(), nullable=False),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("scope"),
    )
    op.create_table(
        "pnl_exchange_summaries",
        sa.Column("exchange", sa.String(length=24), nullable=False),
        sa.Column("realized_pnl", sa.Numeric(30, 10), nullable=False),
        sa.Column("funding_fee", sa.Numeric(30, 10), nullable=False),
        sa.Column("trading_fee", sa.Numeric(30, 10), nullable=False),
        sa.Column("investment_return", sa.Numeric(30, 10), nullable=False),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("exchange"),
    )
    op.create_index(
        "ix_pnl_exchange_summary_calculated",
        "pnl_exchange_summaries",
        ["calculated_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_pnl_exchange_summary_calculated", table_name="pnl_exchange_summaries")
    op.drop_table("pnl_exchange_summaries")
    op.drop_table("pnl_analytics_summaries")
