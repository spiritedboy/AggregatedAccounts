from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.config import settings
from app.database import SessionLocal
from app.models import (
    AccountBalanceSnapshot,
    AssetBalanceSnapshot,
    ClosedPosition,
    DailyPnlSnapshot,
    ExchangeAccount,
    PositionSnapshot,
    SecurityAuditLog,
    SyncJob,
    TrackingPeriod,
)
from app.services.analytics import calculate_max_drawdown, calculate_risk_level
from app.services.maintenance import (
    apply_data_retention,
    cleanup_polymarket_closed_positions,
)


def test_risk_calculations():
    assert calculate_max_drawdown([100, 120, 90, 110]) == 25
    assert (
        calculate_risk_level(
            max_drawdown_percent=5,
            largest_exchange_concentration_percent=30,
            margin_utilization_percent=20,
            nearest_liquidation_distance_percent=None,
        )
        == "LOW"
    )
    assert (
        calculate_risk_level(
            max_drawdown_percent=16,
            largest_exchange_concentration_percent=30,
            margin_utilization_percent=20,
            nearest_liquidation_distance_percent=40,
        )
        == "MEDIUM"
    )
    assert (
        calculate_risk_level(
            max_drawdown_percent=5,
            largest_exchange_concentration_percent=55,
            margin_utilization_percent=20,
            nearest_liquidation_distance_percent=40,
        )
        == "HIGH"
    )


@pytest.mark.asyncio
async def test_polymarket_duplicate_cleanup_is_previewable_and_recalculates_daily_pnl():
    started = datetime(2026, 7, 1, tzinfo=UTC)
    closed_at = datetime(2026, 7, 26, 12, 25, tzinfo=UTC)
    async with SessionLocal() as db:
        account = ExchangeAccount(
            exchange="POLYMARKET",
            connection_name="cleanup-test",
            masked_identifier="0x12••••34",
            tracking_started_at=started,
            last_synced_at=started,
        )
        db.add(account)
        await db.flush()
        period = TrackingPeriod(
            exchange="POLYMARKET",
            exchange_account_id=account.id,
            started_at=started,
            is_active=True,
        )
        db.add(period)
        await db.flush()
        for index, timestamp in enumerate((1785067200, 1785067216)):
            created_at = closed_at + timedelta(minutes=index)
            db.add(
                ClosedPosition(
                    exchange="POLYMARKET",
                    exchange_account_id=account.id,
                    tracking_period_id=period.id,
                    source_record_id=f"stable-asset:{timestamp}",
                    symbol="Duplicate · Yes",
                    normalized_symbol="POLY-DUPLICATE",
                    side="LONG",
                    open_time=started,
                    close_time=closed_at + timedelta(seconds=index * 16),
                    realized_pnl=Decimal("6"),
                    net_pnl=Decimal("6"),
                    tracking_started_at=started,
                    created_at=created_at,
                    updated_at=created_at,
                )
            )
        db.add(
            DailyPnlSnapshot(
                exchange="POLYMARKET",
                exchange_account_id=account.id,
                tracking_period_id=period.id,
                source_record_id="daily-2026-07-26",
                snapshot_date=date(2026, 7, 26),
                realized_pnl=Decimal("12"),
            )
        )
        await db.commit()

        preview = await cleanup_polymarket_closed_positions(db, apply=False)
        assert preview["duplicates_to_delete"] == 1
        assert preview["applied"] is False
        assert await db.scalar(select(func.count()).select_from(ClosedPosition)) == 2

        applied = await cleanup_polymarket_closed_positions(db, apply=True)
        assert applied["duplicates_to_delete"] == 1
        rows = list((await db.scalars(select(ClosedPosition))).all())
        assert len(rows) == 1
        assert rows[0].source_record_id == "poly-closed:stable-asset"
        daily = await db.scalar(select(DailyPnlSnapshot))
        assert daily.realized_pnl == Decimal("6")


