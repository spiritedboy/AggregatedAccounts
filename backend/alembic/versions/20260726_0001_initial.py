"""Create portfolio schema.

Revision ID: 20260726_0001
Revises:
"""

from alembic import op
from app.models import Base

revision = "20260726_0001"
down_revision = None
branch_labels = None
depends_on = None

# This original revision historically used live ORM metadata. Keep later-added
# tables out of the baseline so a brand-new database can advance through each
# owning revision without attempting to create the same table twice.
LATER_TABLES = {
    "asset_balance_snapshots",
    "portfolio_equity_points",
    "polymarket_translations",
    "latest_account_balances",
    "latest_asset_balances",
    "pnl_analytics_summaries",
    "pnl_exchange_summaries",
}


def upgrade() -> None:
    tables = [table for table in Base.metadata.sorted_tables if table.name not in LATER_TABLES]
    Base.metadata.create_all(bind=op.get_bind(), tables=tables)


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
