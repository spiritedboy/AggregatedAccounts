import argparse
import asyncio
import json
from datetime import UTC, datetime

from sqlalchemy import select

from app.database import SessionLocal
from app.models import ExchangeAccount, TrackingPeriod
from app.services.accounts import adapter_for_account
from app.services.maintenance import rebuild_okx_closed_position_cycles


async def run(apply: bool) -> None:
    results = []
    async with SessionLocal() as db:
        accounts = (
            await db.scalars(
                select(ExchangeAccount).where(
                    ExchangeAccount.exchange == "OKX",
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
            adapter = await adapter_for_account(db, account)
            try:
                normalized = await adapter.get_closed_positions(
                    max(account.tracking_started_at, period.started_at),
                    datetime.now(UTC),
                )
            finally:
                await adapter.close()
            result = await rebuild_okx_closed_position_cycles(
                db,
                account=account,
                period=period,
                normalized_positions=normalized,
                apply=apply,
            )
            results.append(
                {
                    "account_id": str(account.id),
                    "connection_name": account.connection_name,
                    **result,
                }
            )
        if not apply:
            await db.rollback()
    print(json.dumps({"accounts": results}, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Preview or rebuild independent OKX closed-position cycles."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply rebuild. Without this flag the command is read-only.",
    )
    arguments = parser.parse_args()
    asyncio.run(run(arguments.apply))
