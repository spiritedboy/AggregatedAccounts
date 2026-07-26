from datetime import datetime
from typing import Any

from app.adapters.base import ExchangeAdapter
from app.services.normalizer import SymbolNormalizer, normalize_side


class HyperliquidAdapter(ExchangeAdapter):
    """Public-address-only Hyperliquid Info adapter.

    Official references:
    https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint
    https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/perpetuals
    """

    info_url = "https://api.hyperliquid.xyz/info"

    async def _info(self, request_type: str, **kwargs: Any) -> Any:
        return await self._request(
            "POST",
            self.info_url,
            headers={"Content-Type": "application/json"},
            json={"type": request_type, "user": self.wallet_address, **kwargs},
        )

    async def test_connection(self) -> bool:
        await self._info("clearinghouseState")
        return True

    async def get_permissions(self) -> dict[str, bool | None]:
        return {
            "read": True,
            "spot_trade": False,
            "futures_trade": False,
            "transfer": False,
            "withdraw": False,
            "public_address_only": True,
        }

    async def get_account_summary(self) -> dict[str, Any]:
        data = await self._info("clearinghouseState")
        summary = data.get("marginSummary", {})
        return {
            "total_equity_usd": float(summary.get("accountValue") or 0),
            "available_balance_usd": max(
                0,
                float(summary.get("accountValue") or 0)
                - float(summary.get("totalMarginUsed") or 0),
            ),
            "margin_balance_usd": float(summary.get("totalMarginUsed") or 0),
            "unrealized_pnl_usd": float(summary.get("totalNtlPos") or 0)
            - float(summary.get("totalRawUsd") or 0),
            "unvalued_asset_count": 0,
            "price_source": "HYPERLIQUID_CLEARINGHOUSE",
        }

    async def get_balances(self) -> list[dict[str, Any]]:
        spot = await self._info("spotClearinghouseState")
        return [
            {
                "asset": row["coin"],
                "available": float(row.get("total") or 0) - float(row.get("hold") or 0),
                "locked": float(row.get("hold") or 0),
                "value_usd": None,
            }
            for row in spot.get("balances", [])
        ]

    async def get_open_positions(self) -> list[dict[str, Any]]:
        state = await self._info("clearinghouseState")
        positions = []
        for wrapper in state.get("assetPositions", []):
            item = wrapper.get("position", {})
            size = float(item.get("szi") or 0)
            if not size:
                continue
            value = abs(float(item.get("positionValue") or 0))
            entry = float(item.get("entryPx") or 0)
            mark = value / abs(size) if size else 0
            positions.append(
                {
                    "source_record_id": f"{item['coin']}:{normalize_side('', size)}",
                    "symbol": item["coin"],
                    "normalized_symbol": SymbolNormalizer.normalize(item["coin"]),
                    "side": normalize_side("", size),
                    "position_size": abs(size),
                    "position_value_usd": value,
                    "entry_price": entry,
                    "mark_price": mark,
                    "liquidation_price": float(item.get("liquidationPx") or 0) or None,
                    "leverage": float((item.get("leverage") or {}).get("value") or 0),
                    "margin_mode": "CROSS"
                    if (item.get("leverage") or {}).get("type") == "cross"
                    else "ISOLATED",
                    "margin_used": float(item.get("marginUsed") or 0),
                    "unrealized_pnl": float(item.get("unrealizedPnl") or 0),
                }
            )
        return positions

    async def get_income_history(
        self, start_time: datetime, end_time: datetime
    ) -> list[dict[str, Any]]:
        fills = await self._info(
            "userFillsByTime",
            startTime=int(start_time.timestamp() * 1000),
            endTime=int(end_time.timestamp() * 1000),
            aggregateByTime=True,
        )
        return [
            {
                "source_record_id": str(row.get("tid")),
                "asset": "USDC",
                "amount": float(row.get("closedPnl") or 0),
                "income_type": "REALIZED_PNL",
                "record_time": datetime.fromtimestamp(
                    int(row["time"]) / 1000, tz=start_time.tzinfo
                ),
                "symbol": row.get("coin"),
            }
            for row in fills
            if int(row["time"]) >= int(start_time.timestamp() * 1000)
        ]

    async def get_funding_history(
        self, start_time: datetime, end_time: datetime
    ) -> list[dict[str, Any]]:
        return await self._info(
            "userFunding",
            startTime=int(start_time.timestamp() * 1000),
            endTime=int(end_time.timestamp() * 1000),
        )
