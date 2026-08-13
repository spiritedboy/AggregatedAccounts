from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import (
    AccountBalanceSnapshot,
    AccountingDailySummary,
    CashFlowRecord,
    ClosedPosition,
    ExchangeAccount,
    FundingRecord,
    IncomeRecord,
    OperationalReadModel,
    SyncJob,
    TrackingPeriod,
    TradingFeeRecord,
)
from app.services.accounting import (
    build_data_completeness,
    list_accounting_records,
)
from app.services.operational_read_models import refresh_operational_read_models
from app.services.pnl_read_model import refresh_pnl_read_model


@pytest.mark.asyncio
async def test_accounting_records_and_component_completeness():
    now = datetime(2026, 7, 26, 15, 0, tzinfo=UTC)
    async with SessionLocal() as db:
        account = ExchangeAccount(
            exchange="BINANCE",
            connection_name="ledger-test",
            masked_identifier="key••••test",
            connection_status="CONNECTED",
            data_completeness="COMPLETE",
            tracking_started_at=now,
            last_synced_at=now,
        )
        db.add(account)
        await db.flush()
        period = TrackingPeriod(
            exchange=account.exchange,
            exchange_account_id=account.id,
            started_at=now,
            is_active=True,
        )
        db.add(period)
        await db.flush()
        common = {
            "exchange": account.exchange,
            "exchange_account_id": account.id,
            "tracking_period_id": period.id,
            "asset": "USDT",
            "record_time": now,
        }
        db.add_all(
            [
                AccountBalanceSnapshot(
                    exchange=account.exchange,
                    exchange_account_id=account.id,
                    tracking_period_id=period.id,
                    source_record_id="balance",
                    recorded_at=now,
                ),
                IncomeRecord(
                    **common,
                    source_record_id="income",
                    income_type="REALIZED_PNL",
                    amount_usd=Decimal("5"),
                ),
                ClosedPosition(
                    exchange=account.exchange,
                    exchange_account_id=account.id,
                    tracking_period_id=period.id,
                    source_record_id="closed",
                    symbol="BTCUSDT",
                    normalized_symbol="BTC-USDT-PERP",
                    side="LONG",
                    open_time=now,
                    close_time=now,
                    realized_pnl=Decimal("6"),
                    net_pnl=Decimal("4.5"),
                    tracking_started_at=now,
                ),
                FundingRecord(
                    **common,
                    source_record_id="funding",
                    symbol="BTCUSDT",
                    amount_usd=Decimal("-1"),
                ),
                TradingFeeRecord(
                    **common,
                    source_record_id="fee",
                    symbol="BTCUSDT",
                    amount_usd=Decimal("0.5"),
                ),
                CashFlowRecord(
                    **common,
                    source_record_id="deposit",
                    flow_type="DEPOSIT",
                    amount_usd=Decimal("10"),
                ),
                CashFlowRecord(
                    **common,
                    source_record_id="withdrawal",
                    flow_type="WITHDRAWAL",
                    amount_usd=Decimal("3"),
                ),
                SyncJob(
                    exchange_account_id=account.id,
                    job_type="FULL_ACCOUNT",
                    status="SUCCESS",
                    started_at=now,
                    finished_at=now,
                ),
            ]
        )
        await db.commit()

        result = await list_accounting_records(db, limit=20)
        assert result["total"] == 5
        assert result["summary"] == {
            "realized_pnl": 6.0,
            "funding_fee": -1.0,
            "trading_fee": 0.5,
            "deposits": 10.0,
            "withdrawals": 3.0,
            "net_effect": 11.5,
            "net_cash_flow": 7.0,
            "net_realized_pnl": 4.5,
        }
        fee_result = await list_accounting_records(
            db, record_type="TRADING_FEE", limit=20
        )
        assert fee_result["total"] == 1
        assert fee_result["items"][0]["signed_amount_usd"] == -0.5

        completeness = await build_data_completeness(db)
        account_status = completeness["accounts"][0]
        assert account_status["components"]["equity"]["status"] == "COMPLETE"
        assert account_status["components"]["positions"]["record_count"] == 0
        assert account_status["components"]["realized_pnl"]["record_count"] == 1
        assert account_status["components"]["funding_fee"]["record_count"] == 1
        assert account_status["components"]["trading_fee"]["record_count"] == 1
        assert account_status["components"]["cash_flow"]["record_count"] == 2

        await refresh_pnl_read_model(db)
        refresh_result = await refresh_operational_read_models(db)
        await db.commit()

        assert refresh_result["read_models"] == 5
        assert refresh_result["accounting_daily_rows"] == 5
        assert await db.scalar(
            select(func.count()).select_from(OperationalReadModel)
        ) == 5
        assert await db.scalar(
            select(func.count()).select_from(AccountingDailySummary)
        ) == 5

        cached_result = await list_accounting_records(
            db,
            start_time=datetime(2026, 7, 25, 16, 0, tzinfo=UTC),
            end_time=datetime(2026, 7, 26, 15, 59, 59, tzinfo=UTC),
            limit=20,
        )
        assert cached_result["summary"] == result["summary"]

        existing_ids = set(await db.scalars(select(AccountingDailySummary.id)))
        db.add(
            TradingFeeRecord(
                exchange=account.exchange,
                exchange_account_id=account.id,
                tracking_period_id=period.id,
                source_record_id="fee-next-day",
                asset="USDT",
                symbol="ETHUSDT",
                amount_usd=Decimal("0.25"),
                record_time=datetime(2026, 7, 26, 16, 1, tzinfo=UTC),
            )
        )
        await db.flush()
        incremental = await refresh_operational_read_models(db)
        await db.commit()
        assert incremental["accounting_daily_rows"] == 1
        assert existing_ids.issubset(
            set(await db.scalars(select(AccountingDailySummary.id)))
        )
