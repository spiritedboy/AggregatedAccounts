from __future__ import annotations

from datetime import UTC, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AppSetting,
    CashFlowRecord,
    ClosedPosition,
    DailyPnlSnapshot,
    FundingRecord,
    IncomeRecord,
    InitialAccountSnapshot,
    TradingFeeRecord,
)

REPORT_TIMEZONE = ZoneInfo("Asia/Shanghai")
MIGRATION_KEY = "daily_pnl_reporting_calendar"
MIGRATION_VERSION = 2


def reporting_day_bounds(day) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=REPORT_TIMEZONE).astimezone(UTC)
    end = datetime.combine(day, time.max, tzinfo=REPORT_TIMEZONE).astimezone(UTC)
    return start, end


async def rebuild_daily_pnl_reporting_calendar(db: AsyncSession) -> dict[str, int | bool]:
    """One-time conversion of legacy UTC daily rows to Asia/Shanghai days."""
    setting = await db.get(AppSetting, MIGRATION_KEY)
    if setting and int((setting.value or {}).get("version", 0)) >= MIGRATION_VERSION:
        return {"applied": False, "rows": 0}

    legacy_rows = (
        await db.scalars(
            select(DailyPnlSnapshot).order_by(
                DailyPnlSnapshot.exchange_account_id,
                DailyPnlSnapshot.snapshot_date,
                DailyPnlSnapshot.updated_at,
            )
        )
    ).all()
    selected: dict[tuple, DailyPnlSnapshot] = {}
    for row in legacy_rows:
        reporting_date = row.updated_at.astimezone(REPORT_TIMEZONE).date()
        key = (row.exchange_account_id, row.tracking_period_id, reporting_date)
        previous = selected.get(key)
        if previous is None or row.updated_at > previous.updated_at:
            selected[key] = row

    initial_rows = (
        await db.scalars(select(InitialAccountSnapshot))
    ).all()
    initial_by_period = {row.tracking_period_id: row for row in initial_rows}
    rebuilt: list[dict] = []
    for (account_id, period_id, reporting_date), source in selected.items():
        start, end = reporting_day_bounds(reporting_date)
        income_count, income_total = (
            await db.execute(
                select(func.count(IncomeRecord.id), func.sum(IncomeRecord.amount_usd)).where(
                    IncomeRecord.exchange_account_id == account_id,
                    IncomeRecord.tracking_period_id == period_id,
                    IncomeRecord.record_time >= start,
                    IncomeRecord.record_time <= end,
                    IncomeRecord.income_type == "REALIZED_PNL",
                )
            )
        ).one()
        realized = income_total if income_count else await db.scalar(
            select(func.sum(ClosedPosition.realized_pnl)).where(
                ClosedPosition.exchange_account_id == account_id,
                ClosedPosition.tracking_period_id == period_id,
                ClosedPosition.close_time >= start,
                ClosedPosition.close_time <= end,
            )
        )
        funding = await db.scalar(
            select(func.sum(FundingRecord.amount_usd)).where(
                FundingRecord.exchange_account_id == account_id,
                FundingRecord.tracking_period_id == period_id,
                FundingRecord.record_time >= start,
                FundingRecord.record_time <= end,
            )
        )
        fees = await db.scalar(
            select(func.sum(TradingFeeRecord.amount_usd)).where(
                TradingFeeRecord.exchange_account_id == account_id,
                TradingFeeRecord.tracking_period_id == period_id,
                TradingFeeRecord.record_time >= start,
                TradingFeeRecord.record_time <= end,
            )
        )
        period_cash_rows = (
            await db.scalars(
                select(CashFlowRecord).where(
                    CashFlowRecord.exchange_account_id == account_id,
                    CashFlowRecord.tracking_period_id == period_id,
                    CashFlowRecord.record_time <= end,
                )
            )
        ).all()
        net_cash_flow = sum(
            (
                -row.amount_usd
                if row.flow_type.upper() in {"WITHDRAW", "WITHDRAWAL"}
                else row.amount_usd
            )
            for row in period_cash_rows
        )
        initial = initial_by_period.get(period_id)
        initial_equity = initial.initial_equity if initial else Decimal("0")
        rebuilt.append(
            {
                "exchange": source.exchange,
                "exchange_account_id": account_id,
                "tracking_period_id": period_id,
                "source_record_id": f"daily-{reporting_date}",
                "snapshot_date": reporting_date,
                "equity_usd": source.equity_usd,
                "realized_pnl": realized or Decimal("0"),
                "unrealized_pnl_change": source.unrealized_pnl_change,
                "funding_fee": funding or Decimal("0"),
                "trading_fee": fees or Decimal("0"),
                "net_cash_flow": net_cash_flow,
                "investment_return": source.equity_usd - initial_equity - net_cash_flow,
            }
        )

    await db.execute(delete(DailyPnlSnapshot))
    db.add_all(DailyPnlSnapshot(**values) for values in rebuilt)
    if setting is None:
        setting = AppSetting(key=MIGRATION_KEY)
        db.add(setting)
    setting.value = {
        "version": MIGRATION_VERSION,
        "timezone": "Asia/Shanghai",
        "migrated_at": datetime.now(UTC).isoformat(),
        "rows": len(rebuilt),
    }
    await db.flush()
    return {"applied": True, "rows": len(rebuilt)}
