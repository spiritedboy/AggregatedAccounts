from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal
from zoneinfo import ZoneInfo

from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ClosedPosition, ExchangeAccount, OperationalReadModel, TrackingPeriod
from app.services.operational_read_models import get_operational_read_model

REPORT_TIMEZONE = ZoneInfo("Asia/Shanghai")
BEHAVIOR_SCHEMA_VERSION = 1
MIN_INSIGHT_SAMPLE_SIZE = 5
BehaviorPeriod = Literal["7d", "30d", "90d", "all"]
BEHAVIOR_PERIODS: tuple[BehaviorPeriod, ...] = ("7d", "30d", "90d", "all")
PERIOD_DAYS: dict[BehaviorPeriod, int | None] = {
    "7d": 7,
    "30d": 30,
    "90d": 90,
    "all": None,
}


@dataclass(frozen=True)
class BehaviorTrade:
    exchange: str
    symbol: str
    normalized_symbol: str
    side: str
    open_time: datetime | None
    close_time: datetime | None
    leverage: float | None
    margin_used: float
    net_pnl: float


def _aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


def duration_bucket(open_time: datetime | None, close_time: datetime | None) -> str | None:
    opened = _aware_utc(open_time)
    closed = _aware_utc(close_time)
    if opened is None or closed is None or closed <= opened:
        return None
    seconds = (closed - opened).total_seconds()
    if seconds < 15 * 60:
        return "lt_15m"
    if seconds < 60 * 60:
        return "15m_1h"
    if seconds < 4 * 60 * 60:
        return "1h_4h"
    if seconds < 12 * 60 * 60:
        return "4h_12h"
    if seconds < 24 * 60 * 60:
        return "12h_1d"
    if seconds <= 3 * 24 * 60 * 60:
        return "1d_3d"
    return "gt_3d"


def open_session_bucket(open_time: datetime | None) -> str | None:
    opened = _aware_utc(open_time)
    if opened is None:
        return None
    hour = opened.astimezone(REPORT_TIMEZONE).hour
    return f"{(hour // 3) * 3:02d}_{((hour // 3) + 1) * 3:02d}"


def weekday_bucket(open_time: datetime | None) -> str | None:
    opened = _aware_utc(open_time)
    if opened is None:
        return None
    return str(opened.astimezone(REPORT_TIMEZONE).weekday())


def leverage_bucket(leverage: float | None) -> str:
    if leverage is None or leverage <= 0:
        return "insufficient"
    if leverage <= 2:
        return "lte_2x"
    if leverage <= 5:
        return "2x_5x"
    if leverage <= 10:
        return "5x_10x"
    if leverage <= 20:
        return "10x_20x"
    return "gt_20x"


def margin_bucket(margin_used: float) -> str:
    if margin_used <= 0:
        return "insufficient"
    if margin_used < 100:
        return "lt_100"
    if margin_used < 500:
        return "100_500"
    if margin_used < 1_000:
        return "500_1k"
    if margin_used < 5_000:
        return "1k_5k"
    return "gte_5k"


def underlying_key(trade: BehaviorTrade) -> str:
    if trade.exchange == "POLYMARKET":
        return trade.symbol
    normalized = trade.normalized_symbol.upper()
    for suffix in ("-USDT-PERP", "-USDC-PERP", "-USD-PERP"):
        if normalized.endswith(suffix):
            return normalized[: -len(suffix)]
    return normalized or trade.symbol


def _empty_accumulator() -> dict[str, float | int]:
    return {
        "trade_count": 0,
        "win_count": 0,
        "loss_count": 0,
        "net_pnl": 0.0,
        "gross_profit": 0.0,
        "gross_loss": 0.0,
    }


def _add_trade(accumulator: dict[str, float | int], trade: BehaviorTrade) -> None:
    accumulator["trade_count"] += 1
    accumulator["net_pnl"] += trade.net_pnl
    if trade.net_pnl > 0:
        accumulator["win_count"] += 1
        accumulator["gross_profit"] += trade.net_pnl
    elif trade.net_pnl < 0:
        accumulator["loss_count"] += 1
        accumulator["gross_loss"] += trade.net_pnl


