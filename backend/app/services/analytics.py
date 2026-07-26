import uuid
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import (
    AccountBalanceSnapshot,
    CashFlowRecord,
    ClosedPosition,
    CurrentPosition,
    DailyPnlSnapshot,
    ExchangeAccount,
    FundingRecord,
    IncomeRecord,
    InitialAccountSnapshot,
    SyncError,
    SyncJob,
    TrackingPeriod,
    TradingFeeRecord,
)


def _number(value: Decimal | float | int | None) -> float:
    return float(value or 0)


def calculate_max_drawdown(equities: list[float]) -> float:
    peak = 0.0
    maximum = 0.0
    for equity in equities:
        if equity > peak:
            peak = equity
        if peak > 0:
            maximum = max(maximum, (peak - equity) / peak * 100)
    return maximum


def calculate_risk_level(
    *,
    max_drawdown_percent: float,
    largest_exchange_concentration_percent: float,
    margin_utilization_percent: float,
    nearest_liquidation_distance_percent: float | None,
) -> str:
    if (
        max_drawdown_percent >= 25
        or largest_exchange_concentration_percent >= 50
        or margin_utilization_percent >= 80
        or (
            nearest_liquidation_distance_percent is not None
            and nearest_liquidation_distance_percent <= 10
        )
    ):
        return "HIGH"
    if (
        max_drawdown_percent >= 15
        or largest_exchange_concentration_percent >= 35
        or margin_utilization_percent >= 50
        or (
            nearest_liquidation_distance_percent is not None
            and nearest_liquidation_distance_percent <= 20
        )
    ):
        return "MEDIUM"
    return "LOW"


async def _active_accounts(db: AsyncSession) -> list[ExchangeAccount]:
    return list(
        (
            await db.scalars(
                select(ExchangeAccount)
                .where(ExchangeAccount.is_active.is_(True))
                .order_by(ExchangeAccount.created_at)
            )
        ).all()
    )


async def _latest_balances(
    db: AsyncSession,
    account_ids: list[uuid.UUID],
) -> dict[uuid.UUID, AccountBalanceSnapshot]:
    if not account_ids:
        return {}
    rows = (
        await db.scalars(
            select(AccountBalanceSnapshot)
            .where(AccountBalanceSnapshot.exchange_account_id.in_(account_ids))
            .order_by(
                AccountBalanceSnapshot.exchange_account_id,
                AccountBalanceSnapshot.recorded_at.desc(),
            )
            .distinct(AccountBalanceSnapshot.exchange_account_id)
        )
    ).all()
    return {row.exchange_account_id: row for row in rows}


async def build_sync_status(db: AsyncSession) -> dict[str, Any]:
    accounts = await _active_accounts(db)
    stale_after_seconds = max(settings.sync_balance_seconds * 2, 120)
    now = datetime.now(UTC)
    items: list[dict[str, Any]] = []
    for account in accounts:
        jobs = list(
            (
                await db.scalars(
                    select(SyncJob)
                    .where(SyncJob.exchange_account_id == account.id)
                    .order_by(SyncJob.started_at.desc())
                    .limit(1_000)
                )
            ).all()
        )
        latest_job = jobs[0] if jobs else None
        last_success = next((job for job in jobs if job.status == "SUCCESS"), None)
        consecutive_failures = 0
        for job in jobs:
            if job.status == "FAILED":
                consecutive_failures += 1
            elif job.status == "SUCCESS":
                break
        latest_error = await db.scalar(
            select(SyncError)
            .where(SyncError.exchange_account_id == account.id)
            .order_by(SyncError.occurred_at.desc())
            .limit(1)
        )
        is_stale = (
            account.last_synced_at is None
            or (now - account.last_synced_at).total_seconds() > stale_after_seconds
        )
        items.append(
            {
                "account_id": account.id,
                "exchange": account.exchange,
                "connection_name": account.connection_name,
                "connection_status": account.connection_status,
                "data_completeness": account.data_completeness,
                "last_synced_at": account.last_synced_at,
                "is_stale": is_stale,
                "stale_after_seconds": stale_after_seconds,
                "consecutive_failures": consecutive_failures,
                "last_success_at": (
                    last_success.finished_at or last_success.started_at if last_success else None
                ),
                "latest_job": (
                    {
                        "status": latest_job.status,
                        "started_at": latest_job.started_at,
                        "finished_at": latest_job.finished_at,
                        "duration_ms": latest_job.duration_ms,
                        "records_written": latest_job.records_written,
                    }
                    if latest_job
                    else None
                ),
                "last_error": (
                    {
                        "type": latest_error.error_type,
                        "message": latest_error.safe_message,
                        "occurred_at": latest_error.occurred_at,
                    }
                    if latest_error
                    else None
                ),
            }
        )
    return {
        "summary": {
            "total_accounts": len(items),
            "healthy_accounts": sum(
                not item["is_stale"]
                and item["connection_status"] == "CONNECTED"
                and item["consecutive_failures"] == 0
                for item in items
            ),
            "stale_accounts": sum(item["is_stale"] for item in items),
            "failing_accounts": sum(item["consecutive_failures"] > 0 for item in items),
            "running_accounts": sum(
                bool(item["latest_job"])
                and item["latest_job"]["status"] == "RUNNING"
                for item in items
            ),
            "checked_at": now,
        },
        "accounts": items,
    }


