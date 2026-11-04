from datetime import UTC, datetime

import httpx
import pytest

from app.adapters.base import AdapterError
from app.adapters.polymarket import PolymarketAdapter, closed_position_source_id

pytestmark = [pytest.mark.no_db, pytest.mark.exchange]


def _page(rows: list[dict], *, next_cursor: str | None = None) -> dict:
    return {
        "data": rows,
        "pagination": {
            "limit": 1000,
            "offset": 0,
            "has_more": next_cursor is not None,
            "next_cursor": next_cursor,
        },
    }


@pytest.mark.asyncio
async def test_polymarket_maps_v2_value_and_positions():
    condition_id = "0x" + "a" * 64
    token_id = "123456789012345678901234567890"

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.host.endswith("publicnode.com"):
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "0xdd40a0"})
        if request.url.path == "/public-profile":
            return httpx.Response(200, json={"proxyWallet": "0x" + "9" * 40})
        if request.url.path == "/v2/value":
            return httpx.Response(
                200,
                json={"data": {"proxy_wallet": "0x" + "9" * 40, "value": 37.5}},
            )
        if request.url.path == "/v2/positions":
            return httpx.Response(
                200,
                json=_page(
                    [
                        {
                            "token_id": token_id,
                            "condition_id": condition_id,
                            "current_size": 50,
                            "avg_price": 0.35,
                            "entry_cost_usdc": 17.5,
                            "current_value": 37.5,
                            "unrealized_pnl": 20,
                            "percent_pnl": 114.2857,
                            "realized_pnl": 1.25,
                            "current_price": 0.75,
                            "title": "Will the integration test pass?",
                            "outcome": "Yes",
                            "outcome_index": 0,
                            "first_entry_at": 1785060000,
                        }
                    ]
                ),
            )
        if request.url.path == "/v2/positions/combos":
            return httpx.Response(200, json=_page([]))
        raise AssertionError(f"unexpected request: {request.url}")

    adapter = PolymarketAdapter(wallet_address="0x" + "1" * 40)
    await adapter.client.aclose()
    adapter.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        assert await adapter.test_connection() is True
        summary = await adapter.get_account_summary()
        balances = await adapter.get_balances()
        positions = await adapter.get_open_positions()
    finally:
        await adapter.close()

    assert summary == {
        "total_equity_usd": 52.0,
        "available_balance_usd": 14.5,
        "margin_balance_usd": 37.5,
        "unrealized_pnl_usd": 20.0,
        "unvalued_asset_count": 0,
        "price_source": "POLYMARKET_DATA_API_V2",
    }
    assert balances[0]["available"] == 14.5
    assert balances[0]["value_usd"] == 52.0
    assert positions[0]["source_record_id"] == token_id
    assert positions[0]["market_type"] == "PREDICTION"
    assert positions[0]["symbol"].endswith("· Yes")
    assert positions[0]["translation_asset_id"] == token_id
    assert positions[0]["translation_source_title"] == "Will the integration test pass?"
    assert positions[0]["unrealized_pnl"] == 20
    assert positions[0]["unrealized_pnl_percent"] == 114.2857
    assert positions[0]["open_time"] == datetime.fromtimestamp(1785060000, tz=UTC)
    assert adapter.wallet_address == "0x" + "9" * 40