def _metrics(accumulator: dict[str, float | int]) -> dict[str, Any]:
    count = int(accumulator["trade_count"])
    win_count = int(accumulator["win_count"])
    loss_count = int(accumulator["loss_count"])
    net_pnl = float(accumulator["net_pnl"])
    gross_profit = float(accumulator["gross_profit"])
    gross_loss = float(accumulator["gross_loss"])
    average_win = gross_profit / win_count if win_count else 0.0
    average_loss = gross_loss / loss_count if loss_count else 0.0
    loss_abs = abs(gross_loss)
    average_loss_abs = abs(average_loss)
    return {
        "trade_count": count,
        "win_rate": win_count / count * 100 if count else 0.0,
        "net_pnl": net_pnl,
        "average_pnl": net_pnl / count if count else 0.0,
        "average_win": average_win,
        "average_loss": average_loss,
        "payoff_ratio": average_win / average_loss_abs if average_loss_abs else None,
        "payoff_ratio_unbounded": bool(average_win > 0 and not loss_count),
        "profit_factor": gross_profit / loss_abs if loss_abs else None,
        "profit_factor_unbounded": bool(gross_profit > 0 and not loss_count),
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
    }


def aggregate_dimension(
    trades: Iterable[BehaviorTrade],
    key_fn: Callable[[BehaviorTrade], str | None],
    definitions: tuple[tuple[str, str], ...] | None = None,
) -> list[dict[str, Any]]:
    accumulators = {
        key: _empty_accumulator() for key, _label in definitions or ()
    }
    labels = dict(definitions or ())
    for trade in trades:
        key = key_fn(trade)
        if key is None:
            continue
        accumulator = accumulators.setdefault(key, _empty_accumulator())
        _add_trade(accumulator, trade)
        labels.setdefault(key, key)
    return [
        {"key": key, "label": labels[key], **_metrics(accumulator)}
        for key, accumulator in accumulators.items()
    ]


DURATION_BUCKETS = (
    ("lt_15m", "少于 15 分钟"),
    ("15m_1h", "15 分钟～1 小时"),
    ("1h_4h", "1～4 小时"),
    ("4h_12h", "4～12 小时"),
    ("12h_1d", "12 小时～1 天"),
    ("1d_3d", "1～3 天"),
    ("gt_3d", "超过 3 天"),
)
OPEN_SESSION_BUCKETS = tuple(
    (f"{start:02d}_{start + 3:02d}", f"{start:02d}:00～{start + 3:02d}:00")
    for start in range(0, 24, 3)
)
WEEKDAY_BUCKETS = tuple(
    (str(index), label)
    for index, label in enumerate(("周一", "周二", "周三", "周四", "周五", "周六", "周日"))
)
LEVERAGE_BUCKETS = (
    ("lte_2x", "不高于 2×"),
    ("2x_5x", "2～5×"),
    ("5x_10x", "5～10×"),
    ("10x_20x", "10～20×"),
    ("gt_20x", "超过 20×"),
    ("insufficient", "数据不足"),
)
MARGIN_BUCKETS = (
    ("lt_100", "少于 100 USD"),
    ("100_500", "100～500 USD"),
    ("500_1k", "500～1,000 USD"),
    ("1k_5k", "1,000～5,000 USD"),
    ("gte_5k", "不低于 5,000 USD"),
    ("insufficient", "数据不足"),
)
SIDE_BUCKETS = (("LONG", "做多"), ("SHORT", "做空"))


def _combined_metrics(trades: Iterable[BehaviorTrade]) -> dict[str, Any]:
    accumulator = _empty_accumulator()
    for trade in trades:
        _add_trade(accumulator, trade)
    return _metrics(accumulator)


