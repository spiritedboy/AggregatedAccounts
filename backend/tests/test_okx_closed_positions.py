from datetime import UTC, datetime, timedelta

import pytest

from app.adapters.okx import OkxAdapter


@pytest.mark.asyncio
async def test_okx_closed_positions_normalize_exchange_history(monkeypatch):
    adapter = OkxAdapter(api_key="key", api_secret="secret", passphrase="pass")
    row = {
        "cTime": "1785059143881",
        "closeAvgPx": "1.576",
        "closeTotalPos": "3148",
        "direction": "long",
        "fee": "-0.498171",
        "fundingFee": "-0.02485346",
        "instId": "TRUMP-USDT-SWAP",
        "instType": "SWAP",
        "liqPenalty": "0",
        "openAvgPx": "1.589",
        "openMaxPos": "3148",
        "pnl": "-4.0924",
        "pnlRatio": "-0.1845368156073002",
        "posId": "3776777608724766720",
        "realizedPnl": "-4.61542446",
        "settledPnl": "",
        "uTime": "1785080589858",
    }

    async def fake_rows(inst_type, *_):
        return [row] if inst_type == "SWAP" else []

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
    assert position["source_record_id"] == "okx:SWAP:3776777608724766720"
    assert position["symbol"] == "TRUMP-USDT-SWAP"
    assert position["normalized_symbol"] == "TRUMP-USDT-PERP"
    assert position["side"] == "LONG"
    assert position["open_time"] == datetime(
        2026, 7, 26, 9, 45, 43, 881000, tzinfo=UTC
    )
    assert position["close_time"] == datetime(
        2026, 7, 26, 15, 43, 9, 858000, tzinfo=UTC
    )
    assert position["average_entry_price"] == 1.589
    assert position["average_exit_price"] == 1.576
    assert position["max_position_size"] == 3148
    assert position["realized_pnl"] == -4.0924
    assert position["funding_fee"] == -0.02485346
    assert position["trading_fee"] == 0.498171
    assert position["net_pnl"] == -4.61542446
    assert position["return_percent"] == pytest.approx(-18.45368156073002)
    assert position["data_source"] == "EXCHANGE_API"
    assert position["data_completeness"] == "COMPLETE"


@pytest.mark.asyncio
async def test_okx_position_history_paginates_by_oldest_update_time(monkeypatch):
    adapter = OkxAdapter(api_key="key", api_secret="secret", passphrase="pass")
    end_time = datetime(2026, 7, 27, tzinfo=UTC)
    start_time = end_time - timedelta(hours=1)
    newest_ms = int((end_time - timedelta(minutes=1)).timestamp() * 1000)
    first_page = [
        {"uTime": str(newest_ms - index * 1000), "posId": str(index)}
        for index in range(100)
    ]
    second_page = [{"uTime": str(newest_ms - 100_000), "posId": "next"}]
    calls = []

    async def fake_get(path, params):
        calls.append((path, dict(params)))
        return first_page if "after" not in params else second_page

    monkeypatch.setattr(adapter, "_get", fake_get)
    try:
        rows = await adapter._position_history_rows("SWAP", start_time, end_time)
    finally:
        await adapter.close()

    assert len(rows) == 101
    assert calls[0] == (
        "/api/v5/account/positions-history",
        {"instType": "SWAP", "limit": 100},
    )
    assert calls[1][1]["after"] == first_page[-1]["uTime"]


@pytest.mark.asyncio
async def test_okx_partial_closes_share_one_position_identity(monkeypatch):
    adapter = OkxAdapter(api_key="key", api_secret="secret", passphrase="pass")
    partial = {
        "cTime": "1785309134228",
        "uTime": "1785352091898",
        "instId": "KIOXIA-USDT-SWAP",
        "instType": "SWAP",
        "posId": "3785165892823834624",
        "direction": "long",
        "openAvgPx": "243.1677427184",
        "closeAvgPx": "259.6567961165",
        "openMaxPos": "4.12",
        "closeTotalPos": "1.03",
        "pnl": "16.983725",
        "fee": "-0.6346488",
        "fundingFee": "-2.3776671026",
        "realizedPnl": "13.9714090974",
        "pnlRatio": "0.13",
    }
    final = {
        **partial,
        "uTime": "1785374042629",
        "closeAvgPx": "258.6036407767",
        "closeTotalPos": "4.12",
        "pnl": "63.5959",
        "fee": "-1.03364905",
        "realizedPnl": "60.1845838474",
        "pnlRatio": "0.60073382",
    }

    async def fake_rows(inst_type, *_):
        return [final, partial] if inst_type == "SWAP" else []

    monkeypatch.setattr(adapter, "_position_history_rows", fake_rows)
    try:
        positions = await adapter.get_closed_positions(
            datetime(2026, 7, 29, tzinfo=UTC),
            datetime(2026, 7, 31, tzinfo=UTC),
        )
    finally:
        await adapter.close()

    assert len(positions) == 1
    assert positions[0]["source_record_id"] == "okx:SWAP:3785165892823834624"
    assert positions[0]["close_time"] == datetime(
        2026, 7, 30, 1, 14, 2, 629000, tzinfo=UTC
    )
    assert positions[0]["net_pnl"] == pytest.approx(60.1845838474)
