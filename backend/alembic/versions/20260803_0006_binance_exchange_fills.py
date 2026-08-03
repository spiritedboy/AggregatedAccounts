"""Classify Binance closed positions as exchange-fill data.

Revision ID: 20260803_0006
Revises: 20260729_0005
"""

import sqlalchemy as sa

from alembic import op

revision: str = "20260803_0006"
down_revision: str | None = "20260729_0005"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE closed_positions
            SET data_source = 'EXCHANGE_FILLS'
            WHERE exchange = 'BINANCE'
              AND data_source = 'RECONSTRUCTED'
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE closed_positions
            SET data_source = 'RECONSTRUCTED'
            WHERE exchange = 'BINANCE'
              AND data_source = 'EXCHANGE_FILLS'
            """
        )
    )
