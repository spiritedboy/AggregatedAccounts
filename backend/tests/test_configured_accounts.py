import json

import pytest
from sqlalchemy import select

from app.database import SessionLocal
from app.models import EncryptedCredential, ExchangeAccount
from app.services.accounts import ADAPTERS
from app.services.configured_accounts import (
    load_account_definitions,
    provision_configured_accounts,
)


def test_default_config_contains_all_five_platforms():
    definitions = load_account_definitions("/app/config/exchange_accounts.json")
    assert {item["exchange"] for item in definitions} == {
        "BINANCE",
        "OKX",
        "BITGET",
        "HYPERLIQUID",
        "POLYMARKET",
    }
    assert all(item["enabled"] is False for item in definitions)


@pytest.mark.asyncio
async def test_config_provisions_public_address_account_once(tmp_path, monkeypatch):
    class FakePolymarketAdapter:
        def __init__(self, **kwargs):
            self.wallet_address = kwargs["wallet_address"]

        async def test_connection(self):
            return True

        async def get_permissions(self):
            return {
                "read": True,
                "spot_trade": False,
                "futures_trade": False,
                "transfer": False,
                "withdraw": False,
                "public_address_only": True,
            }

        async def get_account_summary(self):
            return {
                "total_equity_usd": 52,
                "available_balance_usd": 14.5,
                "margin_balance_usd": 37.5,
                "unrealized_pnl_usd": 20,
            }

        async def get_open_positions(self):
            return []

        async def close(self):
            return None

    config_path = tmp_path / "accounts.json"
    config_path.write_text(
        json.dumps(
            {
                "accounts": [
                    {
                        "exchange": "POLYMARKET",
                        "connection_name": "Configured prediction account",
                        "enabled": True,
                        "wallet_address_env": "TEST_POLYMARKET_ADDRESS",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("TEST_POLYMARKET_ADDRESS", "0x" + "d" * 40)
    monkeypatch.setitem(ADAPTERS, "POLYMARKET", FakePolymarketAdapter)

    async with SessionLocal() as db:
        first = await provision_configured_accounts(db, str(config_path))
        monkeypatch.delenv("TEST_POLYMARKET_ADDRESS")
        second = await provision_configured_accounts(db, str(config_path))
        account = await db.scalar(
            select(ExchangeAccount).where(
                ExchangeAccount.connection_name == "Configured prediction account"
            )
        )
        credential = await db.scalar(
            select(EncryptedCredential).where(
                EncryptedCredential.exchange_account_id == account.id
            )
        )

    assert first["created"] == 1
    assert second["existing"] == 1
    assert account.public_identifier == "0x" + "d" * 40
    assert credential is None
