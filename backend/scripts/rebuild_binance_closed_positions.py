import argparse
import asyncio
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.adapters.binance import BinanceAdapter
from app.database import SessionLocal
from app.models import ClosedPosition, ExchangeAccount, SecurityAuditLog, TrackingPeriod
from app.services.accounts import _upsert_closed_positions, adapter_for_account
from app.services.operational_read_models import refresh_operational_read_models
from app.services.pnl_read_model import refresh_pnl_read_model


def _value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal | float | int):
        normalized = Decimal(str(value)).quantize(Decimal("0.0000000001"))
        return format(normalized, "f")
    return str(value)


def _comparison(
    existing: ClosedPosition | None,
    rebuilt: dict[str, Any],
) -> dict[str, Any]:
    fields = (
        "open_time",
        "close_time",
        "max_position_size",
        "realized_pnl",
        "funding_fee",
        "trading_fee",
        "net_pnl",
    )
    changes = {
        field: {
            "before": _value(getattr(existing, field, None)),
            "after": _value(rebuilt.get(field)),
        }
        for field in fields
        if _value(getattr(existing, field, None)) != _value(rebuilt.get(field))
    }
    return {
        "source_record_id": str(rebuilt["source_record_id"]),
        "symbol": rebuilt["normalized_symbol"],
        "side": rebuilt["side"],
        "changes": changes,
    }


async def run(*, apply: bool, symbol: str | None) -> None:
    requested_symbol = symbol.upper() if symbol else None
    results: list[dict[str, Any]] = []
    changed = 0
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
            end_time = datetime.now(UTC)
            start_time = max(
                account.tracking_started_at,
                period.started_at,
                end_time - timedelta(days=89),
            )
            adapter = await adapter_for_account(db, account)
            if not isinstance(adapter, BinanceAdapter):
                await adapter.close()
                raise TypeError("Expected BinanceAdapter for BINANCE account")
            try:
                if requested_symbol:
                    normalized = await adapter._closed_positions_for_symbols(
                        [requested_symbol], start_time, end_time
                    )
                else:
                    normalized = await adapter.get_closed_positions(start_time, end_time)
            finally:
                await adapter.close()

            if requested_symbol:
                normalized = [
                    item
                    for item in normalized
                    if str(item.get("symbol") or "").upper() == requested_symbol
                    or str(item.get("normalized_symbol") or "").upper()
                    == requested_symbol
                ]
            source_ids = [str(item["source_record_id"]) for item in normalized]
            existing_rows = (
                await db.scalars(
                    select(ClosedPosition).where(
                        ClosedPosition.exchange_account_id == account.id,
                        ClosedPosition.tracking_period_id == period.id,
                        ClosedPosition.source_record_id.in_(source_ids),
                    )
                )
            ).all()
            existing_by_source = {row.source_record_id: row for row in existing_rows}
            comparisons = [
                _comparison(existing_by_source.get(str(item["source_record_id"])), item)
                for item in normalized
            ]
            comparisons = [item for item in comparisons if item["changes"]]
            changed += len(comparisons)
            results.append(
                {
                    "account_id": str(account.id),
                    "connection_name": account.connection_name,
                    "rebuilt_positions": len(normalized),
                    "changed_positions": len(comparisons),
                    "positions": comparisons,
                }
            )
            if apply and normalized:
                await _upsert_closed_positions(db, account, period, normalized)

        if apply and changed:
            await db.flush()
            await refresh_pnl_read_model(db)
            await refresh_operational_read_models(db, full_accounting=True)
            db.add(
                SecurityAuditLog(
                    action="BINANCE_CLOSED_POSITIONS_REBUILT",
                    outcome="SUCCESS",
                    client_ip="maintenance",
                    details={
                        "symbol": requested_symbol,
                        "changed_positions": changed,
                        "accounts": results,
                    },
                )
            )
            await db.commit()
        else:
            await db.rollback()

    print(
        json.dumps(
            {
                "applied": apply,
                "symbol": requested_symbol,
                "changed_positions": changed,
                "accounts": results,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Preview or rebuild Binance closed positions from full fill cycles."
    )
    parser.add_argument(
        "--symbol",
        help="Limit rebuild to one Binance contract symbol, for example SOXLUSDT.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply changes. Without this flag the command is read-only.",
    )
    arguments = parser.parse_args()
    asyncio.run(run(apply=arguments.apply, symbol=arguments.symbol))