@pytest.mark.asyncio
async def test_polymarket_maps_v2_combo_positions_and_closed_history():
    combo_id = "987654321"
    open_combo = {
        "combo_position_id": combo_id,
        "combo_condition_id": "0x" + "e" * 64,
        "outcome_index": 0,
        "outcome_label": "Yes",
        "current_size": 10,
        "entry_avg_price_usdc": 0.48,
        "gross_entry_cost_usdc": 5,
        "entry_fees_usdc": 0.2,
        "status": "OPEN",
        "first_entry_at": "2026-07-26T10:00:00Z",
        "legs": [
            {
                "leg_status": "RESOLVED_WIN",
                "leg_current_price": 1,
                "market": {"title": "Team A wins", "outcome": "Yes"},
            },
            {
                "leg_status": "OPEN",
                "leg_current_price": 0.8,
                "market": {"title": "Team B wins", "outcome": "Yes"},
            },
        ],
    }
    closed_combo = {
        **open_combo,
        "current_size": 0,
        "status": "RESOLVED_WIN",
        "resolved_at": "2026-07-27T10:00:00Z",
        "realized_payout_usdc": 10,
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2/positions":
            return httpx.Response(200, json=_page([]))
        if request.url.path == "/v2/positions/combos":
            statuses = request.url.params["status"]
            rows = [closed_combo] if "RESOLVED" in statuses else [open_combo]
            return httpx.Response(200, json=_page(rows))
        raise AssertionError(f"unexpected request: {request.url}")

    adapter = PolymarketAdapter(wallet_address="0x" + "4" * 40)
    await adapter.client.aclose()
    adapter.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        current = await adapter.get_open_positions()
        closed = await adapter.get_closed_positions(
            datetime(2026, 7, 25, tzinfo=UTC), datetime(2026, 7, 28, tzinfo=UTC)
        )
    finally:
        await adapter.close()

    assert current[0]["source_record_id"] == combo_id
    assert current[0]["market_type"] == "PREDICTION_COMBO"
    assert current[0]["mark_price"] == pytest.approx(0.8)
    assert current[0]["position_value_usd"] == pytest.approx(8)
    assert current[0]["unrealized_pnl"] == pytest.approx(3)
    assert current[0]["translation_source_title"].startswith("Combo:")
    assert closed[0]["source_record_id"] == f"poly-closed:{combo_id}"
    assert closed[0]["realized_pnl"] == pytest.approx(5.2)
    assert closed[0]["trading_fee"] == pytest.approx(0.2)
    assert closed[0]["net_pnl"] == pytest.approx(5)


@pytest.mark.asyncio
async def test_polymarket_v2_closed_positions_keep_window_during_cursor_pagination():
    start = datetime(2026, 7, 25, tzinfo=UTC)
    end = datetime(2026, 7, 27, tzinfo=UTC)
    seen_requests: list[dict[str, str]] = []

    def closed_row(token_id: str, timestamp: int) -> dict:
        return {
            "token_id": token_id,
            "condition_id": "0x" + "b" * 64,
            "avg_price": 0.4,
            "total_size": 10,
            "realized_pnl": 6,
            "current_price": 1,
            "last_event_at": timestamp,
            "first_entry_at": timestamp - 3600,
            "title": "Closed position",
            "outcome": "Yes",
            "outcome_index": 0,
        }

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v2/positions/combos":
            return httpx.Response(200, json=_page([]))
        assert request.url.path == "/v2/positions"
        params = dict(request.url.params)
        seen_requests.append(params)
        assert params["status"] == "CLOSED"
        assert params["start"] == str(int(start.timestamp()))
        assert params["end"] == str(int(end.timestamp()))
        if "cursor" not in params:
            return httpx.Response(
                200,
                json=_page([closed_row("first", 1785067200)], next_cursor="next"),
            )
        assert params["cursor"] == "next"
        return httpx.Response(200, json=_page([closed_row("second", 1785063600)]))

    adapter = PolymarketAdapter(wallet_address="0x" + "2" * 40)
    await adapter.client.aclose()
    adapter.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        rows = await adapter.get_closed_positions(start, end)
    finally:
        await adapter.close()

    assert len(rows) == 2
    assert {row["source_record_id"] for row in rows} == {
        "poly-closed:first",
        "poly-closed:second",
    }
    assert len(seen_requests) == 2


def test_polymarket_closed_position_identity_uses_v2_token_id():
    first = {
        "token_id": "stable-outcome-token",
        "condition_id": "0x" + "d" * 64,
        "outcome_index": 0,
        "last_event_at": 1785067200,
    }
    second = {**first, "last_event_at": 1785067201}

    assert closed_position_source_id(first) == closed_position_source_id(second)
    assert closed_position_source_id(first) == "poly-closed:stable-outcome-token"


@pytest.mark.asyncio
async def test_polymarket_rejects_invalid_v2_envelope():
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    adapter = PolymarketAdapter(wallet_address="0x" + "3" * 40)
    await adapter.client.aclose()
    adapter.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(AdapterError, match="响应格式无效"):
            await adapter.get_open_positions()
    finally:
        await adapter.close()
