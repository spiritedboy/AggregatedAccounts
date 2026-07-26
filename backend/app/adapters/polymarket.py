import csv
import io
import re
import zipfile
from datetime import datetime
from typing import Any

import httpx

from app.adapters.base import AdapterError, ExchangeAdapter


def _display_symbol(title: str, outcome: str) -> str:
    value = f"{title.strip()} · {outcome.strip()}".strip(" ·")
    return value if len(value) <= 80 else f"{value[:77]}..."


def _normalized_symbol(item: dict[str, Any]) -> str:
    condition_id = str(item.get("conditionId") or "").removeprefix("0x")
    asset = str(item.get("asset") or "")
    outcome_index = int(item.get("outcomeIndex") or 0)
    return f"POLY-{condition_id[:16]}-{outcome_index}-{asset[-12:]}"[:80]


def closed_position_source_id(item: dict[str, Any]) -> str:
    """Build a stable closed-position identity from the outcome token.

    Polymarket's ``timestamp`` can move between responses for the same closed
    outcome, while ``asset`` is the stable outcome-token identifier.
    """

    asset = str(item.get("asset") or "").strip()
    if asset:
        return f"poly-closed:{asset}"
    condition_id = str(item.get("conditionId") or "").removeprefix("0x")
    outcome_index = int(item.get("outcomeIndex") or 0)
    return f"poly-closed:{condition_id}:{outcome_index}"


