from datetime import UTC, datetime

import pytest

from app.adapters.binance import BinanceAdapter


def _trade(
    trade_id,
    side,
    quantity,
    price,
    realized_pnl,
    commission,
    timestamp,
):
    return {
        "id": trade_id,
        "orderId": trade_id,
        "symbol": "BTCUSDT",
        "positionSide": "BOTH",
        "side": side,
        "qty": str(quantity),
        "price": str(price),
        "realizedPnl": str(realized_pnl),
        "commission": str(commission),
        "commissionAsset": "USDT",
        "time": timestamp,
    }


@pytest.mark.asyncio
async def test_binance_closed_positions_reconstruct_one_way_cycle(monkeypatch):
    adapter = BinanceAdapter(api_key="key", api_secret="secret")
    start_time = datetime(2026, 7, 26, 11, tzinfo=UTC)
    end_time = datetime(2026, 7, 27, tzinfo=UTC)
    rows = [
        _trade(1, "BUY", 2, 100, 0, 0.1, 1785056400000),
        _trade(2, "BUY", 1, 110, 0, 0.05, 1785056460000),
        _trade(3, "SELL", 1, 120, 16.6666666667, 0.05, 1785060000000),
        _trade(4, "SELL", 2, 90, -26.6666666667, 0.1, 1785063600000),
    ]

    async def fake_income_rows(*_):
        return [{"symbol": "BTCUSDT", "incomeType": "REALIZED_PNL"}]

    async def fake_trade_rows(symbol, *_):
        assert symbol == "BTCUSDT"
        return rows

    monkeypatch.setattr(adapter, "_income_rows", fake_income_rows)
    monkeypatch.setattr(adapter, "_trade_rows", fake_trade_rows)
    try:
        positions = await adapter.get_closed_positions(start_time, end_time)
    finally:
        await adapter.close()

    assert len(positions) == 1
    position = positions[0]
    assert position["source_record_id"] == "binance:BTCUSDT:LONG:4"
    assert position["normalized_symbol"] == "BTC-USDT-PERP"
    assert position["side"] == "LONG"
    assert position["average_entry_price"] == pytest.approx(103.3333333333)
    assert position["average_exit_price"] == pytest.approx(100)
    assert position["max_position_size"] == 3
    assert position["realized_pnl"] == pytest.approx(-10)
    assert position["trading_fee"] == pytest.approx(0.3)
    assert position["net_pnl"] == pytest.approx(-10.3)
    assert position["data_source"] == "RECONSTRUCTED"
    assert position["data_completeness"] == "PARTIAL"


def test_binance_hedge_cycle_uses_position_side():
    start_time = datetime(2026, 7, 26, 11, tzinfo=UTC)
    rows = [
        {
            **_trade(1, "SELL", 2, 100, 0, 0.1, 1785056400000),
            "positionSide": "SHORT",
        },
        {
            **_trade(2, "BUY", 2, 90, 20, 0.1, 1785063600000),
            "positionSide": "SHORT",
        },
    ]

    cycles = BinanceAdapter._closed_cycles_from_hedge_trades(rows, start_time)

    assert len(cycles) == 1
    assert cycles[0]["side"] == "SHORT"
    assert cycles[0]["realized_pnl"] == 20
    assert cycles[0]["closing_trade_id"] == "2"
