from decimal import Decimal

import pytest

from app.services.liquidation import (
    liquidation_distance_percent,
    liquidation_risk_level,
)

pytestmark = pytest.mark.no_db


@pytest.mark.parametrize(
    ("side", "mark", "liquidation", "expected"),
    [
        ("LONG", Decimal("100"), Decimal("70"), 30.0),
        ("SHORT", Decimal("100"), Decimal("130"), 30.0),
        ("LONG", Decimal("100"), Decimal("115"), -15.0),
        ("SHORT", Decimal("100"), Decimal("85"), -15.0),
    ],
)
def test_liquidation_distance_uses_side_aware_exchange_prices(
    side: str,
    mark: Decimal,
    liquidation: Decimal,
    expected: float,
):
    assert liquidation_distance_percent(
        side=side,
        mark_price=mark,
        liquidation_price=liquidation,
    ) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("mark", "liquidation"),
    [
        (Decimal("100"), None),
        (Decimal("0"), Decimal("70")),
        (Decimal("-1"), Decimal("70")),
        (Decimal("100"), Decimal("0")),
    ],
)
def test_liquidation_distance_degrades_without_reliable_prices(mark, liquidation):
    assert liquidation_distance_percent(
        side="LONG",
        mark_price=mark,
        liquidation_price=liquidation,
    ) is None


@pytest.mark.parametrize(
    ("distance", "expected"),
    [
        (14.999, "DANGER"),
        (15.0, "WATCH"),
        (29.999, "WATCH"),
        (30.0, "SAFE"),
        (None, None),
    ],
)
def test_liquidation_risk_boundaries(distance, expected):
    assert liquidation_risk_level(distance) == expected
