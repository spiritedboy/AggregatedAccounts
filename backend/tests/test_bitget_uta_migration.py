from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import CashFlowRecord, ExchangeAccount, TrackingPeriod
from app.services.accounts import _upsert_amount_records


@pytest.mark.asyncio
async def test_bitget_external_deposit_reuses_legacy_internal_transfer():
    now = datetime.now(UTC).replace(microsecond=0)
    async with SessionLocal() as db:
        account = ExchangeAccount(
            exchange="BITGET",
            connection_name="bitget-uta-migration",
            masked_identifier="test",
            tracking_started_at=now - timedelta(days=1),
        )
        db.add(account)
        await db.flush()
        period = TrackingPeriod(
            exchange="BITGET",
            exchange_account_id=account.id,
            started_at=now - timedelta(days=1),
            is_active=True,
        )
        db.add(period)
        await db.flush()
        old = CashFlowRecord(
            exchange="BITGET",
            exchange_account_id=account.id,
            tracking_period_id=period.id,
            source_record_id="old-bill:cash",
            asset="USDT",
            amount_usd=Decimal("209.99"),
            flow_type="DEPOSIT",
            record_time=now - timedelta(seconds=2),
        )
        db.add(old)
        await db.flush()
        await _upsert_amount_records(
            db, account, period, CashFlowRecord,
            [{
                "source_record_id": "v3:funding:new-bill:cash",
                "asset": "USDT", "amount_usd": 209.99,
                "flow_type": "DEPOSIT", "record_time": now - timedelta(seconds=4),
            }],
        )
        await db.flush()
        rows = (await db.scalars(select(CashFlowRecord))).all()
        assert len(rows) == 1
        assert rows[0].id == old.id
        assert rows[0].source_record_id == "v3:funding:new-bill:cash"
        assert rows[0].amount_usd == Decimal("209.99")
