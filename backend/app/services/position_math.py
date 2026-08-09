from decimal import Decimal


def position_margin_used(
    *,
    position_value_usd: Decimal,
    entry_price: Decimal,
    mark_price: Decimal,
    position_size: Decimal,
    leverage: Decimal,
    reported_margin: Decimal,
) -> Decimal:
    """Return one cross-exchange margin basis without assuming contract size is one."""
    if leverage <= 0:
        return abs(reported_margin)
    if position_value_usd and entry_price > 0 and mark_price > 0:
        entry_notional = abs(position_value_usd) * entry_price / mark_price
    else:
        entry_notional = abs(entry_price * position_size)
    return entry_notional / leverage
