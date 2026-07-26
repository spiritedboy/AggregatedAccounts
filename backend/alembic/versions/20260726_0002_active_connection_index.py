"""Allow repeated historical connections while keeping active names unique.

Revision ID: 20260726_0002
Revises: 20260726_0001
"""

import sqlalchemy as sa

from alembic import op

revision = "20260726_0002"
down_revision = "20260726_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("uq_active_connection", "exchange_accounts", type_="unique")
    op.create_index(
        "uq_active_connection",
        "exchange_accounts",
        ["exchange", "connection_name"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )


def downgrade() -> None:
    op.drop_index("uq_active_connection", table_name="exchange_accounts")
    op.create_unique_constraint(
        "uq_active_connection",
        "exchange_accounts",
        ["exchange", "connection_name", "is_active"],
    )
