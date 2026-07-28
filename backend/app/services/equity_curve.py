import calendar
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import case, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import AccountBalanceSnapshot, ExchangeAccount, PortfolioEquityPoint

EquityRange = Literal["1d", "1w", "1m", "6m", "1y"]


@dataclass(frozen=True)
class RangeSpec:
    months: int
    days: int
    source: str
    resolution: str
    fallback_bucket_seconds: int


RANGE_SPECS: dict[EquityRange, RangeSpec] = {
    "1d": RangeSpec(0, 1, "portfolio_equity_points", "5m", 5 * 60),
    "1w": RangeSpec(0, 7, "portfolio_equity_30m", "30m", 30 * 60),
    "1m": RangeSpec(1, 0, "portfolio_equity_2h", "2h", 2 * 60 * 60),
    "6m": RangeSpec(6, 0, "portfolio_equity_6h", "6h", 6 * 60 * 60),
    "1y": RangeSpec(12, 0, "portfolio_equity_12h", "12h", 12 * 60 * 60),
}


class _CurveCache:
    def __init__(self) -> None:
        self._values: dict[str, tuple[float, dict[str, Any]]] = {}

    def get(self, key: str) -> dict[str, Any] | None:
        item = self._values.get(key)
        if not item:
            return None
        expires_at, value = item
        if expires_at <= time.monotonic():
            self._values.pop(key, None)
            return None
        return value

    def set(self, key: str, value: dict[str, Any]) -> None:
        ttl = max(settings.equity_curve_cache_seconds, 1)
        self._values[key] = (time.monotonic() + ttl, value)

    def clear(self) -> None:
        self._values.clear()


curve_cache = _CurveCache()


