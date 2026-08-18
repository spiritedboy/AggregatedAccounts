import pytest
from pydantic import ValidationError

from app.schemas import ExchangeAccountCreate


def test_hyperliquid_accepts_only_public_address():
    payload = ExchangeAccountCreate(
        exchange="HYPERLIQUID",
        connection_name="Public wallet",
        wallet_address="0x" + "a" * 40,
    )
    assert payload.wallet_address.endswith("a" * 40)
    assert payload.api_secret is None


def test_hyperliquid_rejects_secret_material():
    with pytest.raises(ValidationError):
        ExchangeAccountCreate(
            exchange="HYPERLIQUID",
            connection_name="Unsafe",
            wallet_address="0x" + "a" * 40,
            api_secret="this-must-not-be-accepted",
        )


def test_polymarket_accepts_only_public_profile_address():
    payload = ExchangeAccountCreate(
        exchange="POLYMARKET",
        connection_name="Prediction account",
        wallet_address="0x" + "b" * 40,
    )
    assert payload.wallet_address == "0x" + "b" * 40
    assert payload.api_key is None


def test_polymarket_rejects_api_credentials():
    with pytest.raises(ValidationError):
        ExchangeAccountCreate(
            exchange="POLYMARKET",
            connection_name="Unsafe prediction account",
            wallet_address="0x" + "b" * 40,
            api_key="must-not-be-saved",
        )


def test_okx_requires_passphrase():
    with pytest.raises(ValidationError):
        ExchangeAccountCreate(
            exchange="OKX",
            connection_name="Missing passphrase",
            api_key="abcdefgh",
            api_secret="abcdefgh",
        )


def test_bybit_requires_key_and_secret_without_passphrase():
    payload = ExchangeAccountCreate(
        exchange="BYBIT",
        connection_name="Bybit read only",
        api_key="abcdefgh",
        api_secret="abcdefgh",
    )
    assert payload.passphrase is None
