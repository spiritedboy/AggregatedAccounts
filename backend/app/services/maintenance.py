from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import (
    AccountBalanceSnapshot,
    AssetBalanceSnapshot,
    ClosedPosition,
    DailyPnlSnapshot,
    PositionSnapshot,
    SecurityAuditLog,
    SyncJob,
)


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


async def apply_data_retention(
    db: AsyncSession,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Prune operational/high-frequency rows while retaining business history.

    Balance rows are removed only when the corresponding daily aggregate
    already exists, so an interrupted aggregation never causes data loss.
    A retention value of 0 disables deletion for that category.
    """
    current_time = now or datetime.now(UTC)
    job_cutoff = (
        current_time - timedelta(days=settings.sync_job_retention_days)
        if settings.sync_job_retention_days > 0
        else None
    )
    balance_cutoff = (
        current_time - timedelta(days=settings.balance_snapshot_retention_days)
        if settings.balance_snapshot_retention_days > 0
        else None
    )
    deleted_jobs = 0
    if job_cutoff is not None:
        deleted_jobs = (
            await db.execute(
                delete(SyncJob).where(
                    SyncJob.started_at < job_cutoff,
                    SyncJob.status != "RUNNING",
                )
            )
        ).rowcount or 0

    deleted_balances = 0
    deleted_asset_balances = 0
    deleted_positions = 0
    if balance_cutoff is not None:
        summarized_day_exists = exists(
            select(DailyPnlSnapshot.id).where(
                DailyPnlSnapshot.exchange_account_id
                == AccountBalanceSnapshot.exchange_account_id,
                DailyPnlSnapshot.tracking_period_id
                == AccountBalanceSnapshot.tracking_period_id,
                func.date(DailyPnlSnapshot.snapshot_date)
                == func.date(AccountBalanceSnapshot.recorded_at),
            )
        )
        deleted_balances = (
            await db.execute(
                delete(AccountBalanceSnapshot).where(
                    AccountBalanceSnapshot.recorded_at < balance_cutoff,
                    summarized_day_exists,
                )
            )
        ).rowcount or 0
        asset_day_exists = exists(
            select(DailyPnlSnapshot.id).where(
                DailyPnlSnapshot.exchange_account_id
                == AssetBalanceSnapshot.exchange_account_id,
                DailyPnlSnapshot.tracking_period_id
                == AssetBalanceSnapshot.tracking_period_id,
                func.date(DailyPnlSnapshot.snapshot_date)
                == func.date(AssetBalanceSnapshot.recorded_at),
            )
        )
        deleted_asset_balances = (
            await db.execute(
                delete(AssetBalanceSnapshot).where(
                    AssetBalanceSnapshot.recorded_at < balance_cutoff,
                    asset_day_exists,
                )
            )
        ).rowcount or 0
        position_day_exists = exists(
            select(DailyPnlSnapshot.id).where(
                DailyPnlSnapshot.exchange_account_id
                == PositionSnapshot.exchange_account_id,
                DailyPnlSnapshot.tracking_period_id
                == PositionSnapshot.tracking_period_id,
                func.date(DailyPnlSnapshot.snapshot_date)
                == func.date(PositionSnapshot.recorded_at),
            )
        )
        deleted_positions = (
            await db.execute(
                delete(PositionSnapshot).where(
                    PositionSnapshot.recorded_at < balance_cutoff,
                    position_day_exists,
                )
            )
        ).rowcount or 0
    result = {
        "sync_jobs_deleted": deleted_jobs,
        "balance_snapshots_deleted": deleted_balances,
        "asset_balance_snapshots_deleted": deleted_asset_balances,
        "position_snapshots_deleted": deleted_positions,
        "sync_job_cutoff": job_cutoff.isoformat() if job_cutoff else None,
        "balance_snapshot_cutoff": (
            balance_cutoff.isoformat() if balance_cutoff else None
        ),
        "sync_job_retention_enabled": job_cutoff is not None,
        "balance_snapshot_retention_enabled": balance_cutoff is not None,
    }
    db.add(
        SecurityAuditLog(
            action="DATA_RETENTION_APPLIED",
            outcome="SUCCESS",
            client_ip="maintenance",
            details=result,
        )
    )
    await db.commit()
    return result
