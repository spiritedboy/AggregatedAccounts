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
    history_streams = frozenset({"income", "funding", "fees", "cash_flows"})

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

    async def _position_history_rows(
        self,
        inst_type: str,
        start_time: datetime,
        end_time: datetime,
    ) -> list[dict[str, Any]]:
        start_ms = int(start_time.timestamp() * 1000)
        end_ms = int(end_time.timestamp() * 1000)
        rows: list[dict[str, Any]] = []
        after: str | None = None
        seen_cursors: set[str] = set()
        for _ in range(50):
            params: dict[str, Any] = {"instType": inst_type, "limit": 100}
            if after:
                params["after"] = after
            page = await self._get("/api/v5/account/positions-history", params)
            if not page:
                break

            timestamps = [int(item.get("uTime") or 0) for item in page]
            rows.extend(
                item
                for item, timestamp in zip(page, timestamps, strict=True)
                if start_ms <= timestamp <= end_ms
            )
            oldest = min((timestamp for timestamp in timestamps if timestamp), default=0)
            if oldest < start_ms or len(page) < 100:
                break
            next_after = str(oldest)
            if next_after in seen_cursors:
                break
            seen_cursors.add(next_after)
            after = next_after
        return rows

    async def get_closed_positions(
        self, start_time: datetime, end_time: datetime
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for inst_type in ("SWAP", "FUTURES"):
            rows.extend(
                await self._position_history_rows(inst_type, start_time, end_time)
            )

        positions_by_id: dict[str, dict[str, Any]] = {}
        for item in rows:
            close_timestamp = int(item.get("uTime") or 0)
            if not close_timestamp:
                continue
            open_timestamp = int(item.get("cTime") or 0)
            open_time = (
                datetime.fromtimestamp(open_timestamp / 1000, tz=UTC)
                if open_timestamp
                else start_time
            )
            close_time = datetime.fromtimestamp(close_timestamp / 1000, tz=UTC)
            pnl = float(item.get("pnl") or 0)
            fee = float(item.get("fee") or 0)
            funding_fee = float(item.get("fundingFee") or 0)
            liquidation_penalty = float(item.get("liqPenalty") or 0)
            settled_pnl = float(item.get("settledPnl") or 0)
            net_pnl = float(
                item.get("realizedPnl")
                or pnl + fee + funding_fee + liquidation_penalty + settled_pnl
            )
            source_record_id = (
                f"okx:{item.get('instType') or 'UNKNOWN'}:"
                f"{item.get('posId') or item.get('instId') or 'position'}:"
                f"{close_timestamp}"
            )
            positions_by_id[source_record_id] = {
                "source_record_id": source_record_id,
                "symbol": item["instId"],
                "normalized_symbol": SymbolNormalizer.normalize(item["instId"]),
                "side": normalize_side(
                    str(item.get("direction") or item.get("posSide") or "")
                ),
                "open_time": open_time,
                "close_time": close_time,
                "average_entry_price": float(item.get("openAvgPx") or 0),
                "average_exit_price": float(item.get("closeAvgPx") or 0),
                "max_position_size": abs(
                    float(item.get("openMaxPos") or item.get("closeTotalPos") or 0)
                ),
                "realized_pnl": pnl,
                "funding_fee": funding_fee,
                "trading_fee": -fee,
                "net_pnl": net_pnl,
                "return_percent": float(item.get("pnlRatio") or 0) * 100,
                "data_source": "EXCHANGE_API",
                "data_completeness": "COMPLETE" if open_timestamp else "PARTIAL",
            }
        return list(positions_by_id.values())

    async def get_income_history(
        self, start_time: datetime, end_time: datetime
    ) -> list[dict[str, Any]]:
        return (await self.get_history_bundle(start_time, end_time))["income"]

    async def _bill_rows(
        self, start_time: datetime, end_time: datetime
    ) -> list[dict[str, Any]]:
        base_params: dict[str, Any] = {
            "begin": int(start_time.timestamp() * 1000),
            "end": int(end_time.timestamp() * 1000),
            "limit": 100,
        }
        rows: list[dict[str, Any]] = []
        after: str | None = None
        for _ in range(50):
            params = {**base_params}
            if after:
                params["after"] = after
            page = await self._get("/api/v5/account/bills-archive", params)
            rows.extend(page)
            if len(page) < 100:
                break
            next_after = str(page[-1].get("billId") or "")
            if not next_after or next_after == after:
                break
            after = next_after
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
        stable_assets = {"USD", "USDT", "USDC"}
        for row in rows:
            timestamp = int(row.get("ts") or 0)
            if timestamp < int(start_time.timestamp() * 1000):
                continue
            asset = str(row.get("ccy") or "USD").upper()
            if asset not in stable_assets:
                bundle["complete"] = False
                continue
            bill_id = str(row.get("billId") or f"{timestamp}")
            subtype = str(row.get("subType") or "")
            record_time = datetime.fromtimestamp(timestamp / 1000, tz=UTC)
            common = {
                "asset": asset,
                "record_time": record_time,
                "symbol": row.get("instId") or None,
            }
            recognized = False
            pnl = float(row.get("pnl") or 0)
            if pnl and subtype not in {"173", "174"}:
                recognized = True
                bundle["income"].append(
                    {
                        **common,
                        "source_record_id": f"{bill_id}:pnl",
                        "amount_usd": pnl,
                        "income_type": "REALIZED_PNL",
                    }
                )
            if subtype in {"173", "174"}:
                recognized = True
                amount = pnl or float(row.get("balChg") or 0)
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
            source_account = str(row.get("from") or "")
            destination_account = str(row.get("to") or "")
            if source_account and destination_account and "18" in {
                source_account,
                destination_account,
            }:
                amount = abs(float(row.get("balChg") or 0))
                if amount:
                    recognized = True
                    bundle["cash_flows"].append(
                        {
                            **common,
                            "source_record_id": f"{bill_id}:cash",
                            "amount_usd": amount,
                            "flow_type": (
                                "DEPOSIT" if destination_account == "18" else "WITHDRAWAL"
                            ),
                        }
                    )
            if float(row.get("balChg") or 0) and not recognized:
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
