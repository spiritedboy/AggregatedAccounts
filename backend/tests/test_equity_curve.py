from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.database import SessionLocal
from app.models import (
    AccountBalanceSnapshot,
    ExchangeAccount,
    PortfolioEquityPoint,
    TrackingPeriod,
)
from app.services.equity_curve import (
    backfill_portfolio_equity_points,
    capture_portfolio_equity_point,
    curve_cache,
    get_equity_curve,
)


@pytest.mark.asyncio
async def test_five_minute_equity_points_and_change_are_calculated_from_endpoints():
    start = datetime(2026, 7, 28, 1, 0, tzinfo=UTC)
    end = start + timedelta(minutes=10)
    async with SessionLocal() as db:
        account = ExchangeAccount(
            exchange="BINANCE",
            connection_name="curve-test",
            masked_identifier="abc••••xyz",
            tracking_started_at=start,
            last_synced_at=end,
        )
        db.add(account)
        await db.flush()
        period = TrackingPeriod(
            exchange=account.exchange,
            exchange_account_id=account.id,
            started_at=start,
            is_active=True,
        )
        db.add(period)
        await db.flush()
        db.add(
            AccountBalanceSnapshot(
                exchange=account.exchange,
                exchange_account_id=account.id,
                tracking_period_id=period.id,
                source_record_id="curve-start",
                total_equity_usd=Decimal("100"),
                available_balance_usd=Decimal("80"),
                recorded_at=start,
            )
        )
        await db.commit()

        first = await capture_portfolio_equity_point(db, now=start)
        assert first is not None
        assert first.bucket_time == start

        db.add(
            AccountBalanceSnapshot(
                exchange=account.exchange,
                exchange_account_id=account.id,
                tracking_period_id=period.id,
                source_record_id="curve-end",
                total_equity_usd=Decimal("110"),
                available_balance_usd=Decimal("85"),
                recorded_at=end,
            )
        )
        await db.commit()
        second = await capture_portfolio_equity_point(db, now=end)
        assert second is not None

        curve_cache.clear()
        result = await get_equity_curve(db, "1d", now=end)

    assert result["sample_interval"] == "5m"
    assert result["resolution"] == "5m"
    assert [point["equity"] for point in result["points"]] == [100.0, 110.0]
    assert result["change"]["amount"] == 10.0
    assert result["change"]["percent"] == 10.0


def test_equity_curve_rejects_unknown_range(client):
    response = client.get("/api/analytics/equity-curve?range=all")
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_backfill_carries_each_accounts_latest_nearby_snapshot_into_bucket():
    bucket = datetime(2026, 7, 28, 2, 0, tzinfo=UTC)
    async with SessionLocal() as db:
        for index, (recorded_at, equity) in enumerate(
            (
                (bucket + timedelta(minutes=1), Decimal("100")),
                (bucket - timedelta(minutes=6), Decimal("200")),
            )
        ):
            account = ExchangeAccount(
                exchange=("BINANCE", "OKX")[index],
                connection_name=f"backfill-{index}",
                masked_identifier=f"demo••••{index}",
                tracking_started_at=bucket - timedelta(days=1),
                last_synced_at=recorded_at,
            )
            db.add(account)
            await db.flush()
            period = TrackingPeriod(
                exchange=account.exchange,
                exchange_account_id=account.id,
                started_at=bucket - timedelta(days=1),
                is_active=True,
            )
            db.add(period)
            await db.flush()
            db.add(
                AccountBalanceSnapshot(
                    exchange=account.exchange,
                    exchange_account_id=account.id,
                    tracking_period_id=period.id,
                    source_record_id=f"backfill-{index}",
                    total_equity_usd=equity,
                    recorded_at=recorded_at,
                )
            )
        await db.commit()

        await backfill_portfolio_equity_points(db)
        point = await db.get(PortfolioEquityPoint, bucket)

    assert point is not None
    assert point.account_count == 2
    assert point.stale_account_count == 1
    assert point.total_equity_usd == Decimal("300")
