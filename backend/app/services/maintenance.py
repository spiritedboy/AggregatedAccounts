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
    ExchangeAccount,
    IncomeRecord,
    PositionSnapshot,
    SecurityAuditLog,
    SyncJob,
    TrackingPeriod,
)


def canonical_polymarket_closed_source_id(source_record_id: str) -> str:
    if source_record_id.startswith("poly-closed:"):
        return source_record_id
    base, separator, suffix = source_record_id.rpartition(":")
    stable_id = base if separator and suffix.isdigit() else source_record_id
    return f"poly-closed:{stable_id}"


def canonical_okx_closed_source_id(source_record_id: str) -> str:
    parts = source_record_id.split(":")
    if (
        len(parts) == 4
        and parts[0] == "okx"
        and parts[2].isdigit()
        and parts[3].isdigit()
    ):
        return ":".join(parts[:3])
    return source_record_id


def canonical_bitget_closed_source_id(source_record_id: str) -> str:
    parts = source_record_id.split(":")
    if (
        len(parts) == 4
        and parts[0] == "bitget"
        and parts[2] != "symbol"
        and parts[3].isdigit()
    ):
        return ":".join(parts[:3])
    return source_record_id


async def _recalculate_realized_pnl_dates(
    db: AsyncSession,
    affected_dates: set[tuple[Any, Any, Any]],
) -> None:
    for account_id, period_id, snapshot_date in affected_dates:
        snapshot = await db.scalar(
            select(DailyPnlSnapshot).where(
                DailyPnlSnapshot.exchange_account_id == account_id,
                DailyPnlSnapshot.tracking_period_id == period_id,
                DailyPnlSnapshot.snapshot_date == snapshot_date,
            )
        )
        if snapshot is None:
            continue
        start = datetime.combine(snapshot_date, time.min, tzinfo=UTC)
        end = datetime.combine(snapshot_date, time.max, tzinfo=UTC)
        income_count, income_total = (
            await db.execute(
                select(
                    func.count(IncomeRecord.id),
                    func.sum(IncomeRecord.amount_usd),
                ).where(
                    IncomeRecord.exchange_account_id == account_id,
                    IncomeRecord.tracking_period_id == period_id,
                    IncomeRecord.record_time >= start,
                    IncomeRecord.record_time <= end,
                    IncomeRecord.income_type == "REALIZED_PNL",
                )
            )
        ).one()
        if income_count:
            snapshot.realized_pnl = income_total or Decimal("0")
            continue
        realized = await db.scalar(
            select(func.sum(ClosedPosition.realized_pnl)).where(
                ClosedPosition.exchange_account_id == account_id,
                ClosedPosition.tracking_period_id == period_id,
                ClosedPosition.close_time >= start,
                ClosedPosition.close_time <= end,
            )
        )
        snapshot.realized_pnl = realized or Decimal("0")


