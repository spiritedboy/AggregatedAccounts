from datetime import UTC, datetime, timedelta

import pytest

from app.adapters.binance import BinanceAdapter

pytestmark = [pytest.mark.no_db, pytest.mark.exchange]


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

    async def fake_funding_rows(*_):
        return []

    monkeypatch.setattr(adapter, "_income_rows", fake_income_rows)
    monkeypatch.setattr(adapter, "_trade_rows", fake_trade_rows)
    monkeypatch.setattr(adapter, "_funding_rows", fake_funding_rows)
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
    assert position["data_source"] == "EXCHANGE_FILLS"
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


@pytest.mark.asyncio
async def test_binance_closed_positions_merge_same_order_fill_fragments(
    monkeypatch,
):
    adapter = BinanceAdapter(api_key="key", api_secret="secret")
    start_time = datetime(2026, 7, 27, tzinfo=UTC)
    end_time = datetime(2026, 7, 29, tzinfo=UTC)
    quantities = (0.78, 0.94, 1.97, 0.78, 1.15)
    realized = (
        -17.54888434,
        -21.14737241,
        -44.31949323,
        -17.54888434,
        -25.88886565,
    )
    commissions = (
        0.10395360,
        0.12527400,
        0.26258800,
        0.10395360,
        0.15324108,
    )
    rows = []
    for index, (quantity, pnl, commission) in enumerate(
        zip(quantities, realized, commissions, strict=True),
        start=8437882,
    ):
        rows.append(
            {
                **_trade(
                    index,
                    "SELL",
                    quantity,
                    333.1896263,
                    pnl,
                    commission,
                    1785237420000,
                ),
                "orderId": 232222246,
                "symbol": "GOOGLUSDT",
                "positionSide": "LONG",
            }
        )

    async def fake_income_rows(*_):
        return [{"symbol": "GOOGLUSDT", "incomeType": "REALIZED_PNL"}]

    async def fake_trade_rows(symbol, *_):
        assert symbol == "GOOGLUSDT"
        return rows

    async def fake_funding_rows(*_):
        return []

    monkeypatch.setattr(adapter, "_income_rows", fake_income_rows)
    monkeypatch.setattr(adapter, "_trade_rows", fake_trade_rows)
    monkeypatch.setattr(adapter, "_funding_rows", fake_funding_rows)
    try:
        positions = await adapter.get_closed_positions(start_time, end_time)
    finally:
        await adapter.close()

    assert len(positions) == 1
    position = positions[0]
    assert position["source_record_id"] == "binance:GOOGLUSDT:LONG:8437886"
    assert position["max_position_size"] == pytest.approx(5.62)
    assert position["average_exit_price"] == pytest.approx(333.1896263)
    assert position["realized_pnl"] == pytest.approx(-126.45349997)
    assert position["trading_fee"] == pytest.approx(0.74901028)
    assert position["net_pnl"] == pytest.approx(-127.20251025)


@pytest.mark.asyncio
async def test_binance_closed_positions_include_long_cycle_reductions_and_funding(
    monkeypatch,
):
    adapter = BinanceAdapter(api_key="key", api_secret="secret")
    start_time = datetime(2026, 10, 28, tzinfo=UTC)
    end_time = datetime(2026, 10, 28, 1, tzinfo=UTC)
    opened_at = datetime(2026, 10, 9, 12, tzinfo=UTC)
    first_reduction_at = datetime(2026, 10, 16, 12, tzinfo=UTC)
    added_at = datetime(2026, 10, 18, 12, tzinfo=UTC)
    closed_at = datetime(2026, 10, 28, 0, 30, tzinfo=UTC)
    rows = [
        {
            **_trade(1, "BUY", 20, 100, 0, 1, int(opened_at.timestamp() * 1000)),
            "positionSide": "LONG",
        },
        {
            **_trade(
                2,
                "SELL",
                5,
                90,
                -50,
                0.25,
                int(first_reduction_at.timestamp() * 1000),
            ),
            "positionSide": "LONG",
        },
        {
            **_trade(3, "BUY", 5, 80, 0, 0.2, int(added_at.timestamp() * 1000)),
            "positionSide": "LONG",
        },
        {
            **_trade(4, "SELL", 20, 110, 200, 1, int(closed_at.timestamp() * 1000)),
            "positionSide": "LONG",
        },
    ]
    funding = [
        {
            "symbol": "BTCUSDT",
            "income": "-10",
            "asset": "USDT",
            "time": int(datetime(2026, 10, 12, tzinfo=UTC).timestamp() * 1000),
        },
        {
            "symbol": "BTCUSDT",
            "income": "-5",
            "asset": "USDT",
            "time": int(datetime(2026, 10, 25, tzinfo=UTC).timestamp() * 1000),
        },
    ]

    async def fake_income_rows(*_):
        return [{"symbol": "BTCUSDT", "incomeType": "REALIZED_PNL"}]

    async def fake_trade_rows(*_):
        return rows

    async def fake_funding_rows(*_):
        return funding

    monkeypatch.setattr(adapter, "_income_rows", fake_income_rows)
    monkeypatch.setattr(adapter, "_trade_rows", fake_trade_rows)
    monkeypatch.setattr(adapter, "_funding_rows", fake_funding_rows)
    try:
        positions = await adapter.get_closed_positions(start_time, end_time)
    finally:
        await adapter.close()

    assert len(positions) == 1
    position = positions[0]
    assert position["max_position_size"] == pytest.approx(20)
    assert position["realized_pnl"] == pytest.approx(150)
    assert position["funding_fee"] == pytest.approx(-15)
    assert position["trading_fee"] == pytest.approx(2.45)
    assert position["net_pnl"] == pytest.approx(132.55)


