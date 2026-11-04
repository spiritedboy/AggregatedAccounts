import re
from datetime import UTC, datetime
from typing import Any

from app.adapters.base import AdapterError, ExchangeAdapter


def _display_symbol(title: str, outcome: str) -> str:
    value = f"{title.strip()} · {outcome.strip()}".strip(" ·")
    return value if len(value) <= 80 else f"{value[:77]}..."


def _normalized_symbol(item: dict[str, Any]) -> str:
    condition_id = str(
        item.get("condition_id") or item.get("conditionId") or ""
    ).removeprefix("0x")
    asset = str(item.get("token_id") or item.get("asset") or "")
    outcome_index = int(item.get("outcome_index") or item.get("outcomeIndex") or 0)
    return f"POLY-{condition_id[:16]}-{outcome_index}-{asset[-12:]}"[:80]


def _translation_source(item: dict[str, Any], title: str, outcome: str) -> dict[str, Any]:
    return {
        "translation_asset_id": str(item.get("token_id") or item.get("asset") or ""),
        "translation_condition_id": str(
            item.get("condition_id") or item.get("conditionId") or ""
        ),
        "translation_outcome_index": int(
            item.get("outcome_index") or item.get("outcomeIndex") or 0
        ),
        "translation_source_title": title.strip(),
        "translation_source_outcome": outcome.strip(),
    }


def closed_position_source_id(item: dict[str, Any]) -> str:
    """Build a stable closed-position identity from the outcome token."""

    asset = str(item.get("token_id") or item.get("asset") or "").strip()
    if asset:
        return f"poly-closed:{asset}"
    condition_id = str(
        item.get("condition_id") or item.get("conditionId") or ""
    ).removeprefix("0x")
    outcome_index = int(item.get("outcome_index") or item.get("outcomeIndex") or 0)
    return f"poly-closed:{condition_id}:{outcome_index}"


def _parse_combo_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def _timestamp(value: Any) -> datetime | None:
    try:
        seconds = int(value or 0)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(seconds, tz=UTC) if seconds > 0 else None


def _combo_identity(item: dict[str, Any]) -> str:
    return str(item.get("combo_position_id") or item.get("combo_condition_id") or "")


