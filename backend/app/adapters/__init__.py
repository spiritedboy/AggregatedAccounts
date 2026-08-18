from app.adapters.binance import BinanceAdapter
from app.adapters.bitget import BitgetAdapter
from app.adapters.bybit import BybitAdapter
from app.adapters.hyperliquid import HyperliquidAdapter
from app.adapters.okx import OkxAdapter
from app.adapters.polymarket import PolymarketAdapter

ADAPTERS = {
    "BINANCE": BinanceAdapter,
    "OKX": OkxAdapter,
    "BITGET": BitgetAdapter,
    "BYBIT": BybitAdapter,
    "HYPERLIQUID": HyperliquidAdapter,
    "POLYMARKET": PolymarketAdapter,
}

__all__ = [
    "ADAPTERS",
    "BinanceAdapter",
    "BitgetAdapter",
    "BybitAdapter",
    "HyperliquidAdapter",
    "OkxAdapter",
    "PolymarketAdapter",
]
