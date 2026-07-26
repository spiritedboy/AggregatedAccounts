import re


class SymbolNormalizer:
    STABLE_QUOTES = ("USDT", "USDC", "USD", "BUSD")

    @classmethod
    def normalize(cls, symbol: str, quote_hint: str | None = None) -> str:
        cleaned = symbol.upper().strip()
        cleaned = cleaned.replace("-SWAP", "")
        cleaned = cleaned.split(":")[0]
        parts = [part for part in re.split(r"[-/_]", cleaned) if part]
        if len(parts) >= 2:
            base, quote = parts[0], parts[1]
        else:
            quote = quote_hint.upper() if quote_hint else ""
            if not quote:
                quote = next((q for q in cls.STABLE_QUOTES if cleaned.endswith(q)), "USDT")
            base = (
                cleaned[: -len(quote)] if cleaned.endswith(quote) and cleaned != quote else cleaned
            )
        return f"{base}-{quote}-PERP"


def normalize_side(value: str, amount: float | None = None) -> str:
    lowered = value.lower()
    if lowered in {"long", "buy"}:
        return "LONG"
    if lowered in {"short", "sell"}:
        return "SHORT"
    return "SHORT" if amount is not None and amount < 0 else "LONG"


def normalize_margin_mode(value: str | None) -> str:
    lowered = (value or "").lower()
    if lowered in {"cross", "crossed", "cross_margin"}:
        return "CROSS"
    if lowered in {"isolated", "fixed"}:
        return "ISOLATED"
    return "UNKNOWN"
