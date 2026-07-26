from datetime import UTC, datetime

import pytest

from app.adapters.hyperliquid import HyperliquidAdapter


def _fill(
    trade_id,
    side,
    start_position,
    size,
    price,
    closed_pnl,
    fee,
    timestamp,
):
    return {
        "tid": trade_id,
        "hash": f"hash-{trade_id}",
        "oid": trade_id,
        "coin": "BTC",
        "dir": "Open Long" if side == "B" else "Close Long",
        "side": side,
        "startPosition": str(start_position),
        "sz": str(size),
        "px": str(price),
        "closedPnl": str(closed_pnl),
        "fee": str(fee),
        "feeToken": "USDC",
        "time": timestamp,
    }


@pytest.mark.asyncio
async def test_hyperliquid_closed_positions_reconstruct_zero_to_zero_cycle(monkeypatch):
    adapter = HyperliquidAdapter(wallet_address="0x0000000000000000000000000000000000000001")
    start_time = datetime(2026, 7, 26, 8, tzinfo=UTC)
    end_time = datetime(2026, 7, 27, tzinfo=UTC)
    fills = [
        _fill(1, "B", 0, 2, 100, 0, 0.1, 1785056400000),
        _fill(2, "B", 2, 1, 110, 0, 0.05, 1785056460000),
        _fill(3, "A", 3, 1, 120, 16.6666666667, 0.05, 1785060000000),
        _fill(4, "A", 2, 2, 90, -26.6666666667, 0.1, 1785063600000),
    ]
    funding = [
        {
            "hash": "funding-1",
            "time": 1785058200000,
            "delta": {"coin": "BTC", "usdc": "-0.2"},
        }
    ]

    async def fake_history(request_type, *_args, **_kwargs):
        return fills if request_type == "userFillsByTime" else funding

    monkeypatch.setattr(adapter, "_time_paginated_info", fake_history)
    try:
        positions = await adapter.get_closed_positions(start_time, end_time)
    finally:
        await adapter.close()

    assert len(positions) == 1
    position = positions[0]
    assert position["source_record_id"] == "hyperliquid:BTC:4"
    assert position["normalized_symbol"] == "BTC-USDT-PERP"
    assert position["side"] == "LONG"
    assert position["average_entry_price"] == pytest.approx(103.3333333333)
    assert position["average_exit_price"] == pytest.approx(100)
    assert position["max_position_size"] == 3
    assert position["realized_pnl"] == pytest.approx(-10)
    assert position["funding_fee"] == pytest.approx(-0.2)
    assert position["trading_fee"] == pytest.approx(0.3)
    assert position["net_pnl"] == pytest.approx(-10.5)
    assert position["data_source"] == "RECONSTRUCTED"
    assert position["data_completeness"] == "COMPLETE"


@pytest.mark.asyncio
async def test_hyperliquid_initial_position_uses_fill_implied_entry(monkeypatch):
    adapter = HyperliquidAdapter(wallet_address="0x0000000000000000000000000000000000000001")
    start_time = datetime(2026, 7, 26, 11, tzinfo=UTC)
    end_time = datetime(2026, 7, 27, tzinfo=UTC)
    fills = [_fill(9, "A", 2, 2, 90, -20, 0.1, 1785063600000)]

    async def fake_history(request_type, *_args, **_kwargs):
        return fills if request_type == "userFillsByTime" else []

    monkeypatch.setattr(adapter, "_time_paginated_info", fake_history)
    try:
        positions = await adapter.get_closed_positions(start_time, end_time)
    finally:
        await adapter.close()

    assert len(positions) == 1
    position = positions[0]
    assert position["open_time"] == start_time
    assert position["average_entry_price"] == 100
    assert position["average_exit_price"] == 90
    assert position["max_position_size"] == 2
    assert position["data_completeness"] == "PARTIAL"
