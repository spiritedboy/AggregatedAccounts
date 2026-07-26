import argparse
import asyncio
import json
from datetime import UTC, datetime

from sqlalchemy import select

from app.database import SessionLocal
from app.models import (
    CashFlowRecord,
    ExchangeAccount,
    FundingRecord,
    IncomeRecord,
    TrackingPeriod,
    TradingFeeRecord,
)
from app.services.accounts import (
    HISTORY_STREAMS,
    _upsert_amount_records,
    adapter_for_account,
    update_completeness,
)

RECORD_MODELS = (
    ("income", IncomeRecord),
    ("funding", FundingRecord),
    ("fees", TradingFeeRecord),
    ("cash_flows", CashFlowRecord),
)


async def run(exchange: str, connection_name: str | None, apply: bool) -> None:
    async with SessionLocal() as db:
        query = select(ExchangeAccount).where(
            ExchangeAccount.exchange == exchange.upper(),
            ExchangeAccount.deleted_at.is_(None),
        )
        if connection_name:
            query = query.where(ExchangeAccount.connection_name == connection_name)
        accounts = (await db.scalars(query)).all()
        if not accounts:
            raise SystemExit("No matching exchange account.")

        results = []
        for account in accounts:
            period = await db.scalar(
                select(TrackingPeriod).where(
                    TrackingPeriod.exchange_account_id == account.id,
                    TrackingPeriod.is_active.is_(True),
                )
            )
            if not period:
                continue
            end_time = datetime.now(UTC)
            start_time = max(account.tracking_started_at, period.started_at)
            adapter = await adapter_for_account(db, account)
            try:
                bundle = await adapter.get_history_bundle(start_time, end_time)
            finally:
                await adapter.close()

            fetched = {}
            for stream, model in RECORD_MODELS:
                rows = bundle.get(stream, [])
                fetched[stream] = len(rows)
                await _upsert_amount_records(db, account, period, model, rows)
            history_status = (
                "COMPLETE"
                if adapter.history_streams == HISTORY_STREAMS and bool(bundle.get("complete"))
                else "PARTIAL"
            )
            update_completeness(
                account,
                {
                    stream: (
                        history_status
                        if stream in adapter.history_streams
                        else "UNSUPPORTED"
                    )
                    for stream in HISTORY_STREAMS
                },
                authoritative=True,
            )
            results.append(
                {
                    "account_id": str(account.id),
                    "exchange": account.exchange,
                    "connection_name": account.connection_name,
                    "from": start_time.isoformat(),
                    "to": end_time.isoformat(),
                    "fetched": fetched,
                    "complete": bool(bundle.get("complete")),
                }
            )

        if apply:
            await db.commit()
        else:
            await db.rollback()
        print(json.dumps({"applied": apply, "accounts": results}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Idempotently backfill accounting history for configured accounts."
    )
    parser.add_argument("--exchange", required=True, help="Exchange name, e.g. HYPERLIQUID.")
    parser.add_argument("--connection-name", help="Optional configured connection name.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Commit the backfill. Without this flag the transaction is rolled back.",
    )
    arguments = parser.parse_args()
    asyncio.run(run(arguments.exchange, arguments.connection_name, arguments.apply))
