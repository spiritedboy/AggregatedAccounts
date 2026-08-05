"""Store leverage and margin for closed-position returns.

Revision ID: 20260805_0007
Revises: 20260803_0006
"""

import sqlalchemy as sa

from alembic import op

revision: str = "20260805_0007"
down_revision: str | None = "20260803_0006"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("closed_positions", sa.Column("leverage", sa.Numeric(12, 4), nullable=True))
    op.add_column(
        "closed_positions",
        sa.Column("margin_used", sa.Numeric(30, 10), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("closed_positions", "margin_used")
    op.drop_column("closed_positions", "leverage")
