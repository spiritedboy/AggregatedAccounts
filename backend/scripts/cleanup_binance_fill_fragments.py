import argparse
import asyncio
import json
from datetime import UTC, datetime

from sqlalchemy import select

from app.database import SessionLocal
from app.models import ClosedPosition, ExchangeAccount, TrackingPeriod
from app.services.accounts import adapter_for_account
from app.services.maintenance import cleanup_binance_fill_fragments


async def run(apply: bool) -> None:
    results = []
    async with SessionLocal() as db:
        accounts = (
            await db.scalars(
                select(ExchangeAccount).where(
                    ExchangeAccount.exchange == "BINANCE",
                    ExchangeAccount.is_active.is_(True),
                    ExchangeAccount.is_demo.is_(False),
                )
            )
        ).all()
        for account in accounts:
            period = await db.scalar(
                select(TrackingPeriod).where(
                    TrackingPeriod.exchange_account_id == account.id,
                    TrackingPeriod.is_active.is_(True),
                )
            )
            if period is None:
                continue
            start_time = max(account.tracking_started_at, period.started_at)
            end_time = datetime.now(UTC)
            stored = (
                await db.scalars(
                    select(ClosedPosition).where(
                        ClosedPosition.exchange_account_id == account.id,
                        ClosedPosition.tracking_period_id == period.id,
                    )
                )
            ).all()
            adapter = await adapter_for_account(db, account)
            try:
                normalized = await adapter.get_closed_positions(
                    start_time,
                    end_time,
                )
                trade_order_ids: dict[str, str] = {}
                for symbol in sorted({row.symbol for row in stored}):
                    trades = await adapter._trade_rows(
                        symbol,
                        start_time,
                        end_time,
                    )
                    trade_order_ids.update(
                        {
                            str(row.get("id")): str(row.get("orderId"))
                            for row in trades
                            if row.get("id") is not None
                            and row.get("orderId") is not None
                        }
                    )
            finally:
                await adapter.close()
            results.append(
                await cleanup_binance_fill_fragments(
                    db,
                    account=account,
                    period=period,
                    normalized_positions=normalized,
                    trade_order_ids=trade_order_ids,
                    apply=apply,
                )
            )
        if not apply:
            await db.rollback()
    print(json.dumps({"accounts": results}, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Preview or merge Binance close-order fill fragments."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply cleanup. Without this flag the command is read-only.",
    )
    arguments = parser.parse_args()
    asyncio.run(run(arguments.apply))
