import base64
import hashlib
import hmac
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

from app.adapters.base import ExchangeAdapter
from app.services.normalizer import SymbolNormalizer, normalize_margin_mode, normalize_side


class BitgetAdapter(ExchangeAdapter):
    """Read-only Bitget v2 adapter.

    Official references:
    https://www.bitget.com/api-doc/spot/account/Get-Account-Assets
    https://www.bitget.com/api-doc/contract/account/Get-Account-List
    https://www.bitget.com/api-doc/classic/contract/position/get-all-position
    """

    base_url = "https://api.bitget.com"

    def _headers(self, method: str, request_path: str) -> dict[str, str]:
        timestamp = str(int(time.time() * 1000))
        prehash = f"{timestamp}{method.upper()}{request_path}"
        signature = base64.b64encode(
            hmac.new((self._api_secret or "").encode(), prehash.encode(), hashlib.sha256).digest()
        ).decode()
        return {
            "ACCESS-KEY": self.api_key or "",
            "ACCESS-SIGN": signature,
            "ACCESS-TIMESTAMP": timestamp,
            "ACCESS-PASSPHRASE": self._passphrase or "",
            "Content-Type": "application/json",
            "locale": "en-US",
        }

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        query = f"?{urlencode(params)}" if params else ""
        request_path = f"{path}{query}"
        payload = await self._request(
            "GET", f"{self.base_url}{request_path}", headers=self._headers("GET", request_path)
        )
        if payload.get("code") != "00000":
            raise ValueError("Bitget 只读接口返回错误")
        return payload.get("data")

    async def test_connection(self) -> bool:
        await self._get("/api/v2/spot/account/assets", {"assetType": "hold_only"})
        return True

    async def get_permissions(self) -> dict[str, bool | None]:
        try:
            info = await self._get("/api/v2/spot/account/info")
            authorities = {str(item).lower() for item in info.get("authorities", [])}
            return {
                "read": True,
                "spot_trade": "spot_trade" in authorities or "trade" in authorities,
                "futures_trade": "contract_trade" in authorities,
                "transfer": "transfer" in authorities,
                "withdraw": "withdraw" in authorities,
            }
        except (ValueError, TypeError):
            return {
                "read": True,
                "spot_trade": None,
                "futures_trade": None,
                "transfer": None,
                "withdraw": None,
            }

    async def get_account_summary(self) -> dict[str, Any]:
        rows = await self._get("/api/v2/mix/account/accounts", {"productType": "USDT-FUTURES"})
        return {
            "total_equity_usd": sum(float(row.get("usdtEquity") or 0) for row in rows),
            "available_balance_usd": sum(float(row.get("available") or 0) for row in rows),
            "margin_balance_usd": sum(
                float(row.get("isolatedMargin") or 0) + float(row.get("crossedMargin") or 0)
                for row in rows
            ),
            "unrealized_pnl_usd": sum(float(row.get("unrealizedPL") or 0) for row in rows),
            "unvalued_asset_count": 0,
            "price_source": "BITGET_USDT_EQUITY",
        }

    async def get_balances(self) -> list[dict[str, Any]]:
        rows = await self._get("/api/v2/spot/account/assets", {"assetType": "hold_only"})
        return [
            {
                "asset": row["coin"].upper(),
                "available": float(row.get("available") or 0),
                "locked": float(row.get("frozen") or 0) + float(row.get("locked") or 0),
                "value_usd": None,
            }
            for row in rows
        ]

    async def get_open_positions(self) -> list[dict[str, Any]]:
        rows = await self._get("/api/v2/mix/position/all-position", {"productType": "USDT-FUTURES"})
        positions = []
        for item in rows:
            size = float(item.get("total") or 0)
            if not size:
                continue
            mark = float(item.get("markPrice") or 0)
            positions.append(
                {
                    "source_record_id": f"{item['symbol']}:{item['holdSide']}",
                    "symbol": item["symbol"],
                    "normalized_symbol": SymbolNormalizer.normalize(item["symbol"]),
                    "side": normalize_side(item["holdSide"]),
                    "position_size": abs(size),
                    "position_value_usd": abs(size * mark),
                    "entry_price": float(item.get("openPriceAvg") or 0),
                    "mark_price": mark,
                    "liquidation_price": float(item.get("liquidationPrice") or 0) or None,
                    "leverage": float(item.get("leverage") or 0),
                    "margin_mode": normalize_margin_mode(item.get("marginMode")),
                    "margin_used": float(item.get("marginSize") or 0),
                    "unrealized_pnl": float(item.get("unrealizedPL") or 0),
                }
            )
        return positions

    async def get_income_history(
        self, start_time: datetime, end_time: datetime
    ) -> list[dict[str, Any]]:
        rows = await self._get(
            "/api/v2/spot/account/bills",
            {
                "startTime": int(start_time.timestamp() * 1000),
                "endTime": int(end_time.timestamp() * 1000),
                "limit": 500,
            },
        )
        return [
            {
                "source_record_id": row["billId"],
                "asset": row.get("coin", "USD").upper(),
                "amount": float(row.get("size") or 0),
                "income_type": row.get("businessType", "UNKNOWN"),
                "record_time": datetime.fromtimestamp(int(row["cTime"]) / 1000, tz=UTC),
                "symbol": None,
            }
            for row in rows
            if int(row["cTime"]) >= int(start_time.timestamp() * 1000)
        ]
