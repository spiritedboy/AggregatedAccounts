import hashlib
import hmac
import time
from datetime import UTC, datetime
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
        futures = await self._signed_get(self.futures_base, "/fapi/v3/account")
        return {
            "total_equity_usd": float(futures.get("totalWalletBalance", 0))
            + float(futures.get("totalUnrealizedProfit", 0)),
            "available_balance_usd": float(futures.get("availableBalance", 0)),
            "margin_balance_usd": float(futures.get("totalInitialMargin", 0)),
            "unrealized_pnl_usd": float(futures.get("totalUnrealizedProfit", 0)),
            "unvalued_asset_count": 0,
            "price_source": "BINANCE_FAPI",
        }

    async def get_balances(self) -> list[dict[str, Any]]:
        spot = await self._signed_get(
            self.spot_base, "/api/v3/account", {"omitZeroBalances": "true"}
        )
        return [
            {
                "asset": item["asset"],
                "available": float(item["free"]),
                "locked": float(item["locked"]),
                "value_usd": None,
            }
            for item in spot.get("balances", [])
        ]

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