def _floor_five_minutes(value: datetime) -> datetime:
    normalized = value.astimezone(UTC)
    return normalized.replace(
        minute=(normalized.minute // 5) * 5,
        second=0,
        microsecond=0,
    )


def _subtract_months(value: datetime, months: int) -> datetime:
    total_months = value.year * 12 + value.month - 1 - months
    year, month_index = divmod(total_months, 12)
    month = month_index + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def _range_start(end: datetime, spec: RangeSpec) -> datetime:
    if spec.months:
        return _subtract_months(end, spec.months)
    return end - timedelta(days=spec.days)


async def capture_portfolio_equity_point(
    db: AsyncSession,
    *,
    now: datetime | None = None,
) -> PortfolioEquityPoint | None:
    captured_at = now or datetime.now(UTC)
    ranked = (
        select(
            AccountBalanceSnapshot.total_equity_usd.label("total_equity_usd"),
            AccountBalanceSnapshot.available_balance_usd.label("available_balance_usd"),
            AccountBalanceSnapshot.margin_balance_usd.label("margin_balance_usd"),
            AccountBalanceSnapshot.unrealized_pnl_usd.label("unrealized_pnl_usd"),
            AccountBalanceSnapshot.unvalued_asset_count.label("unvalued_asset_count"),
            AccountBalanceSnapshot.recorded_at.label("recorded_at"),
            func.row_number()
            .over(
                partition_by=AccountBalanceSnapshot.exchange_account_id,
                order_by=AccountBalanceSnapshot.recorded_at.desc(),
            )
            .label("row_number"),
        )
        .join(
            ExchangeAccount,
            ExchangeAccount.id == AccountBalanceSnapshot.exchange_account_id,
        )
        .where(
            ExchangeAccount.is_active.is_(True),
            AccountBalanceSnapshot.recorded_at <= captured_at,
        )
        .subquery()
    )
    stale_before = captured_at - timedelta(
        seconds=max(settings.sync_balance_seconds * 3, 180)
    )
    summary = (
        await db.execute(
            select(
                func.coalesce(func.sum(ranked.c.total_equity_usd), 0),
                func.coalesce(func.sum(ranked.c.available_balance_usd), 0),
                func.coalesce(func.sum(ranked.c.margin_balance_usd), 0),
                func.coalesce(func.sum(ranked.c.unrealized_pnl_usd), 0),
                func.coalesce(func.sum(ranked.c.unvalued_asset_count), 0),
                func.count(),
                func.coalesce(
                    func.sum(
                        case((ranked.c.recorded_at < stale_before, 1), else_=0)
                    ),
                    0,
                ),
                func.max(ranked.c.recorded_at),
            ).where(ranked.c.row_number == 1)
        )
    ).one()
    account_count = int(summary[5] or 0)
    if account_count == 0:
        return None

    values = {
        "bucket_time": _floor_five_minutes(captured_at),
        "total_equity_usd": Decimal(summary[0]),
        "available_balance_usd": Decimal(summary[1]),
        "margin_balance_usd": Decimal(summary[2]),
        "unrealized_pnl_usd": Decimal(summary[3]),
        "unvalued_asset_count": int(summary[4] or 0),
        "account_count": account_count,
        "stale_account_count": int(summary[6] or 0),
        "source_latest_at": summary[7],
    }
    if db.bind and db.bind.dialect.name == "postgresql":
        statement = pg_insert(PortfolioEquityPoint).values(**values)
        statement = statement.on_conflict_do_update(
            index_elements=[PortfolioEquityPoint.bucket_time],
            set_={key: value for key, value in values.items() if key != "bucket_time"},
        )
        await db.execute(statement)
        point = await db.get(PortfolioEquityPoint, values["bucket_time"])
    else:
        point = await db.get(PortfolioEquityPoint, values["bucket_time"])
        if point is None:
            point = PortfolioEquityPoint(**values)
            db.add(point)
        else:
            for key, value in values.items():
                setattr(point, key, value)
    await db.commit()
    curve_cache.clear()
    return point


def _row_to_point(row: Any) -> dict[str, Any]:
    return {
        "timestamp": row.bucket_time,
        "equity": float(row.total_equity_usd or 0),
        "available_balance": float(row.available_balance_usd or 0),
        "margin_balance": float(row.margin_balance_usd or 0),
        "unrealized_pnl": float(row.unrealized_pnl_usd or 0),
        "account_count": int(row.account_count or 0),
        "stale_account_count": int(row.stale_account_count or 0),
        "source_latest_at": row.source_latest_at,
    }


def _downsample(
    rows: list[PortfolioEquityPoint],
    bucket_seconds: int,
) -> list[PortfolioEquityPoint]:
    latest_by_bucket: dict[int, PortfolioEquityPoint] = {}
    for row in rows:
        key = int(row.bucket_time.timestamp()) // bucket_seconds
        latest_by_bucket[key] = row
    return [latest_by_bucket[key] for key in sorted(latest_by_bucket)]


async def _aggregate_exists(db: AsyncSession, name: str) -> bool:
    if not db.bind or db.bind.dialect.name != "postgresql":
        return False
    return bool(await db.scalar(text("SELECT to_regclass(:name)"), {"name": name}))


async def get_equity_curve(
    db: AsyncSession,
    range_key: EquityRange,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    end = now or datetime.now(UTC)
    spec = RANGE_SPECS[range_key]
    start = _range_start(end, spec)
    cache_key = f"{range_key}:{_floor_five_minutes(end).isoformat()}"
    cached = curve_cache.get(cache_key)
    if cached is not None:
        return cached

    if spec.source != "portfolio_equity_points" and await _aggregate_exists(
        db, spec.source
    ):
        rows = (
            await db.execute(
                text(
                    f"""
                    SELECT
                        bucket_time,
                        total_equity_usd,
                        available_balance_usd,
                        margin_balance_usd,
                        unrealized_pnl_usd,
                        account_count,
                        stale_account_count,
                        source_latest_at
                    FROM {spec.source}
                    WHERE bucket_time >= :start AND bucket_time <= :end
                    ORDER BY bucket_time
                    """
                ),
                {"start": start, "end": end},
            )
        ).all()
    else:
        raw_rows = (
            await db.scalars(
                select(PortfolioEquityPoint)
                .where(
                    PortfolioEquityPoint.bucket_time >= start,
                    PortfolioEquityPoint.bucket_time <= end,
                )
                .order_by(PortfolioEquityPoint.bucket_time)
            )
        ).all()
        rows = (
            raw_rows
            if spec.source == "portfolio_equity_points"
            else _downsample(list(raw_rows), spec.fallback_bucket_seconds)
        )

    points = [_row_to_point(row) for row in rows]
    first_equity = points[0]["equity"] if points else None
    last_equity = points[-1]["equity"] if points else None
    change_amount = (
        last_equity - first_equity
        if first_equity is not None and last_equity is not None
        else None
    )
    change_percent = (
        change_amount / first_equity * 100
        if change_amount is not None and first_equity
        else None
    )
    result = {
        "range": range_key,
        "sample_interval": "5m",
        "resolution": spec.resolution,
        "from": start,
        "to": end,
        "points": points,
        "change": {
            "amount": change_amount,
            "percent": change_percent,
        },
    }
    curve_cache.set(cache_key, result)
    return result


async def backfill_portfolio_equity_points(db: AsyncSession) -> int:
    """Backfill exact five-minute buckets from existing account snapshots."""
    if not db.bind or db.bind.dialect.name != "postgresql":
        return 0
    result = await db.execute(
        text(
            """
            WITH buckets AS (
                SELECT DISTINCT
                    time_bucket(INTERVAL '5 minutes', s.recorded_at) AS bucket_time
                FROM account_balance_snapshots s
                JOIN exchange_accounts a ON a.id = s.exchange_account_id
                WHERE a.is_active = true
            ),
            eligible_accounts AS (
                SELECT
                    b.bucket_time,
                    a.id AS exchange_account_id
                FROM buckets b
                JOIN exchange_accounts a
                    ON a.is_active = true
                    AND a.tracking_started_at < b.bucket_time + INTERVAL '5 minutes'
            ),
            per_account AS (
                SELECT
                    eligible.bucket_time,
                    eligible.exchange_account_id,
                    snapshot.total_equity_usd,
                    snapshot.available_balance_usd,
                    snapshot.margin_balance_usd,
                    snapshot.unrealized_pnl_usd,
                    snapshot.unvalued_asset_count,
                    snapshot.recorded_at AS source_latest_at
                FROM eligible_accounts eligible
                JOIN LATERAL (
                    SELECT
                        s.total_equity_usd,
                        s.available_balance_usd,
                        s.margin_balance_usd,
                        s.unrealized_pnl_usd,
                        s.unvalued_asset_count,
                        s.recorded_at
                    FROM account_balance_snapshots s
                    WHERE
                        s.exchange_account_id = eligible.exchange_account_id
                        AND s.recorded_at < eligible.bucket_time + INTERVAL '5 minutes'
                        AND s.recorded_at >= eligible.bucket_time - INTERVAL '5 minutes'
                    ORDER BY s.recorded_at DESC
                    LIMIT 1
                ) snapshot ON true
            ),
            expected_accounts AS (
                SELECT bucket_time, count(*)::integer AS expected_count
                FROM eligible_accounts
                GROUP BY bucket_time
            ),
            aggregated AS (
                SELECT
                    bucket_time,
                    sum(total_equity_usd) AS total_equity_usd,
                    sum(available_balance_usd) AS available_balance_usd,
                    sum(margin_balance_usd) AS margin_balance_usd,
                    sum(unrealized_pnl_usd) AS unrealized_pnl_usd,
                    sum(unvalued_asset_count)::integer AS unvalued_asset_count,
                    count(*)::integer AS account_count,
                    0::integer AS stale_account_count,
                    max(source_latest_at) AS source_latest_at
                FROM per_account
                GROUP BY bucket_time
            )
            INSERT INTO portfolio_equity_points (
                bucket_time,
                total_equity_usd,
                available_balance_usd,
                margin_balance_usd,
                unrealized_pnl_usd,
                unvalued_asset_count,
                account_count,
                stale_account_count,
                source_latest_at
            )
            SELECT
                bucket_time,
                total_equity_usd,
                available_balance_usd,
                margin_balance_usd,
                unrealized_pnl_usd,
                unvalued_asset_count,
                account_count,
                stale_account_count,
                source_latest_at
            FROM aggregated
            JOIN expected_accounts USING (bucket_time)
            WHERE aggregated.account_count = expected_accounts.expected_count
            ON CONFLICT (bucket_time) DO UPDATE SET
                total_equity_usd = EXCLUDED.total_equity_usd,
                available_balance_usd = EXCLUDED.available_balance_usd,
                margin_balance_usd = EXCLUDED.margin_balance_usd,
                unrealized_pnl_usd = EXCLUDED.unrealized_pnl_usd,
                unvalued_asset_count = EXCLUDED.unvalued_asset_count,
                account_count = EXCLUDED.account_count,
                stale_account_count = EXCLUDED.stale_account_count,
                source_latest_at = EXCLUDED.source_latest_at
            """
        )
    )
    await db.commit()
    curve_cache.clear()
    return result.rowcount or 0
