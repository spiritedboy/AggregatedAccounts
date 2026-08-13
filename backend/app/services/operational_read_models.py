from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi.encoders import jsonable_encoder
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AccountingDailySummary,
    CashFlowRecord,
    ClosedPosition,
    FundingRecord,
    OperationalReadModel,
    TradingFeeRecord,
)

DASHBOARD_SCOPE = "DASHBOARD_SUMMARY"
RECONCILIATION_SCOPE = "RECONCILIATION"
RISK_SCOPE = "RISK_METRICS"
SYNC_STATUS_SCOPE = "SYNC_STATUS"
COMPLETENESS_SCOPE = "DATA_COMPLETENESS"


async def get_operational_read_model(
    db: AsyncSession, scope: str
) -> dict[str, Any] | None:
    row = await db.get(OperationalReadModel, scope)
    return row.payload if row is not None else None


async def _store(
    db: AsyncSession,
    scope: str,
    payload: dict[str, Any],
    calculated_at: datetime,
) -> None:
    row = await db.get(OperationalReadModel, scope)
    if row is None:
        row = OperationalReadModel(scope=scope)
        db.add(row)
    row.payload = jsonable_encoder(payload)
    row.calculated_at = calculated_at


async def rebuild_accounting_daily_summaries(
    db: AsyncSession, *, calculated_at: datetime
) -> int:
    await db.execute(delete(AccountingDailySummary))
    specifications = (
        (ClosedPosition, ClosedPosition.close_time, "REALIZED_PNL", ClosedPosition.realized_pnl),
        (FundingRecord, FundingRecord.record_time, "FUNDING_FEE", FundingRecord.amount_usd),
        (
            TradingFeeRecord,
            TradingFeeRecord.record_time,
            "TRADING_FEE",
            TradingFeeRecord.amount_usd,
        ),
    )
    rows_written = 0
    for model, time_column, record_type, amount_column in specifications:
        report_date = func.date(func.timezone("Asia/Shanghai", time_column))
        rows = (
            await db.execute(
                select(
                    model.exchange,
                    model.exchange_account_id,
                    report_date.label("record_date"),
                    func.coalesce(func.sum(amount_column), 0).label("amount_usd"),
                    func.count(model.id).label("record_count"),
                ).group_by(model.exchange, model.exchange_account_id, report_date)
            )
        ).all()
        for row in rows:
            db.add(
                AccountingDailySummary(
                    exchange=row.exchange,
                    exchange_account_id=row.exchange_account_id,
                    record_date=row.record_date,
                    record_type=record_type,
                    amount_usd=Decimal(row.amount_usd),
                    record_count=int(row.record_count),
                    calculated_at=calculated_at,
                )
            )
        rows_written += len(rows)

    report_date = func.date(func.timezone("Asia/Shanghai", CashFlowRecord.record_time))
    cash_rows = (
        await db.execute(
            select(
                CashFlowRecord.exchange,
                CashFlowRecord.exchange_account_id,
                report_date.label("record_date"),
                func.upper(CashFlowRecord.flow_type).label("flow_type"),
                func.coalesce(func.sum(CashFlowRecord.amount_usd), 0).label("amount_usd"),
                func.count(CashFlowRecord.id).label("record_count"),
            ).group_by(
                CashFlowRecord.exchange,
                CashFlowRecord.exchange_account_id,
                report_date,
                func.upper(CashFlowRecord.flow_type),
            )
        )
    ).all()
    normalized_cash: dict[tuple[Any, ...], tuple[Decimal, int]] = {}
    for row in cash_rows:
        normalized_type = (
            "WITHDRAWAL" if row.flow_type in {"WITHDRAW", "WITHDRAWAL"} else "DEPOSIT"
        )
        key = (
            row.exchange,
            row.exchange_account_id,
            row.record_date,
            normalized_type,
        )
        amount, count = normalized_cash.get(key, (Decimal(0), 0))
        normalized_cash[key] = (
            amount + Decimal(row.amount_usd),
            count + int(row.record_count),
        )
    for (exchange, account_id, record_date, normalized_type), (
        amount,
        count,
    ) in normalized_cash.items():
        db.add(
            AccountingDailySummary(
                exchange=exchange,
                exchange_account_id=account_id,
                record_date=record_date,
                record_type=normalized_type,
                amount_usd=amount,
                record_count=count,
                calculated_at=calculated_at,
            )
        )
    rows_written += len(normalized_cash)
    return rows_written


async def refresh_operational_read_models(db: AsyncSession) -> dict[str, int]:
    """Rebuild expensive page summaries from authoritative detail tables."""
    from app.api import _calculate_dashboard_summary_data
    from app.services.accounting import calculate_data_completeness
    from app.services.analytics import (
        calculate_reconciliation,
        calculate_risk_metrics,
        calculate_sync_status,
    )

    calculated_at = datetime.now(UTC)
    payloads = {
        DASHBOARD_SCOPE: await _calculate_dashboard_summary_data(db),
        RECONCILIATION_SCOPE: await calculate_reconciliation(db),
        RISK_SCOPE: await calculate_risk_metrics(db),
        SYNC_STATUS_SCOPE: await calculate_sync_status(db),
        COMPLETENESS_SCOPE: await calculate_data_completeness(db),
    }
    for scope, payload in payloads.items():
        await _store(db, scope, payload, calculated_at)
    accounting_rows = await rebuild_accounting_daily_summaries(
        db, calculated_at=calculated_at
    )
    await db.flush()
    return {"read_models": len(payloads), "accounting_daily_rows": accounting_rows}
