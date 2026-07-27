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
async def test_binance_summary_and_asset_details_include_spot(monkeypatch):
    adapter = BinanceAdapter(api_key="key", api_secret="secret")

    async def fake_signed_get(_base, path, _params=None):
        if path == "/fapi/v3/account":
            return {
                "totalWalletBalance": "100",
                "totalUnrealizedProfit": "5",
                "availableBalance": "80",
                "totalInitialMargin": "20",
                "assets": [
                    {
                        "asset": "USDT",
                        "walletBalance": "100",
                        "unrealizedProfit": "5",
                        "availableBalance": "80",
                        "marginBalance": "105",
                    }
                ],
            }
        return {
            "balances": [
                {"asset": "USDT", "free": "10", "locked": "0"},
                {"asset": "BTC", "free": "0.1", "locked": "0"},
            ]
        }

    async def fake_request(*_args, **_kwargs):
        return [{"symbol": "BTCUSDT", "price": "50"}]

    monkeypatch.setattr(adapter, "_signed_get", fake_signed_get)
    monkeypatch.setattr(adapter, "_request", fake_request)
    try:
        summary = await adapter.get_account_summary()
        balances = await adapter.get_balances()
    finally:
        await adapter.close()

    assert summary["total_equity_usd"] == 120
    assert summary["available_balance_usd"] == 95
    assert {(row["asset"], row["account_type"]) for row in balances} == {
        ("USDT", "SPOT"),
        ("BTC", "SPOT"),
        ("USDT", "USD_M_FUTURES"),
    }


@pytest.mark.asyncio
async def test_binance_positions_use_v2_leverage_and_margin_type(monkeypatch):
    adapter = BinanceAdapter(api_key="key", api_secret="secret")

    async def fake_signed_get(_base, path, _params=None):
        assert path == "/fapi/v2/positionRisk"
        return [
            {
                "symbol": "GOOGLUSDT",
                "positionSide": "LONG",
                "positionAmt": "5.62",
                "entryPrice": "325.38",
                "markPrice": "325.38",
                "liquidationPrice": "0",
                "leverage": "20",
                "marginType": "cross",
                "isolatedMargin": "0",
                "unRealizedProfit": "-170.34",
            }
        ]

    monkeypatch.setattr(adapter, "_signed_get", fake_signed_get)
    try:
        positions = await adapter.get_open_positions()
    finally:
        await adapter.close()

    assert len(positions) == 1
    assert positions[0]["normalized_symbol"] == "GOOGL-USDT-PERP"
    assert positions[0]["leverage"] == 20
    assert positions[0]["margin_mode"] == "CROSS"


@pytest.mark.asyncio
async def test_bitget_summary_and_positions_cover_spot_usdt_and_usdc(monkeypatch):
    adapter = BitgetAdapter(api_key="key", api_secret="secret", passphrase="pass")

    async def fake_get(path, params=None):
        product_type = (params or {}).get("productType")
        if path.endswith("/account/accounts"):
            if product_type == "USDT-FUTURES":
                return [
                    {
                        "marginCoin": "USDT",
                        "usdtEquity": "100",
                        "accountEquity": "100",
                        "available": "80",
                        "crossedMargin": "20",
                        "unrealizedPL": "2",
                    }
                ]
            return [
                {
                    "marginCoin": "USDC",
                    "usdtEquity": "20",
                    "accountEquity": "20",
                    "available": "15",
                    "crossedMargin": "5",
                    "unrealizedPL": "1",
                }
            ]
        if path.endswith("/account/assets"):
            return [
                {"coin": "USDT", "available": "10", "frozen": "0", "locked": "0"},
                {"coin": "DOGE", "available": "2", "frozen": "0", "locked": "0"},
            ]
        if path.endswith("/market/tickers"):
            return [{"symbol": "DOGEUSDT", "lastPr": "0.05"}]
        if path.endswith("/position/all-position"):
            quote = "USDT" if product_type == "USDT-FUTURES" else "USDC"
            return [
                {
                    "symbol": f"BTC{quote}",
                    "holdSide": "long",
                    "total": "1",
                    "markPrice": "100",
                    "openPriceAvg": "90",
                    "marginSize": "20",
                    "unrealizedPL": "10",
                }
            ]
        raise AssertionError(path)

    monkeypatch.setattr(adapter, "_get", fake_get)
    try:
        summary = await adapter.get_account_summary()
        balances = await adapter.get_balances()
        positions = await adapter.get_open_positions()
    finally:
        await adapter.close()

    assert summary["total_equity_usd"] == 130.1
    assert summary["legacy_excluded_equity_usd"] == 30.1
    assert {row["account_type"] for row in balances} == {
        "SPOT",
        "USDT_FUTURES",
        "USDC_FUTURES",
    }
    assert {row["normalized_symbol"] for row in positions} == {
        "BTC-USDT-PERP",
        "BTC-USDC-PERP",
    }


