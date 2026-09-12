from decimal import Decimal
from typing import Literal

LIQUIDATION_DANGER_THRESHOLD_PERCENT = 15.0
LIQUIDATION_SAFE_THRESHOLD_PERCENT = 30.0

LiquidationRiskLevel = Literal["SAFE", "WATCH", "DANGER"]


def liquidation_distance_percent(
    *,
    side: str,
    mark_price: Decimal | float | int | None,
    liquidation_price: Decimal | float | int | None,
) -> float | None:
    """Return the exchange-reported liquidation distance without estimating prices.

    A negative value is intentionally preserved. It indicates that the reported
    liquidation price is already on the unexpected side of the mark price and
    must be surfaced as dangerous rather than hidden or clamped.
    """
    if liquidation_price is None:
        return None
    mark = float(mark_price or 0)
    liquidation = float(liquidation_price)
    if mark <= 0 or liquidation <= 0:
        return None
    normalized_side = side.upper()
    if normalized_side == "LONG":
        return (mark - liquidation) / mark * 100
    if normalized_side == "SHORT":
        return (liquidation - mark) / mark * 100
    return None


def liquidation_risk_level(
    distance_percent: float | None,
) -> LiquidationRiskLevel | None:
    if distance_percent is None:
        return None
    if distance_percent < LIQUIDATION_DANGER_THRESHOLD_PERCENT:
        return "DANGER"
    if distance_percent < LIQUIDATION_SAFE_THRESHOLD_PERCENT:
        return "WATCH"
    return "SAFE"
