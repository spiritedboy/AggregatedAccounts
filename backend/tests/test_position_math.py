from decimal import Decimal

import pytest

from app.services.position_math import position_margin_used

pytestmark = pytest.mark.no_db


@pytest.mark.parametrize("exchange", ["BINANCE", "OKX", "BITGET", "HYPERLIQUID"])
def test_leveraged_margin_uses_usd_notional_for_every_exchange(exchange):
    del exchange  # The formula deliberately has no exchange-specific branch.
    margin = position_margin_used(
        position_value_usd=Decimal("982.00756496"),
        entry_price=Decimal("55.157"),
        mark_price=Decimal("54.312"),
        position_size=Decimal("181"),
        leverage=Decimal("20"),
        reported_margin=Decimal("0"),
    )
    expected = Decimal("982.00756496") * Decimal("55.157") / Decimal("54.312") / 20
    assert margin == pytest.approx(expected)


def test_unleveraged_position_keeps_exchange_reported_margin():
    margin = position_margin_used(
        position_value_usd=Decimal("100"),
        entry_price=Decimal("0.4"),
        mark_price=Decimal("0.5"),
        position_size=Decimal("200"),
        leverage=Decimal("0"),
        reported_margin=Decimal("80"),
    )
    assert margin == Decimal("80")