@pytest.mark.asyncio
async def test_hyperliquid_summary_includes_perp_and_spot_usdc(monkeypatch):
    adapter = HyperliquidAdapter(wallet_address="0x" + "a" * 40)

    async def fake_info(request_type, **_):
        if request_type == "userAbstraction":
            return "disabled"
        return {
            "balances": [
                {
                    "coin": "USDC",
                    "token": 0,
                    "total": "200.662483",
                    "hold": "0.5",
                }
            ]
        }

    monkeypatch.setattr(adapter, "_info", fake_info)
    monkeypatch.setattr(
        adapter,
        "_perp_states",
        AsyncMock(
            return_value=[
                (
                    "",
                    {
                        "marginSummary": {
                            "accountValue": "50",
                            "totalMarginUsed": "10",
                        },
                        "withdrawable": "40",
                        "assetPositions": [
                            {"position": {"unrealizedPnl": "2"}}
                        ],
                    },
                )
            ]
        ),
    )
    try:
        summary = await adapter.get_account_summary()
    finally:
        await adapter.close()

    assert summary == {
        "total_equity_usd": 250.662483,
        "available_balance_usd": 240.162483,
        "margin_balance_usd": 10,
        "unrealized_pnl_usd": 2,
        "unvalued_asset_count": 0,
        "price_source": "HYPERLIQUID_PERP_AND_SPOT",
    }


@pytest.mark.asyncio
async def test_hyperliquid_summary_values_non_usdc_spot_assets(monkeypatch):
    adapter = HyperliquidAdapter(wallet_address="0x" + "a" * 40)

    async def fake_info(request_type, **_):
        if request_type == "userAbstraction":
            return "disabled"
        return {
            "balances": [
                {"coin": "HYPE", "token": 150, "total": "2", "hold": "0.25"},
                {"coin": "UNKNOWN", "token": 999, "total": "3", "hold": "0"},
            ]
        }

    market_data = [
        {"universe": [{"tokens": [150, 0], "name": "HYPE/USDC"}]},
        [{"markPx": "25"}],
    ]
    monkeypatch.setattr(adapter, "_info", fake_info)
    monkeypatch.setattr(adapter, "_perp_states", AsyncMock(return_value=[]))
    monkeypatch.setattr(adapter, "_spot_market_data", AsyncMock(return_value=market_data))
    try:
        summary = await adapter.get_account_summary()
    finally:
        await adapter.close()

    assert summary["total_equity_usd"] == 50
    assert summary["available_balance_usd"] == 43.75
    assert summary["unvalued_asset_count"] == 1


@pytest.mark.asyncio
async def test_hyperliquid_unified_summary_does_not_double_count_hip3(monkeypatch):
    adapter = HyperliquidAdapter(wallet_address="0x" + "a" * 40)

    async def fake_info(request_type, **_):
        if request_type == "userAbstraction":
            return "unifiedAccount"
        return {
            "balances": [
                {
                    "coin": "USDC",
                    "token": 0,
                    "total": "197.789317",
                    "hold": "63.200324",
                }
            ]
        }

    monkeypatch.setattr(adapter, "_info", fake_info)
    monkeypatch.setattr(
        adapter,
        "_perp_states",
        AsyncMock(
            return_value=[
                (
                    "xyz",
                    {
                        "marginSummary": {
                            "accountValue": "63.265874",
                            "totalMarginUsed": "63.265874",
                        },
                        "withdrawable": "0",
                        "assetPositions": [
                            {
                                "position": {
                                    "coin": "xyz:CXMT",
                                    "unrealizedPnl": "-15.80895",
                                }
                            }
                        ],
                    },
                )
            ]
        ),
    )
    try:
        summary = await adapter.get_account_summary()
    finally:
        await adapter.close()

    assert summary["total_equity_usd"] == 197.789317
    assert summary["available_balance_usd"] == pytest.approx(134.588993)
    assert summary["margin_balance_usd"] == 63.265874
    assert summary["unrealized_pnl_usd"] == -15.80895
    assert summary["price_source"] == "HYPERLIQUID_UNIFIED"


