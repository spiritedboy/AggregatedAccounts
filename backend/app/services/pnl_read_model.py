from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PnlAnalyticsSummary, PnlExchangeSummary

ACTIVE_SCOPE = "ACTIVE_PORTFOLIO"


def _number(value: Decimal | float | int | None) -> float:
    return float(value or 0)


async def refresh_pnl_read_model(db: AsyncSession) -> dict[str, Any]:
    """Rebuild the complete PnL read model from authoritative detail tables."""
    # Imported lazily to keep the API module focused on transport while this
    # service remains callable from startup and scheduled jobs without an
    # import-time cycle.
    from app.api import _calculate_pnl_bootstrap_data

    payload = jsonable_encoder(await _calculate_pnl_bootstrap_data(db))
    calculated_at = datetime.now(UTC)
    exchange_rows = payload.pop("by_exchange")

    row = await db.get(PnlAnalyticsSummary, ACTIVE_SCOPE)
    if row is None:
        row = PnlAnalyticsSummary(scope=ACTIVE_SCOPE)
        db.add(row)
    row.summary = payload["summary"]
    row.daily = payload["daily"]
    row.weekly = payload["weekly"]
    row.monthly = payload["monthly"]
    row.by_side = payload["by_side"]
    row.trade_quality = payload["trade_quality"]
    row.calculated_at = calculated_at

    active_exchanges = {item["exchange"] for item in exchange_rows}
    if active_exchanges:
        await db.execute(
            delete(PnlExchangeSummary).where(
                PnlExchangeSummary.exchange.not_in(active_exchanges)
            )
        )
    else:
        await db.execute(delete(PnlExchangeSummary))
    for item in exchange_rows:
        exchange_row = await db.get(PnlExchangeSummary, item["exchange"])
        if exchange_row is None:
            exchange_row = PnlExchangeSummary(exchange=item["exchange"])
            db.add(exchange_row)
        exchange_row.realized_pnl = Decimal(str(item["realized_pnl"]))
        exchange_row.funding_fee = Decimal(str(item["funding_fee"]))
        exchange_row.trading_fee = Decimal(str(item["trading_fee"]))
        exchange_row.investment_return = Decimal(str(item["investment_return"]))
        exchange_row.calculated_at = calculated_at

    await db.flush()
    return {**payload, "by_exchange": exchange_rows}


async def get_pnl_read_model(db: AsyncSession) -> dict[str, Any] | None:
    row = await db.get(PnlAnalyticsSummary, ACTIVE_SCOPE)
    if row is None:
        return None
    exchanges = (
        await db.scalars(select(PnlExchangeSummary).order_by(PnlExchangeSummary.exchange))
    ).all()
    return {
        "summary": row.summary,
        "daily": row.daily,
        "weekly": row.weekly,
        "monthly": row.monthly,
        "by_exchange": [
            {
                "exchange": item.exchange,
                "realized_pnl": _number(item.realized_pnl),
                "funding_fee": _number(item.funding_fee),
                "trading_fee": _number(item.trading_fee),
                "investment_return": _number(item.investment_return),
            }
            for item in exchanges
        ],
        "by_side": row.by_side,
        "trade_quality": row.trade_quality,
    }