@pytest.mark.asyncio
async def test_binance_funding_is_attributed_to_sequential_hedge_cycles(monkeypatch):
    adapter = BinanceAdapter(api_key="key", api_secret="secret")
    start_time = datetime(2026, 10, 20, tzinfo=UTC)
    end_time = datetime(2026, 10, 21, tzinfo=UTC)
    timestamps = [
        int(datetime(2026, 10, 20, hour, tzinfo=UTC).timestamp() * 1000)
        for hour in range(1, 7)
    ]
    rows = [
        {
            **_trade(1, "BUY", 10, 100, 0, 0.1, timestamps[0]),
            "positionSide": "LONG",
        },
        {
            **_trade(2, "SELL", 10, 110, 100, 0.1, timestamps[2]),
            "positionSide": "LONG",
        },
        {
            **_trade(3, "SELL", 5, 120, 0, 0.1, timestamps[3]),
            "positionSide": "SHORT",
        },
        {
            **_trade(4, "BUY", 5, 110, 50, 0.1, timestamps[5]),
            "positionSide": "SHORT",
        },
    ]
    funding = [
        {
            "symbol": "BTCUSDT",
            "income": "-2",
            "asset": "USDT",
            "time": timestamps[1],
        },
        {
            "symbol": "BTCUSDT",
            "income": "1",
            "asset": "USDT",
            "time": timestamps[4],
        },
    ]

    async def fake_income_rows(*_):
        return [{"symbol": "BTCUSDT", "incomeType": "REALIZED_PNL"}]

    async def fake_trade_rows(*_):
        return rows

    async def fake_funding_rows(*_):
        return funding

    monkeypatch.setattr(adapter, "_income_rows", fake_income_rows)
    monkeypatch.setattr(adapter, "_trade_rows", fake_trade_rows)
    monkeypatch.setattr(adapter, "_funding_rows", fake_funding_rows)
    try:
        positions = await adapter.get_closed_positions(start_time, end_time)
    finally:
        await adapter.close()

    by_side = {position["side"]: position for position in positions}
    assert by_side["LONG"]["funding_fee"] == pytest.approx(-2)
    assert by_side["LONG"]["net_pnl"] == pytest.approx(97.8)
    assert by_side["SHORT"]["funding_fee"] == pytest.approx(1)
    assert by_side["SHORT"]["net_pnl"] == pytest.approx(50.8)


@pytest.mark.asyncio
async def test_binance_trade_history_scans_supported_range_in_seven_day_windows(
    monkeypatch,
):
    adapter = BinanceAdapter(api_key="key", api_secret="secret")
    end_time = datetime(2026, 10, 28, tzinfo=UTC)
    old_trade_timestamp = int(
        (end_time - adapter.closed_position_lookback + timedelta(days=1)).timestamp()
        * 1000
    )
    windows = []

    async def fake_signed_get(_base, path, params):
        assert path == "/fapi/v1/userTrades"
        if "startTime" not in params:
            return []
        windows.append((params["startTime"], params["endTime"]))
        if params["startTime"] <= old_trade_timestamp <= params["endTime"]:
            return [_trade(99, "BUY", 1, 100, 0, 0.01, old_trade_timestamp)]
        return []

    monkeypatch.setattr(adapter, "_signed_get", fake_signed_get)
    try:
        rows = await adapter._trade_rows("BTCUSDT", end_time, end_time)
    finally:
        await adapter.close()

    assert [row["id"] for row in rows] == [99]
    assert len(windows) == 13
    assert all(end - start < 7 * 24 * 60 * 60 * 1000 for start, end in windows)
