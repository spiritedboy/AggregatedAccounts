import asyncio
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
    history_streams = frozenset({"income", "funding", "fees", "cash_flows"})

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
        usdt_rows, usdc_rows, balances = await asyncio.gather(
            self._get("/api/v2/mix/account/accounts", {"productType": "USDT-FUTURES"}),
            self._get("/api/v2/mix/account/accounts", {"productType": "USDC-FUTURES"}),
            self.get_balances(),
        )
        self._latest_balances = balances
        rows = [*(usdt_rows or []), *(usdc_rows or [])]
        usdc_equity = sum(
            float(row.get("usdtEquity") or row.get("accountEquity") or 0)
            for row in (usdc_rows or [])
        )
        usdc_available = sum(
            float(row.get("available") or 0) for row in (usdc_rows or [])
        )
        usdc_margin = sum(
            float(row.get("isolatedMargin") or 0)
            + float(row.get("crossedMargin") or 0)
            for row in (usdc_rows or [])
        )
        usdc_unrealized = sum(
            float(row.get("unrealizedPL") or 0) for row in (usdc_rows or [])
        )
        spot_equity = sum(
            float(row["value_usd"])
            for row in balances
            if row["account_type"] == "SPOT" and row["value_usd"] is not None
        )
        spot_available = sum(
            float(row["available"]) * float(row.get("price_usd") or 0)
            for row in balances
            if row["account_type"] == "SPOT" and row["value_usd"] is not None
        )
        return {
            "total_equity_usd": sum(
                float(row.get("usdtEquity") or row.get("accountEquity") or 0)
                for row in rows
            )
            + spot_equity,
            "available_balance_usd": sum(
                float(row.get("available") or 0) for row in rows
            )
            + spot_available,
            "margin_balance_usd": sum(
                float(row.get("isolatedMargin") or 0) + float(row.get("crossedMargin") or 0)
                for row in rows
            ),
            "unrealized_pnl_usd": sum(float(row.get("unrealizedPL") or 0) for row in rows),
            "unvalued_asset_count": sum(
                row["value_usd"] is None for row in balances
            ),
            "price_source": "BITGET_FUTURES_AND_SPOT_TICKER",
            "legacy_excluded_equity_usd": spot_equity + usdc_equity,
            "legacy_excluded_available_usd": spot_available + usdc_available,
            "legacy_excluded_margin_usd": usdc_margin,
            "legacy_excluded_unrealized_pnl_usd": usdc_unrealized,
        }

    async def get_balances(self) -> list[dict[str, Any]]:
        if hasattr(self, "_latest_balances"):
            return self._latest_balances
        rows, tickers, usdt_accounts, usdc_accounts = await asyncio.gather(
            self._get("/api/v2/spot/account/assets", {"assetType": "hold_only"}),
            self._get("/api/v2/spot/market/tickers"),
            self._get(
                "/api/v2/mix/account/accounts",
                {"productType": "USDT-FUTURES"},
            ),
            self._get(
                "/api/v2/mix/account/accounts",
                {"productType": "USDC-FUTURES"},
            ),
        )
        prices = {
            str(row.get("symbol") or "").upper(): float(row.get("lastPr") or 0)
            for row in (tickers or [])
            if float(row.get("lastPr") or 0) > 0
        }
        stable_assets = {"USD", "USDT", "USDC"}
        balances: list[dict[str, Any]] = []
        for row in rows or []:
            asset = str(row["coin"]).upper()
            available = float(row.get("available") or 0)
            locked = float(row.get("frozen") or 0) + float(row.get("locked") or 0)
            total = available + locked
            explicit_value = row.get("usdtValue")
            price = (
                1.0
                if asset in stable_assets
                else prices.get(f"{asset}USDT")
            )
            value_usd = (
                float(explicit_value)
                if explicit_value not in {None, ""}
                else total * price
                if price is not None
                else None
            )
            effective_price = value_usd / total if value_usd is not None and total else price
            balances.append(
                {
                    "asset": asset,
                    "account_type": "SPOT",
                    "available": available,
                    "locked": locked,
                    "value_usd": value_usd,
                    "price_usd": effective_price,
                    "price_source": (
                        "BITGET_USDT_VALUE"
                        if explicit_value not in {None, ""}
                        else "STABLECOIN_PARITY"
                        if asset in stable_assets
                        else "BITGET_SPOT_TICKER"
                    ),
                }
            )
        for account_type, accounts in (
            ("USDT_FUTURES", usdt_accounts or []),
            ("USDC_FUTURES", usdc_accounts or []),
        ):
            for row in accounts:
                asset = str(row.get("marginCoin") or "UNKNOWN").upper()
                price = (
                    1.0
                    if asset in stable_assets
                    else prices.get(f"{asset}USDT")
                )
                equity = float(row.get("accountEquity") or 0)
                value_usd = row.get("usdtEquity")
                balances.append(
                    {
                        "asset": asset,
                        "account_type": account_type,
                        "available": float(row.get("available") or 0),
                        "locked": max(
                            0.0,
                            equity - float(row.get("available") or 0),
                        ),
                        "value_usd": (
                            float(value_usd)
                            if value_usd not in {None, ""}
                            else equity * price
                            if price is not None
                            else None
                        ),
                        "price_usd": price,
                        "price_source": (
                            "BITGET_USDT_EQUITY"
                            if value_usd not in {None, ""}
                            else "STABLECOIN_PARITY"
                            if asset in stable_assets
                            else "BITGET_SPOT_TICKER"
                        ),
                    }
                )
        self._latest_balances = balances
        return balances

    async def get_open_positions(self) -> list[dict[str, Any]]:
        usdt_rows, usdc_rows = await asyncio.gather(
            self._get(
                "/api/v2/mix/position/all-position",
                {"productType": "USDT-FUTURES"},
            ),
            self._get(
                "/api/v2/mix/position/all-position",
                {"productType": "USDC-FUTURES"},
            ),
        )
        positions = []
        for product_type, rows in (
            ("USDT-FUTURES", usdt_rows or []),
            ("USDC-FUTURES", usdc_rows or []),
        ):
            for item in rows:
                size = float(item.get("total") or 0)
                if not size:
                    continue
                mark = float(item.get("markPrice") or 0)
                positions.append(
                    {
                        "source_record_id": (
                            f"{product_type}:{item['symbol']}:{item['holdSide']}"
                        ),
                        "symbol": item["symbol"],
                        "normalized_symbol": SymbolNormalizer.normalize(item["symbol"]),
                        "side": normalize_side(item["holdSide"]),
                        "position_size": abs(size),
                        "position_value_usd": abs(size * mark),
                        "entry_price": float(item.get("openPriceAvg") or 0),
                        "mark_price": mark,
                        "liquidation_price": (
                            float(item.get("liquidationPrice") or 0) or None
                        ),
                        "leverage": float(item.get("leverage") or 0),
                        "margin_mode": normalize_margin_mode(item.get("marginMode")),
                        "margin_used": float(item.get("marginSize") or 0),
                        "unrealized_pnl": float(item.get("unrealizedPL") or 0),
                    }
                )
        return positions

    async def _position_history_rows(
        self,
        product_type: str,
        start_time: datetime,
        end_time: datetime,
    ) -> list[dict[str, Any]]:
        base_params: dict[str, Any] = {
            "productType": product_type,
            "startTime": int(start_time.timestamp() * 1000),
            "endTime": int(end_time.timestamp() * 1000),
            "limit": 100,
        }
        rows: list[dict[str, Any]] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        for _ in range(50):
            params = {**base_params}
            if cursor:
                params["idLessThan"] = cursor
            payload = await self._get("/api/v2/mix/position/history-position", params)
            page = (payload or {}).get("list", [])
            rows.extend(page)
            next_cursor = str((payload or {}).get("endId") or "")
            if (
                len(page) < 100
                or not next_cursor
                or next_cursor == cursor
                or next_cursor in seen_cursors
            ):
                break
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        return rows

    async def get_closed_positions(
        self, start_time: datetime, end_time: datetime
    ) -> list[dict[str, Any]]:
        positions: dict[str, dict[str, Any]] = {}
        start_ms = int(start_time.timestamp() * 1000)
        end_ms = int(end_time.timestamp() * 1000)
        for product_type in ("USDT-FUTURES", "USDC-FUTURES"):
            rows = await self._position_history_rows(product_type, start_time, end_time)
            for item in rows:
                close_timestamp = int(item.get("utime") or 0)
                if not start_ms <= close_timestamp <= end_ms:
                    continue
                open_timestamp = int(item.get("ctime") or 0)
                realized_pnl = float(item.get("pnl") or 0)
                funding_fee = float(item.get("totalFunding") or 0)
                fee_contribution = float(item.get("openFee") or 0) + float(
                    item.get("closeFee") or 0
                )
                net_pnl = float(
                    item.get("netProfit")
                    or realized_pnl + funding_fee + fee_contribution
                )
                entry_price = float(item.get("openAvgPrice") or 0)
                max_size = abs(
                    float(item.get("openTotalPos") or item.get("closeTotalPos") or 0)
                )
                initial_notional = entry_price * max_size
                source_record_id = (
                    f"bitget:{product_type}:"
                    f"{item.get('positionId') or item.get('symbol')}:{close_timestamp}"
                )
                positions[source_record_id] = {
                    "source_record_id": source_record_id,
                    "symbol": item["symbol"],
                    "normalized_symbol": SymbolNormalizer.normalize(item["symbol"]),
                    "side": normalize_side(str(item.get("holdSide") or "")),
                    "open_time": (
                        datetime.fromtimestamp(open_timestamp / 1000, tz=UTC)
                        if open_timestamp
                        else start_time
                    ),
                    "close_time": datetime.fromtimestamp(close_timestamp / 1000, tz=UTC),
                    "average_entry_price": entry_price,
                    "average_exit_price": float(item.get("closeAvgPrice") or 0),
                    "max_position_size": max_size,
                    "realized_pnl": realized_pnl,
                    "funding_fee": funding_fee,
                    "trading_fee": -fee_contribution,
                    "net_pnl": net_pnl,
                    "return_percent": (
                        realized_pnl / initial_notional * 100 if initial_notional else 0
                    ),
                    "data_source": "EXCHANGE_API",
                    "data_completeness": "COMPLETE" if open_timestamp else "PARTIAL",
                }
        return list(positions.values())

    async def get_income_history(
        self, start_time: datetime, end_time: datetime
    ) -> list[dict[str, Any]]:
        return (await self.get_history_bundle(start_time, end_time))["income"]

    async def _bill_rows(
        self, start_time: datetime, end_time: datetime
    ) -> list[dict[str, Any]]:
        base_params: dict[str, Any] = {
            "productType": "USDT-FUTURES",
            "startTime": int(start_time.timestamp() * 1000),
            "endTime": int(end_time.timestamp() * 1000),
            "limit": 100,
        }
        rows: list[dict[str, Any]] = []
        cursor: str | None = None
        for _ in range(50):
            params = {**base_params}
            if cursor:
                params["idLessThan"] = cursor
            payload = await self._get("/api/v2/mix/account/bill", params)
            page = (payload or {}).get("bills", [])
            rows.extend(page)
            next_cursor = str((payload or {}).get("endId") or "")
            if len(page) < 100 or not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor
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
            "close_long",
            "close_short",
            "force_close_long",
            "force_close_short",
            "force_buy",
            "force_sell",
            "burst_long_loss_query",
            "burst_short_loss_query",
            "burst_buy",
            "burst_sell",
            "delivery_long",
            "delivery_short",
            "tracking_trader_income",
        }
        deposit_types = {
            "trans_from_exchange",
            "trans_from_contract",
            "trans_from_otc",
            "trans_from_cross",
            "trans_from_isolated",
        }
        withdrawal_types = {
            "trans_to_exchange",
            "trans_to_contract",
            "trans_to_otc",
            "trans_to_cross",
            "trans_to_isolated",
        }
        stable_assets = {"USD", "USDT", "USDC"}
        for row in rows:
            timestamp = int(row.get("cTime") or 0)
            if timestamp < int(start_time.timestamp() * 1000):
                continue
            asset = str(row.get("coin") or "USD").upper()
            if asset not in stable_assets:
                bundle["complete"] = False
                continue
            bill_id = str(row.get("billId") or timestamp)
            business_type = str(row.get("businessType") or "unknown").lower()
            amount = float(row.get("amount") or 0)
            common = {
                "asset": asset,
                "record_time": datetime.fromtimestamp(timestamp / 1000, tz=UTC),
                "symbol": row.get("symbol") or None,
            }
            recognized = False
            if business_type in realized_types and amount:
                recognized = True
                bundle["income"].append(
                    {
                        **common,
                        "source_record_id": f"{bill_id}:pnl",
                        "amount_usd": amount,
                        "income_type": "REALIZED_PNL",
                    }
                )
            if business_type == "contract_settle_fee" and amount:
                recognized = True
                bundle["funding"].append(
                    {
                        **common,
                        "source_record_id": f"{bill_id}:funding",
                        "amount_usd": amount,
                    }
                )
            fee = float(row.get("fee") or 0)
            if fee:
                recognized = True
                bundle["fees"].append(
                    {
                        **common,
                        "source_record_id": f"{bill_id}:fee",
                        "amount_usd": -fee,
                    }
                )
            if business_type in deposit_types | withdrawal_types and amount:
                recognized = True
                bundle["cash_flows"].append(
                    {
                        **common,
                        "source_record_id": f"{bill_id}:cash",
                        "amount_usd": abs(amount),
                        "flow_type": (
                            "DEPOSIT" if business_type in deposit_types else "WITHDRAWAL"
                        ),
                    }
                )
            if amount and not recognized:
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
