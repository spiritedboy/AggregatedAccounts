import uuid
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import case, func, or_, select
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
    latest_snapshot_id = (
        select(AccountBalanceSnapshot.id)
        .where(
            AccountBalanceSnapshot.exchange_account_id == ExchangeAccount.id
        )
        .order_by(
            AccountBalanceSnapshot.recorded_at.desc(),
            AccountBalanceSnapshot.id.desc(),
        )
        .limit(1)
        .correlate(ExchangeAccount)
        .scalar_subquery()
    )
    rows = (
        await db.scalars(
            select(AccountBalanceSnapshot)
            .join(
                ExchangeAccount,
                ExchangeAccount.id
                == AccountBalanceSnapshot.exchange_account_id,
            )
            .where(
                ExchangeAccount.id.in_(account_ids),
                AccountBalanceSnapshot.id == latest_snapshot_id,
            )
        )
    ).all()
    return {row.exchange_account_id: row for row in rows}


async def build_sync_status(
    db: AsyncSession,
    accounts: list[ExchangeAccount] | None = None,
) -> dict[str, Any]:
    accounts = accounts if accounts is not None else await _active_accounts(db)
    account_ids = [account.id for account in accounts]
    if account_ids:
        latest_jobs = (
            await db.scalars(
                select(SyncJob)
                .where(SyncJob.exchange_account_id.in_(account_ids))
                .order_by(
                    SyncJob.exchange_account_id,
                    SyncJob.started_at.desc(),
                    SyncJob.id.desc(),
                )
                .distinct(SyncJob.exchange_account_id)
            )
        ).all()
        last_successes = (
            await db.scalars(
                select(SyncJob)
                .where(
                    SyncJob.exchange_account_id.in_(account_ids),
                    SyncJob.status == "SUCCESS",
                )
                .order_by(
                    SyncJob.exchange_account_id,
                    SyncJob.started_at.desc(),
                    SyncJob.id.desc(),
                )
                .distinct(SyncJob.exchange_account_id)
            )
        ).all()
        latest_errors = (
            await db.scalars(
                select(SyncError)
                .where(SyncError.exchange_account_id.in_(account_ids))
                .order_by(
                    SyncError.exchange_account_id,
                    SyncError.occurred_at.desc(),
                    SyncError.id.desc(),
                )
                .distinct(SyncError.exchange_account_id)
            )
        ).all()
        last_success_times = (
            select(
                SyncJob.exchange_account_id.label("account_id"),
                func.max(SyncJob.started_at).label("started_at"),
            )
            .where(
                SyncJob.exchange_account_id.in_(account_ids),
                SyncJob.status == "SUCCESS",
            )
            .group_by(SyncJob.exchange_account_id)
            .subquery("last_success_times")
        )
        failure_rows = (
            await db.execute(
                select(
                    SyncJob.exchange_account_id,
                    func.count(SyncJob.id),
                )
                .outerjoin(
                    last_success_times,
                    last_success_times.c.account_id
                    == SyncJob.exchange_account_id,
                )
                .where(
                    SyncJob.exchange_account_id.in_(account_ids),
                    SyncJob.status == "FAILED",
                    or_(
                        last_success_times.c.started_at.is_(None),
                        SyncJob.started_at > last_success_times.c.started_at,
                    ),
                )
                .group_by(SyncJob.exchange_account_id)
            )
        ).all()
    else:
        latest_jobs = []
        last_successes = []
        latest_errors = []
        failure_rows = []
    latest_job_by_account = {
        row.exchange_account_id: row for row in latest_jobs
    }
    last_success_by_account = {
        row.exchange_account_id: row for row in last_successes
    }
    latest_error_by_account = {
        row.exchange_account_id: row for row in latest_errors
    }
    failures_by_account = {row[0]: int(row[1]) for row in failure_rows}
    stale_after_seconds = max(settings.sync_balance_seconds * 2, 120)
    now = datetime.now(UTC)
    items: list[dict[str, Any]] = []
    for account in accounts:
        latest_job = latest_job_by_account.get(account.id)
        last_success = last_success_by_account.get(account.id)
        latest_error = latest_error_by_account.get(account.id)
        consecutive_failures = failures_by_account.get(account.id, 0)
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
    closed_rows = (
        await db.execute(
            select(
                ClosedPosition.tracking_period_id,
                func.coalesce(func.sum(ClosedPosition.realized_pnl), 0).label(
                    "realized_pnl"
                ),
                func.coalesce(func.sum(ClosedPosition.funding_fee), 0).label(
                    "funding_fee"
                ),
                func.coalesce(
                    func.sum(func.abs(ClosedPosition.trading_fee)),
                    0,
                ).label("trading_fee"),
            )
            .where(ClosedPosition.tracking_period_id.in_(period_ids))
            .group_by(ClosedPosition.tracking_period_id)
        )
    ).mappings()
    cash_rows = (
        await db.execute(
            select(
                CashFlowRecord.tracking_period_id,
                func.coalesce(
                    func.sum(
                        case(
                            (
                                func.upper(CashFlowRecord.flow_type).notin_(
                                    {"WITHDRAW", "WITHDRAWAL"}
                                ),
                                CashFlowRecord.amount_usd,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("deposits"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                func.upper(CashFlowRecord.flow_type).in_(
                                    {"WITHDRAW", "WITHDRAWAL"}
                                ),
                                CashFlowRecord.amount_usd,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("withdrawals"),
            )
            .where(CashFlowRecord.tracking_period_id.in_(period_ids))
            .group_by(CashFlowRecord.tracking_period_id)
        )
    ).mappings()

    async def amount_stats(model: Any) -> dict[uuid.UUID, dict[str, Any]]:
        rows = (
            await db.execute(
                select(
                    model.tracking_period_id,
                    func.count(model.id).label("record_count"),
                    func.coalesce(func.sum(model.amount_usd), 0).label("amount"),
                )
                .where(model.tracking_period_id.in_(period_ids))
                .group_by(model.tracking_period_id)
            )
        ).mappings()
        return {row["tracking_period_id"]: dict(row) for row in rows}

    closed_by_period = {
        row["tracking_period_id"]: dict(row) for row in closed_rows
    }
    cash_by_period = {
        row["tracking_period_id"]: dict(row) for row in cash_rows
    }
    funding_by_period = await amount_stats(FundingRecord)
    fees_by_period = await amount_stats(TradingFeeRecord)
    income_by_period = await amount_stats(IncomeRecord)

    items: list[dict[str, Any]] = []
    for account in accounts:
        period = period_by_account.get(account.id)
        balance = latest_balances.get(account.id)
        initial = initial_by_period.get(period.id) if period else None
        period_id = period.id if period else None
        initial_equity = _number(initial.initial_equity if initial else None)
        current_equity = _number(balance.total_equity_usd if balance else None)
        cash_stats = cash_by_period.get(period_id, {})
        closed_stats = closed_by_period.get(period_id, {})
        deposits = _number(cash_stats.get("deposits"))
        withdrawals = _number(cash_stats.get("withdrawals"))
        net_cash_flow = deposits - withdrawals
        income_stats = income_by_period.get(period_id, {})
        funding_stats = funding_by_period.get(period_id, {})
        fee_stats = fees_by_period.get(period_id, {})
        realized_pnl = (
            _number(income_stats.get("amount"))
            if income_stats.get("record_count", 0)
            else _number(closed_stats.get("realized_pnl"))
        )
        funding_fee = (
            _number(funding_stats.get("amount"))
            if funding_stats.get("record_count", 0)
            else _number(closed_stats.get("funding_fee"))
        )
        trading_fee = (
            _number(fee_stats.get("amount"))
            if fee_stats.get("record_count", 0)
            else _number(closed_stats.get("trading_fee"))
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
