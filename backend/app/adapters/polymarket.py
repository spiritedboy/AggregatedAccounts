import csv
import io
import re
import zipfile
from datetime import UTC, datetime
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


def _translation_source(item: dict[str, Any], title: str, outcome: str) -> dict[str, Any]:
    return {
        "translation_asset_id": str(item.get("asset") or ""),
        "translation_condition_id": str(item.get("conditionId") or ""),
        "translation_outcome_index": int(item.get("outcomeIndex") or 0),
        "translation_source_title": title.strip(),
        "translation_source_outcome": outcome.strip(),
    }


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


def _parse_combo_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def _combo_identity(item: dict[str, Any]) -> str:
    return str(item.get("combo_position_id") or item.get("combo_condition_id") or "")


def _combo_description(item: dict[str, Any]) -> tuple[str, str]:
    selections: list[str] = []
    for leg in item.get("legs") or []:
        market = leg.get("market") or {}
        event = market.get("event") or {}
        title = str(
            event.get("event_title")
            or market.get("title")
            or leg.get("leg_condition_id")
            or "Polymarket"
        ).strip()
        outcome = str(
            market.get("outcome")
            or leg.get("leg_outcome_label")
            or f"Outcome {leg.get('leg_outcome_index', 0)}"
        ).strip()
        selections.append(f"{title} — {outcome}")
    title = "Combo: " + " + ".join(selections) if selections else "Polymarket Combo"
    return title, str(item.get("side") or "Yes").title()


def _combo_translation_source(item: dict[str, Any], title: str, outcome: str) -> dict[str, Any]:
    return {
        "translation_asset_id": _combo_identity(item),
        "translation_condition_id": str(item.get("combo_condition_id") or ""),
        "translation_outcome_index": 0 if outcome.upper() == "YES" else 1,
        "translation_source_title": title,
        "translation_source_outcome": outcome,
    }


def _combo_mark_price(item: dict[str, Any]) -> float:
    yes_price = 1.0
    for leg in item.get("legs") or []:
        status = str(leg.get("status") or "").upper()
        if status == "RESOLVED_WIN":
            price = 1.0
        elif status == "RESOLVED_LOSS":
            price = 0.0
        else:
            price = float(leg.get("leg_current_price") or 0)
            if price <= 0:
                return float(item.get("entry_avg_price_usdc") or 0)
        yes_price *= min(max(price, 0.0), 1.0)
    return 1.0 - yes_price if str(item.get("side") or "YES").upper() == "NO" else yes_price