async def cleanup_bitget_closed_positions(
    db: AsyncSession,
    *,
    apply: bool,
) -> dict[str, Any]:
    rows = (
        await db.scalars(
            select(ClosedPosition)
            .where(ClosedPosition.exchange == "BITGET")
            .order_by(ClosedPosition.created_at)
        )
    ).all()
    groups: dict[tuple[Any, Any, str], list[ClosedPosition]] = {}
    for row in rows:
        canonical = canonical_bitget_closed_source_id(row.source_record_id)
        groups.setdefault(
            (row.exchange_account_id, row.tracking_period_id, canonical),
            [],
        ).append(row)

    delete_rows: list[ClosedPosition] = []
    keepers: list[tuple[ClosedPosition, str]] = []
    affected_dates: set[tuple[Any, Any, Any]] = set()
    for (account_id, period_id, canonical), items in groups.items():
        keeper = max(
            items,
            key=lambda row: (row.close_time, row.updated_at, row.created_at),
        )
        keepers.append((keeper, canonical))
        duplicates = [row for row in items if row.id != keeper.id]
        delete_rows.extend(duplicates)
        if duplicates:
            for row in items:
                affected_dates.add(
                    (account_id, period_id, row.close_time.date())
                )

    result = {
        "scanned": len(rows),
        "duplicate_groups": sum(len(items) > 1 for items in groups.values()),
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
    await _recalculate_realized_pnl_dates(db, affected_dates)
    db.add(
        SecurityAuditLog(
            action="BITGET_CLOSED_POSITION_IDS_NORMALIZED",
            outcome="SUCCESS",
            client_ip="maintenance",
            details=result,
        )
    )
    await db.commit()
    return result


async def cleanup_binance_fill_fragments(
    db: AsyncSession,
    *,
    account: ExchangeAccount,
    period: TrackingPeriod,
    normalized_positions: list[dict[str, Any]],
    trade_order_ids: dict[str, str],
    apply: bool,
) -> dict[str, Any]:
    rows = (
        await db.scalars(
            select(ClosedPosition).where(
                ClosedPosition.exchange_account_id == account.id,
                ClosedPosition.tracking_period_id == period.id,
                ClosedPosition.exchange == "BINANCE",
            )
        )
    ).all()
    groups: dict[tuple[str, str, str], list[ClosedPosition]] = {}
    for row in rows:
        trade_id = row.source_record_id.rsplit(":", 1)[-1]
        order_id = trade_order_ids.get(trade_id)
        if order_id:
            groups.setdefault((row.symbol, row.side, order_id), []).append(row)

    normalized_by_source = {
        str(item["source_record_id"]): item for item in normalized_positions
    }
    delete_rows: list[ClosedPosition] = []
    affected_dates: set[tuple[Any, Any, Any]] = set()
    group_preview: list[dict[str, Any]] = []
    unresolved_groups: list[dict[str, Any]] = []
    for (symbol, side, order_id), items in groups.items():
        if len(items) < 2:
            continue
        sources = {row.source_record_id for row in items}
        matches = [
            item
            for source_id, item in normalized_by_source.items()
            if source_id in sources
        ]
        if len(matches) != 1:
            unresolved_groups.append(
                {
                    "symbol": symbol,
                    "side": side,
                    "order_id": order_id,
                    "stored_rows": len(items),
                    "normalized_matches": len(matches),
                }
            )
            continue
        normalized = matches[0]
        canonical_source = str(normalized["source_record_id"])
        duplicates = [
            row for row in items if row.source_record_id != canonical_source
        ]
        delete_rows.extend(duplicates)
        for row in items:
            affected_dates.add(
                (
                    row.exchange_account_id,
                    row.tracking_period_id,
                    row.close_time.date(),
                )
            )
        group_preview.append(
            {
                "symbol": symbol,
                "side": side,
                "order_id": order_id,
                "rows": len(items),
                "keep_source_record_id": canonical_source,
                "merged_size": str(normalized.get("max_position_size") or 0),
                "merged_net_pnl": str(normalized.get("net_pnl") or 0),
            }
        )

    result = {
        "scanned": len(rows),
        "fragment_groups": len(group_preview),
        "fragments_to_delete": len(delete_rows),
        "unresolved_groups": unresolved_groups,
        "groups": group_preview,
        "applied": apply,
    }
    if not apply:
        return result
    if unresolved_groups:
        raise ValueError("Binance fill fragment cleanup has unresolved groups")

    for row in delete_rows:
        await db.delete(row)
    await db.flush()
    from app.services.accounts import _upsert_closed_positions

    await _upsert_closed_positions(
        db,
        account,
        period,
        normalized_positions,
    )
    await _recalculate_realized_pnl_dates(db, affected_dates)
    db.add(
        SecurityAuditLog(
            action="BINANCE_FILL_FRAGMENTS_MERGED",
            outcome="SUCCESS",
            client_ip="maintenance",
            details=result,
        )
    )
    await db.commit()
    return result


async def cleanup_okx_closed_positions(
    db: AsyncSession,
    *,
    apply: bool,
) -> dict[str, Any]:
    rows = (
        await db.scalars(
            select(ClosedPosition)
            .where(ClosedPosition.exchange == "OKX")
            .order_by(ClosedPosition.created_at)
        )
    ).all()
    groups: dict[tuple[Any, Any, str], list[ClosedPosition]] = {}
    for row in rows:
        canonical = canonical_okx_closed_source_id(row.source_record_id)
        groups.setdefault(
            (row.exchange_account_id, row.tracking_period_id, canonical),
            [],
        ).append(row)

    duplicate_groups = [items for items in groups.values() if len(items) > 1]
    delete_rows: list[ClosedPosition] = []
    keepers: list[tuple[ClosedPosition, str]] = []
    affected_dates: set[tuple[Any, Any, Any]] = set()
    group_preview: list[dict[str, Any]] = []
    for (account_id, period_id, canonical), items in groups.items():
        keeper = max(
            items,
            key=lambda row: (row.close_time, row.updated_at, row.created_at),
        )
        keepers.append((keeper, canonical))
        duplicates = [row for row in items if row.id != keeper.id]
        if duplicates:
            delete_rows.extend(duplicates)
            for row in items:
                affected_dates.add(
                    (account_id, period_id, row.close_time.date())
                )
            group_preview.append(
                {
                    "symbol": keeper.normalized_symbol,
                    "pos_id": canonical.rsplit(":", 1)[-1],
                    "rows": len(items),
                    "keep_close_time": keeper.close_time.isoformat(),
                    "keep_net_pnl": str(keeper.net_pnl),
                }
            )

    result = {
        "scanned": len(rows),
        "duplicate_groups": len(duplicate_groups),
        "duplicates_to_delete": len(delete_rows),
        "source_ids_to_normalize": sum(
            row.source_record_id != canonical for row, canonical in keepers
        ),
        "groups": group_preview,
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

    for account_id, period_id, snapshot_date in affected_dates:
        snapshot = await db.scalar(
            select(DailyPnlSnapshot).where(
                DailyPnlSnapshot.exchange_account_id == account_id,
                DailyPnlSnapshot.tracking_period_id == period_id,
                DailyPnlSnapshot.snapshot_date == snapshot_date,
            )
        )
        if snapshot is None:
            continue
        start = datetime.combine(snapshot_date, time.min, tzinfo=UTC)
        end = datetime.combine(snapshot_date, time.max, tzinfo=UTC)
        income_count, income_total = (
            await db.execute(
                select(
                    func.count(IncomeRecord.id),
                    func.sum(IncomeRecord.amount_usd),
                ).where(
                    IncomeRecord.exchange_account_id == account_id,
                    IncomeRecord.tracking_period_id == period_id,
                    IncomeRecord.record_time >= start,
                    IncomeRecord.record_time <= end,
                    IncomeRecord.income_type == "REALIZED_PNL",
                )
            )
        ).one()
        if income_count:
            snapshot.realized_pnl = income_total or Decimal("0")
        else:
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
            action="OKX_PARTIAL_CLOSE_DUPLICATES_CLEANED",
            outcome="SUCCESS",
            client_ip="maintenance",
            details=result,
        )
    )
    await db.commit()
    return result


