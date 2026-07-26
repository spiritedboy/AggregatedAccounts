from app.adapters.binance import BinanceAdapter
from app.adapters.bitget import BitgetAdapter
from app.adapters.hyperliquid import HyperliquidAdapter
from app.adapters.okx import OkxAdapter

ADAPTERS = {
    "BINANCE": BinanceAdapter,
    "OKX": OkxAdapter,
    "BITGET": BitgetAdapter,
    "HYPERLIQUID": HyperliquidAdapter,
}

__all__ = ["ADAPTERS", "BinanceAdapter", "BitgetAdapter", "HyperliquidAdapter", "OkxAdapter"]
