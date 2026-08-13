from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.adapters import ADAPTERS
from app.database import SessionLocal
from app.models import (
    AccountBalanceSnapshot,
    AssetBalanceSnapshot,
    CashFlowRecord,
    CurrentPosition,
    DailyPnlSnapshot,
    ExchangeAccount,
    FundingRecord,
    IncomeRecord,
    InitialAccountSnapshot,
    LatestAccountBalance,
    LatestAssetBalance,
    PositionSnapshot,
    SyncError,
    SyncJob,
    TrackingPeriod,
    TradingFeeRecord,
)
from app.services.accounts import (
    _upsert_amount_records,
    _write_summary,
    sync_account,
    update_completeness,
)


class FakeAccountingAdapter:
    history_streams = frozenset({"income", "funding", "fees", "cash_flows"})

    def __init__(self, **_):
        pass

    async def close(self):
        return None

    async def get_account_summary(self):
        return {
            "total_equity_usd": 110,
            "available_balance_usd": 90,
            "margin_balance_usd": 20,
            "unrealized_pnl_usd": 3,
        }

    async def get_open_positions(self):
        return [
            {
                "source_record_id": "BTC:LONG",
                "symbol": "BTC",
                "normalized_symbol": "BTC-USDC-PERP",
                "side": "LONG",
                "position_size": 1,
                "position_value_usd": 100,
                "entry_price": 95,
                "mark_price": 100,
                "margin_used": 20,
                "unrealized_pnl": 5,
            }
        ]

    async def get_balances(self):
        return [
            {
                "asset": "USDC",
                "account_type": "SPOT",
                "available": 10,
                "locked": 0,
                "value_usd": 10,
                "price_source": "STABLECOIN_PARITY",
            }
        ]

    async def get_closed_positions(self, *_):
        return []

    async def get_history_bundle(self, start_time, _):
        recorded_at = start_time + timedelta(minutes=1)
        common = {
            "asset": "USDC",
            "record_time": recorded_at,
            "symbol": "BTC",
        }
        return {
            "income": [
                {
                    **common,
                    "source_record_id": "pnl-1",
                    "amount_usd": 7,
                    "income_type": "REALIZED_PNL",
                }
            ],
            "funding": [
                {**common, "source_record_id": "funding-1", "amount_usd": -1}
            ],
            "fees": [{**common, "source_record_id": "fee-1", "amount_usd": 2}],
            "cash_flows": [
                {
                    **common,
                    "source_record_id": "cash-1",
                    "amount_usd": 5,
                    "flow_type": "DEPOSIT",
                }
            ],
            "complete": True,
        }


class FailingAccountingAdapter(FakeAccountingAdapter):
    async def get_history_bundle(self, *_):
        raise RuntimeError("secret upstream detail")


class InvalidDatabaseValueAdapter(FakeAccountingAdapter):
    async def get_closed_positions(self, *_):
        now = datetime.now(UTC)
        return [
            {
                "source_record_id": "invalid-source",
                "symbol": "BTC",
                "normalized_symbol": "BTC-USDC-PERP",
                "side": "LONG",
                "open_time": now - timedelta(minutes=1),
                "close_time": now,
                "data_source": "X" * 25,
                "data_completeness": "COMPLETE",
            }
        ]


def test_incremental_clean_window_does_not_erase_prior_partial_status():
    account = ExchangeAccount(
        exchange="OKX",
        connection_name="sticky-completeness",
        masked_identifier="test",
        tracking_started_at=datetime.now(UTC),
        data_completeness_details={
            "income": "PARTIAL",
            "funding": "COMPLETE",
            "fees": "COMPLETE",
            "cash_flows": "COMPLETE",
        },
    )
    update_completeness(account, {"income": "COMPLETE"})
    assert account.data_completeness_details["income"] == "PARTIAL"
    update_completeness(
        account,
        {"income": "COMPLETE"},
        authoritative=True,
    )
    assert account.data_completeness_details["income"] == "COMPLETE"


async def _create_account() -> ExchangeAccount:
    started = datetime.now(UTC) - timedelta(hours=1)
    async with SessionLocal() as db:
        account = ExchangeAccount(
            exchange="HYPERLIQUID",
            connection_name="accounting-sync",
            public_identifier="0x" + "a" * 40,
            masked_identifier="0xaa••••aa",
            tracking_started_at=started,
            last_synced_at=started,
            data_completeness="PARTIAL",
        )
        db.add(account)
        await db.flush()
        period = TrackingPeriod(
            exchange=account.exchange,
            exchange_account_id=account.id,
            started_at=started,
            is_active=True,
        )
        db.add(period)
        await db.flush()
        db.add(
            InitialAccountSnapshot(
                exchange=account.exchange,
                exchange_account_id=account.id,
                tracking_period_id=period.id,
                source_record_id="initial",
                initial_equity=Decimal("100"),
                initial_unrealized_pnl=Decimal("1"),
                tracking_started_at=started,
            )
        )
        await db.commit()
        await db.refresh(account)
        return account


