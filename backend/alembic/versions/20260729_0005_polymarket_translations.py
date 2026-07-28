"""add persistent polymarket translation cache

Revision ID: 20260729_0005
Revises: 20260728_0004
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260729_0005"
down_revision: str | None = "20260728_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "polymarket_translations",
        sa.Column("asset_id", sa.String(length=160), nullable=False),
        sa.Column("condition_id", sa.String(length=80), nullable=False),
        sa.Column("outcome_index", sa.Integer(), nullable=False),
        sa.Column("source_title", sa.Text(), nullable=False),
        sa.Column("source_outcome", sa.String(length=320), nullable=False),
        sa.Column("source_display", sa.Text(), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("translated_display", sa.Text(), nullable=True),
        sa.Column("target_language", sa.String(length=16), server_default="zh", nullable=False),
        sa.Column("provider", sa.String(length=32), server_default="BAIDU_LLM", nullable=False),
        sa.Column("status", sa.String(length=16), server_default="PENDING", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.String(length=240), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("asset_id"),
    )
    op.create_index(
        "ix_polymarket_translation_status",
        "polymarket_translations",
        ["status", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_polymarket_translation_status",
        table_name="polymarket_translations",
    )
    op.drop_table("polymarket_translations")
