import hashlib
import hmac
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import pytest

from app.adapters.bybit import BybitAdapter

pytestmark = [pytest.mark.no_db, pytest.mark.exchange]

START = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)
END = START + timedelta(hours=1)


def test_bybit_v5_signature(monkeypatch):
    adapter = BybitAdapter(api_key="public", api_secret="secret")
    monkeypatch.setattr("app.adapters.bybit.time.time", lambda: 1_700_000_000.123)
    query = urlencode({"accountType": "UNIFIED", "coin": "USDT"})
    headers = adapter._headers(query)
    message = f"1700000000123public5000{query}"
    expected = hmac.new(b"secret", message.encode(), hashlib.sha256).hexdigest()
    assert headers["X-BAPI-SIGN"] == expected
    assert headers["X-BAPI-TIMESTAMP"] == "1700000000123"


@pytest.mark.asyncio
async def test_bybit_permissions_require_read_only_key(monkeypatch):
    adapter = BybitAdapter(api_key="public", api_secret="secret")

    async def fake_get(path, params=None):
        assert path == "/v5/user/query-api"
        return {
            "readOnly": 1,
            "permissions": {
                "Spot": ["SpotTrade"],
                "ContractTrade": ["Order", "Position"],
                "Wallet": ["Withdraw"],
            },
        }

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
async def test_bybit_summary_balances_and_positions(monkeypatch):
    adapter = BybitAdapter(api_key="public", api_secret="secret")

    async def fake_get(path, params=None):
        if path == "/v5/account/wallet-balance":
            return {
                "list": [
                    {
                        "totalEquity": "125",
                        "totalAvailableBalance": "80",
                        "totalInitialMargin": "20",
                        "totalPerpUPL": "5",
                        "coin": [
                            {
                                "coin": "USDT",
                                "walletBalance": "120",
                                "locked": "2",
                                "totalOrderIM": "3",
                                "totalPositionIM": "20",
                                "usdValue": "125",
                            }
                        ],
                    }
                ]
            }
        if path == "/v5/account/info":
            return {"marginMode": "REGULAR_MARGIN"}
        raise AssertionError(path)

    async def fake_paged(path, params, **_kwargs):
        if path != "/v5/position/list" or params.get("settleCoin") != "USDT":
            return []
        return [
            {
                "symbol": "BTCUSDT",
                "positionIdx": 0,
                "side": "Buy",
                "size": "0.1",
                "positionValue": "7000",
                "avgPrice": "69000",
                "markPrice": "70000",
                "liqPrice": "62000",
                "leverage": "10",
                "positionIM": "700",
                "unrealisedPnl": "100",
                "createdTime": "1785542400000",
            }
        ]

    monkeypatch.setattr(adapter, "_get", fake_get)
    monkeypatch.setattr(adapter, "_paged", fake_paged)
    try:
        summary = await adapter.get_account_summary()
        balances = await adapter.get_balances()
        positions = await adapter.get_open_positions()
    finally:
        await adapter.close()

    assert summary["total_equity_usd"] == 125
    assert balances[0]["available"] == 95
    assert positions[0]["normalized_symbol"] == "BTC-USDT-PERP"
    assert positions[0]["side"] == "LONG"
    assert positions[0]["margin_used"] == 700
    assert positions[0]["unrealized_pnl"] == 100


@pytest.mark.asyncio
async def test_bybit_closed_pnl_and_transaction_log_are_normalized(monkeypatch):
    adapter = BybitAdapter(api_key="public", api_secret="secret")

    async def fake_paged(path, params, **_kwargs):
        if path == "/v5/position/closed-pnl":
            if params["category"] == "inverse":
                return []
            return [
                {
                    "symbol": "ETHUSDT",
                    "orderId": "close-1",
                    # Sell is the closing order, so the position itself was long.
                    "side": "Sell",
                    "closedSize": "2",
                    "avgEntryPrice": "100",
                    "avgExitPrice": "110",
                    "closedPnl": "18.5",
                    "openFee": "0.5",
                    "closeFee": "0.5",
                    "leverage": "5",
                    "cumEntryValue": "200",
                    "createdTime": str(int(START.timestamp() * 1000)),
                    "updatedTime": str(int(END.timestamp() * 1000)),
                }
            ]
        if path == "/v5/account/transaction-log":
            return [
                {
                    "id": "trade-1",
                    "transactionTime": str(int(END.timestamp() * 1000)),
                    "type": "TRADE",
                    "currency": "USDT",
                    "symbol": "ETHUSDT",
                    "cashFlow": "20",
                    "funding": "-0.5",
                    "fee": "1",
                },
                {
                    "id": "transfer-1",
                    "transactionTime": str(int(END.timestamp() * 1000)),
                    "type": "TRANSFER_IN",
                    "currency": "USDT",
                    "cashFlow": "50",
                    "funding": "0",
                    "fee": "0",
                },
            ]
        raise AssertionError(path)

    monkeypatch.setattr(adapter, "_paged", fake_paged)
    try:
        closed = await adapter.get_closed_positions(START, END)
        history = await adapter.get_history_bundle(START, END)
    finally:
        await adapter.close()

    assert len(closed) == 1
    assert closed[0]["source_record_id"] == "bybit:linear:close-1"
    assert closed[0]["side"] == "LONG"
    assert closed[0]["realized_pnl"] == pytest.approx(20)
    assert closed[0]["funding_fee"] == pytest.approx(-0.5)
    assert closed[0]["trading_fee"] == pytest.approx(1)
    assert closed[0]["net_pnl"] == pytest.approx(18.5)
    assert closed[0]["return_percent"] == pytest.approx(46.25)
    assert history["income"][0]["amount_usd"] == 20
    assert history["funding"][0]["amount_usd"] == -0.5
    assert history["fees"][0]["amount_usd"] == 1
    assert history["cash_flows"][0]["flow_type"] == "DEPOSIT"
    assert history["cash_flows"][0]["amount_usd"] == 50


def test_bybit_history_windows_never_exceed_seven_days():
    windows = list(BybitAdapter._windows(START, START + timedelta(days=15)))
    assert len(windows) == 3
    assert all(end - start < timedelta(days=7) for start, end in windows)