@pytest.mark.asyncio
async def test_full_sync_idempotently_persists_accounting_records(monkeypatch):
    account = await _create_account()
    monkeypatch.setitem(ADAPTERS, "HYPERLIQUID", FakeAccountingAdapter)
    async with SessionLocal() as db:
        stored = await db.get(ExchangeAccount, account.id)
        result = await sync_account(db, stored)
        assert result["status"] == "SUCCESS"
        assert stored.data_completeness == "COMPLETE"
        assert stored.data_completeness_details["quality_checked_at"]
        assert {
            issue["code"]
            for issue in stored.data_completeness_details["quality_issues"]
        } == {"INVALID_LEVERAGE"}
        assert (
            await db.scalar(select(func.count()).select_from(AssetBalanceSnapshot))
            == 1
        )
        assert (
            await db.scalar(select(func.count()).select_from(PositionSnapshot))
            == 1
        )
        assert (
            await db.scalar(select(func.count()).select_from(LatestAccountBalance))
            == 1
        )
        assert (
            await db.scalar(select(func.count()).select_from(LatestAssetBalance))
            == 1
        )
        for model in (
            IncomeRecord,
            FundingRecord,
            TradingFeeRecord,
            CashFlowRecord,
        ):
            assert await db.scalar(select(func.count()).select_from(model)) == 1
        daily = await db.scalar(select(DailyPnlSnapshot))
        assert daily.realized_pnl == Decimal("7")
        assert daily.funding_fee == Decimal("-1")
        assert daily.trading_fee == Decimal("2")
        assert daily.net_cash_flow == Decimal("5")

        period = await db.scalar(
            select(TrackingPeriod).where(
                TrackingPeriod.exchange_account_id == stored.id
            )
        )
        bundle = await FakeAccountingAdapter().get_history_bundle(
            stored.tracking_started_at, datetime.now(UTC)
        )
        for model, stream in (
            (IncomeRecord, "income"),
            (FundingRecord, "funding"),
            (TradingFeeRecord, "fees"),
            (CashFlowRecord, "cash_flows"),
        ):
            await _upsert_amount_records(
                db, stored, period, model, bundle[stream]
            )
        await db.commit()
        for model in (
            IncomeRecord,
            FundingRecord,
            TradingFeeRecord,
            CashFlowRecord,
        ):
            assert await db.scalar(select(func.count()).select_from(model)) == 1


@pytest.mark.asyncio
async def test_repeated_sync_updates_latest_state_without_duplicate_daily_snapshots(
    monkeypatch,
):
    account = await _create_account()
    monkeypatch.setitem(ADAPTERS, "HYPERLIQUID", FakeAccountingAdapter)

    async with SessionLocal() as db:
        stored = await db.get(ExchangeAccount, account.id)
        assert (await sync_account(db, stored))["status"] == "SUCCESS"
        first_latest = await db.scalar(
            select(LatestAccountBalance).where(
                LatestAccountBalance.exchange_account_id == stored.id
            )
        )
        first_recorded_at = first_latest.recorded_at

        assert (await sync_account(db, stored))["status"] == "SUCCESS"
        await db.refresh(first_latest)

        assert first_latest.recorded_at >= first_recorded_at
        assert (
            await db.scalar(select(func.count()).select_from(AccountBalanceSnapshot))
            == 1
        )
        assert (
            await db.scalar(select(func.count()).select_from(AssetBalanceSnapshot))
            == 1
        )
        assert (
            await db.scalar(select(func.count()).select_from(PositionSnapshot))
            == 1
        )


@pytest.mark.asyncio
async def test_daily_snapshot_rolls_over_at_shanghai_midnight():
    account = await _create_account()
    summary = await FakeAccountingAdapter().get_account_summary()
    before_midnight = datetime(2026, 8, 10, 15, 59, tzinfo=UTC)
    after_midnight = datetime(2026, 8, 10, 16, 1, tzinfo=UTC)

    async with SessionLocal() as db:
        stored = await db.get(ExchangeAccount, account.id)
        period = await db.scalar(
            select(TrackingPeriod).where(
                TrackingPeriod.exchange_account_id == stored.id
            )
        )
        assert await _write_summary(
            db, stored, period, summary, before_midnight
        ) is True
        await db.flush()
        assert await _write_summary(
            db, stored, period, summary, after_midnight
        ) is True
        await db.flush()

        source_ids = set(
            await db.scalars(select(AccountBalanceSnapshot.source_record_id))
        )
        assert source_ids == {
            "balance-daily-20260810",
            "balance-daily-20260811",
        }


