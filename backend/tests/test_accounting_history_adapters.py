from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.adapters.binance import BinanceAdapter
from app.adapters.bitget import BitgetAdapter
from app.adapters.hyperliquid import HyperliquidAdapter
from app.adapters.okx import OkxAdapter

START = datetime(2026, 7, 26, 12, 0, tzinfo=UTC)
END = datetime(2026, 7, 26, 13, 0, tzinfo=UTC)
TIME_MS = int((START.timestamp() + 60) * 1000)


@pytest.mark.asyncio
async def test_binance_history_bundle_classifies_accounting_streams(monkeypatch):
    adapter = BinanceAdapter(api_key="key", api_secret="secret")
    monkeypatch.setattr(
        adapter,
        "_income_rows",
        AsyncMock(
            return_value=[
                {
                    "tranId": 1,
                    "asset": "USDT",
                    "income": "5",
                    "incomeType": "REALIZED_PNL",
                    "symbol": "BTCUSDT",
                    "time": TIME_MS,
                },
                {
                    "tranId": 2,
                    "asset": "USDT",
                    "income": "-1.2",
                    "incomeType": "FUNDING_FEE",
                    "symbol": "BTCUSDT",
                    "time": TIME_MS,
                },
                {
                    "tranId": 3,
                    "asset": "USDT",
                    "income": "-0.4",
                    "incomeType": "COMMISSION",
                    "symbol": "BTCUSDT",
                    "time": TIME_MS,
                },
                {
                    "tranId": 4,
                    "asset": "USDT",
                    "income": "20",
                    "incomeType": "TRANSFER",
                    "symbol": "",
                    "time": TIME_MS,
                },
            ]
        ),
    )
    try:
        bundle = await adapter.get_history_bundle(START, END)
    finally:
        await adapter.close()
    assert bundle["income"][0]["amount_usd"] == 5
    assert bundle["funding"][0]["amount_usd"] == -1.2
    assert bundle["fees"][0]["amount_usd"] == 0.4
    assert bundle["cash_flows"][0]["flow_type"] == "DEPOSIT"


@pytest.mark.asyncio
async def test_okx_history_bundle_uses_pnl_fee_funding_and_transfer_fields(monkeypatch):
    adapter = OkxAdapter(api_key="key", api_secret="secret", passphrase="pass")
    monkeypatch.setattr(
        adapter,
        "_bill_rows",
        AsyncMock(
            return_value=[
                {
                    "billId": "1",
                    "ccy": "USDT",
                    "pnl": "3.5",
                    "fee": "-0.2",
                    "balChg": "3.3",
                    "subType": "5",
                    "instId": "BTC-USDT-SWAP",
                    "ts": str(TIME_MS),
                    "from": "",
                    "to": "",
                },
                {
                    "billId": "2",
                    "ccy": "USDT",
                    "pnl": "-0.8",
                    "fee": "0",
                    "balChg": "-0.8",
                    "subType": "173",
                    "instId": "BTC-USDT-SWAP",
                    "ts": str(TIME_MS),
                    "from": "",
                    "to": "",
                },
                {
                    "billId": "3",
                    "ccy": "USDT",
                    "pnl": "0",
                    "fee": "0",
                    "balChg": "10",
                    "subType": "",
                    "instId": "",
                    "ts": str(TIME_MS),
                    "from": "6",
                    "to": "18",
                },
            ]
        ),
    )
    try:
        bundle = await adapter.get_history_bundle(START, END)
    finally:
        await adapter.close()
    assert [row["amount_usd"] for row in bundle["income"]] == [3.5]
    assert [row["amount_usd"] for row in bundle["funding"]] == [-0.8]
    assert [row["amount_usd"] for row in bundle["fees"]] == [0.2]
    assert bundle["cash_flows"][0]["flow_type"] == "DEPOSIT"


@pytest.mark.asyncio
async def test_bitget_history_bundle_classifies_contract_bills(monkeypatch):
    adapter = BitgetAdapter(api_key="key", api_secret="secret", passphrase="pass")
    monkeypatch.setattr(
        adapter,
        "_bill_rows",
        AsyncMock(
            return_value=[
                {
                    "billId": "1",
                    "coin": "USDT",
                    "amount": "4",
                    "fee": "-0.1",
                    "businessType": "close_long",
                    "symbol": "BTCUSDT",
                    "cTime": str(TIME_MS),
                },
                {
                    "billId": "2",
                    "coin": "USDT",
                    "amount": "-0.5",
                    "fee": "0",
                    "businessType": "contract_settle_fee",
                    "symbol": "BTCUSDT",
                    "cTime": str(TIME_MS),
                },
                {
                    "billId": "3",
                    "coin": "USDT",
                    "amount": "-12",
                    "fee": "0",
                    "businessType": "trans_to_exchange",
                    "symbol": "",
                    "cTime": str(TIME_MS),
                },
            ]
        ),
    )
    try:
        bundle = await adapter.get_history_bundle(START, END)
    finally:
        await adapter.close()
    assert bundle["income"][0]["amount_usd"] == 4
    assert bundle["funding"][0]["amount_usd"] == -0.5
    assert bundle["fees"][0]["amount_usd"] == 0.1
    assert bundle["cash_flows"][0]["flow_type"] == "WITHDRAWAL"


@pytest.mark.asyncio
async def test_hyperliquid_history_bundle_normalizes_public_ledger(monkeypatch):
    adapter = HyperliquidAdapter(wallet_address="0x" + "a" * 40)

    async def fake_info(request_type, **_):
        if request_type == "userFillsByTime":
            return [
                {
                    "tid": 7,
                    "time": TIME_MS,
                    "coin": "BTC",
                    "closedPnl": "2.5",
                    "fee": "0.05",
                    "feeToken": "USDC",
                }
            ]
        if request_type == "userFunding":
            return [
                {
                    "hash": "0xfunding",
                    "time": TIME_MS,
                    "delta": {"coin": "BTC", "usdc": "-0.25"},
                }
            ]
        return [
            {
                "hash": "0xdeposit",
                "time": TIME_MS,
                "delta": {"type": "deposit", "usdc": "15"},
            }
        ]

    monkeypatch.setattr(adapter, "_info", fake_info)
    try:
        bundle = await adapter.get_history_bundle(START, END)
    finally:
        await adapter.close()
    assert bundle["income"][0]["amount_usd"] == 2.5
    assert bundle["funding"][0]["amount_usd"] == -0.25
    assert bundle["fees"][0]["amount_usd"] == 0.05
    assert bundle["cash_flows"][0]["amount_usd"] == 15
