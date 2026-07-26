import asyncio
import hashlib
import hmac
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

from app.adapters.base import AdapterError, ExchangeAdapter
from app.services.normalizer import SymbolNormalizer, normalize_margin_mode, normalize_side


class BinanceAdapter(ExchangeAdapter):
    """Read-only Binance Spot/SAPI/USD-M adapter.

    Official references:
    https://developers.binance.com/docs/binance-spot-api-docs/rest-api/account-endpoints
    https://developers.binance.com/docs/wallet/account/api-key-permission
    https://developers.binance.com/docs/derivatives/usds-margined-futures/account/rest-api-v3
    """

    spot_base = "https://api.binance.com"
    futures_base = "https://fapi.binance.com"
    history_streams = frozenset({"income", "funding", "fees", "cash_flows"})

    def _signed(self, params: dict[str, Any] | None = None) -> tuple[str, dict[str, str]]:
        payload = {
            **(params or {}),
            "timestamp": int(time.time() * 1000),
            "recvWindow": 5000,
        }
        query = urlencode(payload)
        signature = hmac.new(
            (self._api_secret or "").encode(), query.encode(), hashlib.sha256
        ).hexdigest()
        return f"{query}&signature={signature}", {"X-MBX-APIKEY": self.api_key or ""}

    async def _signed_get(self, base: str, path: str, params: dict[str, Any] | None = None) -> Any:
        query, headers = self._signed(params)
        return await self._request("GET", f"{base}{path}?{query}", headers=headers)

    async def test_connection(self) -> bool:
        try:
            await self._signed_get(self.spot_base, "/api/v3/account", {"omitZeroBalances": "true"})
        except AdapterError:
            await self._signed_get(self.futures_base, "/fapi/v3/account")
        return True

    async def get_permissions(self) -> dict[str, bool | None]:
        try:
            data = await self._signed_get(self.spot_base, "/sapi/v1/account/apiRestrictions")
            return {
                "read": bool(data.get("enableReading", True)),
                "spot_trade": bool(data.get("enableSpotAndMarginTrading", False)),
                "futures_trade": bool(data.get("enableFutures", False)),
                "transfer": bool(data.get("enableInternalTransfer", False)),
                "withdraw": bool(data.get("enableWithdrawals", False)),
            }
        except AdapterError:
            return {
                "read": True,
                "spot_trade": None,
                "futures_trade": None,
                "transfer": None,
                "withdraw": None,
            }

    async def get_account_summary(self) -> dict[str, Any]:
        futures, balances = await asyncio.gather(
            self._signed_get(self.futures_base, "/fapi/v3/account"),
            self.get_balances(),
        )
        self._latest_balances = balances
        valued = [
            row
            for row in balances
            if row["account_type"] == "SPOT" and row["value_usd"] is not None
        ]
        spot_equity = sum(float(row["value_usd"]) for row in valued)
        spot_available = sum(
            float(row["available"]) * float(row.get("price_usd") or 0)
            for row in valued
        )
        return {
            "total_equity_usd": float(futures.get("totalWalletBalance", 0))
            + float(futures.get("totalUnrealizedProfit", 0))
            + spot_equity,
            "available_balance_usd": float(futures.get("availableBalance", 0))
            + spot_available,
            "margin_balance_usd": float(futures.get("totalInitialMargin", 0)),
            "unrealized_pnl_usd": float(futures.get("totalUnrealizedProfit", 0)),
            "unvalued_asset_count": sum(
                row["value_usd"] is None for row in balances
            ),
            "price_source": "BINANCE_FAPI_AND_SPOT_TICKER",
            "legacy_excluded_equity_usd": spot_equity,
            "legacy_excluded_available_usd": spot_available,
            "legacy_excluded_margin_usd": 0,
            "legacy_excluded_unrealized_pnl_usd": 0,
        }

    async def get_balances(self) -> list[dict[str, Any]]:
        if hasattr(self, "_latest_balances"):
            return self._latest_balances
        spot, tickers, futures = await asyncio.gather(
            self._signed_get(
                self.spot_base, "/api/v3/account", {"omitZeroBalances": "true"}
            ),
            self._request("GET", f"{self.spot_base}/api/v3/ticker/price"),
            self._signed_get(self.futures_base, "/fapi/v3/account"),
        )
        prices = {
            str(item.get("symbol")): float(item.get("price") or 0)
            for item in tickers
            if float(item.get("price") or 0) > 0
        }
        stable_assets = {"USD", "USDT", "USDC", "FDUSD", "BUSD"}
        balances: list[dict[str, Any]] = []
        for item in spot.get("balances", []):
            asset = str(item["asset"]).upper()
            available = float(item.get("free") or 0)
            locked = float(item.get("locked") or 0)
            total = available + locked
            price = 1.0 if asset in stable_assets else prices.get(f"{asset}USDT")
            balances.append(
                {
                    "asset": asset,
                    "account_type": "SPOT",
                    "available": available,
                    "locked": locked,
                    "value_usd": total * price if price is not None else None,
                    "price_usd": price,
                    "price_source": (
                        "STABLECOIN_PARITY" if asset in stable_assets else "BINANCE_SPOT_TICKER"
                    ),
                }
            )
        for item in futures.get("assets", []):
            wallet = float(item.get("walletBalance") or 0)
            unrealized = float(item.get("unrealizedProfit") or 0)
            if not wallet and not unrealized:
                continue
            asset = str(item.get("asset") or "UNKNOWN").upper()
            price = 1.0 if asset in stable_assets else prices.get(f"{asset}USDT")
            balances.append(
                {
                    "asset": asset,
                    "account_type": "USD_M_FUTURES",
                    "available": float(item.get("availableBalance") or 0),
                    "locked": max(
                        0.0,
                        float(item.get("marginBalance") or wallet + unrealized)
                        - float(item.get("availableBalance") or 0),
                    ),
                    "value_usd": (
                        (wallet + unrealized) * price if price is not None else None
                    ),
                    "price_usd": price,
                    "price_source": (
                        "STABLECOIN_PARITY"
                        if asset in stable_assets
                        else "BINANCE_SPOT_TICKER"
                    ),
                }
            )
        self._latest_balances = balances
        return balances

    async def get_open_positions(self) -> list[dict[str, Any]]:
        rows = await self._signed_get(self.futures_base, "/fapi/v3/positionRisk")
        positions = []
        for item in rows:
            amount = float(item.get("positionAmt", 0))
            if not amount:
                continue
            mark = float(item.get("markPrice", 0))
            positions.append(
                {
                    "source_record_id": f"{item['symbol']}:{item.get('positionSide', amount)}",
                    "symbol": item["symbol"],
                    "normalized_symbol": SymbolNormalizer.normalize(item["symbol"]),
                    "side": normalize_side(item.get("positionSide", ""), amount),
                    "position_size": abs(amount),
                    "position_value_usd": abs(amount * mark),
                    "entry_price": float(item.get("entryPrice", 0)),
                    "mark_price": mark,
                    "liquidation_price": float(item.get("liquidationPrice") or 0) or None,
                    "leverage": float(item.get("leverage", 0)),
                    "margin_mode": normalize_margin_mode(item.get("marginType")),
                    "margin_used": float(item.get("isolatedMargin", 0)),
                    "unrealized_pnl": float(item.get("unRealizedProfit", 0)),
                }
            )
        return positions

    async def _trade_rows(
        self,
        symbol: str,
        start_time: datetime,
        end_time: datetime,
    ) -> list[dict[str, Any]]:
        query_start = max(start_time - timedelta(days=7), end_time - timedelta(days=7))
        params: dict[str, Any] = {
            "symbol": symbol,
            "startTime": int(query_start.timestamp() * 1000),
            "endTime": int(end_time.timestamp() * 1000),
            "limit": 1000,
        }
        rows_by_id: dict[str, dict[str, Any]] = {}
        for page_number in range(20):
            page = await self._signed_get(
                self.futures_base, "/fapi/v1/userTrades", params
            )
            for row in page:
                rows_by_id[str(row.get("id"))] = row
            if len(page) < 1000:
                break
            last_id = max(int(row.get("id") or 0) for row in page)
            if not last_id:
                break
            params = {"symbol": symbol, "fromId": last_id + 1, "limit": 1000}
            if page_number == 19:
                break
        return sorted(
            rows_by_id.values(),
            key=lambda row: (int(row.get("time") or 0), int(row.get("id") or 0)),
        )

    @staticmethod
    def _new_trade_cycle(
        symbol: str,
        side: str,
        open_time: datetime,
        complete: bool,
    ) -> dict[str, Any]:
        return {
            "symbol": symbol,
            "side": side,
            "open_time": open_time,
            "complete": complete,
            "current_size": 0.0,
            "max_position_size": 0.0,
            "open_quantity": 0.0,
            "open_notional": 0.0,
            "close_quantity": 0.0,
            "close_notional": 0.0,
            "inferred_entry_quantity": 0.0,
            "inferred_entry_notional": 0.0,
            "realized_pnl": 0.0,
            "trading_fee": 0.0,
        }

    @staticmethod
    def _add_binance_fee(
        cycle: dict[str, Any],
        row: dict[str, Any],
        quantity_share: float = 1.0,
    ) -> None:
        fee = float(row.get("commission") or 0) * quantity_share
        if str(row.get("commissionAsset") or "USDT").upper() in {
            "USD",
            "USDT",
            "USDC",
            "FDUSD",
        }:
            cycle["trading_fee"] += fee
        elif fee:
            cycle["complete"] = False

    @classmethod
    def _add_binance_close(
        cls,
        cycle: dict[str, Any],
        row: dict[str, Any],
        close_quantity: float,
        fee_share: float,
    ) -> None:
        price = float(row.get("price") or 0)
        realized_pnl = float(row.get("realizedPnl") or 0)
        cycle["close_quantity"] += close_quantity
        cycle["close_notional"] += price * close_quantity
        cycle["realized_pnl"] += realized_pnl
        inferred_entry = (
            price - realized_pnl / close_quantity
            if cycle["side"] == "LONG"
            else price + realized_pnl / close_quantity
        )
        cycle["inferred_entry_quantity"] += close_quantity
        cycle["inferred_entry_notional"] += inferred_entry * close_quantity
        cls._add_binance_fee(cycle, row, fee_share)

    @classmethod
    def _add_binance_open(
        cls,
        cycle: dict[str, Any],
        row: dict[str, Any],
        open_quantity: float,
        fee_share: float,
    ) -> None:
        cycle["open_quantity"] += open_quantity
        cycle["open_notional"] += float(row.get("price") or 0) * open_quantity
        cycle["current_size"] += open_quantity
        cycle["max_position_size"] = max(
            cycle["max_position_size"], cycle["current_size"]
        )
        cls._add_binance_fee(cycle, row, fee_share)

    @staticmethod
    def _finish_binance_cycle(
        cycle: dict[str, Any],
        row: dict[str, Any],
    ) -> dict[str, Any]:
        cycle["close_time"] = datetime.fromtimestamp(
            int(row.get("time") or 0) / 1000, tz=UTC
        )
        cycle["closing_trade_id"] = str(row.get("id") or row.get("orderId"))
        return cycle

    @classmethod
    def _closed_cycles_from_hedge_trades(
        cls,
        rows: list[dict[str, Any]],
        start_time: datetime,
    ) -> list[dict[str, Any]]:
        epsilon = 1e-12
        active: dict[tuple[str, str], dict[str, Any]] = {}
        closed: list[dict[str, Any]] = []
        for row in rows:
            position_side = str(row.get("positionSide") or "").upper()
            if position_side not in {"LONG", "SHORT"}:
                continue
            symbol = str(row.get("symbol") or "")
            key = (symbol, position_side)
            trade_side = str(row.get("side") or "").upper()
            quantity = abs(float(row.get("qty") or 0))
            if not symbol or not quantity:
                continue
            is_open = (position_side == "LONG" and trade_side == "BUY") or (
                position_side == "SHORT" and trade_side == "SELL"
            )
            fill_time = datetime.fromtimestamp(
                int(row.get("time") or 0) / 1000, tz=UTC
            )
            cycle = active.get(key)
            if is_open:
                if cycle is None:
                    cycle = cls._new_trade_cycle(
                        symbol, position_side, fill_time, True
                    )
                    active[key] = cycle
                cls._add_binance_open(cycle, row, quantity, 1.0)
                continue

            if cycle is None:
                cycle = cls._new_trade_cycle(
                    symbol, position_side, start_time, False
                )
                cycle["current_size"] = quantity
                cycle["max_position_size"] = quantity
                active[key] = cycle
            close_quantity = min(quantity, cycle["current_size"])
            cls._add_binance_close(cycle, row, close_quantity, 1.0)
            cycle["current_size"] = max(0.0, cycle["current_size"] - close_quantity)
            if cycle["current_size"] <= epsilon:
                closed.append(cls._finish_binance_cycle(cycle, row))
                active.pop(key, None)
        return closed

    @classmethod
    def _closed_cycles_from_one_way_trades(
        cls,
        rows: list[dict[str, Any]],
        start_time: datetime,
    ) -> list[dict[str, Any]]:
        epsilon = 1e-12
        active: dict[str, dict[str, Any]] = {}
        signed_positions: dict[str, float] = {}
        closed: list[dict[str, Any]] = []
        for row in rows:
            if str(row.get("positionSide") or "BOTH").upper() != "BOTH":
                continue
            symbol = str(row.get("symbol") or "")
            quantity = abs(float(row.get("qty") or 0))
            if not symbol or not quantity:
                continue
            delta = quantity if str(row.get("side") or "").upper() == "BUY" else -quantity
            position = signed_positions.get(symbol, 0.0)
            fill_time = datetime.fromtimestamp(
                int(row.get("time") or 0) / 1000, tz=UTC
            )
            cycle = active.get(symbol)
            if not position or position * delta > 0:
                if cycle is None:
                    cycle = cls._new_trade_cycle(
                        symbol,
                        "LONG" if delta > 0 else "SHORT",
                        fill_time,
                        True,
                    )
                    active[symbol] = cycle
                cls._add_binance_open(cycle, row, quantity, 1.0)
                signed_positions[symbol] = position + delta
                continue

            if cycle is None:
                cycle = cls._new_trade_cycle(
                    symbol,
                    "LONG" if position > 0 else "SHORT",
                    start_time,
                    False,
                )
                cycle["current_size"] = abs(position)
                cycle["max_position_size"] = abs(position)
                active[symbol] = cycle
            close_quantity = min(abs(position), quantity)
            cls._add_binance_close(
                cycle, row, close_quantity, close_quantity / quantity
            )
            cycle["current_size"] = max(0.0, cycle["current_size"] - close_quantity)
            new_position = position + delta
            if abs(new_position) <= epsilon or position * new_position < 0:
                closed.append(cls._finish_binance_cycle(cycle, row))
                active.pop(symbol, None)

            open_quantity = quantity - close_quantity
            if open_quantity > epsilon:
                new_cycle = cls._new_trade_cycle(
                    symbol,
                    "LONG" if new_position > 0 else "SHORT",
                    fill_time,
                    True,
                )
                cls._add_binance_open(
                    new_cycle, row, open_quantity, open_quantity / quantity
                )
                active[symbol] = new_cycle
            signed_positions[symbol] = (
                0.0 if abs(new_position) <= epsilon else new_position
            )
        return closed

    @classmethod
    def _normalize_binance_cycles(
        cls,
        cycles: list[dict[str, Any]],
        start_time: datetime,
        end_time: datetime,
    ) -> list[dict[str, Any]]:
        positions: list[dict[str, Any]] = []
        for cycle in cycles:
            if not start_time <= cycle["close_time"] <= end_time:
                continue
            open_quantity = float(cycle["open_quantity"])
            inferred_quantity = float(cycle["inferred_entry_quantity"])
            if cycle["complete"] and open_quantity:
                entry_price = float(cycle["open_notional"]) / open_quantity
            elif inferred_quantity:
                entry_price = float(cycle["inferred_entry_notional"]) / inferred_quantity
            else:
                entry_price = 0.0
            close_quantity = float(cycle["close_quantity"])
            exit_price = (
                float(cycle["close_notional"]) / close_quantity if close_quantity else 0.0
            )
            realized_pnl = float(cycle["realized_pnl"])
            trading_fee = float(cycle["trading_fee"])
            initial_notional = entry_price * float(cycle["max_position_size"])
            positions.append(
                {
                    "source_record_id": (
                        f"binance:{cycle['symbol']}:{cycle['side']}:"
                        f"{cycle['closing_trade_id']}"
                    ),
                    "symbol": cycle["symbol"],
                    "normalized_symbol": SymbolNormalizer.normalize(cycle["symbol"]),
                    "side": cycle["side"],
                    "open_time": cycle["open_time"],
                    "close_time": cycle["close_time"],
                    "average_entry_price": entry_price,
                    "average_exit_price": exit_price,
                    "max_position_size": cycle["max_position_size"],
                    "realized_pnl": realized_pnl,
                    "funding_fee": 0.0,
                    "trading_fee": trading_fee,
                    "net_pnl": realized_pnl - trading_fee,
                    "return_percent": (
                        realized_pnl / initial_notional * 100 if initial_notional else 0
                    ),
                    "data_source": "RECONSTRUCTED",
                    "data_completeness": "PARTIAL",
                }
            )
        return positions

    async def get_closed_positions(
        self, start_time: datetime, end_time: datetime
    ) -> list[dict[str, Any]]:
        income_rows = await self._income_rows(start_time, end_time)
        symbols = sorted(
            {
                str(row.get("symbol"))
                for row in income_rows
                if row.get("symbol")
                and str(row.get("incomeType") or "").upper()
                in {"REALIZED_PNL", "COMMISSION"}
            }
        )
        trade_pages = await asyncio.gather(
            *(self._trade_rows(symbol, start_time, end_time) for symbol in symbols)
        )
        rows = [row for page in trade_pages for row in page]
        cycles = self._closed_cycles_from_hedge_trades(rows, start_time)
        cycles.extend(self._closed_cycles_from_one_way_trades(rows, start_time))
        return self._normalize_binance_cycles(cycles, start_time, end_time)

    async def get_income_history(
        self, start_time: datetime, end_time: datetime
    ) -> list[dict[str, Any]]:
        bundle = await self.get_history_bundle(start_time, end_time)
        return bundle["income"]

    async def _income_rows(
        self, start_time: datetime, end_time: datetime
    ) -> list[dict[str, Any]]:
        params = {
            "startTime": int(start_time.timestamp() * 1000),
            "endTime": int(end_time.timestamp() * 1000),
            "limit": 1000,
        }
        rows: list[dict[str, Any]] = []
        for page in range(1, 21):
            page_rows = await self._signed_get(
                self.futures_base,
                "/fapi/v1/income",
                {**params, "page": page},
            )
            rows.extend(page_rows)
            if len(page_rows) < 1000:
                break
        return rows

    async def get_history_bundle(
        self, start_time: datetime, end_time: datetime
    ) -> dict[str, Any]:
        rows = await self._income_rows(start_time, end_time)
        bundle: dict[str, Any] = {
            "income": [],
            "funding": [],
            "fees": [],
            "cash_flows": [],
            "complete": True,
        }
        stable_assets = {"USD", "USDT", "USDC", "FDUSD"}
        transfer_types = {
            "TRANSFER",
            "INTERNAL_TRANSFER",
            "CROSS_COLLATERAL_TRANSFER",
            "COIN_SWAP_DEPOSIT",
            "COIN_SWAP_WITHDRAW",
        }
        for row in rows:
            timestamp = int(row.get("time") or 0)
            if timestamp < int(start_time.timestamp() * 1000):
                continue
            asset = str(row.get("asset") or "USD").upper()
            if asset not in stable_assets:
                bundle["complete"] = False
                continue
            income_type = str(row.get("incomeType") or "UNKNOWN").upper()
            amount = float(row.get("income") or 0)
            source_id = (
                f"{row.get('tranId')}:{income_type}:"
                f"{row.get('symbol') or asset}:{timestamp}"
            )
            record_time = datetime.fromtimestamp(timestamp / 1000, tz=UTC)
            common = {
                "source_record_id": source_id,
                "asset": asset,
                "record_time": record_time,
                "symbol": row.get("symbol"),
            }
            if income_type == "REALIZED_PNL":
                bundle["income"].append(
                    {**common, "amount_usd": amount, "income_type": "REALIZED_PNL"}
                )
            elif income_type == "FUNDING_FEE":
                bundle["funding"].append({**common, "amount_usd": amount})
            elif income_type in {
                "COMMISSION",
                "POSITION_LIMIT_INCREASE_FEE",
                "COMMISSION_REBATE",
                "REFERRAL_KICKBACK",
                "API_REBATE",
            }:
                bundle["fees"].append({**common, "amount_usd": -amount})
            elif income_type in transfer_types and amount:
                bundle["cash_flows"].append(
                    {
                        **common,
                        "amount_usd": abs(amount),
                        "flow_type": "DEPOSIT" if amount > 0 else "WITHDRAWAL",
                    }
                )
            elif amount:
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