class PolymarketAdapter(ExchangeAdapter):
    """Public-profile-address-only adapter for Polymarket account analytics."""

    data_url = "https://data-api.polymarket.com"
    gamma_url = "https://gamma-api.polymarket.com"

    async def _resolve_profile_address(self) -> str:
        profile = await self._request(
            "GET",
            f"{self.gamma_url}/public-profile",
            params={"address": self.wallet_address},
        )
        proxy_wallet = str(profile.get("proxyWallet") or "")
        if not re.fullmatch(r"0x[a-fA-F0-9]{40}", proxy_wallet):
            raise AdapterError("Polymarket 账户没有有效的 Profile / Proxy Wallet 地址")
        self.wallet_address = proxy_wallet
        return proxy_wallet

    async def _accounting_snapshot(self) -> dict[str, float | str]:
        try:
            response = await self.client.get(
                f"{self.data_url}/v1/accounting/snapshot",
                params={"user": self.wallet_address},
            )
            response.raise_for_status()
            with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                with archive.open("equity.csv") as equity_file:
                    rows = list(csv.DictReader(io.TextIOWrapper(equity_file, encoding="utf-8")))
        except (httpx.HTTPError, KeyError, OSError, ValueError, zipfile.BadZipFile) as exc:
            raise AdapterError(
                f"Polymarket 账户快照读取失败：{type(exc).__name__}"
            ) from None
        if not rows:
            return {
                "cashBalance": 0.0,
                "positionsValue": 0.0,
                "equity": 0.0,
                "valuationTime": "",
            }
        row = rows[-1]
        return {
            "cashBalance": float(row.get("cashBalance") or 0),
            "positionsValue": float(row.get("positionsValue") or 0),
            "equity": float(row.get("equity") or 0),
            "valuationTime": row.get("valuationTime") or "",
        }

    async def _positions(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        limit = 500
        for offset in range(0, 10_001, limit):
            page = await self._request(
                "GET",
                f"{self.data_url}/positions",
                params={
                    "user": self.wallet_address,
                    "limit": limit,
                    "offset": offset,
                    "sizeThreshold": 0.01,
                    "sortBy": "CURRENT",
                    "sortDirection": "DESC",
                },
            )
            if not isinstance(page, list):
                raise AdapterError("Polymarket 当前持仓响应格式无效")
            rows.extend(page)
            if len(page) < limit:
                break
        return rows

    async def test_connection(self) -> bool:
        await self._resolve_profile_address()
        await self._accounting_snapshot()
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
        snapshot = await self._accounting_snapshot()
        positions = await self._positions()
        return {
            "total_equity_usd": snapshot["equity"],
            "available_balance_usd": snapshot["cashBalance"],
            "margin_balance_usd": snapshot["positionsValue"],
            "unrealized_pnl_usd": sum(float(row.get("cashPnl") or 0) for row in positions),
            "unvalued_asset_count": 0,
            "price_source": "POLYMARKET_ACCOUNTING_SNAPSHOT",
        }

    async def get_balances(self) -> list[dict[str, Any]]:
        snapshot = await self._accounting_snapshot()
        return [
            {
                "asset": "USD",
                "account_type": "PREDICTION",
                "available": snapshot["cashBalance"],
                "locked": snapshot["positionsValue"],
                "value_usd": snapshot["equity"],
                "price_source": "POLYMARKET_ACCOUNTING_SNAPSHOT",
            }
        ]

    async def get_open_positions(self) -> list[dict[str, Any]]:
        positions: list[dict[str, Any]] = []
        for item in await self._positions():
            size = float(item.get("size") or 0)
            if size <= 0:
                continue
            title = str(item.get("title") or "Polymarket")
            outcome = str(item.get("outcome") or f"Outcome {item.get('outcomeIndex', 0)}")
            positions.append(
                {
                    "source_record_id": str(item.get("asset") or item.get("conditionId")),
                    "symbol": _display_symbol(title, outcome),
                    "normalized_symbol": _normalized_symbol(item),
                    "market_type": "PREDICTION",
                    "side": "LONG",
                    "position_size": size,
                    "position_value_usd": float(item.get("currentValue") or 0),
                    "entry_price": float(item.get("avgPrice") or 0),
                    "mark_price": float(item.get("curPrice") or 0),
                    "liquidation_price": None,
                    "leverage": 1,
                    "margin_mode": "CASH",
                    "margin_used": float(item.get("initialValue") or 0),
                    "unrealized_pnl": float(item.get("cashPnl") or 0),
                    "unrealized_pnl_percent": float(item.get("percentPnl") or 0),
                    "realized_pnl": float(item.get("realizedPnl") or 0),
                    "open_time": None,
                }
            )
        return positions

    async def get_closed_positions(
        self, start_time: datetime, end_time: datetime
    ) -> list[dict[str, Any]]:
        positions_by_id: dict[str, dict[str, Any]] = {}
        limit = 50
        stop = False
        for offset in range(0, 100_001, limit):
            page = await self._request(
                "GET",
                f"{self.data_url}/closed-positions",
                params={
                    "user": self.wallet_address,
                    "limit": limit,
                    "offset": offset,
                    "sortBy": "TIMESTAMP",
                    "sortDirection": "DESC",
                },
            )
            if not isinstance(page, list):
                raise AdapterError("Polymarket 已平仓响应格式无效")
            for item in page:
                timestamp = int(item.get("timestamp") or 0)
                close_time = datetime.fromtimestamp(timestamp, tz=start_time.tzinfo)
                if close_time < start_time:
                    stop = True
                    break
                if close_time > end_time:
                    continue
                bought = float(item.get("totalBought") or 0)
                entry = float(item.get("avgPrice") or 0)
                realized = float(item.get("realizedPnl") or 0)
                title = str(item.get("title") or "Polymarket")
                outcome = str(item.get("outcome") or f"Outcome {item.get('outcomeIndex', 0)}")
                source_record_id = closed_position_source_id(item)
                positions_by_id[source_record_id] = {
                    "source_record_id": source_record_id,
                    "asset_id": str(item.get("asset") or ""),
                    "symbol": _display_symbol(title, outcome),
                    "normalized_symbol": _normalized_symbol(item),
                    "side": "LONG",
                    "open_time": start_time,
                    "close_time": close_time,
                    "average_entry_price": entry,
                    "average_exit_price": float(item.get("curPrice") or 0),
                    "max_position_size": bought,
                    "realized_pnl": realized,
                    "funding_fee": 0,
                    "trading_fee": 0,
                    "net_pnl": realized,
                    "return_percent": realized / (entry * bought) * 100
                    if entry and bought
                    else 0,
                    "data_source": "EXCHANGE_API",
                    "data_completeness": "PARTIAL",
                }
            if stop or len(page) < limit:
                break
        return list(positions_by_id.values())
