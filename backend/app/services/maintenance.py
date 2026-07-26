from datetime import UTC, datetime, time
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ClosedPosition, DailyPnlSnapshot, SecurityAuditLog


def canonical_polymarket_closed_source_id(source_record_id: str) -> str:
    if source_record_id.startswith("poly-closed:"):
        return source_record_id
    base, separator, suffix = source_record_id.rpartition(":")
    stable_id = base if separator and suffix.isdigit() else source_record_id
    return f"poly-closed:{stable_id}"


async def cleanup_polymarket_closed_positions(
    db: AsyncSession,
    *,
    apply: bool,
) -> dict[str, Any]:
    rows = (
        await db.scalars(
            select(ClosedPosition)
            .where(ClosedPosition.exchange == "POLYMARKET")
            .order_by(ClosedPosition.created_at)
        )
    ).all()
    groups: dict[tuple[Any, Any, str], list[ClosedPosition]] = {}
    for row in rows:
        canonical = canonical_polymarket_closed_source_id(row.source_record_id)
        groups.setdefault(
            (row.exchange_account_id, row.tracking_period_id, canonical),
            [],
        ).append(row)

    duplicate_groups = [items for items in groups.values() if len(items) > 1]
    delete_rows: list[ClosedPosition] = []
    keepers: list[tuple[ClosedPosition, str]] = []
    affected_periods: set[tuple[Any, Any]] = set()
    for (_, _, canonical), items in groups.items():
        keeper = max(
            items,
            key=lambda row: (row.updated_at, row.created_at, row.close_time),
        )
        keepers.append((keeper, canonical))
        duplicates = [row for row in items if row.id != keeper.id]
        if duplicates:
            delete_rows.extend(duplicates)
            affected_periods.add((keeper.exchange_account_id, keeper.tracking_period_id))

    result = {
        "scanned": len(rows),
        "duplicate_groups": len(duplicate_groups),
        "duplicates_to_delete": len(delete_rows),
        "source_ids_to_normalize": sum(
            row.source_record_id != canonical for row, canonical in keepers
        ),
        "applied": apply,
    }
    if not apply:
        return result

    for row in delete_rows:
        await db.delete(row)
    await db.flush()
    for row, canonical in keepers:
        row.source_record_id = canonical
    await db.flush()

    for account_id, period_id in affected_periods:
        daily_rows = (
            await db.scalars(
                select(DailyPnlSnapshot).where(
                    DailyPnlSnapshot.exchange_account_id == account_id,
                    DailyPnlSnapshot.tracking_period_id == period_id,
                )
            )
        ).all()
        for snapshot in daily_rows:
            start = datetime.combine(snapshot.snapshot_date, time.min, tzinfo=UTC)
            end = datetime.combine(snapshot.snapshot_date, time.max, tzinfo=UTC)
            realized = await db.scalar(
                select(func.sum(ClosedPosition.realized_pnl)).where(
                    ClosedPosition.exchange_account_id == account_id,
                    ClosedPosition.tracking_period_id == period_id,
                    ClosedPosition.close_time >= start,
                    ClosedPosition.close_time <= end,
                )
            )
            snapshot.realized_pnl = realized or Decimal("0")

    db.add(
        SecurityAuditLog(
            action="POLYMARKET_DUPLICATES_CLEANED",
            outcome="SUCCESS",
            client_ip="maintenance",
            details=result,
        )
    )
    await db.commit()
    return result