@pytest.mark.asyncio
async def test_daily_pnl_uses_shanghai_reporting_date():
    account = await _create_account()
    summary = await FakeAccountingAdapter().get_account_summary()
    after_midnight = datetime(2026, 8, 10, 16, 1, tzinfo=UTC)
    async with SessionLocal() as db:
        stored = await db.get(ExchangeAccount, account.id)
        period = await db.scalar(
            select(TrackingPeriod).where(
                TrackingPeriod.exchange_account_id == stored.id
            )
        )
        from app.services.accounts import _write_daily_snapshot

        await _write_daily_snapshot(db, stored, period, summary, after_midnight)
        await db.flush()
        daily = await db.scalar(select(DailyPnlSnapshot))
        assert str(daily.snapshot_date) == "2026-08-11"


@pytest.mark.asyncio
async def test_stream_cursors_skip_fresh_streams_and_keep_long_position_lookback(
    monkeypatch,
):
    account = await _create_account()

    class CountingAdapter(FakeAccountingAdapter):
        calls = {"balance": 0, "positions": 0, "closed": 0, "history": 0}
        closed_start = None

        async def get_account_summary(self):
            self.calls["balance"] += 1
            return await super().get_account_summary()

        async def get_balances(self):
            return await super().get_balances()

        async def get_open_positions(self):
            self.calls["positions"] += 1
            return await super().get_open_positions()

        async def get_closed_positions(self, start_time, end_time):
            del end_time
            self.calls["closed"] += 1
            type(self).closed_start = start_time
            return []

        async def get_history_bundle(self, start_time, end_time):
            self.calls["history"] += 1
            return await super().get_history_bundle(start_time, end_time)

    monkeypatch.setitem(ADAPTERS, "HYPERLIQUID", CountingAdapter)
    async with SessionLocal() as db:
        stored = await db.get(ExchangeAccount, account.id)
        period = await db.scalar(
            select(TrackingPeriod).where(
                TrackingPeriod.exchange_account_id == stored.id
            )
        )
        long_open_time = datetime.now(UTC) - timedelta(days=2)
        db.add(
            CurrentPosition(
                exchange=stored.exchange,
                exchange_account_id=stored.id,
                tracking_period_id=period.id,
                source_record_id="long-held",
                symbol="BTC",
                normalized_symbol="BTC-USDC-PERP",
                side="LONG",
                open_time=long_open_time,
                tracking_started_at=stored.tracking_started_at,
            )
        )
        await db.commit()

        assert (await sync_account(db, stored))["status"] == "SUCCESS"
        assert CountingAdapter.calls == {
            "balance": 1,
            "positions": 1,
            "closed": 1,
            "history": 1,
        }
        assert CountingAdapter.closed_start == long_open_time

        CountingAdapter.calls = {key: 0 for key in CountingAdapter.calls}
        assert (await sync_account(db, stored))["status"] == "SUCCESS"
        assert CountingAdapter.calls == {
            "balance": 0,
            "positions": 0,
            "closed": 0,
            "history": 0,
        }


@pytest.mark.asyncio
async def test_accounting_failure_does_not_block_primary_asset_sync(monkeypatch):
    account = await _create_account()
    monkeypatch.setitem(ADAPTERS, "HYPERLIQUID", FailingAccountingAdapter)
    async with SessionLocal() as db:
        stored = await db.get(ExchangeAccount, account.id)
        result = await sync_account(db, stored)
        assert result["status"] == "SUCCESS"
        assert stored.connection_status == "CONNECTED"
        assert stored.data_completeness == "PARTIAL"
        error = await db.scalar(select(SyncError))
        assert error.safe_message == "资产同步成功，但账务流水同步不完整"
        assert "secret upstream detail" not in error.safe_message


@pytest.mark.asyncio
async def test_database_flush_failure_is_rolled_back_and_recorded(monkeypatch):
    account = await _create_account()
    monkeypatch.setitem(ADAPTERS, "HYPERLIQUID", InvalidDatabaseValueAdapter)
    async with SessionLocal() as db:
        stored = await db.get(ExchangeAccount, account.id)
        result = await sync_account(db, stored)
        assert result["status"] == "FAILED"

        failed_account = await db.get(ExchangeAccount, account.id)
        assert failed_account.connection_status == "ERROR"
        job = await db.scalar(
            select(SyncJob)
            .where(SyncJob.exchange_account_id == account.id)
            .order_by(SyncJob.started_at.desc())
        )
        assert job.status == "FAILED"
        error = await db.scalar(
            select(SyncError)
            .where(SyncError.exchange_account_id == account.id)
            .order_by(SyncError.occurred_at.desc())
        )
        assert error.error_type == "DBAPIError"
        assert error.safe_message == "同步失败，请测试连接或检查只读 API 权限"