async def build_reconciliation(db: AsyncSession) -> dict[str, Any]:
    accounts = await _active_accounts(db)
    account_ids = [account.id for account in accounts]
    latest_balances = await _latest_balances(db, account_ids)
    periods = (
        await db.scalars(
            select(TrackingPeriod).where(
                TrackingPeriod.exchange_account_id.in_(account_ids),
                TrackingPeriod.is_active.is_(True),
            )
        )
    ).all()
    period_by_account = {row.exchange_account_id: row for row in periods}
    period_ids = [row.id for row in periods]
    initials = (
        await db.scalars(
            select(InitialAccountSnapshot).where(
                InitialAccountSnapshot.tracking_period_id.in_(period_ids)
            )
        )
    ).all()
    initial_by_period = {row.tracking_period_id: row for row in initials}
    closed_positions = (
        await db.scalars(
            select(ClosedPosition).where(ClosedPosition.tracking_period_id.in_(period_ids))
        )
    ).all()
    cash_flows = (
        await db.scalars(
            select(CashFlowRecord).where(CashFlowRecord.tracking_period_id.in_(period_ids))
        )
    ).all()
    funding_records = (
        await db.scalars(
            select(FundingRecord).where(FundingRecord.tracking_period_id.in_(period_ids))
        )
    ).all()
    fee_records = (
        await db.scalars(
            select(TradingFeeRecord).where(TradingFeeRecord.tracking_period_id.in_(period_ids))
        )
    ).all()
    income_records = (
        await db.scalars(
            select(IncomeRecord).where(IncomeRecord.tracking_period_id.in_(period_ids))
        )
    ).all()

    closed_by_period: dict[uuid.UUID, list[ClosedPosition]] = defaultdict(list)
    cash_by_period: dict[uuid.UUID, list[CashFlowRecord]] = defaultdict(list)
    funding_by_period: dict[uuid.UUID, list[FundingRecord]] = defaultdict(list)
    fees_by_period: dict[uuid.UUID, list[TradingFeeRecord]] = defaultdict(list)
    income_by_period: dict[uuid.UUID, list[IncomeRecord]] = defaultdict(list)
    for row in closed_positions:
        closed_by_period[row.tracking_period_id].append(row)
    for row in cash_flows:
        cash_by_period[row.tracking_period_id].append(row)
    for row in funding_records:
        funding_by_period[row.tracking_period_id].append(row)
    for row in fee_records:
        fees_by_period[row.tracking_period_id].append(row)
    for row in income_records:
        income_by_period[row.tracking_period_id].append(row)

    items: list[dict[str, Any]] = []
    for account in accounts:
        period = period_by_account.get(account.id)
        balance = latest_balances.get(account.id)
        initial = initial_by_period.get(period.id) if period else None
        period_id = period.id if period else None
        initial_equity = _number(initial.initial_equity if initial else None)
        current_equity = _number(balance.total_equity_usd if balance else None)
        deposits = sum(
            _number(row.amount_usd)
            for row in cash_by_period.get(period_id, [])
            if row.flow_type.upper() not in {"WITHDRAW", "WITHDRAWAL"}
        )
        withdrawals = sum(
            _number(row.amount_usd)
            for row in cash_by_period.get(period_id, [])
            if row.flow_type.upper() in {"WITHDRAW", "WITHDRAWAL"}
        )
        net_cash_flow = deposits - withdrawals
        income_items = income_by_period.get(period_id, [])
        funding_items = funding_by_period.get(period_id, [])
        fee_items = fees_by_period.get(period_id, [])
        realized_pnl = (
            sum(_number(row.amount_usd) for row in income_items)
            if income_items
            else sum(
                _number(row.realized_pnl) for row in closed_by_period.get(period_id, [])
            )
        )
        funding_fee = (
            sum(_number(row.amount_usd) for row in funding_items)
            if funding_items
            else sum(
                _number(row.funding_fee) for row in closed_by_period.get(period_id, [])
            )
        )
        trading_fee = (
            sum(_number(row.amount_usd) for row in fee_items)
            if fee_items
            else sum(
                abs(_number(row.trading_fee))
                for row in closed_by_period.get(period_id, [])
            )
        )
        unrealized_change = _number(
            balance.unrealized_pnl_usd if balance else None
        ) - _number(initial.initial_unrealized_pnl if initial else None)
        equity_return = current_equity - initial_equity - net_cash_flow
        component_return = realized_pnl + funding_fee - trading_fee + unrealized_change
        variance = equity_return - component_return
        tolerance = max(1.0, abs(current_equity) * 0.001)
        items.append(
            {
                "account_id": account.id,
                "exchange": account.exchange,
                "connection_name": account.connection_name,
                "tracking_started_at": account.tracking_started_at,
                "last_synced_at": account.last_synced_at,
                "initial_equity": initial_equity,
                "current_equity": current_equity,
                "deposits": deposits,
                "withdrawals": withdrawals,
                "net_cash_flow": net_cash_flow,
                "equity_return": equity_return,
                "realized_pnl": realized_pnl,
                "funding_fee": funding_fee,
                "trading_fee": trading_fee,
                "unrealized_pnl_change": unrealized_change,
                "component_return": component_return,
                "variance": variance,
                "tolerance": tolerance,
                "status": "MATCHED" if abs(variance) <= tolerance else "REVIEW",
                "data_completeness": account.data_completeness,
            }
        )

    total_keys = (
        "initial_equity",
        "current_equity",
        "deposits",
        "withdrawals",
        "net_cash_flow",
        "equity_return",
        "realized_pnl",
        "funding_fee",
        "trading_fee",
        "unrealized_pnl_change",
        "component_return",
        "variance",
    )
    totals = {key: sum(item[key] for item in items) for key in total_keys}
    totals["status"] = "MATCHED" if all(item["status"] == "MATCHED" for item in items) else "REVIEW"
    return {
        "totals": totals,
        "accounts": items,
        "notice": (
            "权益收益来自当前权益减初始权益及净资金流；组成收益来自已实现收益、"
            "资金费、手续费和未实现收益变化。差额用于发现接口覆盖不足或重复记录。"
        ),
    }


