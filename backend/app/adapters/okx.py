import base64
import hashlib
import hmac
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

from app.adapters.base import ExchangeAdapter
from app.services.normalizer import SymbolNormalizer, normalize_margin_mode, normalize_side


class OkxAdapter(ExchangeAdapter):
    """Read-only OKX v5 adapter.

    Official reference: https://www.okx.com/docs-v5/en/
    """

    base_url = "https://www.okx.com"

    def _headers(self, method: str, request_path: str) -> dict[str, str]:
        timestamp = datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        prehash = f"{timestamp}{method.upper()}{request_path}"
        signature = base64.b64encode(
            hmac.new((self._api_secret or "").encode(), prehash.encode(), hashlib.sha256).digest()
        ).decode()
        return {
            "OK-ACCESS-KEY": self.api_key or "",
            "OK-ACCESS-SIGN": signature,
            "OK-ACCESS-TIMESTAMP": timestamp,
            "OK-ACCESS-PASSPHRASE": self._passphrase or "",
        }

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        query = f"?{urlencode(params)}" if params else ""
        request_path = f"{path}{query}"
        payload = await self._request(
            "GET", f"{self.base_url}{request_path}", headers=self._headers("GET", request_path)
        )
        if payload.get("code") != "0":
            raise ValueError("OKX 只读接口返回错误")
        return payload.get("data", [])

    async def test_connection(self) -> bool:
        await self._get("/api/v5/account/balance")
        return True

    async def get_permissions(self) -> dict[str, bool | None]:
        config = (await self._get("/api/v5/account/config"))[0]
        permissions = {item.strip().lower() for item in config.get("perm", "").split(",")}
        return {
            "read": "read_only" in permissions or "read" in permissions,
            "spot_trade": "trade" in permissions,
            "futures_trade": "trade" in permissions,
            "transfer": "trade" in permissions,
            "withdraw": "withdraw" in permissions,
        }

    async def get_account_summary(self) -> dict[str, Any]:
        data = (await self._get("/api/v5/account/balance"))[0]
        details = data.get("details", [])
        return {
            "total_equity_usd": float(data.get("totalEq") or 0),
            "available_balance_usd": sum(float(item.get("availEq") or 0) for item in details),
            "margin_balance_usd": sum(float(item.get("frozenBal") or 0) for item in details),
            "unrealized_pnl_usd": sum(float(item.get("upl") or 0) for item in details),
            "unvalued_asset_count": 0,
            "price_source": "OKX_TOTAL_EQ",
        }

    async def get_balances(self) -> list[dict[str, Any]]:
        data = (await self._get("/api/v5/account/balance"))[0]
        return [
            {
                "asset": item["ccy"],
                "available": float(item.get("availBal") or 0),
                "locked": float(item.get("frozenBal") or 0),
                "value_usd": float(item.get("eqUsd") or 0),
            }
            for item in data.get("details", [])
        ]

    async def get_open_positions(self) -> list[dict[str, Any]]:
        rows = await self._get("/api/v5/account/positions")
        positions = []
        for item in rows:
            size = float(item.get("pos") or 0)
            if not size:
                continue
            mark = float(item.get("markPx") or 0)
            positions.append(
                {
                    "source_record_id": item.get("posId") or f"{item['instId']}:{item['posSide']}",
                    "symbol": item["instId"],
                    "normalized_symbol": SymbolNormalizer.normalize(item["instId"]),
                    "side": normalize_side(item.get("posSide", ""), size),
                    "position_size": abs(size),
                    "position_value_usd": abs(float(item.get("notionalUsd") or size * mark)),
                    "entry_price": float(item.get("avgPx") or 0),
                    "mark_price": mark,
                    "liquidation_price": float(item.get("liqPx") or 0) or None,
                    "leverage": float(item.get("lever") or 0),
                    "margin_mode": normalize_margin_mode(item.get("mgnMode")),
                    "margin_used": float(item.get("margin") or 0),
                    "unrealized_pnl": float(item.get("upl") or 0),
                }
            )
        return positions

    async def get_income_history(
        self, start_time: datetime, end_time: datetime
    ) -> list[dict[str, Any]]:
        rows = await self._get(
            "/api/v5/account/bills-archive",
            {
                "begin": int(start_time.timestamp() * 1000),
                "end": int(end_time.timestamp() * 1000),
                "limit": 100,
            },
        )
        return [
            {
                "source_record_id": row["billId"],
                "asset": row.get("ccy", "USD"),
                "amount": float(row.get("balChg") or 0),
                "income_type": row.get("subType", row.get("type", "UNKNOWN")),
                "record_time": datetime.fromtimestamp(int(row["ts"]) / 1000, tz=UTC),
                "symbol": row.get("instId"),
            }
            for row in rows
            if int(row["ts"]) >= int(start_time.timestamp() * 1000)
        ]
