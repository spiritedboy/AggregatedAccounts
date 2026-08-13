"""add operational page read models

Revision ID: 20260813_0012
Revises: 20260813_0011
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260813_0012"
down_revision: str | None = "20260813_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "operational_read_models",
        sa.Column("scope", sa.String(length=40), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.PrimaryKeyConstraint("scope"),
    )
    op.create_table(
        "accounting_daily_summaries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("exchange", sa.String(length=24), nullable=False),
        sa.Column("exchange_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("record_date", sa.Date(), nullable=False),
        sa.Column("record_type", sa.String(length=24), nullable=False),
        sa.Column("amount_usd", sa.Numeric(30, 10), nullable=False),
        sa.Column("record_count", sa.Integer(), nullable=False),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "exchange_account_id", "record_date", "record_type", name="uq_accounting_daily_summary"
        ),
    )
    op.create_index(
        "ix_accounting_daily_summary_filters",
        "accounting_daily_summaries",
        ["record_date", "exchange", "record_type"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_accounting_daily_summary_filters", table_name="accounting_daily_summaries"
    )
    op.drop_table("accounting_daily_summaries")
    op.drop_table("operational_read_models")
