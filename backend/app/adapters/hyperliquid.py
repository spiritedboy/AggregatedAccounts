import asyncio
from datetime import UTC, datetime
from typing import Any

from app.adapters.base import ExchangeAdapter
from app.services.normalizer import SymbolNormalizer, normalize_side


class HyperliquidAdapter(ExchangeAdapter):
    """Public-address-only Hyperliquid Info adapter.

    Official references:
    https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint
    https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/perpetuals
    """

    info_url = "https://api.hyperliquid.xyz/info"
    history_streams = frozenset({"income", "funding", "fees", "cash_flows"})

    @staticmethod
    def _normalized_perp_symbol(coin: str) -> str:
        """Normalize first-party and HIP-3 ``dex:coin`` symbols."""
        return SymbolNormalizer.normalize(coin.rsplit(":", 1)[-1])

    async def _info(self, request_type: str, **kwargs: Any) -> Any:
        return await self._request(
            "POST",
            self.info_url,
            headers={"Content-Type": "application/json"},
            json={"type": request_type, "user": self.wallet_address, **kwargs},
        )

    async def test_connection(self) -> bool:
        await self._info("clearinghouseState")
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

    async def _load_perp_dex_names(self) -> list[str]:
        rows = await self._request(
            "POST",
            self.info_url,
            headers={"Content-Type": "application/json"},
            json={"type": "perpDexs"},
        )
        names = [""]
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name") or "").strip()
            if name and name not in names:
                names.append(name)
        return names

    async def _perp_dex_names(self) -> list[str]:
        task = getattr(self, "_perp_dex_names_task", None)
        if task is None:
            task = asyncio.create_task(self._load_perp_dex_names())
            self._perp_dex_names_task = task
        return await asyncio.shield(task)

    async def _load_perp_states(self) -> list[tuple[str, dict[str, Any]]]:
        dex_names = await self._perp_dex_names()
        states = await asyncio.gather(
            *(self._info("clearinghouseState", dex=dex) for dex in dex_names)
        )
        return [
            (dex, state)
            for dex, state in zip(dex_names, states, strict=True)
            if isinstance(state, dict)
        ]

    async def _perp_states(self) -> list[tuple[str, dict[str, Any]]]:
        # Summary and positions run concurrently during a sync, so share the
        # same DEX discovery and clearinghouse requests.
        task = getattr(self, "_perp_states_task", None)
        if task is None:
            task = asyncio.create_task(self._load_perp_states())
            self._perp_states_task = task
        return await asyncio.shield(task)

    async def get_account_summary(self) -> dict[str, Any]:
        perp_states, spot, abstraction = await asyncio.gather(
            self._perp_states(),
            self._info("spotClearinghouseState"),
            self._info("userAbstraction"),
        )
        spot_prices = {0: 1.0}
        non_usdc_balances = [
            row
            for row in spot.get("balances", [])
            if int(row.get("token") or 0) != 0 and float(row.get("total") or 0)
        ]
        if non_usdc_balances:
            spot_prices.update(self._spot_token_prices(await self._spot_market_data()))

        spot_equity = 0.0
        spot_available = 0.0
        unvalued_asset_count = 0
        for row in spot.get("balances", []):
            total = float(row.get("total") or 0)
            if not total:
                continue
            price = spot_prices.get(int(row.get("token") or 0))
            if price is None:
                unvalued_asset_count += 1
                continue
            hold = float(row.get("hold") or 0)
            spot_equity += total * price
            spot_available += max(0, total - hold) * price

        perp_equity = 0.0
        perp_available = 0.0
        margin_used = 0.0
        unrealized_pnl = 0.0
        for _dex, state in perp_states:
            summary = state.get("marginSummary", {})
            account_value = float(summary.get("accountValue") or 0)
            state_margin = float(summary.get("totalMarginUsed") or 0)
            perp_equity += account_value
            margin_used += state_margin
            withdrawable = state.get("withdrawable")
            perp_available += max(
                0.0,
                float(withdrawable)
                if withdrawable not in (None, "")
                else account_value - state_margin,
            )
            unrealized_pnl += sum(
                float((wrapper.get("position") or {}).get("unrealizedPnl") or 0)
                for wrapper in state.get("assetPositions", [])
            )

        # Unified and portfolio accounts expose the single source of balance
        # truth in spotClearinghouseState. Per-DEX equity must not be added a
        # second time, but positions, margin and unrealized PnL still matter.
        unified = abstraction in {"unifiedAccount", "portfolioMargin"}
        return {
            "total_equity_usd": spot_equity if unified else perp_equity + spot_equity,
            "available_balance_usd": (
                spot_available if unified else perp_available + spot_available
            ),
            "margin_balance_usd": margin_used,
            "unrealized_pnl_usd": unrealized_pnl,
            "unvalued_asset_count": unvalued_asset_count,
            "price_source": (
                "HYPERLIQUID_UNIFIED"
                if unified
                else "HYPERLIQUID_PERP_AND_SPOT"
            ),
        }

    async def _spot_market_data(self) -> Any:
        return await self._request(
            "POST",
            self.info_url,
            headers={"Content-Type": "application/json"},
            json={"type": "spotMetaAndAssetCtxs"},
        )

    @staticmethod
    def _spot_token_prices(data: Any) -> dict[int, float]:
        if not isinstance(data, list) or len(data) != 2:
            return {}
        metadata, contexts = data
        universe = metadata.get("universe", []) if isinstance(metadata, dict) else []
        markets: list[tuple[int, int, float]] = []
        for market, context in zip(universe, contexts, strict=False):
            tokens = market.get("tokens", [])
            if len(tokens) != 2:
                continue
            price = float(context.get("markPx") or context.get("midPx") or 0)
            if price > 0:
                markets.append((int(tokens[0]), int(tokens[1]), price))

        prices = {0: 1.0}
        for _ in range(len(markets)):
            changed = False
            for base_token, quote_token, market_price in markets:
                if quote_token in prices and base_token not in prices:
                    prices[base_token] = prices[quote_token] * market_price
                    changed = True
                elif base_token in prices and quote_token not in prices:
                    prices[quote_token] = prices[base_token] / market_price
                    changed = True
            if not changed:
                break
        return prices

    async def get_balances(self) -> list[dict[str, Any]]:
        spot = await self._info("spotClearinghouseState")
        non_usdc_balances = [
            row
            for row in spot.get("balances", [])
            if int(row.get("token") or 0) != 0 and float(row.get("total") or 0)
        ]
        prices = {0: 1.0}
        if non_usdc_balances:
            prices.update(self._spot_token_prices(await self._spot_market_data()))
        balances: list[dict[str, Any]] = []
        for row in spot.get("balances", []):
            total = float(row.get("total") or 0)
            hold = float(row.get("hold") or 0)
            if not total and not hold:
                continue
            token = int(row.get("token") or 0)
            price = prices.get(token)
            balances.append(
                {
                    "asset": row["coin"],
                    "account_type": "SPOT",
                    "available": total - hold,
                    "locked": hold,
                    "value_usd": total * price if price is not None else None,
                    "price_source": (
                        "STABLECOIN_PARITY"
                        if token == 0
                        else "HYPERLIQUID_SPOT_MARK"
                    ),
                }
            )
        return balances

    async def get_open_positions(self) -> list[dict[str, Any]]:
        states = await self._perp_states()
        positions = []
        for _dex, state in states:
            for wrapper in state.get("assetPositions", []):
                item = wrapper.get("position", {})
                size = float(item.get("szi") or 0)
                if not size:
                    continue
                value = abs(float(item.get("positionValue") or 0))
                entry = float(item.get("entryPx") or 0)
                mark = value / abs(size) if size else 0
                positions.append(
                    {
                        "source_record_id": (
                            f"{item['coin']}:{normalize_side('', size)}"
                        ),
                        "symbol": item["coin"],
                        "normalized_symbol": self._normalized_perp_symbol(item["coin"]),
                        "side": normalize_side("", size),
                        "position_size": abs(size),
                        "position_value_usd": value,
                        "entry_price": entry,
                        "mark_price": mark,
                        "liquidation_price": (
                            float(item.get("liquidationPx") or 0) or None
                        ),
                        "leverage": float(
                            (item.get("leverage") or {}).get("value") or 0
                        ),
                        "margin_mode": (
                            "CROSS"
                            if (item.get("leverage") or {}).get("type") == "cross"
                            else "ISOLATED"
                        ),
                        "margin_used": float(item.get("marginUsed") or 0),
                        "unrealized_pnl": float(item.get("unrealizedPnl") or 0),
                    }
                )
        return positions

    async def _time_paginated_info(
        self,
        request_type: str,
        start_time: datetime,
        end_time: datetime,
        *,
        aggregate_by_time: bool = False,
    ) -> list[dict[str, Any]]:
        start_ms = int(start_time.timestamp() * 1000)
        end_ms = int(end_time.timestamp() * 1000)
        cursor = start_ms
        rows_by_id: dict[str, dict[str, Any]] = {}
        for _ in range(20):
            kwargs: dict[str, Any] = {"startTime": cursor, "endTime": end_ms}
            if aggregate_by_time:
                kwargs["aggregateByTime"] = True
            page = await self._info(request_type, **kwargs)
            if not page:
                break
            timestamps = [int(item.get("time") or 0) for item in page]
            for item, timestamp in zip(page, timestamps, strict=True):
                if not start_ms <= timestamp <= end_ms:
                    continue
                source_id = str(
                    item.get("tid")
                    or (
                        f"{item.get('hash')}:{item.get('oid') or ''}:"
                        f"{(item.get('delta') or {}).get('coin') or item.get('coin') or ''}:"
                        f"{timestamp}"
                    )
                )
                rows_by_id[source_id] = item
            latest = max(timestamps, default=0)
            if not latest or latest >= end_ms or latest < cursor:
                break
            cursor = latest + 1
        return sorted(
            rows_by_id.values(),
            key=lambda item: (int(item.get("time") or 0), int(item.get("tid") or 0)),
        )

    @staticmethod
    def _new_position_cycle(
        coin: str,
        side: str,
        open_time: datetime,
        complete: bool,
    ) -> dict[str, Any]:
        return {
            "coin": coin,
            "side": side,
            "open_time": open_time,
            "complete": complete,
            "open_quantity": 0.0,
            "open_notional": 0.0,
            "close_quantity": 0.0,
            "close_notional": 0.0,
            "inferred_entry_quantity": 0.0,
            "inferred_entry_notional": 0.0,
            "max_position_size": 0.0,
            "realized_pnl": 0.0,
            "trading_fee": 0.0,
        }

    @staticmethod
    def _add_hyperliquid_fee(
        cycle: dict[str, Any],
        row: dict[str, Any],
        quantity_share: float,
    ) -> None:
        fee = float(row.get("fee") or 0) * quantity_share
        if str(row.get("feeToken") or "USDC").upper().strip() == "USDC":
            cycle["trading_fee"] += fee
        elif fee:
            cycle["complete"] = False

    @classmethod
    def _closed_cycles_from_fills(
        cls,
        fills: list[dict[str, Any]],
        start_time: datetime,
        end_time: datetime,
    ) -> list[dict[str, Any]]:
        epsilon = 1e-12
        active: dict[str, dict[str, Any]] = {}
        closed: list[dict[str, Any]] = []
        start_ms = int(start_time.timestamp() * 1000)
        end_ms = int(end_time.timestamp() * 1000)

        for row in fills:
            direction = str(row.get("dir") or "")
            if "Long" not in direction and "Short" not in direction:
                continue
            timestamp = int(row.get("time") or 0)
            if not start_ms <= timestamp <= end_ms:
                continue
            coin = str(row.get("coin") or "")
            size = abs(float(row.get("sz") or 0))
            price = float(row.get("px") or 0)
            if not coin or not size:
                continue
            start_position = float(row.get("startPosition") or 0)
            delta = size if str(row.get("side") or "").upper() == "B" else -size
            end_position = start_position + delta
            if abs(end_position) < epsilon:
                end_position = 0.0

            if start_position and coin not in active:
                side = "LONG" if start_position > 0 else "SHORT"
                active[coin] = cls._new_position_cycle(
                    coin, side, start_time, False
                )
                active[coin]["max_position_size"] = abs(start_position)

            close_quantity = 0.0
            if start_position and start_position * delta < 0:
                close_quantity = min(abs(start_position), size)
            open_quantity = size - close_quantity
            fill_time = datetime.fromtimestamp(timestamp / 1000, tz=UTC)
            fill_fee_denominator = size or 1

            if close_quantity:
                side = "LONG" if start_position > 0 else "SHORT"
                cycle = active.get(coin)
                if cycle is None or cycle["side"] != side:
                    cycle = cls._new_position_cycle(coin, side, start_time, False)
                    active[coin] = cycle
                cycle["max_position_size"] = max(
                    cycle["max_position_size"], abs(start_position)
                )
                cycle["close_quantity"] += close_quantity
                cycle["close_notional"] += price * close_quantity
                closed_pnl = float(row.get("closedPnl") or 0)
                cycle["realized_pnl"] += closed_pnl
                inferred_entry = (
                    price - closed_pnl / close_quantity
                    if side == "LONG"
                    else price + closed_pnl / close_quantity
                )
                cycle["inferred_entry_quantity"] += close_quantity
                cycle["inferred_entry_notional"] += inferred_entry * close_quantity
                cls._add_hyperliquid_fee(
                    cycle, row, close_quantity / fill_fee_denominator
                )

                if not end_position or end_position * start_position < 0:
                    cycle["close_time"] = fill_time
                    cycle["closing_fill_id"] = str(
                        row.get("tid") or f"{row.get('hash')}:{timestamp}"
                    )
                    closed.append(cycle)
                    active.pop(coin, None)

            if open_quantity and end_position:
                side = "LONG" if end_position > 0 else "SHORT"
                cycle = active.get(coin)
                if cycle is None or cycle["side"] != side:
                    cycle = cls._new_position_cycle(coin, side, fill_time, True)
                    active[coin] = cycle
                cycle["open_quantity"] += open_quantity
                cycle["open_notional"] += price * open_quantity
                cycle["max_position_size"] = max(
                    cycle["max_position_size"], abs(end_position)
                )
                cls._add_hyperliquid_fee(
                    cycle, row, open_quantity / fill_fee_denominator
                )

        return closed

    async def get_closed_positions(
        self, start_time: datetime, end_time: datetime
    ) -> list[dict[str, Any]]:
        fills, funding_rows = await asyncio.gather(
            self._time_paginated_info(
                "userFillsByTime",
                start_time,
                end_time,
                aggregate_by_time=True,
            ),
            self._time_paginated_info("userFunding", start_time, end_time),
        )
        cycles = self._closed_cycles_from_fills(fills, start_time, end_time)
        positions: list[dict[str, Any]] = []
        for cycle in cycles:
            open_quantity = float(cycle["open_quantity"])
            inferred_quantity = float(cycle["inferred_entry_quantity"])
            if cycle["complete"] and open_quantity:
                entry_price = float(cycle["open_notional"]) / open_quantity
            elif inferred_quantity:
                entry_price = float(cycle["inferred_entry_notional"]) / inferred_quantity
            else:
                entry_price = 0.0
                cycle["complete"] = False
            close_quantity = float(cycle["close_quantity"])
            exit_price = (
                float(cycle["close_notional"]) / close_quantity if close_quantity else 0.0
            )
            funding_fee = 0.0
            for row in funding_rows:
                delta = row.get("delta") or row
                timestamp = int(row.get("time") or 0)
                if (
                    str(delta.get("coin") or "") == cycle["coin"]
                    and int(cycle["open_time"].timestamp() * 1000)
                    <= timestamp
                    <= int(cycle["close_time"].timestamp() * 1000)
                ):
                    funding_fee += float(delta.get("usdc") or 0)
            realized_pnl = float(cycle["realized_pnl"])
            trading_fee = float(cycle["trading_fee"])
            net_pnl = realized_pnl + funding_fee - trading_fee
            initial_notional = entry_price * float(cycle["max_position_size"])
            positions.append(
                {
                    "source_record_id": (
                        f"hyperliquid:{cycle['coin']}:{cycle['closing_fill_id']}"
                    ),
                    "symbol": cycle["coin"],
                    "normalized_symbol": self._normalized_perp_symbol(cycle["coin"]),
                    "side": cycle["side"],
                    "open_time": cycle["open_time"],
                    "close_time": cycle["close_time"],
                    "average_entry_price": entry_price,
                    "average_exit_price": exit_price,
                    "max_position_size": cycle["max_position_size"],
                    "realized_pnl": realized_pnl,
                    "funding_fee": funding_fee,
                    "trading_fee": trading_fee,
                    "net_pnl": net_pnl,
                    "return_percent": (
                        realized_pnl / initial_notional * 100 if initial_notional else 0
                    ),
                    "data_source": "EXCHANGE_FILLS_RECONSTRUCTED",
                    "data_completeness": (
                        "COMPLETE" if cycle["complete"] else "PARTIAL"
                    ),
                }
            )
        return positions

    async def get_income_history(
        self, start_time: datetime, end_time: datetime
    ) -> list[dict[str, Any]]:
        fills = await self._info(
            "userFillsByTime",
            startTime=int(start_time.timestamp() * 1000),
            endTime=int(end_time.timestamp() * 1000),
            aggregateByTime=True,
        )
        return [
            {
                "source_record_id": str(row.get("tid")),
                "asset": "USDC",
                "amount_usd": float(row.get("closedPnl") or 0),
                "income_type": "REALIZED_PNL",
                "record_time": datetime.fromtimestamp(
                    int(row["time"]) / 1000, tz=start_time.tzinfo
                ),
                "symbol": row.get("coin"),
            }
            for row in fills
            if int(row["time"]) >= int(start_time.timestamp() * 1000)
        ]

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

    async def get_history_bundle(
        self, start_time: datetime, end_time: datetime
    ) -> dict[str, Any]:
        start_ms = int(start_time.timestamp() * 1000)
        end_ms = int(end_time.timestamp() * 1000)
        fills, funding_rows, ledger_rows = await asyncio.gather(
            self._info(
                "userFillsByTime",
                startTime=start_ms,
                endTime=end_ms,
                aggregateByTime=True,
            ),
            self._info("userFunding", startTime=start_ms, endTime=end_ms),
            self._info(
                "userNonFundingLedgerUpdates",
                startTime=start_ms,
                endTime=end_ms,
            ),
        )
        bundle: dict[str, Any] = {
            "income": [],
            "funding": [],
            "fees": [],
            "cash_flows": [],
            "complete": True,
        }
        for row in fills:
            timestamp = int(row.get("time") or 0)
            if timestamp < start_ms:
                continue
            source_id = str(row.get("tid") or f"{row.get('hash')}:{timestamp}")
            record_time = datetime.fromtimestamp(timestamp / 1000, tz=UTC)
            closed_pnl = float(row.get("closedPnl") or 0)
            if closed_pnl:
                bundle["income"].append(
                    {
                        "source_record_id": f"{source_id}:pnl",
                        "asset": "USDC",
                        "amount_usd": closed_pnl,
                        "income_type": "REALIZED_PNL",
                        "record_time": record_time,
                        "symbol": row.get("coin"),
                    }
                )
            fee = float(row.get("fee") or 0)
            if fee:
                fee_token = str(row.get("feeToken") or "USDC").upper()
                if fee_token != "USDC":
                    bundle["complete"] = False
                else:
                    bundle["fees"].append(
                        {
                            "source_record_id": f"{source_id}:fee",
                            "asset": "USDC",
                            "amount_usd": fee,
                            "record_time": record_time,
                            "symbol": row.get("coin"),
                        }
                    )

        for row in funding_rows:
            timestamp = int(row.get("time") or 0)
            delta = row.get("delta") or row
            amount = float(delta.get("usdc") or 0)
            bundle["funding"].append(
                {
                    "source_record_id": (
                        f"{row.get('hash') or 'funding'}:{delta.get('coin') or ''}:{timestamp}"
                    ),
                    "asset": "USDC",
                    "amount_usd": amount,
                    "record_time": datetime.fromtimestamp(timestamp / 1000, tz=UTC),
                    "symbol": delta.get("coin"),
                }
            )

        wallet = (self.wallet_address or "").lower()
        for row in ledger_rows:
            timestamp = int(row.get("time") or 0)
            delta = row.get("delta") or {}
            event_type = str(delta.get("type") or "")
            amount = self._ledger_amount(delta)
            flow_type = self._ledger_flow_type(delta, wallet)
            if amount is None or flow_type is None:
                if amount:
                    bundle["complete"] = False
                continue
            bundle["cash_flows"].append(
                {
                    "source_record_id": (
                        f"{row.get('hash') or event_type}:{event_type}:{timestamp}"
                    ),
                    "asset": "USDC",
                    "amount_usd": abs(amount),
                    "record_time": datetime.fromtimestamp(timestamp / 1000, tz=UTC),
                    "flow_type": flow_type,
                }
            )
        return bundle

    @staticmethod
    def _ledger_amount(delta: dict[str, Any]) -> float | None:
        for field in ("usdc", "usdcValue", "netWithdrawnUsd", "requestedUsd"):
            value = delta.get(field)
            if value not in (None, ""):
                return float(value)
        return None

    @staticmethod
    def _ledger_flow_type(delta: dict[str, Any], wallet: str) -> str | None:
        event_type = str(delta.get("type") or "")
        if event_type in {"deposit", "vaultWithdraw", "vaultDistribution"}:
            return "DEPOSIT"
        if event_type in {"withdraw", "vaultDeposit"}:
            return "WITHDRAWAL"
        if event_type == "accountClassTransfer":
            return "DEPOSIT" if bool(delta.get("toPerp")) else "WITHDRAWAL"
        if event_type in {"internalTransfer", "subAccountTransfer", "spotTransfer", "send"}:
            destination = str(delta.get("destination") or "").lower()
            user = str(delta.get("user") or "").lower()
            if destination == wallet and user == wallet:
                amount = HyperliquidAdapter._ledger_amount(delta)
                if amount:
                    return "DEPOSIT" if amount > 0 else "WITHDRAWAL"
            if destination == wallet:
                return "DEPOSIT"
            if user == wallet:
                return "WITHDRAWAL"
            amount = HyperliquidAdapter._ledger_amount(delta)
            if amount:
                return "DEPOSIT" if amount > 0 else "WITHDRAWAL"
        return None
