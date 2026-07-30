from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.api import _balances_data
from app.database import SessionLocal
from app.models import (
    AccountBalanceSnapshot,
    AssetBalanceSnapshot,
    ExchangeAccount,
    SyncError,
    SyncJob,
    TrackingPeriod,
)
from app.services.analytics import build_sync_status


async def _account_and_period() -> tuple[ExchangeAccount, TrackingPeriod]:
    started_at = datetime(2026, 7, 1, tzinfo=UTC)
    account = ExchangeAccount(
        exchange="BINANCE",
        connection_name="query-optimization-test",
        masked_identifier="test••••test",
        tracking_started_at=started_at,
        last_synced_at=datetime.now(UTC),
    )
    async with SessionLocal() as db:
        db.add(account)
        await db.flush()
        period = TrackingPeriod(
            exchange=account.exchange,
            exchange_account_id=account.id,
            started_at=started_at,
            is_active=True,
        )
        db.add(period)
        await db.commit()
        await db.refresh(account)
        await db.refresh(period)
    return account, period


@pytest.mark.asyncio
async def test_balances_only_returns_latest_asset_batch():
    account, period = await _account_and_period()
    old_time = datetime(2026, 7, 30, 10, 0, tzinfo=UTC)
    latest_time = old_time + timedelta(minutes=1)
    async with SessionLocal() as db:
        db.add(
            AccountBalanceSnapshot(
                exchange=account.exchange,
                exchange_account_id=account.id,
                tracking_period_id=period.id,
                source_record_id="balance-latest",
                total_equity_usd=Decimal("125"),
                recorded_at=latest_time,
            )
        )
        for source_id, asset, value, recorded_at in (
            ("asset-old-usdt", "USDT", "100", old_time),
            ("asset-latest-usdt", "USDT", "120", latest_time),
            ("asset-latest-btc", "BTC", "5", latest_time),
        ):
            db.add(
                AssetBalanceSnapshot(
                    exchange=account.exchange,
                    exchange_account_id=account.id,
                    tracking_period_id=period.id,
                    source_record_id=source_id,
                    asset=asset,
                    value_usd=Decimal(value),
                    recorded_at=recorded_at,
                )
            )
        await db.commit()

        result = await _balances_data(db)

    assert len(result) == 1
    assert {
        item["asset"]: item["value_usd"] for item in result[0]["assets"]
    } == {"BTC": 5.0, "USDT": 120.0}


@pytest.mark.asyncio
async def test_sync_status_batches_latest_jobs_successes_and_errors():
    account, _ = await _account_and_period()
    base_time = datetime(2026, 7, 30, 10, 0, tzinfo=UTC)
    async with SessionLocal() as db:
        for offset, status in enumerate(
            ("SUCCESS", "FAILED", "FAILED", "RUNNING")
        ):
            started_at = base_time + timedelta(minutes=offset)
            db.add(
                SyncJob(
                    exchange_account_id=account.id,
                    job_type="FULL_ACCOUNT",
                    status=status,
                    started_at=started_at,
                    finished_at=(
                        started_at + timedelta(seconds=1)
                        if status != "RUNNING"
                        else None
                    ),
                    records_written=offset,
                )
            )
        for offset in range(2):
            db.add(
                SyncError(
                    exchange_account_id=account.id,
                    error_type=f"ERROR_{offset}",
                    safe_message=f"safe error {offset}",
                    occurred_at=base_time + timedelta(minutes=offset),
                )
            )
        await db.commit()

        result = await build_sync_status(db)

    item = result["accounts"][0]
    assert item["latest_job"]["status"] == "RUNNING"
    assert item["last_success_at"] == base_time + timedelta(seconds=1)
    assert item["consecutive_failures"] == 2
    assert item["last_error"]["type"] == "ERROR_1"