async def build_risk_metrics(db: AsyncSession) -> dict[str, Any]:
    accounts = await _active_accounts(db)
    account_ids = [account.id for account in accounts]
    account_by_id = {account.id: account for account in accounts}
    latest_balances = await _latest_balances(db, account_ids)
    positions = (
        await db.scalars(
            select(CurrentPosition).where(CurrentPosition.exchange_account_id.in_(account_ids))
        )
    ).all()
    daily_rows = (
        await db.scalars(
            select(DailyPnlSnapshot)
            .where(DailyPnlSnapshot.exchange_account_id.in_(account_ids))
            .order_by(DailyPnlSnapshot.snapshot_date)
        )
    ).all()

    total_equity = sum(_number(row.total_equity_usd) for row in latest_balances.values())
    exchange_equity: dict[str, float] = defaultdict(float)
    for account_id, balance in latest_balances.items():
        exchange_equity[account_by_id[account_id].exchange] += _number(
            balance.total_equity_usd
        )
    exchange_concentration = sorted(
        (
            {
                "exchange": exchange,
                "equity": equity,
                "percent": equity / total_equity * 100 if total_equity else 0,
            }
            for exchange, equity in exchange_equity.items()
        ),
        key=lambda item: item["equity"],
        reverse=True,
    )

    exposure_groups: dict[str, dict[str, Any]] = {}
    liquidation_risks: list[dict[str, Any]] = []
    total_margin = sum(
        abs(_number(row.margin_balance_usd))
        for row in latest_balances.values()
    )
    for position in positions:
        value = abs(_number(position.position_value_usd))
        exposure = exposure_groups.setdefault(
            position.normalized_symbol,
            {
                "symbol": position.symbol,
                "normalized_symbol": position.normalized_symbol,
                "exchanges": set(),
                "position_value": 0.0,
                "unrealized_pnl": 0.0,
            },
        )
        exposure["exchanges"].add(position.exchange)
        exposure["position_value"] += value
        exposure["unrealized_pnl"] += _number(position.unrealized_pnl)
        mark = _number(position.mark_price)
        liquidation = _number(position.liquidation_price)
        if mark > 0 and liquidation > 0:
            distance = (
                (mark - liquidation) / mark * 100
                if position.side == "LONG"
                else (liquidation - mark) / mark * 100
            )
            liquidation_risks.append(
                {
                    "exchange": position.exchange,
                    "symbol": position.symbol,
                    "side": position.side,
                    "distance_percent": max(distance, 0),
                }
            )

    top_exposures = sorted(
        (
            {
                **item,
                "exchanges": sorted(item["exchanges"]),
                "equity_percent": (
                    item["position_value"] / total_equity * 100 if total_equity else 0
                ),
            }
            for item in exposure_groups.values()
        ),
        key=lambda item: item["position_value"],
        reverse=True,
    )[:10]

    equity_by_date: dict[Any, float] = defaultdict(float)
    for row in daily_rows:
        equity_by_date[row.snapshot_date] += _number(row.equity_usd)
    max_drawdown = calculate_max_drawdown(
        [equity_by_date[day] for day in sorted(equity_by_date)]
    )
    largest_exchange = max(
        (item["percent"] for item in exchange_concentration),
        default=0,
    )
    largest_position = max(
        (item["equity_percent"] for item in top_exposures),
        default=0,
    )
    margin_utilization = total_margin / total_equity * 100 if total_equity else 0
    nearest_liquidation = min(
        (item["distance_percent"] for item in liquidation_risks),
        default=None,
    )
    return {
        "summary": {
            "risk_level": calculate_risk_level(
                max_drawdown_percent=max_drawdown,
                largest_exchange_concentration_percent=largest_exchange,
                margin_utilization_percent=margin_utilization,
                nearest_liquidation_distance_percent=nearest_liquidation,
            ),
            "total_equity": total_equity,
            "total_position_value": sum(
                abs(_number(position.position_value_usd)) for position in positions
            ),
            "max_drawdown_percent": max_drawdown,
            "largest_exchange_concentration_percent": largest_exchange,
            "largest_position_exposure_percent": largest_position,
            "margin_utilization_percent": margin_utilization,
            "nearest_liquidation_distance_percent": nearest_liquidation,
        },
        "exchange_concentration": exchange_concentration,
        "top_exposures": top_exposures,
        "liquidation_risks": sorted(
            liquidation_risks,
            key=lambda item: item["distance_percent"],
        )[:10],
    }
