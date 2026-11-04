from datetime import UTC, datetime, timedelta

import pytest

from app.adapters.bitget import BitgetAdapter

pytestmark = [pytest.mark.no_db, pytest.mark.exchange]


@pytest.mark.asyncio
async def test_bitget_closed_positions_normalize_native_history(monkeypatch):
    adapter = BitgetAdapter(api_key="key", api_secret="secret", passphrase="pass")
    row = {
        "positionId": "position-1",
        "marginCoin": "USDT",
        "symbol": "BTCUSDT",
        "posSide": "long",
        "openPriceAvg": "32000",
        "closePriceAvg": "32500",
        "openTotalPos": "0.01",
        "closeTotalPos": "0.01",
        "cumRealisedPnl": "5",
        "netProfit": "4.7",
        "totalFunding": "-0.1",
        "openFeeTotal": "-0.08",
        "closeFeeTotal": "-0.12",
        "createdTime": "1785059143881",
        "updatedTime": "1785080589858",
        "leverage": "20",
    }

    async def fake_rows(product_type, *_):
        return [row] if product_type == "USDT-FUTURES" else []

    monkeypatch.setattr(adapter, "_position_history_rows", fake_rows)
    try:
        positions = await adapter.get_closed_positions(
            datetime(2026, 7, 26, 11, tzinfo=UTC),
            datetime(2026, 7, 27, tzinfo=UTC),
        )
    finally:
        await adapter.close()

    assert len(positions) == 1
    position = positions[0]
    assert position["source_record_id"] == "bitget:USDT-FUTURES:position-1"
    assert position["normalized_symbol"] == "BTC-USDT-PERP"
    assert position["side"] == "LONG"
    assert position["average_entry_price"] == 32000
    assert position["average_exit_price"] == 32500
    assert position["max_position_size"] == 0.01
    assert position["realized_pnl"] == 5
    assert position["funding_fee"] == -0.1
    assert position["trading_fee"] == pytest.approx(0.2)
    assert position["net_pnl"] == 4.7
    assert position["leverage"] == 20
    assert position["margin_used"] == 16
    assert position["return_percent"] == pytest.approx(29.375)
    assert position["data_source"] == "EXCHANGE_API"
    assert position["data_completeness"] == "COMPLETE"


@pytest.mark.asyncio
async def test_bitget_closed_positions_keep_latest_row_for_position_id(
    monkeypatch,
):
    adapter = BitgetAdapter(api_key="key", api_secret="secret", passphrase="pass")
    base = {
        "positionId": "123456",
        "marginCoin": "USDT",
        "symbol": "BTCUSDT",
        "posSide": "long",
        "openPriceAvg": "32000",
        "closePriceAvg": "32500",
        "openTotalPos": "0.01",
        "closeTotalPos": "0.01",
        "cumRealisedPnl": "5",
        "netProfit": "4.7",
        "totalFunding": "-0.1",
        "openFeeTotal": "-0.08",
        "closeFeeTotal": "-0.12",
        "createdTime": "1785059143881",
    }
    rows = [
        {**base, "updatedTime": "1785080000000", "netProfit": "1.2"},
        {**base, "updatedTime": "1785080589858"},
    ]

    async def fake_rows(product_type, *_):
        return rows if product_type == "USDT-FUTURES" else []

    monkeypatch.setattr(adapter, "_position_history_rows", fake_rows)
    try:
        positions = await adapter.get_closed_positions(
            datetime(2026, 7, 26, 11, tzinfo=UTC),
            datetime(2026, 7, 27, tzinfo=UTC),
        )
    finally:
        await adapter.close()

    assert len(positions) == 1
    assert positions[0]["source_record_id"] == "bitget:USDT-FUTURES:123456"
    assert positions[0]["net_pnl"] == 4.7


@pytest.mark.asyncio
async def test_bitget_position_history_uses_v3_cursor_pagination(monkeypatch):
    adapter = BitgetAdapter(api_key="key", api_secret="secret", passphrase="pass")
    first_page = [{"positionId": str(index)} for index in range(100)]
    calls = []

    async def fake_get(path, params):
        calls.append((path, dict(params)))
        if "cursor" not in params:
            return {"list": first_page, "cursor": "cursor-1"}
        if params["cursor"] == "cursor-1":
            return {"list": [{"positionId": "older"}], "cursor": "cursor-2"}
        return {"list": [], "cursor": ""}

    monkeypatch.setattr(adapter, "_get", fake_get)
    try:
        rows = await adapter._position_history_rows(
            "USDT-FUTURES",
            datetime.now(UTC) - timedelta(hours=1),
            datetime.now(UTC),
        )
    finally:
        await adapter.close()

    assert len(rows) == 101
    assert calls[0][0] == "/api/v3/position/history-position"
    assert "cursor" not in calls[0][1]
    assert calls[1][1]["cursor"] == "cursor-1"


@pytest.mark.asyncio
async def test_bitget_permissions_use_uta_permission_type(monkeypatch):
    adapter = BitgetAdapter(api_key="key", api_secret="secret", passphrase="pass")

    async def fake_get(path):
        assert path == "/api/v3/account/info"
        return {"permType": "readonly", "permissions": ["uta_mgt", "uta_trade"]}

    monkeypatch.setattr(adapter, "_get", fake_get)
    try:
        permissions = await adapter.get_permissions()
    finally:
        await adapter.close()
    assert permissions == {
        "read": True,
        "spot_trade": False,
        "futures_trade": False,
        "transfer": False,
        "withdraw": False,
    }


@pytest.mark.asyncio
async def test_bitget_uta_financial_rows_exclude_internal_transfers(monkeypatch):
    adapter = BitgetAdapter(api_key="key", api_secret="secret", passphrase="pass")
    timestamp = int(datetime.now(UTC).timestamp() * 1000)

    async def fake_rows(*_):
        return [
            {"id": "1", "coin": "USDT", "type": "TRANSFER_IN", "amount": "25", "ts": timestamp},
            {"id": "2", "coin": "USDT", "type": "deposit", "amount": "25",
             "ts": timestamp, "_funding_account": True},
            {"id": "3", "coin": "USDT", "type": "CONTRACT_MAIN_SETTLE_FEE_USER_OUT",
             "amount": "-0.3", "ts": timestamp},
            {"id": "4", "coin": "USDT", "type": "CLOSE_LONG", "amount": "4",
             "fee": "0", "ts": timestamp},
        ]

    monkeypatch.setattr(adapter, "_bill_rows", fake_rows)
    try:
        bundle = await adapter.get_history_bundle(
            datetime.now(UTC) - timedelta(hours=1), datetime.now(UTC) + timedelta(hours=1)
        )
    finally:
        await adapter.close()
    assert [item["amount_usd"] for item in bundle["cash_flows"]] == [25]
    assert bundle["funding"][0]["amount_usd"] == -0.3
    assert bundle["income"][0]["amount_usd"] == 4
    assert bundle["fees"] == []
    assert bundle["complete"] is True