@pytest.mark.asyncio
async def test_data_retention_prunes_only_safely_summarized_operational_rows():
    now = datetime(2026, 7, 26, 12, tzinfo=UTC)
    old_time = now - timedelta(days=120)
    async with SessionLocal() as db:
        account = ExchangeAccount(
            exchange="BINANCE",
            connection_name="retention-test",
            masked_identifier="abc••••xyz",
            tracking_started_at=old_time,
            last_synced_at=now,
        )
        db.add(account)
        await db.flush()
        period = TrackingPeriod(
            exchange=account.exchange,
            exchange_account_id=account.id,
            started_at=old_time,
            is_active=True,
        )
        db.add(period)
        await db.flush()
        summarized = AccountBalanceSnapshot(
            exchange=account.exchange,
            exchange_account_id=account.id,
            tracking_period_id=period.id,
            source_record_id="old-summarized",
            recorded_at=old_time,
        )
        unsummarized = AccountBalanceSnapshot(
            exchange=account.exchange,
            exchange_account_id=account.id,
            tracking_period_id=period.id,
            source_record_id="old-unsummarized",
            recorded_at=old_time + timedelta(days=1),
        )
        db.add_all([summarized, unsummarized])
        db.add(
            AssetBalanceSnapshot(
                exchange=account.exchange,
                exchange_account_id=account.id,
                tracking_period_id=period.id,
                source_record_id="old-asset",
                asset="USDT",
                account_type="SPOT",
                recorded_at=old_time,
            )
        )
        db.add(
            PositionSnapshot(
                exchange=account.exchange,
                exchange_account_id=account.id,
                tracking_period_id=period.id,
                source_record_id="old-position",
                normalized_symbol="BTC-USDT-PERP",
                side="LONG",
                recorded_at=old_time,
            )
        )
        db.add(
            DailyPnlSnapshot(
                exchange=account.exchange,
                exchange_account_id=account.id,
                tracking_period_id=period.id,
                source_record_id=f"daily-{old_time.date()}",
                snapshot_date=old_time.date(),
            )
        )
        db.add_all(
            [
                SyncJob(
                    exchange_account_id=account.id,
                    job_type="ACCOUNT_REFRESH",
                    status="SUCCESS",
                    started_at=now - timedelta(days=40),
                ),
                SyncJob(
                    exchange_account_id=account.id,
                    job_type="ACCOUNT_REFRESH",
                    status="SUCCESS",
                    started_at=now - timedelta(days=2),
                ),
            ]
        )
        await db.commit()

        result = await apply_data_retention(db, now=now)

        assert result["sync_jobs_deleted"] == 1
        assert result["balance_snapshots_deleted"] == 1
        assert result["asset_balance_snapshots_deleted"] == 1
        assert result["position_snapshots_deleted"] == 1
        remaining_sources = set(
            await db.scalars(select(AccountBalanceSnapshot.source_record_id))
        )
        assert remaining_sources == {"old-unsummarized"}


@pytest.mark.asyncio
async def test_zero_retention_values_keep_database_rows_forever(monkeypatch):
    now = datetime(2026, 7, 28, 12, tzinfo=UTC)
    old_time = now - timedelta(days=365)
    monkeypatch.setattr(settings, "sync_job_retention_days", 0)
    monkeypatch.setattr(settings, "balance_snapshot_retention_days", 0)

    async with SessionLocal() as db:
        account = ExchangeAccount(
            exchange="BINANCE",
            connection_name="permanent-retention-test",
            masked_identifier="abc••••xyz",
            tracking_started_at=old_time,
            last_synced_at=now,
        )
        db.add(account)
        await db.flush()
        period = TrackingPeriod(
            exchange=account.exchange,
            exchange_account_id=account.id,
            started_at=old_time,
            is_active=True,
        )
        db.add(period)
        await db.flush()
        db.add(
            AccountBalanceSnapshot(
                exchange=account.exchange,
                exchange_account_id=account.id,
                tracking_period_id=period.id,
                source_record_id="permanent-balance",
                recorded_at=old_time,
            )
        )
        db.add(
            SyncJob(
                exchange_account_id=account.id,
                job_type="ACCOUNT_REFRESH",
                status="SUCCESS",
                started_at=old_time,
            )
        )
        await db.commit()

        result = await apply_data_retention(db, now=now)

        assert result["sync_job_retention_enabled"] is False
        assert result["balance_snapshot_retention_enabled"] is False
        assert await db.scalar(select(func.count()).select_from(SyncJob)) == 1
        assert (
            await db.scalar(select(func.count()).select_from(AccountBalanceSnapshot))
            == 1
        )
        assert await db.scalar(select(func.count()).select_from(SyncJob)) == 1
        audit = await db.scalar(
            select(SecurityAuditLog).where(
                SecurityAuditLog.action == "DATA_RETENTION_APPLIED"
            )
        )
        assert audit is not None
