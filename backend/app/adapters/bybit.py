import hashlib
import hmac
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import unquote, urlencode

from app.adapters.base import AdapterError, ExchangeAdapter
from app.services.normalizer import SymbolNormalizer, normalize_margin_mode, normalize_side


class BybitAdapter(ExchangeAdapter):
    """Read-only Bybit V5 adapter for Unified Trading Accounts."""

    base_url = "https://api.bybit.com"
    recv_window = "5000"
    history_streams = frozenset({"income", "funding", "fees", "cash_flows"})
    stable_assets = frozenset({"USD", "USDT", "USDC"})
    realized_types = frozenset({"TRADE", "SETTLEMENT", "DELIVERY", "LIQUIDATION", "ADL"})

    def _headers(self, query: str) -> dict[str, str]:
        timestamp = str(int(time.time() * 1000))
        payload = f"{timestamp}{self.api_key or ''}{self.recv_window}{query}"
        signature = hmac.new(
            (self._api_secret or "").encode(), payload.encode(), hashlib.sha256
        ).hexdigest()
        return {
            "X-BAPI-API-KEY": self.api_key or "",
            "X-BAPI-TIMESTAMP": timestamp,
            "X-BAPI-SIGN": signature,
            "X-BAPI-RECV-WINDOW": self.recv_window,
        }

    async def _get(
        self, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        query = urlencode(params or {})
        url = f"{self.base_url}{path}{'?' + query if query else ''}"
        payload = await self._request("GET", url, headers=self._headers(query))
        if payload.get("retCode") != 0:
            code = payload.get("retCode", "UNKNOWN")
            raise AdapterError(f"Bybit 只读接口返回错误（{code}）")
        result = payload.get("result")
        return result if isinstance(result, dict) else {}

    async def test_connection(self) -> bool:
        await self._get("/v5/account/wallet-balance", {"accountType": "UNIFIED"})
        return True

    async def get_permissions(self) -> dict[str, bool | None]:
        data = await self._get("/v5/user/query-api")
        read_only = int(data.get("readOnly") or 0) == 1
        permissions = data.get("permissions") or {}
        wallet = set(permissions.get("Wallet") or [])
        derivatives = {
            *permissions.get("ContractTrade", []),
            *permissions.get("Derivatives", []),
            *permissions.get("Options", []),
        }
        return {
            "read": True,
            "spot_trade": not read_only and bool(permissions.get("Spot")),
            "futures_trade": not read_only and bool(derivatives),
            "transfer": not read_only
            and bool(wallet & {"AccountTransfer", "SubMemberTransfer"}),
            "withdraw": not read_only and "Withdraw" in wallet,
        }

    async def _wallet(self) -> dict[str, Any]:
        data = await self._get(
            "/v5/account/wallet-balance", {"accountType": "UNIFIED"}
        )
        rows = data.get("list") or []
        if not rows:
            raise AdapterError("Bybit 统一账户余额为空")
        return rows[0]

    async def get_account_summary(self) -> dict[str, Any]:
        data = await self._wallet()
        return {
            "total_equity_usd": float(data.get("totalEquity") or 0),
            "available_balance_usd": float(
                data.get("totalAvailableBalance") or 0
            ),
            "margin_balance_usd": float(data.get("totalInitialMargin") or 0),
            "unrealized_pnl_usd": float(data.get("totalPerpUPL") or 0),
            "unvalued_asset_count": sum(
                not str(item.get("usdValue") or "").strip()
                for item in data.get("coin") or []
            ),
            "price_source": "BYBIT_UNIFIED_WALLET",
        }

    async def get_balances(self) -> list[dict[str, Any]]:
        data = await self._wallet()
        balances: list[dict[str, Any]] = []
        for item in data.get("coin") or []:
            wallet = float(item.get("walletBalance") or 0)
            locked = float(item.get("locked") or 0)
            order_margin = float(item.get("totalOrderIM") or 0)
            position_margin = float(item.get("totalPositionIM") or 0)
            balances.append(
                {
                    "asset": str(item.get("coin") or "UNKNOWN").upper(),
                    "account_type": "UNIFIED",
                    "available": max(wallet - locked - order_margin - position_margin, 0),
                    "locked": locked + order_margin + position_margin,
                    "value_usd": float(item.get("usdValue") or 0),
                    "price_source": "BYBIT_USD_VALUE",
                }
            )
        return balances

    async def _paged(
        self,
        path: str,
        params: dict[str, Any],
        *,
        row_key: str = "list",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        cursor = ""
        for _ in range(100):
            page_params = {**params, "limit": limit}
            if cursor:
                page_params["cursor"] = unquote(cursor)
            result = await self._get(path, page_params)
            page = result.get(row_key) or []
            rows.extend(page)
            next_cursor = str(result.get("nextPageCursor") or "")
            if not next_cursor or next_cursor == cursor or len(page) < limit:
                break
            cursor = next_cursor
        return rows

    async def get_open_positions(self) -> list[dict[str, Any]]:
        account_info = await self._get("/v5/account/info")
        margin_mode = normalize_margin_mode(
            "isolated"
            if account_info.get("marginMode") == "ISOLATED_MARGIN"
            else "cross"
        )
        requests = (
            {"category": "linear", "settleCoin": "USDT"},
            {"category": "linear", "settleCoin": "USDC"},
            {"category": "inverse"},
        )
        positions: list[dict[str, Any]] = []
        seen: set[str] = set()
        for params in requests:
            rows = await self._paged("/v5/position/list", params, limit=200)
            for item in rows:
                size = abs(float(item.get("size") or 0))
                if not size:
                    continue
                symbol = str(item.get("symbol") or "")
                source_id = (
                    f"bybit:{params['category']}:{symbol}:"
                    f"{item.get('positionIdx', 0)}"
                )
                if source_id in seen:
                    continue
                seen.add(source_id)
                mark = float(item.get("markPrice") or 0)
                entry = float(item.get("avgPrice") or 0)
                value = abs(float(item.get("positionValue") or 0))
                leverage = float(item.get("leverage") or 0)
                margin = abs(
                    float(
                        item.get("positionIMByMp")
                        or item.get("positionIM")
                        or 0
                    )
                )
                unrealized = float(item.get("unrealisedPnl") or 0)
                if params["category"] == "inverse":
                    margin *= mark
                    unrealized *= mark
                if not margin and leverage:
                    margin = value / leverage
                positions.append(
                    {
                        "source_record_id": source_id,
                        "symbol": symbol,
                        "normalized_symbol": SymbolNormalizer.normalize(symbol),
                        "side": normalize_side(str(item.get("side") or "")),
                        "position_size": size,
                        "position_value_usd": value or size * mark,
                        "entry_price": entry,
                        "mark_price": mark,
                        "liquidation_price": float(item.get("liqPrice") or 0) or None,
                        "leverage": leverage,
                        "margin_mode": margin_mode,
                        "margin_used": margin,
                        "unrealized_pnl": unrealized,
                        "open_time": self._timestamp(item.get("createdTime")),
                    }
                )
        return positions

    @staticmethod
    def _timestamp(value: Any, fallback: datetime | None = None) -> datetime:
        try:
            milliseconds = int(value or 0)
        except (TypeError, ValueError):
            milliseconds = 0
        return (
            datetime.fromtimestamp(milliseconds / 1000, tz=UTC)
            if milliseconds
            else fallback or datetime.now(UTC)
        )

    @staticmethod
    def _windows(start_time: datetime, end_time: datetime):
        cursor = start_time
        while cursor < end_time:
            window_end = min(cursor + timedelta(days=7) - timedelta(milliseconds=1), end_time)
            yield cursor, window_end
            cursor = window_end + timedelta(milliseconds=1)

    async def get_closed_positions(
        self, start_time: datetime, end_time: datetime
    ) -> list[dict[str, Any]]:
        positions: dict[str, dict[str, Any]] = {}
        for category in ("linear", "inverse"):
            for window_start, window_end in self._windows(start_time, end_time):
                rows = await self._paged(
                    "/v5/position/closed-pnl",
                    {
                        "category": category,
                        "startTime": int(window_start.timestamp() * 1000),
                        "endTime": int(window_end.timestamp() * 1000),
                    },
                )
                for item in rows:
                    order_id = str(item.get("orderId") or "")
                    close_time = self._timestamp(item.get("updatedTime"), window_end)
                    source_id = (
                        f"bybit:{category}:{order_id}"
                        if order_id
                        else (
                            f"bybit:{category}:{item.get('symbol')}:"
                            f"{int(close_time.timestamp() * 1000)}"
                        )
                    )
                    entry = float(item.get("avgEntryPrice") or 0)
                    exit_price = float(item.get("avgExitPrice") or 0)
                    size = abs(float(item.get("closedSize") or 0))
                    closing_side = str(item.get("side") or "")
                    position_side = "LONG" if closing_side.lower() == "sell" else "SHORT"
                    net_pnl = float(item.get("closedPnl") or 0)
                    fees = abs(float(item.get("openFee") or 0)) + abs(
                        float(item.get("closeFee") or 0)
                    )
                    if category == "inverse":
                        net_pnl *= exit_price
                        fees *= exit_price
                        gross_pnl = (
                            size * (1 / entry - 1 / exit_price) * exit_price
                            if entry and exit_price
                            else net_pnl + fees
                        )
                        if position_side == "SHORT":
                            gross_pnl = -gross_pnl
                    else:
                        gross_pnl = (
                            (exit_price - entry) * size
                            if position_side == "LONG"
                            else (entry - exit_price) * size
                        )
                    funding = net_pnl - gross_pnl + fees
                    leverage = float(item.get("leverage") or 0)
                    entry_value = abs(float(item.get("cumEntryValue") or 0))
                    margin = entry_value / leverage if leverage else 0
                    positions[source_id] = {
                        "source_record_id": source_id,
                        "symbol": str(item.get("symbol") or ""),
                        "normalized_symbol": SymbolNormalizer.normalize(
                            str(item.get("symbol") or "")
                        ),
                        "side": position_side,
                        "open_time": self._timestamp(
                            item.get("createdTime"), window_start
                        ),
                        "close_time": close_time,
                        "average_entry_price": entry,
                        "average_exit_price": exit_price,
                        "max_position_size": size,
                        "realized_pnl": gross_pnl,
                        "funding_fee": funding,
                        "trading_fee": fees,
                        "net_pnl": net_pnl,
                        "leverage": leverage or None,
                        "margin_used": margin,
                        "return_percent": net_pnl / margin * 100 if margin else 0,
                        "data_source": "EXCHANGE_API",
                        "data_completeness": "COMPLETE",
                    }
        return list(positions.values())

    async def _transaction_rows(
        self, start_time: datetime, end_time: datetime
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for window_start, window_end in self._windows(start_time, end_time):
            rows.extend(
                await self._paged(
                    "/v5/account/transaction-log",
                    {
                        "accountType": "UNIFIED",
                        "startTime": int(window_start.timestamp() * 1000),
                        "endTime": int(window_end.timestamp() * 1000),
                    },
                    limit=50,
                )
            )
        return rows

    async def get_history_bundle(
        self, start_time: datetime, end_time: datetime
    ) -> dict[str, Any]:
        rows = await self._transaction_rows(start_time, end_time)
        bundle: dict[str, Any] = {
            "income": [],
            "funding": [],
            "fees": [],
            "cash_flows": [],
            "complete": True,
        }
        for item in rows:
            asset = str(item.get("currency") or "USD").upper()
            if asset not in self.stable_assets:
                bundle["complete"] = False
                continue
            record_id = str(item.get("id") or item.get("transactionTime") or "")
            record_time = self._timestamp(item.get("transactionTime"), start_time)
            symbol = item.get("symbol") or None
            common = {"asset": asset, "record_time": record_time, "symbol": symbol}
            record_type = str(item.get("type") or "").upper()
            cash_flow = float(item.get("cashFlow") or 0)
            funding = float(item.get("funding") or 0)
            fee = float(item.get("fee") or 0)
            if record_type in {"TRANSFER_IN", "TRANSFER_OUT"} and cash_flow:
                bundle["cash_flows"].append(
                    {
                        **common,
                        "source_record_id": f"{record_id}:cash",
                        "amount_usd": abs(cash_flow),
                        "flow_type": (
                            "DEPOSIT" if record_type == "TRANSFER_IN" else "WITHDRAWAL"
                        ),
                    }
                )
            elif cash_flow and record_type in self.realized_types:
                bundle["income"].append(
                    {
                        **common,
                        "source_record_id": f"{record_id}:pnl",
                        "amount_usd": cash_flow,
                        "income_type": "REALIZED_PNL",
                    }
                )
            elif cash_flow:
                bundle["complete"] = False
            if funding:
                bundle["funding"].append(
                    {
                        **common,
                        "source_record_id": f"{record_id}:funding",
                        "amount_usd": funding,
                    }
                )
            if fee:
                bundle["fees"].append(
                    {
                        **common,
                        "source_record_id": f"{record_id}:fee",
                        "amount_usd": fee,
                    }
                )
        return bundle

    async def get_income_history(self, start_time, end_time):
        return (await self.get_history_bundle(start_time, end_time))["income"]

    async def get_funding_history(self, start_time, end_time):
        return (await self.get_history_bundle(start_time, end_time))["funding"]

    async def get_fee_history(self, start_time, end_time):
        return (await self.get_history_bundle(start_time, end_time))["fees"]

    async def get_cash_flow_history(self, start_time, end_time):
        return (await self.get_history_bundle(start_time, end_time))["cash_flows"]
