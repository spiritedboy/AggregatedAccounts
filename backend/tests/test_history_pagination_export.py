import csv
import io
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app import api
from app.database import SessionLocal
from app.models import ClosedPosition, ExchangeAccount, TrackingPeriod


@pytest.mark.asyncio
async def test_equal_close_times_page_stably_and_export_every_batch(client, monkeypatch):
    monkeypatch.setattr(api, "HISTORY_EXPORT_BATCH_SIZE", 2)
    closed_at = datetime(2026, 11, 13, 1, 0, tzinfo=UTC)
    started_at = closed_at - timedelta(days=1)
    async with SessionLocal() as db:
        account = ExchangeAccount(
            exchange="BINANCE",
            connection_name="history-pagination-test",
            masked_identifier="test",
            tracking_started_at=started_at,
        )
        db.add(account)
        await db.flush()
        period = TrackingPeriod(
            exchange=account.exchange,
            exchange_account_id=account.id,
            started_at=started_at,
        )
        db.add(period)
        await db.flush()
        db.add_all(
            ClosedPosition(
                id=uuid.UUID(int=index),
                exchange=account.exchange,
                exchange_account_id=account.id,
                tracking_period_id=period.id,
                source_record_id=f"closed-{index}",
                symbol=f"TEST{index}",
                normalized_symbol=f"TEST{index}-USDT-PERP",
                side="LONG",
                open_time=started_at,
                close_time=closed_at,
                net_pnl=Decimal(index),
                tracking_started_at=started_at,
            )
            for index in range(1, 8)
        )
        await db.commit()

    expected_ids = [str(uuid.UUID(int=index)) for index in range(7, 0, -1)]
    page_ids = []
    for page in range(1, 4):
        response = client.get(f"/api/positions/history?symbol=TEST&page={page}&page_size=3")
        assert response.status_code == 200
        assert response.json()["data"]["total"] == 7
        page_ids.extend(item["id"] for item in response.json()["data"]["items"])
    assert page_ids == expected_ids

    bootstrap = client.get("/api/positions/history/bootstrap?symbol=TEST&page=2&page_size=3")
    assert bootstrap.status_code == 200
    bootstrap_ids = [item["id"] for item in bootstrap.json()["data"]["history"]["items"]]
    assert bootstrap_ids == expected_ids[3:6]

    export = client.get("/api/positions/history/export?symbol=TEST")
    assert export.status_code == 200
    rows = list(csv.DictReader(io.StringIO(export.text)))
    assert [row["symbol"] for row in rows] == [f"TEST{index}" for index in range(7, 0, -1)]
