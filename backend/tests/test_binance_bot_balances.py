from unittest.mock import AsyncMock

import pytest

from app.adapters.base import AdapterError
from app.adapters.binance import BinanceAdapter

pytestmark = [pytest.mark.no_db, pytest.mark.exchange]


async def summary_for(monkeypatch, *, futures_equity, bot_equity):
    adapter = BinanceAdapter(api_key="key", api_secret="secret")
    calls = []

    async def signed_get(_base, path, params=None):
        calls.append(path)
        if path == "/fapi/v3/account":
            return {
                "totalWalletBalance": str(futures_equity),
                "totalUnrealizedProfit": "5",
                "availableBalance": "80",
                "totalInitialMargin": "20",
                "assets": [{
                    "asset": "USDT", "walletBalance": str(futures_equity),
                    "unrealizedProfit": "5", "availableBalance": "80",
                    "marginBalance": str(futures_equity + 5),
                }],
            }
        if path == "/api/v3/account":
            return {"balances": [{"asset": "USDT", "free": "10", "locked": "0"}]}
        assert path == "/sapi/v1/asset/wallet/balance"
        assert params == {"quoteAsset": "USDT", "needBalanceDetail": "true"}
        return [
            {"walletName": "Spot", "balance": "10"},
            {"walletName": "USDⓈ-M Futures", "balance": str(futures_equity + 5)},
            {"walletName": "Trading Bots", "balance": str(bot_equity), "assetBalances": [
                {"asset": "USDT", "free": str(bot_equity), "locked": "0",
                 "btcValuation": str(bot_equity)},
            ]},
        ]

    monkeypatch.setattr(adapter, "_signed_get", signed_get)
    monkeypatch.setattr(adapter, "_request", AsyncMock(return_value=[]))
    try:
        summary = await adapter.get_account_summary()
        balances = await adapter.get_balances()
        assert calls.count("/sapi/v1/asset/wallet/balance") == 1
        return summary, balances
    finally:
        await adapter.close()


@pytest.mark.asyncio
async def test_internal_grid_transfer_preserves_equity_and_excludes_bot_cash(monkeypatch):
    before, _ = await summary_for(monkeypatch, futures_equity=1000, bot_equity=0)
    after, balances = await summary_for(monkeypatch, futures_equity=500, bot_equity=500)

    assert before["total_equity_usd"] == after["total_equity_usd"] == 1015
    assert after["available_balance_usd"] == 90
    assert after["margin_balance_usd"] == 20
    assert after["unrealized_pnl_usd"] == 5
    assert after["legacy_excluded_equity_usd"] == 10
    bots = [row for row in balances if row["account_type"] == "TRADING_BOTS"]
    assert len(bots) == 1
    assert bots[0]["available"] == 0
    assert bots[0]["locked"] == 500
    assert bots[0]["value_usd"] == 500


@pytest.mark.asyncio
async def test_grid_uses_live_equity_instead_of_initial_investment(monkeypatch):
    summary, _ = await summary_for(monkeypatch, futures_equity=500, bot_equity=479.30882268)
    assert summary["total_equity_usd"] == pytest.approx(994.30882268)


def test_bot_multi_asset_valuation_follows_requested_quote():
    balances = BinanceAdapter._bot_balances([{
        "walletName": "Trading Bots", "balance": "507.5", "assetBalances": [
            {"asset": "USDT", "free": "200", "locked": "5", "freeze": "2",
             "withdrawing": "0.5", "btcValuation": "207.5"},
            {"asset": "BTC", "free": "0.005", "btcValuation": "300"},
        ],
    }])
    assert sum(row["value_usd"] for row in balances) == 507.5
    assert balances[0]["locked"] == 207.5
    assert balances[1]["locked"] == 0.005
    assert balances[1]["price_usd"] == 60000
    assert all(row["available"] == 0 for row in balances)


@pytest.mark.parametrize("wallets", [
    [],
    [{"walletName": "Trading Bots", "activate": False, "balance": "0"}],
    [{"walletName": "Trading Bots", "balance": "0", "assetBalances": []}],
])
def test_no_bot_funds_adds_no_balances(wallets):
    assert BinanceAdapter._bot_balances(wallets) == []


@pytest.mark.parametrize("wallets", [
    {"code": -2015},
    [{"walletName": "Trading Bots", "balance": "500"}],
    [{"walletName": "Trading Bots", "balance": "500", "assetBalances": []}],
    [{"walletName": "Trading Bots", "balance": "500", "assetBalances": [
        {"asset": "USDT", "free": "500"},
    ]}],
    [{"walletName": "Trading Bots", "balance": "500", "assetBalances": [
        {"asset": "USDT", "free": "400", "btcValuation": "400"},
    ]}],
])
def test_incomplete_bot_valuation_fails_instead_of_publishing_lower_equity(wallets):
    with pytest.raises(AdapterError):
        BinanceAdapter._bot_balances(wallets)


@pytest.mark.asyncio
async def test_wallet_request_failure_is_not_treated_as_zero(monkeypatch):
    adapter = BinanceAdapter(api_key="key", api_secret="secret")

    async def signed_get(_base, path, _params=None):
        if path == "/sapi/v1/asset/wallet/balance":
            raise AdapterError("wallet unavailable")
        return {}

    monkeypatch.setattr(adapter, "_signed_get", signed_get)
    monkeypatch.setattr(adapter, "_request", AsyncMock(return_value=[]))
    try:
        with pytest.raises(AdapterError, match="wallet unavailable"):
            await adapter.get_account_summary()
        assert not hasattr(adapter, "_latest_balances")
    finally:
        await adapter.close()
