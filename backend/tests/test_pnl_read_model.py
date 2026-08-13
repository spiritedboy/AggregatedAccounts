from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select

from app.api import _calculate_pnl_bootstrap_data, _pnl_bootstrap_data
from app.database import SessionLocal
from app.models import (
    ClosedPosition,
    DailyPnlSnapshot,
    ExchangeAccount,
    InitialAccountSnapshot,
    PnlAnalyticsSummary,
    PnlExchangeSummary,
    TrackingPeriod,
)
from app.services.pnl_read_model import ACTIVE_SCOPE, refresh_pnl_read_model


@pytest.mark.asyncio
async def test_pnl_read_model_is_persisted_and_served_without_live_reaggregation():
    started = datetime(2026, 8, 1, tzinfo=UTC)
    async with SessionLocal() as db:
        account = ExchangeAccount(
            exchange="OKX",
            connection_name="pnl-read-model-test",
            masked_identifier="test••••pnl",
            tracking_started_at=started,
            connection_status="CONNECTED",
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
                    initial_equity=Decimal("1000"),
                    tracking_started_at=started,
                ),
                DailyPnlSnapshot(
                    exchange="OKX",
                    exchange_account_id=account.id,
                    tracking_period_id=period.id,
                    source_record_id="daily-2026-08-01",
                    snapshot_date=date(2026, 8, 1),
                    equity_usd=Decimal("1012"),
                    realized_pnl=Decimal("15"),
                    funding_fee=Decimal("-1"),
                    trading_fee=Decimal("2"),
                    investment_return=Decimal("12"),
                ),
                ClosedPosition(
                    exchange="OKX",
                    exchange_account_id=account.id,
                    tracking_period_id=period.id,
                    source_record_id="win",
                    symbol="BTC-USDT-SWAP",
                    normalized_symbol="BTC-USDT-PERP",
                    side="LONG",
                    open_time=started,
                    close_time=datetime(2026, 8, 1, 1, tzinfo=UTC),
                    net_pnl=Decimal("20"),
                    tracking_started_at=started,
                ),
                ClosedPosition(
                    exchange="OKX",
                    exchange_account_id=account.id,
                    tracking_period_id=period.id,
                    source_record_id="loss",
                    symbol="ETH-USDT-SWAP",
                    normalized_symbol="ETH-USDT-PERP",
                    side="SHORT",
                    open_time=started,
                    close_time=datetime(2026, 8, 1, 2, tzinfo=UTC),
                    net_pnl=Decimal("-8"),
                    tracking_started_at=started,
                ),
            ]
        )
        await db.flush()

        expected = await _calculate_pnl_bootstrap_data(db)
        await refresh_pnl_read_model(db)
        await db.commit()

        assert await db.get(PnlAnalyticsSummary, ACTIVE_SCOPE) is not None
        assert await db.scalar(select(PnlExchangeSummary)) is not None
        persisted = await _pnl_bootstrap_data(db)
        assert persisted == jsonable_encoder(expected)
        assert persisted["summary"]["total_profit"] == 20
        assert persisted["summary"]["total_loss"] == 8
        assert persisted["summary"]["period_net_realized_pnl"] == 12

        win = await db.scalar(
            select(ClosedPosition).where(ClosedPosition.source_record_id == "win")
        )
        win.net_pnl = Decimal("200")
        await db.commit()

        # The endpoint-facing reader remains stable until the synchronization
        # pipeline explicitly rebuilds the read model.
        still_persisted = await _pnl_bootstrap_data(db)
        assert still_persisted["summary"]["total_profit"] == 20

        read_model = await db.get(PnlAnalyticsSummary, ACTIVE_SCOPE)
        read_model.calculated_at = datetime.now(UTC) - timedelta(minutes=10)
        await db.commit()
        stale_fallback = await _pnl_bootstrap_data(db)
        assert stale_fallback["summary"]["total_profit"] == 200

        await refresh_pnl_read_model(db)
        await db.commit()
        refreshed = await _pnl_bootstrap_data(db)
        assert refreshed["summary"]["total_profit"] == 200
        assert refreshed["summary"]["period_net_realized_pnl"] == 192
