from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import (
    AppSetting,
    DailyPnlSnapshot,
    ExchangeAccount,
    FundingRecord,
    InitialAccountSnapshot,
    TrackingPeriod,
)
from app.services.reporting_calendar import (
    MIGRATION_KEY,
    rebuild_daily_pnl_reporting_calendar,
)


@pytest.mark.asyncio
async def test_reporting_calendar_rebuilds_legacy_utc_rows_once():
    started = datetime(2026, 7, 30, tzinfo=UTC)
    async with SessionLocal() as db:
        account = ExchangeAccount(
            exchange="OKX",
            connection_name="reporting-calendar",
            masked_identifier="test",
            tracking_started_at=started,
        )
        db.add(account)
        await db.flush()
        period = TrackingPeriod(
            exchange="OKX",
            exchange_account_id=account.id,
            started_at=started,
            is_active=True,
        )
        db.add(period)
        await db.flush()
        db.add_all(
            [
                InitialAccountSnapshot(
                    exchange="OKX",
                    exchange_account_id=account.id,
                    tracking_period_id=period.id,
                    source_record_id="initial",
                    initial_equity=Decimal("100"),
                    tracking_started_at=started,
                ),
                DailyPnlSnapshot(
                    exchange="OKX",
                    exchange_account_id=account.id,
                    tracking_period_id=period.id,
                    source_record_id="daily-2026-07-30",
                    snapshot_date=date(2026, 7, 30),
                    equity_usd=Decimal("110"),
                    investment_return=Decimal("10"),
                    updated_at=datetime(2026, 7, 30, 16, 30, tzinfo=UTC),
                ),
                FundingRecord(
                    exchange="OKX",
                    exchange_account_id=account.id,
                    tracking_period_id=period.id,
                    source_record_id="funding",
                    asset="USDT",
                    amount_usd=Decimal("-1"),
                    record_time=datetime(2026, 7, 30, 16, 15, tzinfo=UTC),
                ),
            ]
        )
        await db.flush()

        result = await rebuild_daily_pnl_reporting_calendar(db)
        await db.commit()
        assert result == {"applied": True, "rows": 1}
        row = await db.scalar(select(DailyPnlSnapshot))
        assert row.snapshot_date == date(2026, 7, 31)
        assert row.funding_fee == Decimal("-1")
        assert (await db.get(AppSetting, MIGRATION_KEY)).value["version"] == 2

        second = await rebuild_daily_pnl_reporting_calendar(db)
        assert second == {"applied": False, "rows": 0}