def _insights(
    *,
    trades: list[BehaviorTrade],
    duration: list[dict[str, Any]],
    open_session: list[dict[str, Any]],
    symbols: list[dict[str, Any]],
    exchanges: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    insights: list[dict[str, Any]] = []
    eligible_duration = [row for row in duration if row["trade_count"] >= MIN_INSIGHT_SAMPLE_SIZE]
    profitable_duration = [row for row in eligible_duration if row["net_pnl"] > 0]
    if profitable_duration:
        best = max(profitable_duration, key=lambda row: row["net_pnl"])
        insights.append({
            "code": "DURATION_BEST",
            "tone": "positive",
            "target_tab": "time",
            "target_key": f"duration-{best['key']}",
            "label": best["label"],
            "trade_count": best["trade_count"],
            "net_pnl": best["net_pnl"],
        })

    high_leverage_trades = [
        trade for trade in trades if trade.leverage is not None and trade.leverage > 10
    ]
    high_leverage = _combined_metrics(high_leverage_trades)
    if (
        high_leverage["trade_count"] >= MIN_INSIGHT_SAMPLE_SIZE
        and high_leverage["profit_factor"] is not None
        and high_leverage["profit_factor"] < 1
    ):
        insights.append({
            "code": "HIGH_LEVERAGE_WEAK",
            "tone": "negative",
            "target_tab": "position",
            "target_key": "leverage-10x_20x",
            "trade_count": high_leverage["trade_count"],
            "profit_factor": high_leverage["profit_factor"],
            "net_pnl": high_leverage["net_pnl"],
        })

    eligible_symbols = [row for row in symbols if row["trade_count"] >= MIN_INSIGHT_SAMPLE_SIZE]
    profitable_symbols = [row for row in eligible_symbols if row["net_pnl"] > 0]
    if profitable_symbols:
        best = max(profitable_symbols, key=lambda row: row["net_pnl"])
        insights.append({
            "code": "SYMBOL_BEST",
            "tone": "positive",
            "target_tab": "symbol",
            "target_key": f"symbol-{best['key']}",
            "label": best["label"],
            "trade_count": best["trade_count"],
            "net_pnl": best["net_pnl"],
        })

    eligible_sessions = [
        row for row in open_session if row["trade_count"] >= MIN_INSIGHT_SAMPLE_SIZE
    ]
    if len(eligible_sessions) >= 2:
        lowest = min(eligible_sessions, key=lambda row: (row["win_rate"], row["net_pnl"]))
        highest = max(eligible_sessions, key=lambda row: row["win_rate"])
        if lowest["win_rate"] < 50 or highest["win_rate"] - lowest["win_rate"] >= 15:
            insights.append({
                "code": "OPEN_SESSION_LOW_WIN_RATE",
                "tone": "warning",
                "target_tab": "time",
                "target_key": f"session-{lowest['key']}",
                "label": lowest["label"],
                "trade_count": lowest["trade_count"],
                "win_rate": lowest["win_rate"],
                "net_pnl": lowest["net_pnl"],
            })

    losing_exchanges = [
        row for row in exchanges
        if row["trade_count"] >= MIN_INSIGHT_SAMPLE_SIZE and row["net_pnl"] < 0
    ]
    if losing_exchanges:
        worst = min(losing_exchanges, key=lambda row: row["net_pnl"])
        insights.append({
            "code": "EXCHANGE_LOSS",
            "tone": "negative",
            "target_tab": "position",
            "target_key": f"exchange-{worst['key']}",
            "label": worst["label"],
            "trade_count": worst["trade_count"],
            "net_pnl": worst["net_pnl"],
        })
    return insights[:5]


def build_behavior_analysis(
    trades: Iterable[BehaviorTrade],
    period: BehaviorPeriod,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    calculated_at = _aware_utc(now) or datetime.now(UTC)
    days = PERIOD_DAYS[period]
    requested_from = calculated_at - timedelta(days=days) if days else None
    eligible = [
        trade
        for trade in trades
        if (_aware_utc(trade.close_time) is not None)
        and (requested_from is None or _aware_utc(trade.close_time) >= requested_from)
        and trade.side in {"LONG", "SHORT"}
    ]
    eligible.sort(key=lambda trade: _aware_utc(trade.close_time) or calculated_at)
    earliest = min((_aware_utc(trade.close_time) for trade in eligible), default=None)
    effective_from = max(filter(None, (requested_from, earliest)), default=None)

    duration = aggregate_dimension(
        eligible, lambda trade: duration_bucket(trade.open_time, trade.close_time), DURATION_BUCKETS
    )
    open_session = aggregate_dimension(
        eligible, lambda trade: open_session_bucket(trade.open_time), OPEN_SESSION_BUCKETS
    )
    weekday = aggregate_dimension(
        eligible, lambda trade: weekday_bucket(trade.open_time), WEEKDAY_BUCKETS
    )
    leverage = aggregate_dimension(
        eligible, lambda trade: leverage_bucket(trade.leverage), LEVERAGE_BUCKETS
    )
    position_size = aggregate_dimension(
        eligible, lambda trade: margin_bucket(trade.margin_used), MARGIN_BUCKETS
    )
    symbols = aggregate_dimension(eligible, underlying_key)
    symbols.sort(key=lambda row: (-row["net_pnl"], -row["trade_count"], row["label"]))
    exchanges = aggregate_dimension(eligible, lambda trade: trade.exchange)
    exchanges.sort(key=lambda row: (-row["net_pnl"], row["label"]))
    sides = aggregate_dimension(eligible, lambda trade: trade.side, SIDE_BUCKETS)
    invalid_duration_count = sum(
        duration_bucket(trade.open_time, trade.close_time) is None for trade in eligible
    )
    return {
        "schema_version": BEHAVIOR_SCHEMA_VERSION,
        "period": period,
        "timezone": str(REPORT_TIMEZONE),
        "requested_from": requested_from,
        "effective_from": effective_from,
        "to": calculated_at,
        "trade_count": len(eligible),
        "minimum_insight_sample_size": MIN_INSIGHT_SAMPLE_SIZE,
        "data_quality": {
            "invalid_duration_count": invalid_duration_count,
            "missing_leverage_count": sum(
                leverage_bucket(trade.leverage) == "insufficient" for trade in eligible
            ),
            "missing_margin_count": sum(
                margin_bucket(trade.margin_used) == "insufficient" for trade in eligible
            ),
            "position_size_basis": "HISTORICAL_MARGIN_USED_USD",
        },
        "duration": duration,
        "open_session": open_session,
        "weekday": weekday,
        "leverage": leverage,
        "position_size": position_size,
        "symbols": symbols,
        "sides": sides,
        "exchanges": exchanges,
        "insights": _insights(
            trades=eligible,
            duration=duration,
            open_session=open_session,
            symbols=symbols,
            exchanges=exchanges,
        ),
    }


def _scope(period: BehaviorPeriod) -> str:
    return f"PNL_BEHAVIOR_{period.upper()}"


async def _load_behavior_trades(db: AsyncSession) -> list[BehaviorTrade]:
    rows = (
        await db.execute(
            select(
                ClosedPosition.exchange,
                ClosedPosition.symbol,
                ClosedPosition.normalized_symbol,
                ClosedPosition.side,
                ClosedPosition.open_time,
                ClosedPosition.close_time,
                ClosedPosition.leverage,
                ClosedPosition.margin_used,
                ClosedPosition.net_pnl,
            )
            .join(
                ExchangeAccount,
                ClosedPosition.exchange_account_id == ExchangeAccount.id,
            )
            .join(
                TrackingPeriod,
                ClosedPosition.tracking_period_id == TrackingPeriod.id,
            )
            .where(
                ExchangeAccount.is_active.is_(True),
                TrackingPeriod.is_active.is_(True),
            )
        )
    ).all()
    return [
        BehaviorTrade(
            exchange=row.exchange,
            symbol=row.symbol,
            normalized_symbol=row.normalized_symbol,
            side=row.side,
            open_time=row.open_time,
            close_time=row.close_time,
            leverage=float(row.leverage) if row.leverage is not None else None,
            margin_used=float(row.margin_used or Decimal("0")),
            net_pnl=float(row.net_pnl or Decimal("0")),
        )
        for row in rows
    ]


async def refresh_behavior_read_models(db: AsyncSession) -> dict[BehaviorPeriod, dict[str, Any]]:
    trades = await _load_behavior_trades(db)
    calculated_at = datetime.now(UTC)
    payloads: dict[BehaviorPeriod, dict[str, Any]] = {}
    for period in BEHAVIOR_PERIODS:
        payload = build_behavior_analysis(trades, period, now=calculated_at)
        row = await db.get(OperationalReadModel, _scope(period))
        if row is None:
            row = OperationalReadModel(scope=_scope(period))
            db.add(row)
        row.payload = jsonable_encoder(payload)
        row.calculated_at = calculated_at
        payloads[period] = payload
    await db.flush()
    return payloads


async def get_behavior_analysis(
    db: AsyncSession, period: BehaviorPeriod
) -> dict[str, Any]:
    cached = await get_operational_read_model(db, _scope(period))
    if cached is not None and cached.get("schema_version") == BEHAVIOR_SCHEMA_VERSION:
        return cached
    trades = await _load_behavior_trades(db)
    return build_behavior_analysis(trades, period)