def _combo_description(item: dict[str, Any]) -> tuple[str, str]:
    selections: list[str] = []
    for leg in item.get("legs") or []:
        market = leg.get("market") or {}
        event = market.get("event") or {}
        title = str(
            event.get("event_title")
            or market.get("question")
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
    outcome = str(item.get("outcome_label") or item.get("side") or "Yes").title()
    return title, outcome


def _combo_translation_source(item: dict[str, Any], title: str, outcome: str) -> dict[str, Any]:
    return {
        "translation_asset_id": _combo_identity(item),
        "translation_condition_id": str(item.get("combo_condition_id") or ""),
        "translation_outcome_index": int(item.get("outcome_index") or 0),
        "translation_source_title": title,
        "translation_source_outcome": outcome,
    }


def _combo_mark_price(item: dict[str, Any]) -> float:
    yes_price = 1.0
    for leg in item.get("legs") or []:
        status = str(leg.get("leg_status") or leg.get("status") or "").upper()
        if status == "RESOLVED_WIN":
            price = 1.0
        elif status == "RESOLVED_LOSS":
            price = 0.0
        else:
            price = float(leg.get("leg_current_price") or 0)
            if price <= 0:
                return float(item.get("entry_avg_price_usdc") or 0)
        yes_price *= min(max(price, 0.0), 1.0)
    outcome = str(item.get("outcome_label") or item.get("side") or "YES").upper()
    return 1.0 - yes_price if outcome == "NO" else yes_price


def _combo_original_size(item: dict[str, Any]) -> float:
    current_size = float(item.get("current_size") or item.get("shares_balance") or 0)
    entry_price = float(item.get("entry_avg_price_usdc") or 0)
    gross_cost = float(item.get("gross_entry_cost_usdc") or 0)
    entry_fees = float(item.get("entry_fees_usdc") or 0)
    inferred_size = (gross_cost - entry_fees) / entry_price if entry_price else 0
    return max(current_size, inferred_size)


class PolymarketAdapter(ExchangeAdapter):
    """Public-profile-address-only adapter for Polymarket account analytics."""

    data_url = "https://data-api.polymarket.com/v2"
    gamma_url = "https://gamma-api.polymarket.com"
    polygon_rpc_urls = (
        "https://polygon-bor-rpc.publicnode.com",
        "https://polygon-rpc.com",
    )
    pusd_contract = "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB"

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

    async def _portfolio_value(self) -> float:
        payload = await self._request(
            "GET",
            f"{self.data_url}/value",
            params={"user": self.wallet_address},
        )
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            raise AdapterError("Polymarket 资产估值响应格式无效")
        return float(data.get("value") or 0)

    async def _cash_balance(self) -> float:
        address = str(self.wallet_address or "").removeprefix("0x").lower()
        if not re.fullmatch(r"[a-f0-9]{40}", address):
            raise AdapterError("Polymarket Proxy Wallet 地址无效")
        call_data = f"0x70a08231{'0' * 24}{address}"
        for rpc_url in self.polygon_rpc_urls:
            try:
                payload = await self._request(
                    "POST",
                    rpc_url,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "eth_call",
                        "params": [
                            {"to": self.pusd_contract, "data": call_data},
                            "latest",
                        ],
                    },
                )
                result = payload.get("result") if isinstance(payload, dict) else None
                if isinstance(result, str) and re.fullmatch(r"0x[0-9a-fA-F]+", result):
                    return int(result, 16) / 1_000_000
            except AdapterError:
                continue
        raise AdapterError("Polymarket pUSD 链上余额读取失败")

    async def _paginated_rows(
        self, path: str, params: dict[str, Any], response_name: str
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        request_params = {**params, "limit": 1000}
        for _ in range(1000):
            payload = await self._request(
                "GET",
                f"{self.data_url}/{path}",
                params=request_params,
            )
            page = payload.get("data") if isinstance(payload, dict) else None
            pagination = payload.get("pagination") if isinstance(payload, dict) else None
            if not isinstance(page, list) or not isinstance(pagination, dict):
                raise AdapterError(f"Polymarket {response_name}响应格式无效")
            rows.extend(page)
            if not pagination.get("has_more"):
                return rows
            cursor = pagination.get("next_cursor")
            if not cursor:
                raise AdapterError(f"Polymarket {response_name}分页游标缺失")
            request_params = {**params, "cursor": cursor}
        raise AdapterError(f"Polymarket {response_name}分页超过安全上限")

    async def _positions(self) -> list[dict[str, Any]]:
        return await self._paginated_rows(
            "positions",
            {
                "user": self.wallet_address,
                "status": "OPEN",
                "filter_type": "TOKENS",
                "filter_amount": 0.01,
                "sort_by": "CURRENT_VALUE",
                "sort_direction": "DESC",
            },
            "当前持仓",
        )

    async def _closed_positions(
        self, start_time: datetime, end_time: datetime
    ) -> list[dict[str, Any]]:
        return await self._paginated_rows(
            "positions",
            {
                "user": self.wallet_address,
                "status": "CLOSED",
                "start": int(start_time.timestamp()),
                "end": int(end_time.timestamp()),
                "sort_by": "TIMESTAMP",
                "sort_direction": "DESC",
            },
            "已平仓",
        )

    async def _combo_positions(self, statuses: str) -> list[dict[str, Any]]:
        return await self._paginated_rows(
            "positions/combos",
            {
                "user": self.wallet_address,
                "status": statuses,
                "sort_by": "FIRST_ENTRY",
                "sort_direction": "DESC",
            },
            "组合单",
        )

    async def test_connection(self) -> bool:
        await self._resolve_profile_address()
        await self._portfolio_value()
        await self._cash_balance()
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
        portfolio_value = await self._portfolio_value()
        cash_balance = await self._cash_balance()
        positions = await self._positions()
        combos = await self._combo_positions("OPEN,PARTIAL")
        combo_unrealized = sum(
            float(row.get("current_size") or 0) * _combo_mark_price(row)
            - float(row.get("gross_entry_cost_usdc") or 0)
            for row in combos
        )
        return {
            "total_equity_usd": portfolio_value + cash_balance,
            "available_balance_usd": cash_balance,
            "margin_balance_usd": portfolio_value,
            "unrealized_pnl_usd": sum(
                float(row.get("unrealized_pnl") or 0) for row in positions
            )
            + combo_unrealized,
            "unvalued_asset_count": 0,
            "price_source": "POLYMARKET_DATA_API_V2",
        }

    async def get_balances(self) -> list[dict[str, Any]]:
        portfolio_value = await self._portfolio_value()
        cash_balance = await self._cash_balance()
        return [
            {
                "asset": "USD",
                "account_type": "PREDICTION",
                "available": cash_balance,
                "locked": portfolio_value,
                "value_usd": portfolio_value + cash_balance,
                "price_source": "POLYMARKET_DATA_API_V2",
            }
        ]

    async def get_open_positions(self) -> list[dict[str, Any]]:
        positions: list[dict[str, Any]] = []
        for item in await self._positions():
            size = float(item.get("current_size") or 0)
            if size <= 0:
                continue
            title = str(item.get("title") or "Polymarket")
            outcome = str(item.get("outcome") or f"Outcome {item.get('outcome_index', 0)}")
            token_id = str(item.get("token_id") or item.get("condition_id") or "")
            positions.append(
                {
                    **_translation_source(item, title, outcome),
                    "source_record_id": token_id,
                    "symbol": _display_symbol(title, outcome),
                    "normalized_symbol": _normalized_symbol(item),
                    "market_type": "PREDICTION",
                    "side": "LONG",
                    "position_size": size,
                    "position_value_usd": float(item.get("current_value") or 0),
                    "entry_price": float(item.get("avg_price") or 0),
                    "mark_price": float(item.get("current_price") or 0),
                    "liquidation_price": None,
                    "leverage": 1,
                    "margin_mode": "CASH",
                    "margin_used": float(item.get("entry_cost_usdc") or 0),
                    "unrealized_pnl": float(item.get("unrealized_pnl") or 0),
                    "unrealized_pnl_percent": float(item.get("percent_pnl") or 0),
                    "realized_pnl": float(item.get("realized_pnl") or 0),
                    "open_time": _timestamp(item.get("first_entry_at")),
                }
            )
        for item in await self._combo_positions("OPEN,PARTIAL"):
            size = float(item.get("current_size") or 0)
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
        for item in await self._closed_positions(start_time, end_time):
            close_time = _timestamp(item.get("last_event_at"))
            if close_time is None:
                continue
            bought = float(item.get("total_size") or 0)
            entry = float(item.get("avg_price") or 0)
            realized = float(item.get("realized_pnl") or 0)
            title = str(item.get("title") or "Polymarket")
            outcome = str(item.get("outcome") or f"Outcome {item.get('outcome_index', 0)}")
            source_record_id = closed_position_source_id(item)
            entry_basis = entry * bought
            positions_by_id[source_record_id] = {
                **_translation_source(item, title, outcome),
                "source_record_id": source_record_id,
                "asset_id": str(item.get("token_id") or ""),
                "symbol": _display_symbol(title, outcome),
                "normalized_symbol": _normalized_symbol(item),
                "side": "LONG",
                "open_time": _timestamp(item.get("first_entry_at")) or start_time,
                "close_time": close_time,
                "average_entry_price": entry,
                "average_exit_price": float(item.get("current_price") or 0),
                "max_position_size": bought,
                "realized_pnl": realized,
                "funding_fee": 0,
                "trading_fee": 0,
                "net_pnl": realized,
                "leverage": 1,
                "margin_used": entry_basis,
                "return_percent": realized / entry_basis * 100 if entry_basis else 0,
                "data_source": "EXCHANGE_API",
                "data_completeness": "PARTIAL",
            }
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
