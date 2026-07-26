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
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    constraint_names = {
        item["name"] for item in inspector.get_unique_constraints("exchange_accounts")
    }
    index_names = {item["name"] for item in inspector.get_indexes("exchange_accounts")}

    if "uq_active_connection" in constraint_names:
        op.drop_constraint("uq_active_connection", "exchange_accounts", type_="unique")
        op.create_index(
            "uq_active_connection",
            "exchange_accounts",
            ["exchange", "connection_name"],
            unique=True,
            postgresql_where=sa.text("is_active"),
        )
    elif "uq_active_connection" not in index_names:
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