def _okx_cycle_base(source_record_id: str) -> str | None:
    parts = source_record_id.split(":")
    if (
        len(parts) == 5
        and parts[0] == "okx"
        and parts[3] == "cycle"
    ):
        return ":".join(parts[:3])
    return None


def _okx_legacy_base(source_record_id: str) -> str | None:
    parts = source_record_id.split(":")
    if (
        len(parts) in {3, 4}
        and parts[0] == "okx"
        and parts[2] != "symbol"
    ):
        return ":".join(parts[:3])
    return None


async def rebuild_okx_closed_position_cycles(
    db: AsyncSession,
    *,
    account: ExchangeAccount,
    period: TrackingPeriod,
    normalized_positions: list[dict[str, Any]],
    apply: bool,
) -> dict[str, Any]:
    rows = (
        await db.scalars(
            select(ClosedPosition).where(
                ClosedPosition.exchange_account_id == account.id,
                ClosedPosition.tracking_period_id == period.id,
                ClosedPosition.exchange == "OKX",
            )
        )
    ).all()
    existing_by_source = {row.source_record_id: row for row in rows}
    legacy_by_base: dict[str, list[ClosedPosition]] = {}
    for row in rows:
        legacy_base = _okx_legacy_base(row.source_record_id)
        if legacy_base:
            legacy_by_base.setdefault(legacy_base, []).append(row)

    matched_legacy_ids: set[Any] = set()
    legacy_delete_rows: list[ClosedPosition] = []
    migrations = 0
    insertions = 0
    for item in normalized_positions:
        source_id = str(item["source_record_id"])
        base = _okx_cycle_base(source_id)
        candidates = [
            row
            for row in legacy_by_base.get(base or "", [])
            if row.normalized_symbol == item["normalized_symbol"]
            and row.side == item["side"]
            and row.open_time == item["open_time"]
        ]
        matched_legacy_ids.update(row.id for row in candidates)
        exact = existing_by_source.get(source_id)
        if exact is not None:
            legacy_delete_rows.extend(candidates)
            continue
        if candidates:
            migrations += 1
            keeper = max(
                candidates,
                key=lambda row: (
                    row.close_time,
                    row.updated_at,
                    row.created_at,
                ),
            )
            legacy_delete_rows.extend(
                row for row in candidates if row.id != keeper.id
            )
        else:
            insertions += 1

    unresolved = [
        {
            "source_record_id": row.source_record_id,
            "symbol": row.normalized_symbol,
            "side": row.side,
            "open_time": row.open_time.isoformat(),
            "close_time": row.close_time.isoformat(),
        }
        for legacy_rows in legacy_by_base.values()
        for row in legacy_rows
        if row.id not in matched_legacy_ids
    ]
    result = {
        "stored_rows": len(rows),
        "exchange_cycles": len(normalized_positions),
        "legacy_rows_to_migrate": migrations,
        "legacy_duplicates_to_delete": len(legacy_delete_rows),
        "cycles_to_insert": insertions,
        "unresolved_legacy_rows": unresolved,
        "applied": apply,
    }
    if not apply:
        return result
    if unresolved:
        raise ValueError("OKX cycle rebuild has unresolved legacy rows")

    for row in legacy_delete_rows:
        await db.delete(row)
    await db.flush()
    from app.services.accounts import _upsert_closed_positions

    await _upsert_closed_positions(
        db,
        account,
        period,
        normalized_positions,
    )
    await db.flush()
    await _recalculate_realized_pnl_dates(
        db,
        {
            (account.id, period.id, item["close_time"].date())
            for item in normalized_positions
        },
    )
    db.add(
        SecurityAuditLog(
            action="OKX_CLOSED_POSITION_CYCLES_REBUILT",
            outcome="SUCCESS",
            client_ip="maintenance",
            details=result,
        )
    )
    await db.commit()
    result["stored_rows_after"] = await db.scalar(
        select(func.count())
        .select_from(ClosedPosition)
        .where(
            ClosedPosition.exchange_account_id == account.id,
            ClosedPosition.tracking_period_id == period.id,
            ClosedPosition.exchange == "OKX",
        )
    )
    return result


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
