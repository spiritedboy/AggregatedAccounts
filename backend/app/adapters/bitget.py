import asyncio
import base64
import hashlib
import hmac
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

from app.adapters.base import ExchangeAdapter
from app.services.normalizer import SymbolNormalizer, normalize_margin_mode, normalize_side


class BitgetAdapter(ExchangeAdapter):
    """Read-only Bitget unified trading account (v3) adapter.

    Official references:
    https://www.bitget.com/legacy-docs/uta/account/Get-Account
    https://www.bitget.com/legacy-docs/uta/trade/Get-Position
    https://www.bitget.com/legacy-docs/uta/trade/Get-Position-History
    """

    base_url = "https://api.bitget.com"
    history_streams = frozenset({"income", "funding", "fees", "cash_flows"})
    FUTURES_CATEGORIES = ("USDT-FUTURES", "USDC-FUTURES", "COIN-FUTURES")

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
        await self._get("/api/v3/account/assets")
        return True

    async def get_permissions(self) -> dict[str, bool | None]:
        try:
            info = await self._get("/api/v3/account/info")
            mode = str((info or {}).get("permType") or "").lower()
            authorities = {str(item).lower() for item in (info or {}).get("permissions", [])}
            writable = mode == "read_and_write"
            return {
                "read": True,
                "spot_trade": writable and "uta_trade" in authorities,
                "futures_trade": writable and "uta_trade" in authorities,
                "transfer": writable and "uta_mgt" in authorities,
                "withdraw": writable and "withdraw" in authorities,
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
        account = await self._get("/api/v3/account/assets") or {}
        self._latest_account_assets = account
        balances = self._normalize_balances(account)
        self._latest_balances = balances
        return {
            # UTA equity already includes spot collateral and futures PnL.
            "total_equity_usd": float(account.get("accountEquity") or 0),
            "available_balance_usd": sum(
                row["available"] * (row["price_usd"] or 0) for row in balances
            ),
            "margin_balance_usd": float(account.get("imr") or 0),
            "unrealized_pnl_usd": float(account.get("unrealisedPnl") or 0),
            "unvalued_asset_count": sum(row["value_usd"] is None for row in balances),
            "price_source": "BITGET_UTA_ASSETS",
        }

    async def get_balances(self) -> list[dict[str, Any]]:
        if hasattr(self, "_latest_balances"):
            return self._latest_balances
        account = await self._get("/api/v3/account/assets") or {}
        self._latest_account_assets = account
        self._latest_balances = self._normalize_balances(account)
        return self._latest_balances

    @staticmethod
    def _normalize_balances(account: dict[str, Any]) -> list[dict[str, Any]]:
        balances: list[dict[str, Any]] = []
        for row in account.get("assets") or []:
            asset = str(row.get("coin") or "UNKNOWN").upper()
            available = float(row.get("available") or 0)
            equity = float(row.get("equity") or 0)
            value_usd = float(row["usdValue"]) if row.get("usdValue") not in {None, ""} else None
            price = value_usd / equity if value_usd is not None and equity > 0 else None
            balances.append(
                {
                    "asset": asset,
                    "account_type": "UNIFIED",
                    "available": available,
                    "locked": max(0.0, equity - available),
                    "value_usd": value_usd,
                    "price_usd": price,
                    "price_source": "BITGET_UTA_USD_VALUE",
                }
            )
        return balances

    async def get_open_positions(self) -> list[dict[str, Any]]:
        pages = await asyncio.gather(
            *(
                self._get("/api/v3/position/current-position", {"category": category})
                for category in self.FUTURES_CATEGORIES
            )
        )
        positions = []
        for product_type, payload in zip(self.FUTURES_CATEGORIES, pages, strict=True):
            for item in (payload or {}).get("list") or []:
                size = float(item.get("total") or 0)
                if not size:
                    continue
                mark = float(item.get("markPrice") or 0)
                balance = float(item.get("positionBalance") or 0)
                positions.append(
                    {
                        "source_record_id": (
                            f"{product_type}:{item['symbol']}:{item['posSide']}"
                        ),
                        "symbol": item["symbol"],
                        "normalized_symbol": SymbolNormalizer.normalize(item["symbol"]),
                        "side": normalize_side(item["posSide"]),
                        "position_size": abs(size),
                        "position_value_usd": abs(size * mark),
                        "entry_price": float(item.get("avgPrice") or 0),
                        "mark_price": mark,
                        "liquidation_price": (
                            float(item.get("liquidationPrice") or 0) or None
                        ),
                        "leverage": float(item.get("leverage") or 0),
                        "margin_mode": normalize_margin_mode(item.get("marginMode")),
                        "margin_used": balance,
                        "unrealized_pnl": float(item.get("unrealisedPnl") or 0),
                    }
                )
        return positions

    @staticmethod
    def _windows(start_time: datetime, end_time: datetime):
        # UTA limits each request to 30 days and exposes only the last 90 days.
        floor = datetime.now(UTC) - timedelta(days=89)
        current = max(start_time, floor)
        while current < end_time:
            end = min(current + timedelta(days=29), end_time)
            yield current, end
            current = end

    async def _paged_rows(
        self, path: str, category: str | None, start_time: datetime, end_time: datetime
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for window_start, window_end in self._windows(start_time, end_time):
            params: dict[str, Any] = {
                "startTime": int(window_start.timestamp() * 1000),
                "endTime": int(window_end.timestamp() * 1000),
                "limit": 100,
            }
            if category:
                params = {"category": category, **params}
            cursor: str | None = None
            seen: set[str] = set()
            for _ in range(100):
                page_params = {**params, **({"cursor": cursor} if cursor else {})}
                payload = await self._get(path, page_params) or {}
                page = payload.get("list") or []
                rows.extend(page)
                next_cursor = str(payload.get("cursor") or "")
                if not next_cursor or not page:
                    break
                if next_cursor == cursor or next_cursor in seen:
                    raise ValueError("Bitget v3 分页游标重复，拒绝提交不完整历史")
                seen.add(next_cursor)
                cursor = next_cursor
            else:
                raise ValueError("Bitget v3 历史分页超过安全上限")
        return rows

    async def _position_history_rows(
        self,
        product_type: str,
        start_time: datetime,
        end_time: datetime,
    ) -> list[dict[str, Any]]:
        return await self._paged_rows(
            "/api/v3/position/history-position", product_type, start_time, end_time
        )

    async def get_closed_positions(
        self, start_time: datetime, end_time: datetime
    ) -> list[dict[str, Any]]:
        positions: dict[str, dict[str, Any]] = {}
        start_ms = int(start_time.timestamp() * 1000)
        end_ms = int(end_time.timestamp() * 1000)
        for product_type in self.FUTURES_CATEGORIES:
            rows = await self._position_history_rows(product_type, start_time, end_time)
            for item in rows:
                close_timestamp = int(item.get("updatedTime") or 0)
                if not start_ms <= close_timestamp <= end_ms:
                    continue
                open_timestamp = int(item.get("createdTime") or 0)
                realized_pnl = float(item.get("cumRealisedPnl") or 0)
                funding_fee = float(item.get("totalFunding") or 0)
                fee_contribution = float(item.get("openFeeTotal") or 0) + float(
                    item.get("closeFeeTotal") or 0
                )
                net_pnl = (
                    float(item["netProfit"])
                    if item.get("netProfit") not in {None, ""}
                    else realized_pnl + funding_fee + fee_contribution
                )
                entry_price = float(item.get("openPriceAvg") or 0)
                max_size = abs(
                    float(item.get("openTotalPos") or item.get("closeTotalPos") or 0)
                )
                initial_notional = entry_price * max_size
                # UTA history/order endpoints do not publish a reliable leverage.
                leverage = float(item.get("leverage") or 0) or None
                position_id = str(item.get("positionId") or "").strip()
                if position_id:
                    source_record_id = f"bitget:{product_type}:{position_id}"
                else:
                    source_record_id = (
                        f"bitget:{product_type}:symbol:"
                        f"{item.get('symbol') or 'position'}:{close_timestamp}"
                    )
                normalized = {
                    "source_record_id": source_record_id,
                    "symbol": item["symbol"],
                    "normalized_symbol": SymbolNormalizer.normalize(item["symbol"]),
                    "side": normalize_side(str(item.get("posSide") or "")),
                    "open_time": (
                        datetime.fromtimestamp(open_timestamp / 1000, tz=UTC)
                        if open_timestamp
                        else start_time
                    ),
                    "close_time": datetime.fromtimestamp(close_timestamp / 1000, tz=UTC),
                    "average_entry_price": entry_price,
                    "average_exit_price": float(item.get("closePriceAvg") or 0),
                    "max_position_size": max_size,
                    "realized_pnl": realized_pnl,
                    "funding_fee": funding_fee,
                    "trading_fee": -fee_contribution,
                    "net_pnl": net_pnl,
                    "leverage": leverage,
                    "margin_used": initial_notional / leverage if leverage else 0,
                    "return_percent": (
                        net_pnl / (initial_notional / leverage) * 100
                        if initial_notional and leverage
                        else realized_pnl / initial_notional * 100
                        if initial_notional
                        else 0
                    ),
                    "data_source": "EXCHANGE_API",
                    "data_completeness": "COMPLETE" if open_timestamp else "PARTIAL",
                }
                existing = positions.get(source_record_id)
                if (
                    existing is None
                    or normalized["close_time"] > existing["close_time"]
                ):
                    positions[source_record_id] = normalized
        return list(positions.values())

    async def get_income_history(
        self, start_time: datetime, end_time: datetime
    ) -> list[dict[str, Any]]:
        return (await self.get_history_bundle(start_time, end_time))["income"]

    async def _bill_rows(
        self, start_time: datetime, end_time: datetime
    ) -> list[dict[str, Any]]:
        categories = ("SPOT", *self.FUTURES_CATEGORIES)
        groups = await asyncio.gather(
            *(
                self._paged_rows(
                    "/api/v3/account/financial-records", category, start_time, end_time
                )
                for category in categories
            ),
            self._paged_rows(
                "/api/v3/account/funding-financial-records", None, start_time, end_time
            ),
        )
        rows = [row for group in groups[:-1] for row in group]
        rows.extend({**row, "_funding_account": True} for row in groups[-1])
        return rows

    async def get_history_bundle(
        self, start_time: datetime, end_time: datetime
    ) -> dict[str, Any]:
        rows = await self._bill_rows(start_time, end_time)
        bundle: dict[str, Any] = {
            "income": [],
            "funding": [],
            "fees": [],
            "cash_flows": [],
            "complete": True,
        }
        realized_types = {
            "CLOSE_LONG", "CLOSE_SHORT", "FORCE_CLOSE_LONG", "FORCE_CLOSE_SHORT",
            "BURST_CLOSE_LONG", "BURST_CLOSE_SHORT", "OFFSET_REDUCE_CLOSE_LONG",
            "OFFSET_REDUCE_CLOSE_SHORT", "FIXED_CLOSE_LONG", "FIXED_CLOSE_SHORT",
            "FIXED_FORCE_CLOSE_LONG", "FIXED_FORCE_CLOSE_SHORT",
            "FIXED_BURST_CLOSE_LONG", "FIXED_BURST_CLOSE_SHORT",
            "DELIVERY_LONG", "DELIVERY_SHORT", "FIXED_DELIVERY_LONG",
            "FIXED_DELIVERY_SHORT", "BUY_DEAL", "SELL_DEAL",
        }
        funding_types = {
            "CONTRACT_MAIN_SETTLE_FEE_USER_IN", "CONTRACT_MAIN_SETTLE_FEE_USER_OUT",
            "MARGIN_SETTLE_FEE_USER_IN", "MARGIN_SETTLE_FEE_USER_OUT",
        }
        stable_assets = {"USD", "USDT", "USDC"}
        for row in rows:
            timestamp = int(row.get("ts") or 0)
            if not (
                int(start_time.timestamp() * 1000)
                <= timestamp
                <= int(end_time.timestamp() * 1000)
            ):
                continue
            asset = str(row.get("coin") or "USD").upper()
            if asset not in stable_assets:
                bundle["complete"] = False
                continue
            bill_id = str(row.get("id") or timestamp)
            business_type = str(row.get("type") or "UNKNOWN").upper()
            amount = float(row.get("amount") or 0)
            common = {
                "asset": asset,
                "record_time": datetime.fromtimestamp(timestamp / 1000, tz=UTC),
                "symbol": row.get("symbol") or None,
            }
            recognized = False
            is_funding_account = bool(row.get("_funding_account"))
            if not is_funding_account and business_type in realized_types and amount:
                recognized = True
                bundle["income"].append(
                    {
                        **common,
                        "source_record_id": f"{bill_id}:pnl",
                        "amount_usd": amount,
                        "income_type": "REALIZED_PNL",
                    }
                )
            if not is_funding_account and business_type in funding_types and amount:
                recognized = True
                bundle["funding"].append(
                    {
                        **common,
                        "source_record_id": f"{bill_id}:funding",
                        "amount_usd": amount,
                    }
                )
            fee = float(row.get("fee") or 0) if not is_funding_account else 0
            if fee:
                recognized = True
                bundle["fees"].append(
                    {
                        **common,
                        "source_record_id": f"{bill_id}:fee",
                        "amount_usd": -fee,
                    }
                )
            # UTA TRANSFER_IN/OUT is an internal movement, not portfolio PnL/cashflow.
            # Only the funding-account external deposit/withdrawal is counted.
            external_deposit = is_funding_account and business_type in {
                "DEPOSIT", "INNER_TRANSFER_RECHARGE", "INNER_CHAIN_RECHARGE",
                "RECHARGE_RECEIVE",
            }
            external_withdrawal = is_funding_account and business_type in {
                "WITHDRAW", "INNER_WITHDRAW", "INNER_ADDR_WITHDRAW",
            }
            if (external_deposit or external_withdrawal) and amount:
                recognized = True
                bundle["cash_flows"].append(
                    {
                        **common,
                        "source_record_id": f"v3:funding:{bill_id}:cash",
                        "amount_usd": abs(amount),
                        "flow_type": (
                            "DEPOSIT" if external_deposit else "WITHDRAWAL"
                        ),
                    }
                )
            if business_type == "ORDER_PLF_FEE_OUT" and amount and not fee:
                recognized = True
                bundle["fees"].append(
                    {**common, "source_record_id": f"{bill_id}:fee", "amount_usd": -amount}
                )
            if business_type in {"TRANSFER_IN", "TRANSFER_OUT"}:
                recognized = True
            if amount and not recognized:
                bundle["complete"] = False
        if start_time < datetime.now(UTC) - timedelta(days=89):
            bundle["complete"] = False
        return bundle

    async def get_funding_history(
        self, start_time: datetime, end_time: datetime
    ) -> list[dict[str, Any]]:
        return (await self.get_history_bundle(start_time, end_time))["funding"]

    async def get_fee_history(
        self, start_time: datetime, end_time: datetime
    ) -> list[dict[str, Any]]:
        return (await self.get_history_bundle(start_time, end_time))["fees"]

    async def get_cash_flow_history(
        self, start_time: datetime, end_time: datetime
    ) -> list[dict[str, Any]]:
        return (await self.get_history_bundle(start_time, end_time))["cash_flows"]
