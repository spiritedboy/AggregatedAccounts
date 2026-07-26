from decimal import Decimal

import pytest

from app.services.normalizer import (
    SymbolNormalizer,
    normalize_margin_mode,
    normalize_side,
)
from app.services.pnl import PeriodPnl


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("BTCUSDT", "BTC-USDT-PERP"),
        ("BTC-USDT-SWAP", "BTC-USDT-PERP"),
        ("BTC/USDT:USDT", "BTC-USDT-PERP"),
        ("BTC", "BTC-USDT-PERP"),
        ("ETH_USDC", "ETH-USDC-PERP"),
    ],
)
def test_symbol_normalizer(raw, expected):
    assert SymbolNormalizer.normalize(raw) == expected


def test_exchange_field_normalization():
    assert normalize_side("sell") == "SHORT"
    assert normalize_side("", -1) == "SHORT"
    assert normalize_margin_mode("crossed") == "CROSS"
    assert normalize_margin_mode("fixed") == "ISOLATED"
    assert normalize_margin_mode(None) == "UNKNOWN"


def test_period_pnl_excludes_cash_flow_and_initial_unrealized():
    pnl = PeriodPnl(
        initial_equity=Decimal("10000"),
        current_equity=Decimal("11600"),
        deposit=Decimal("1000"),
        withdrawal=Decimal("200"),
        realized_pnl=Decimal("700"),
        current_unrealized_pnl=Decimal("450"),
        initial_unrealized_pnl=Decimal("300"),
        funding_fee=Decimal("-20"),
        trading_fee=Decimal("35"),
    )
    assert pnl.net_cash_flow == Decimal("800")
    assert pnl.investment_return == Decimal("800")
    assert pnl.trading_return == Decimal("645")
    assert pnl.unrealized_pnl_change == Decimal("150")
