import io
import zipfile
from datetime import UTC, datetime

import httpx
import pytest

from app.adapters.polymarket import PolymarketAdapter

pytestmark = [pytest.mark.no_db, pytest.mark.exchange]


def _snapshot_zip() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(
            "positions.csv",
            "conditionId,asset,size,curPrice,valuationTime\n",
        )
        archive.writestr(
            "equity.csv",
            "cashBalance,positionsValue,equity,valuationTime\n"
            "14.5,37.5,52.0,2026-07-26T12:00:00Z\n",
        )
    return output.getvalue()


@pytest.mark.asyncio
async def test_polymarket_maps_accounting_snapshot_and_positions():
    condition_id = "0x" + "a" * 64
    asset = "123456789012345678901234567890"

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/public-profile":
            return httpx.Response(200, json={"proxyWallet": "0x" + "9" * 40})
        if request.url.path == "/v1/accounting/snapshot":
            return httpx.Response(200, content=_snapshot_zip())
        if request.url.path == "/positions":
            return httpx.Response(
                200,
                json=[
                    {
                        "asset": asset,
                        "conditionId": condition_id,
                        "size": 50,
                        "avgPrice": 0.35,
                        "initialValue": 17.5,
                        "currentValue": 37.5,
                        "cashPnl": 20,
                        "percentPnl": 114.2857,
                        "realizedPnl": 1.25,
                        "curPrice": 0.75,
                        "title": "Will the integration test pass?",
                        "outcome": "Yes",
                        "outcomeIndex": 0,
                    }
                ],
            )
        raise AssertionError(f"unexpected request: {request.url}")

    adapter = PolymarketAdapter(wallet_address="0x" + "1" * 40)
    await adapter.client.aclose()
    adapter.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        assert await adapter.test_connection() is True
        summary = await adapter.get_account_summary()
        positions = await adapter.get_open_positions()
    finally:
        await adapter.close()

    assert summary == {
        "total_equity_usd": 52.0,
        "available_balance_usd": 14.5,
        "margin_balance_usd": 37.5,
        "unrealized_pnl_usd": 20.0,
        "unvalued_asset_count": 0,
        "price_source": "POLYMARKET_ACCOUNTING_SNAPSHOT",
    }
    assert positions[0]["source_record_id"] == asset
    assert positions[0]["market_type"] == "PREDICTION"
    assert positions[0]["symbol"].endswith("· Yes")
    assert positions[0]["translation_asset_id"] == asset
    assert positions[0]["translation_source_title"] == "Will the integration test pass?"
    assert positions[0]["translation_source_outcome"] == "Yes"
    assert positions[0]["unrealized_pnl"] == 20
    assert positions[0]["unrealized_pnl_percent"] == 114.2857
    assert adapter.wallet_address == "0x" + "9" * 40


@pytest.mark.asyncio
async def test_polymarket_closed_positions_stop_at_tracking_boundary():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/closed-positions"
        return httpx.Response(
            200,
            json=[
                {
                    "asset": "new",
                    "conditionId": "0x" + "b" * 64,
                    "avgPrice": 0.4,
                    "totalBought": 10,
                    "realizedPnl": 6,
                    "curPrice": 1,
                    "timestamp": 1785067200,
                    "title": "New close",
                    "outcome": "Yes",
                    "outcomeIndex": 0,
                },
                {
                    "asset": "old",
                    "conditionId": "0x" + "c" * 64,
                    "avgPrice": 0.8,
                    "totalBought": 10,
                    "realizedPnl": -8,
                    "curPrice": 0,
                    "timestamp": 1784894400,
                    "title": "Old close",
                    "outcome": "No",
                    "outcomeIndex": 1,
                },
            ],
        )

    adapter = PolymarketAdapter(wallet_address="0x" + "2" * 40)
    await adapter.client.aclose()
    adapter.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        rows = await adapter.get_closed_positions(
            datetime(2026, 7, 25, tzinfo=UTC),
            datetime(2026, 7, 27, tzinfo=UTC),
        )
    finally:
        await adapter.close()

    assert len(rows) == 1
    assert rows[0]["source_record_id"] == "poly-closed:new"
    assert rows[0]["translation_asset_id"] == "new"
    assert rows[0]["realized_pnl"] == 6
    assert rows[0]["data_completeness"] == "PARTIAL"


@pytest.mark.asyncio
async def test_polymarket_closed_position_identity_ignores_moving_timestamp():
    requests = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(
            200,
            json=[
                {
                    "asset": "stable-outcome-token",
                    "conditionId": "0x" + "d" * 64,
                    "avgPrice": 0.4,
                    "totalBought": 10,
                    "realizedPnl": 6,
                    "curPrice": 1,
                    "timestamp": 1785067200 + requests,
                    "title": "Stable identity",
                    "outcome": "Yes",
                    "outcomeIndex": 0,
                }
            ],
        )

    adapter = PolymarketAdapter(wallet_address="0x" + "3" * 40)
    await adapter.client.aclose()
    adapter.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        first = await adapter.get_closed_positions(
            datetime(2026, 7, 25, tzinfo=UTC),
            datetime(2026, 7, 27, tzinfo=UTC),
        )
        second = await adapter.get_closed_positions(
            datetime(2026, 7, 25, tzinfo=UTC),
            datetime(2026, 7, 27, tzinfo=UTC),
        )
    finally:
        await adapter.close()

    assert first[0]["close_time"] != second[0]["close_time"]
    assert first[0]["source_record_id"] == second[0]["source_record_id"]
    assert first[0]["source_record_id"] == "poly-closed:stable-outcome-token"
