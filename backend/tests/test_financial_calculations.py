from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from app.api import _bucket_pnl_points, _daily_pnl_points, _pnl_summary_data
from app.database import SessionLocal
from app.models import (
    AccountBalanceSnapshot,
    ClosedPosition,
    CurrentPosition,
    DailyPnlSnapshot,
    ExchangeAccount,
    InitialAccountSnapshot,
    TrackingPeriod,
)
from app.services.analytics import build_reconciliation, build_risk_metrics


async def _account_with_period(
    *,
    exchange: str = "OKX",
    initial_equity: str = "100",
    initial_unrealized: str = "0",
) -> tuple[ExchangeAccount, TrackingPeriod]:
    started = datetime(2026, 7, 1, tzinfo=UTC)
    account = ExchangeAccount(
        exchange=exchange,
        connection_name=f"{exchange}-calculation-test",
        masked_identifier="test••••test",
        tracking_started_at=started,
        last_synced_at=started,
        connection_status="CONNECTED",
    )
    period = TrackingPeriod(
        exchange=exchange,
        exchange_account_id=account.id,
        started_at=started,
        is_active=True,
    )
    async with SessionLocal() as db:
        db.add(account)
        await db.flush()
        period.exchange_account_id = account.id
        db.add(period)
        await db.flush()
        db.add(
            InitialAccountSnapshot(
                exchange=exchange,
                exchange_account_id=account.id,
                tracking_period_id=period.id,
                source_record_id="initial",
                initial_equity=Decimal(initial_equity),
                initial_unrealized_pnl=Decimal(initial_unrealized),
                tracking_started_at=started,
            )
        )
        await db.commit()
        await db.refresh(account)
        await db.refresh(period)
    return account, period


@pytest.mark.asyncio
async def test_daily_and_weekly_returns_use_deltas_not_sum_of_cumulative_values():
    account, period = await _account_with_period()
    async with SessionLocal() as db:
        rows = zip(
            ("10", "7", "12"),
            ("4", "-1", "3"),
            ("1", "-2", "0"),
            ("0.5", "0.25", "0.25"),
            strict=True,
        )
        for offset, (cumulative, realized, funding, fee) in enumerate(rows):
            snapshot_date = date(2026, 7, 1) + timedelta(days=offset)
            db.add(
                DailyPnlSnapshot(
                    exchange=account.exchange,
                    exchange_account_id=account.id,
                    tracking_period_id=period.id,
                    source_record_id=f"daily-{snapshot_date}",
                    snapshot_date=snapshot_date,
                    equity_usd=Decimal("100") + Decimal(cumulative),
                    investment_return=Decimal(cumulative),
                    realized_pnl=Decimal(realized),
                    funding_fee=Decimal(funding),
                    trading_fee=Decimal(fee),
                )
            )
        db.add(
            CurrentPosition(
                exchange=account.exchange,
                exchange_account_id=account.id,
                tracking_period_id=period.id,
                source_record_id="current-position",
                symbol="TEST-USDT-SWAP",
                normalized_symbol="TEST-USDT-PERP",
                side="LONG",
                unrealized_pnl=Decimal("9.5"),
                tracking_started_at=period.started_at,
            )
        )
        await db.commit()
        daily = await _daily_pnl_points(db)
        summary = await _pnl_summary_data(db, daily)

    assert [point["investment_return"] for point in daily] == [10, -3, 5]
    assert [point["cumulative_return"] for point in daily] == [10, 7, 12]
    assert summary["period_investment_return"] == 12
    assert summary["period_realized_pnl"] == 6
    assert summary["period_funding_fee"] == -1
    assert summary["period_trading_fee"] == 1
    assert summary["period_net_realized_pnl"] == 4
    assert summary["current_position_pnl"] == 9.5
    weekly = _bucket_pnl_points(daily, "week")
    assert weekly[0]["investment_return"] == 12
    assert weekly[0]["cumulative_return"] == 12


@pytest.mark.asyncio
async def test_reconciliation_keeps_initial_unrealized_baseline_after_position_closes():
    account, period = await _account_with_period(initial_unrealized="-20")
    now = datetime(2026, 7, 2, tzinfo=UTC)
    async with SessionLocal() as db:
        db.add(
            AccountBalanceSnapshot(
                exchange=account.exchange,
                exchange_account_id=account.id,
                tracking_period_id=period.id,
                source_record_id="balance",
                total_equity_usd=Decimal("125"),
                unrealized_pnl_usd=Decimal("0"),
                recorded_at=now,
            )
        )
        db.add(
            ClosedPosition(
                exchange=account.exchange,
                exchange_account_id=account.id,
                tracking_period_id=period.id,
                source_record_id="closed",
                symbol="TEST-USDT-SWAP",
                normalized_symbol="TEST-USDT-PERP",
                side="LONG",
                open_time=period.started_at,
                close_time=now,
                realized_pnl=Decimal("5"),
                net_pnl=Decimal("5"),
                tracking_started_at=period.started_at,
            )
        )
        await db.commit()
        result = await build_reconciliation(db)

    item = result["accounts"][0]
    assert item["net_realized_pnl"] == 5
    assert item["current_position_pnl"] == 0
    assert item["initial_position_pnl"] == -20
    assert item["component_return"] == 25
    assert item["variance"] == 0
    assert item["status"] == "MATCHED"


@pytest.mark.asyncio
async def test_risk_margin_uses_account_summary_for_cross_margin_positions():
    account, period = await _account_with_period()
    async with SessionLocal() as db:
        db.add(
            AccountBalanceSnapshot(
                exchange=account.exchange,
                exchange_account_id=account.id,
                tracking_period_id=period.id,
                source_record_id="balance",
                total_equity_usd=Decimal("100"),
                margin_balance_usd=Decimal("40"),
                recorded_at=datetime(2026, 7, 2, tzinfo=UTC),
            )
        )
        await db.commit()
        result = await build_risk_metrics(db)

    assert result["summary"]["margin_utilization_percent"] == 40
