from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.adapters import ADAPTERS
from app.database import SessionLocal
from app.models import (
    AssetBalanceSnapshot,
    CashFlowRecord,
    DailyPnlSnapshot,
    ExchangeAccount,
    FundingRecord,
    IncomeRecord,
    InitialAccountSnapshot,
    PositionSnapshot,
    SyncError,
    SyncJob,
    TrackingPeriod,
    TradingFeeRecord,
)
from app.services.accounts import (
    _upsert_amount_records,
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
