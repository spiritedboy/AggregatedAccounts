from datetime import UTC, datetime

import pytest

from app.adapters.bitget import BitgetAdapter


@pytest.mark.asyncio
async def test_bitget_closed_positions_normalize_native_history(monkeypatch):
    adapter = BitgetAdapter(api_key="key", api_secret="secret", passphrase="pass")
    row = {
        "positionId": "position-1",
        "marginCoin": "USDT",
        "symbol": "BTCUSDT",
        "holdSide": "long",
        "openAvgPrice": "32000",
        "closeAvgPrice": "32500",
        "openTotalPos": "0.01",
        "closeTotalPos": "0.01",
        "pnl": "5",
        "netProfit": "4.7",
        "totalFunding": "-0.1",
        "openFee": "-0.08",
        "closeFee": "-0.12",
        "ctime": "1785059143881",
        "utime": "1785080589858",
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
    assert position["source_record_id"] == (
        "bitget:USDT-FUTURES:position-1:1785080589858"
    )
    assert position["normalized_symbol"] == "BTC-USDT-PERP"
    assert position["side"] == "LONG"
    assert position["average_entry_price"] == 32000
    assert position["average_exit_price"] == 32500
    assert position["max_position_size"] == 0.01
    assert position["realized_pnl"] == 5
    assert position["funding_fee"] == -0.1
    assert position["trading_fee"] == pytest.approx(0.2)
    assert position["net_pnl"] == 4.7
    assert position["return_percent"] == pytest.approx(1.5625)
    assert position["data_source"] == "EXCHANGE_API"
    assert position["data_completeness"] == "COMPLETE"


@pytest.mark.asyncio
async def test_bitget_position_history_uses_end_id_pagination(monkeypatch):
    adapter = BitgetAdapter(api_key="key", api_secret="secret", passphrase="pass")
    first_page = [{"positionId": str(index)} for index in range(100)]
    calls = []

    async def fake_get(path, params):
        calls.append((path, dict(params)))
        if "idLessThan" not in params:
            return {"list": first_page, "endId": "cursor-1"}
        return {"list": [{"positionId": "older"}], "endId": "cursor-2"}

    monkeypatch.setattr(adapter, "_get", fake_get)
    try:
        rows = await adapter._position_history_rows(
            "USDT-FUTURES",
            datetime(2026, 7, 26, tzinfo=UTC),
            datetime(2026, 7, 27, tzinfo=UTC),
        )
    finally:
        await adapter.close()

    assert len(rows) == 101
    assert calls[0][0] == "/api/v2/mix/position/history-position"
    assert "idLessThan" not in calls[0][1]
    assert calls[1][1]["idLessThan"] == "cursor-1"