def _combo_original_size(item: dict[str, Any]) -> float:
    current_size = float(item.get("shares_balance") or 0)
    entry_price = float(item.get("entry_avg_price_usdc") or 0)
    gross_cost = float(item.get("gross_entry_cost_usdc") or 0)
    entry_fees = float(item.get("entry_fees_usdc") or 0)
    inferred_size = (gross_cost - entry_fees) / entry_price if entry_price else 0
    return max(current_size, inferred_size)


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

    async def _combo_positions(self, statuses: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        limit = 1000
        for offset in range(0, 100_001, limit):
            payload = await self._request(
                "GET",
                f"{self.data_url}/v1/positions/combos",
                params={
                    "user": self.wallet_address,
                    "status": statuses,
                    "limit": limit,
                    "offset": offset,
                },
            )
            if not isinstance(payload, dict) or not isinstance(payload.get("combos"), list):
                raise AdapterError("Polymarket 组合单响应格式无效")
            page = payload["combos"]
            rows.extend(page)
            pagination = payload.get("pagination") or {}
            if len(page) < limit or not pagination.get("has_more"):
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
        combos = await self._combo_positions("OPEN,PARTIAL")
        combo_values = [
            float(row.get("shares_balance") or 0) * _combo_mark_price(row)
            for row in combos
        ]
        combo_costs = [float(row.get("gross_entry_cost_usdc") or 0) for row in combos]
        combo_value = sum(combo_values)
        return {
            "total_equity_usd": float(snapshot["equity"]) + combo_value,
            "available_balance_usd": snapshot["cashBalance"],
            "margin_balance_usd": float(snapshot["positionsValue"]) + combo_value,
            "unrealized_pnl_usd": sum(float(row.get("cashPnl") or 0) for row in positions)
            + combo_value
            - sum(combo_costs),
            "unvalued_asset_count": 0,
            "price_source": "POLYMARKET_ACCOUNTING_SNAPSHOT",
        }

    async def get_balances(self) -> list[dict[str, Any]]:
        snapshot = await self._accounting_snapshot()
        combos = await self._combo_positions("OPEN,PARTIAL")
        combo_value = sum(
            float(row.get("shares_balance") or 0) * _combo_mark_price(row)
            for row in combos
        )
        return [
            {
                "asset": "USD",
                "account_type": "PREDICTION",
                "available": snapshot["cashBalance"],
                "locked": float(snapshot["positionsValue"]) + combo_value,
                "value_usd": float(snapshot["equity"]) + combo_value,
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
                    **_translation_source(item, title, outcome),
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
        for item in await self._combo_positions("OPEN,PARTIAL"):
            size = float(item.get("shares_balance") or 0)
            if size <= 0:
                continue
            title, outcome = _combo_description(item)
            mark_price = _combo_mark_price(item)
            gross_cost = float(item.get("gross_entry_cost_usdc") or 0)
            current_value = size * mark_price
            identity = _combo_identity(item)
            positions.append(
                {
                    **_combo_translation_source(item, title, outcome),
                    "source_record_id": identity,
                    "symbol": _display_symbol(title, outcome),
                    "normalized_symbol": f"POLY-COMBO-{identity[-32:]}"[:80],
                    "market_type": "PREDICTION_COMBO",
                    "side": "LONG",
                    "position_size": size,
                    "position_value_usd": current_value,
                    "entry_price": float(item.get("entry_avg_price_usdc") or 0),
                    "mark_price": mark_price,
                    "liquidation_price": None,
                    "leverage": 1,
                    "margin_mode": "CASH",
                    "margin_used": gross_cost,
                    "unrealized_pnl": current_value - gross_cost,
                    "unrealized_pnl_percent": (current_value - gross_cost) / gross_cost * 100
                    if gross_cost
                    else 0,
                    "realized_pnl": 0,
                    "open_time": _parse_combo_time(item.get("first_entry_at")),
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
                    **_translation_source(item, title, outcome),
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
                    "leverage": 1,
                    "margin_used": entry * bought,
                    "return_percent": realized / (entry * bought) * 100
                    if entry and bought
                    else 0,
                    "data_source": "EXCHANGE_API",
                    "data_completeness": "PARTIAL",
                }
            if stop or len(page) < limit:
                break
        for item in await self._combo_positions(
            "RESOLVED_PARTIAL,RESOLVED_WIN,RESOLVED_LOSS"
        ):
            close_time = _parse_combo_time(item.get("resolved_at"))
            if close_time is None or close_time < start_time or close_time > end_time:
                continue
            identity = _combo_identity(item)
            if not identity:
                continue
            title, outcome = _combo_description(item)
            entry_price = float(item.get("entry_avg_price_usdc") or 0)
            gross_cost = float(item.get("gross_entry_cost_usdc") or 0)
            entry_fees = float(item.get("entry_fees_usdc") or 0)
            payout = float(item.get("realized_payout_usdc") or 0)
            net_entry_cost = gross_cost - entry_fees
            realized_pnl = payout - net_entry_cost
            net_pnl = payout - gross_cost
            size = _combo_original_size(item)
            source_record_id = f"poly-closed:{identity}"
            positions_by_id[source_record_id] = {
                **_combo_translation_source(item, title, outcome),
                "source_record_id": source_record_id,
                "asset_id": identity,
                "symbol": _display_symbol(title, outcome),
                "normalized_symbol": f"POLY-COMBO-{identity[-32:]}"[:80],
                "side": "LONG",
                "open_time": _parse_combo_time(item.get("first_entry_at")) or start_time,
                "close_time": close_time,
                "average_entry_price": entry_price,
                "average_exit_price": payout / size if size else 0,
                "max_position_size": size,
                "realized_pnl": realized_pnl,
                "funding_fee": 0,
                "trading_fee": entry_fees,
                "net_pnl": net_pnl,
                "leverage": 1,
                "margin_used": gross_cost,
                "return_percent": net_pnl / gross_cost * 100 if gross_cost else 0,
                "data_source": "EXCHANGE_API",
                "data_completeness": "COMPLETE",
            }
        return list(positions_by_id.values())