@pytest.mark.asyncio
async def test_hyperliquid_open_positions_include_hip3_dex(monkeypatch):
    adapter = HyperliquidAdapter(wallet_address="0x" + "a" * 40)
    monkeypatch.setattr(
        adapter,
        "_perp_states",
        AsyncMock(
            return_value=[
                ("", {"assetPositions": []}),
                (
                    "xyz",
                    {
                        "assetPositions": [
                            {
                                "position": {
                                    "coin": "xyz:CXMT",
                                    "szi": "-28.5",
                                    "positionValue": "215.30895",
                                    "entryPx": "7.0",
                                    "liquidationPx": "9.3091002172",
                                    "leverage": {
                                        "type": "isolated",
                                        "value": 5,
                                    },
                                    "marginUsed": "63.265874",
                                    "unrealizedPnl": "-15.80895",
                                }
                            }
                        ]
                    },
                ),
            ]
        ),
    )
    try:
        positions = await adapter.get_open_positions()
    finally:
        await adapter.close()

    assert len(positions) == 1
    assert positions[0]["symbol"] == "xyz:CXMT"
    assert positions[0]["normalized_symbol"] == "CXMT-USDT-PERP"
    assert positions[0]["side"] == "SHORT"
    assert positions[0]["position_size"] == 28.5


@pytest.mark.asyncio
async def test_hyperliquid_discovers_default_and_builder_perp_dexs(monkeypatch):
    adapter = HyperliquidAdapter(wallet_address="0x" + "a" * 40)
    monkeypatch.setattr(
        adapter,
        "_request",
        AsyncMock(return_value=[None, {"name": "xyz"}, {"name": "flx"}]),
    )

    async def fake_info(request_type, **kwargs):
        assert request_type == "clearinghouseState"
        return {"dex": kwargs["dex"], "assetPositions": []}

    monkeypatch.setattr(adapter, "_info", fake_info)
    try:
        states = await adapter._perp_states()
    finally:
        await adapter.close()

    assert [dex for dex, _state in states] == ["", "xyz", "flx"]


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
                {
                    "billId": "4",
                    "ccy": "USDC",
                    "pnl": "0",
                    "fee": "0",
                    "balChg": "200.7",
                    "subType": "318",
                    "instId": "",
                    "ts": str(TIME_MS),
                    "from": "",
                    "to": "",
                },
                {
                    "billId": "5",
                    "ccy": "USDT",
                    "pnl": "0",
                    "fee": "0",
                    "balChg": "-201",
                    "subType": "319",
                    "instId": "",
                    "ts": str(TIME_MS),
                    "from": "",
                    "to": "",
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
    assert bundle["complete"] is True


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
    wallet = "0x" + "a" * 40
    adapter = HyperliquidAdapter(wallet_address=wallet)

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
            },
            {
                "hash": "0xsend-in",
                "time": TIME_MS,
                "delta": {
                    "type": "send",
                    "user": "0x" + "b" * 40,
                    "destination": wallet,
                    "token": "USDC",
                    "amount": "200.3",
                    "usdcValue": "200.3",
                },
            },
            {
                "hash": "0xsend-out",
                "time": TIME_MS,
                "delta": {
                    "type": "send",
                    "user": wallet,
                    "destination": "0x" + "c" * 40,
                    "token": "USDC",
                    "amount": "12",
                    "usdcValue": "12",
                },
            },
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
    assert [
        (row["amount_usd"], row["flow_type"]) for row in bundle["cash_flows"]
    ] == [
        (15, "DEPOSIT"),
        (200.3, "DEPOSIT"),
        (12, "WITHDRAWAL"),
    ]
