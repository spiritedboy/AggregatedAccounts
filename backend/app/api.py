import asyncio
import csv
import io
import uuid
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, desc, exists, func, or_, select, text, true
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    AccountBalanceSnapshot,
    AppSession,
    AssetBalanceSnapshot,
    ClosedPosition,
    CurrentPosition,
    DailyPnlSnapshot,
    ExchangeAccount,
    InitialAccountSnapshot,
    PolymarketTranslation,
    PositionSnapshot,
    TrackingPeriod,
)
from app.schemas import AccountResponse, ExchangeAccountCreate, envelope
from app.security.session import (
    client_ip,
    require_csrf,
    require_session,
)
from app.services.accounting import (
    build_data_completeness,
    list_accounting_records,
)
from app.services.accounts import create_account, delete_account, sync_account
from app.services.analytics import (
    build_reconciliation,
    build_risk_metrics,
    build_sync_status,
)
from app.services.equity_curve import get_equity_curve

router = APIRouter(prefix="/api")


def _num(value: Decimal | float | None) -> float:
    return float(value or 0)


def _polymarket_asset_id(row: CurrentPosition | ClosedPosition) -> str | None:
    if row.exchange != "POLYMARKET":
        return None
    return row.source_record_id.removeprefix("poly-closed:")


async def _polymarket_translation_map(
    db: AsyncSession,
    rows: list[CurrentPosition] | list[ClosedPosition],
) -> dict[str, PolymarketTranslation]:
    asset_ids = {
        asset_id
        for row in rows
        if (asset_id := _polymarket_asset_id(row))
    }
    if not asset_ids:
        return {}
    translations = (
        await db.scalars(
            select(PolymarketTranslation).where(
                PolymarketTranslation.asset_id.in_(asset_ids)
            )
        )
    ).all()
    return {row.asset_id: row for row in translations}


def _translation_fields(
    row: CurrentPosition | ClosedPosition,
    translation: PolymarketTranslation | None,
) -> dict[str, str]:
    if row.exchange != "POLYMARKET":
        return {
            "display_symbol": row.symbol,
            "original_symbol": row.symbol,
            "translation_status": "NOT_APPLICABLE",
            "translation_provider": "",
        }
    if translation is None:
        return {
            "display_symbol": row.symbol,
            "original_symbol": row.symbol,
            "translation_status": "PENDING",
            "translation_provider": "BAIDU_LLM",
        }
    ready = translation.status == "READY" and bool(translation.translated_display)
    return {
        "display_symbol": (
            translation.translated_display if ready else translation.source_display
        ),
        "original_symbol": translation.source_display,
        "translation_status": translation.status,
        "translation_provider": translation.provider,
    }


async def _active_account(db: AsyncSession, account_id: uuid.UUID) -> ExchangeAccount:
    account = await db.scalar(
        select(ExchangeAccount).where(
            ExchangeAccount.id == account_id, ExchangeAccount.is_active.is_(True)
        )
    )
    if not account:
        raise HTTPException(status_code=404, detail="交易所账户不存在")
    return account


@router.get("/health")
async def health(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    await db.execute(text("SELECT 1"))
    return {
        "status": "healthy",
        "database": "connected",
        "database_host": "host.docker.internal",
        "services": {"backend": "healthy"},
    }


@router.get("/auth/status")
async def auth_status(_: AppSession = Depends(require_session)) -> dict[str, Any]:
    return envelope({"authenticated": True, "mode": "PUBLIC_READ_ONLY"})


@router.get("/exchange-accounts")
async def list_accounts(
    _: AppSession = Depends(require_session), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return envelope(await _account_list_data(db))


async def _account_rows(db: AsyncSession) -> list[ExchangeAccount]:
    return list(
        (
            await db.scalars(
                select(ExchangeAccount)
                .where(ExchangeAccount.is_active.is_(True))
                .order_by(
                    ExchangeAccount.is_demo.desc(),
                    ExchangeAccount.created_at,
                )
            )
        ).all()
    )


async def _account_list_data(
    db: AsyncSession,
    accounts: list[ExchangeAccount] | None = None,
) -> list[dict[str, Any]]:
    accounts = accounts if accounts is not None else await _account_rows(db)
    return [AccountResponse.model_validate(item).model_dump() for item in accounts]


@router.post("/exchange-accounts", status_code=status.HTTP_201_CREATED)
async def add_account(
    payload: ExchangeAccountCreate,
    request: Request,
    _: AppSession = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        account = await create_account(db, payload, client_ip(request))
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except Exception:
        await db.rollback()
        raise HTTPException(
            status_code=400, detail="只读连接测试失败，请检查凭证、IP 白名单和权限"
        ) from None
    return envelope(AccountResponse.model_validate(account).model_dump())


@router.get("/exchange-accounts/{account_id}")
async def get_account(
    account_id: uuid.UUID,
    _: AppSession = Depends(require_session),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    account = await _active_account(db, account_id)
    return envelope(AccountResponse.model_validate(account).model_dump())


@router.post("/exchange-accounts/{account_id}/test")
async def test_account(
    account_id: uuid.UUID,
    _: AppSession = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    del account_id, db
    raise HTTPException(status_code=403, detail="公开只读模式不允许触发连接测试")


@router.post("/exchange-accounts/{account_id}/sync")
async def sync_one_account(
    account_id: uuid.UUID,
    _: AppSession = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    del account_id, db
    raise HTTPException(status_code=403, detail="公开只读模式不允许触发手动同步")


@router.delete("/exchange-accounts/{account_id}")
async def remove_account(
    account_id: uuid.UUID,
    request: Request,
    _: AppSession = Depends(require_csrf),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    account = await _active_account(db, account_id)
    if account.is_demo:
        raise HTTPException(status_code=400, detail="演示账户不可删除")
    await delete_account(db, account, client_ip(request))
    return envelope({"deleted": True, "account_id": account_id})


async def _latest_balances(
    db: AsyncSession, exchange: str | None = None
) -> list[tuple[AccountBalanceSnapshot, ExchangeAccount]]:
    latest_snapshot_id = (
        select(AccountBalanceSnapshot.id)
        .where(
            AccountBalanceSnapshot.exchange_account_id == ExchangeAccount.id
        )
        .order_by(
            AccountBalanceSnapshot.recorded_at.desc(),
            AccountBalanceSnapshot.id.desc(),
        )
        .limit(1)
        .correlate(ExchangeAccount)
        .scalar_subquery()
    )
    query = (
        select(AccountBalanceSnapshot, ExchangeAccount)
        .join(ExchangeAccount, ExchangeAccount.id == AccountBalanceSnapshot.exchange_account_id)
        .where(
            ExchangeAccount.is_active.is_(True),
            AccountBalanceSnapshot.id == latest_snapshot_id,
        )
        .order_by(ExchangeAccount.created_at, ExchangeAccount.id)
    )
    if exchange:
        query = query.where(ExchangeAccount.exchange == exchange.upper())
    return list((await db.execute(query)).all())


async def _daily_pnl_rows(db: AsyncSession) -> list[DailyPnlSnapshot]:
    return list(
        (
            await db.scalars(
                select(DailyPnlSnapshot)
                .join(ExchangeAccount)
                .where(ExchangeAccount.is_active.is_(True))
                .order_by(
                    DailyPnlSnapshot.exchange_account_id,
                    DailyPnlSnapshot.snapshot_date,
                )
            )
        ).all()
    )


def _daily_pnl_points_from_rows(
    rows: list[DailyPnlSnapshot],
    exchange: str | None = None,
) -> list[dict[str, Any]]:
    normalized_exchange = exchange.upper() if exchange else None
    previous_return: dict[uuid.UUID, float] = {}
    previous_unrealized: dict[uuid.UUID, float] = {}
    by_date: dict[date, dict[str, float]] = defaultdict(
        lambda: {
            "investment_return": 0.0,
            "realized_pnl": 0.0,
            "unrealized_pnl_change": 0.0,
            "funding_fee": 0.0,
            "trading_fee": 0.0,
            "equity": 0.0,
        }
    )
    for row in rows:
        if normalized_exchange and row.exchange != normalized_exchange:
            continue
        account_id = row.exchange_account_id
        cumulative_return = _num(row.investment_return)
        cumulative_unrealized = _num(row.unrealized_pnl_change)
        point = by_date[row.snapshot_date]
        point["investment_return"] += cumulative_return - previous_return.get(
            account_id, 0.0
        )
        point["unrealized_pnl_change"] += (
            cumulative_unrealized - previous_unrealized.get(account_id, 0.0)
        )
        point["realized_pnl"] += _num(row.realized_pnl)
        point["funding_fee"] += _num(row.funding_fee)
        point["trading_fee"] += _num(row.trading_fee)
        point["equity"] += _num(row.equity_usd)
        previous_return[account_id] = cumulative_return
        previous_unrealized[account_id] = cumulative_unrealized

    cumulative_return = 0.0
    cumulative_unrealized = 0.0
    result: list[dict[str, Any]] = []
    for snapshot_date in sorted(by_date):
        point = by_date[snapshot_date]
        cumulative_return += point["investment_return"]
        cumulative_unrealized += point["unrealized_pnl_change"]
        result.append(
            {
                "period": str(snapshot_date),
                **point,
                "cumulative_return": cumulative_return,
                "cumulative_unrealized_pnl_change": cumulative_unrealized,
            }
        )
    return result


async def _daily_pnl_points(
    db: AsyncSession,
    exchange: str | None = None,
) -> list[dict[str, Any]]:
    return _daily_pnl_points_from_rows(await _daily_pnl_rows(db), exchange)


def _bucket_pnl_points(
    daily: list[dict[str, Any]],
    bucket: str,
) -> list[dict[str, Any]]:
    if bucket == "daily":
        return daily
    grouped: dict[date, dict[str, Any]] = {}
    for point in daily:
        point_date = date.fromisoformat(str(point["period"])[:10])
        period_date = (
            point_date - timedelta(days=point_date.weekday())
            if bucket == "week"
            else point_date.replace(day=1)
        )
        aggregate = grouped.setdefault(
            period_date,
            {
                "period": str(period_date),
                "investment_return": 0.0,
                "realized_pnl": 0.0,
                "unrealized_pnl_change": 0.0,
                "funding_fee": 0.0,
                "trading_fee": 0.0,
                "equity": 0.0,
                "cumulative_return": 0.0,
                "cumulative_unrealized_pnl_change": 0.0,
            },
        )
        for field in (
            "investment_return",
            "realized_pnl",
            "unrealized_pnl_change",
            "funding_fee",
            "trading_fee",
        ):
            aggregate[field] += point[field]
        for field in (
            "equity",
            "cumulative_return",
            "cumulative_unrealized_pnl_change",
        ):
            aggregate[field] = point[field]
    return [grouped[key] for key in sorted(grouped)]


async def _latest_asset_rows(
    db: AsyncSession, account_ids: list[uuid.UUID]
) -> list[AssetBalanceSnapshot]:
    if not account_ids:
        return []
    latest_asset_time = (
        select(AssetBalanceSnapshot.recorded_at.label("recorded_at"))
        .where(AssetBalanceSnapshot.exchange_account_id == ExchangeAccount.id)
        .order_by(AssetBalanceSnapshot.recorded_at.desc())
        .limit(1)
        .correlate(ExchangeAccount)
        .lateral("latest_asset_time")
    )
    return (
        await db.scalars(
            select(AssetBalanceSnapshot)
            .select_from(ExchangeAccount)
            .join(latest_asset_time, true())
            .join(
                AssetBalanceSnapshot,
                and_(
                    AssetBalanceSnapshot.exchange_account_id == ExchangeAccount.id,
                    AssetBalanceSnapshot.recorded_at == latest_asset_time.c.recorded_at,
                ),
            )
            .where(ExchangeAccount.id.in_(account_ids))
            .order_by(
                AssetBalanceSnapshot.exchange_account_id,
                AssetBalanceSnapshot.account_type,
                AssetBalanceSnapshot.asset,
            )
        )
    ).all()


async def _dashboard_summary_data(db: AsyncSession) -> dict[str, Any]:
    latest = await _latest_balances(db)
    current_positions = (
        await db.scalars(
            select(CurrentPosition).join(ExchangeAccount).where(ExchangeAccount.is_active.is_(True))
        )
    ).all()
    dashboard_positions = current_positions[:6]
    translations = await _polymarket_translation_map(db, dashboard_positions)
    daily_rows = await _daily_pnl_points(db)
    total_equity = sum(_num(row.total_equity_usd) for row, _ in latest)
    available = sum(_num(row.available_balance_usd) for row, _ in latest)
    margin = sum(_num(row.margin_balance_usd) for row, _ in latest)
    realized_pnl = sum(row["realized_pnl"] for row in daily_rows)
    funding_fee = sum(row["funding_fee"] for row in daily_rows)
    trading_fee = sum(row["trading_fee"] for row in daily_rows)
    cumulative_net_pnl = realized_pnl + funding_fee - trading_fee
    current_position_pnl = sum(_num(row.unrealized_pnl) for row in current_positions)
    today_key = str(datetime.now(UTC).date())
    today_return = sum(
        row["investment_return"] for row in daily_rows if row["period"] == today_key
    )
    account_by_id = {account.id: account for _, account in latest}
    unvalued_assets = [
        {
            "exchange": account_by_id[row.exchange_account_id].exchange,
            "connection_name": account_by_id[row.exchange_account_id].connection_name,
            "asset": row.asset,
            "account_type": row.account_type,
            "quantity": _num(row.available) + _num(row.locked),
            "price_source": row.price_source,
        }
        for row in await _latest_asset_rows(db, list(account_by_id))
        if row.value_usd is None and (_num(row.available) or _num(row.locked))
    ]
    return {
        "estimated_total_equity": total_equity,
        "available_balance": available,
        "margin_used": margin,
        "current_position_pnl": current_position_pnl,
        "today_pnl": today_return,
        "cumulative_net_pnl": cumulative_net_pnl,
        # Compatibility aliases for older read-only clients.
        "unrealized_pnl_change": current_position_pnl,
        "cumulative_pnl": cumulative_net_pnl,
        "unvalued_asset_count": sum(row.unvalued_asset_count for row, _ in latest),
        "unvalued_assets": unvalued_assets,
        "tracking_started_at": min(
            (account.tracking_started_at for _, account in latest), default=None
        ),
        "last_updated_at": max(
            (account.last_synced_at for _, account in latest if account.last_synced_at),
            default=None,
        ),
        "by_exchange": [
            {
                "exchange": account.exchange,
                "connection_name": account.connection_name,
                "equity": _num(snapshot.total_equity_usd),
                "available": _num(snapshot.available_balance_usd),
                "unrealized_pnl": _num(snapshot.unrealized_pnl_usd),
                "status": account.connection_status,
                "completeness": account.data_completeness,
            }
            for snapshot, account in latest
        ],
        "equity_curve": [
            {
                "date": row["period"],
                "pnl": row["cumulative_return"],
                "equity": row["equity"],
            }
            for row in daily_rows
        ],
        "positions": [
            _position_dict(
                item,
                translations.get(_polymarket_asset_id(item) or ""),
            )
            for item in dashboard_positions
        ],
        "notice": "仅统计添加 API Key 后产生的数据",
        "demo_mode": any(account.is_demo for _, account in latest),
    }


@router.get("/dashboard/summary")
async def dashboard_summary(
    _: AppSession = Depends(require_session), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return envelope(await _dashboard_summary_data(db))


@router.get("/analytics/equity-curve")
async def equity_curve(
    range_key: Literal["1d", "1w", "1m", "6m", "1y"] = Query(
        "1d", alias="range"
    ),
    _: AppSession = Depends(require_session),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return envelope(await get_equity_curve(db, range_key))


@router.get("/dashboard/bootstrap")
async def dashboard_bootstrap(
    range_key: Literal["1d", "1w", "1m", "6m", "1y"] = Query(
        "1d", alias="range"
    ),
    _: AppSession = Depends(require_session),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return envelope(
        {
            "dashboard": await _dashboard_summary_data(db),
            "risk": await build_risk_metrics(db),
            "equity_curve": await get_equity_curve(db, range_key),
        }
    )


@router.get("/exchanges/status")
async def exchange_status(
    _: AppSession = Depends(require_session), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    accounts = (
        await db.scalars(select(ExchangeAccount).where(ExchangeAccount.is_active.is_(True)))
    ).all()
    return envelope(
        [
            {
                "account_id": row.id,
                "exchange": row.exchange,
                "name": row.connection_name,
                "status": row.connection_status,
                "last_sync": row.last_synced_at,
                "completeness": row.data_completeness,
            }
            for row in accounts
        ]
    )


async def _balances_data(
    db: AsyncSession,
    exchange: str | None = None,
) -> list[dict[str, Any]]:
    latest = await _latest_balances(db, exchange)
    account_ids = [account.id for _, account in latest]
    asset_rows = await _latest_asset_rows(db, account_ids)
    assets_by_account: dict[uuid.UUID, list[AssetBalanceSnapshot]] = defaultdict(list)
    for asset_row in asset_rows:
        assets_by_account[asset_row.exchange_account_id].append(asset_row)
    return [
        {
            "exchange": account.exchange,
            "account_id": account.id,
            "connection_name": account.connection_name,
            "total_equity_usd": _num(row.total_equity_usd),
            "available_balance_usd": _num(row.available_balance_usd),
            "margin_balance_usd": _num(row.margin_balance_usd),
            "unrealized_pnl_usd": _num(row.unrealized_pnl_usd),
            "unvalued_asset_count": row.unvalued_asset_count,
            "price_source": row.price_source,
            "recorded_at": row.recorded_at,
            "assets": [
                {
                    "asset": asset.asset,
                    "account_type": asset.account_type,
                    "available": _num(asset.available),
                    "locked": _num(asset.locked),
                    "value_usd": (
                        _num(asset.value_usd)
                        if asset.value_usd is not None
                        else None
                    ),
                    "price_source": asset.price_source,
                    "recorded_at": asset.recorded_at,
                }
                for asset in assets_by_account.get(account.id, [])
            ],
        }
        for row, account in latest
    ]


@router.get("/balances")
async def balances(
    exchange: str | None = None,
    _: AppSession = Depends(require_session),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return envelope(await _balances_data(db, exchange))


@router.get("/accounts/bootstrap")
async def accounts_bootstrap(
    _: AppSession = Depends(require_session),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    accounts = await _account_rows(db)
    return envelope(
        {
            "accounts": await _account_list_data(db, accounts),
            "sync_status": await build_sync_status(db, accounts),
            "balances": await _balances_data(db),
        }
    )


def _position_dict(
    row: CurrentPosition,
    translation: PolymarketTranslation | None = None,
) -> dict[str, Any]:
    leverage = _num(row.leverage)
    entry_notional = abs(_num(row.entry_price) * _num(row.position_size))
    margin_used = entry_notional / leverage if leverage > 0 else abs(_num(row.margin_used))
    unrealized_pnl = _num(row.unrealized_pnl)
    return {
        "id": row.id,
        "exchange": row.exchange,
        "exchange_account_id": row.exchange_account_id,
        "tracking_period_id": row.tracking_period_id,
        "symbol": row.symbol,
        "normalized_symbol": row.normalized_symbol,
        "market_type": row.market_type,
        "side": row.side,
        "position_size": _num(row.position_size),
        "position_value_usd": _num(row.position_value_usd),
        "entry_price": _num(row.entry_price),
        "mark_price": _num(row.mark_price),
        "liquidation_price": _num(row.liquidation_price) if row.liquidation_price else None,
        "leverage": leverage,
        "margin_mode": row.margin_mode,
        "margin_used": margin_used,
        "unrealized_pnl": unrealized_pnl,
        "tracking_unrealized_pnl_change": _num(row.tracking_unrealized_pnl_change),
        "unrealized_pnl_percent": (
            unrealized_pnl / margin_used * 100
            if margin_used > 0
            else _num(row.unrealized_pnl_percent)
        ),
        "realized_pnl": _num(row.realized_pnl),
        "funding_fee": _num(row.funding_fee),
        "trading_fee": _num(row.trading_fee),
        "open_time": row.open_time,
        "tracking_started_at": row.tracking_started_at,
        "is_initial_position": row.is_initial_position,
        "update_time": row.updated_at,
        **_translation_fields(row, translation),
    }


@router.get("/positions/current")
async def current_positions(
    exchange: str | None = None,
    account_id: uuid.UUID | None = None,
    symbol: str | None = None,
    side: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    _: AppSession = Depends(require_session),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    query = select(CurrentPosition).join(ExchangeAccount).where(ExchangeAccount.is_active.is_(True))
    if exchange:
        query = query.where(CurrentPosition.exchange == exchange.upper())
    if account_id:
        query = query.where(CurrentPosition.exchange_account_id == account_id)
    if symbol:
        query = query.where(
            or_(
                CurrentPosition.normalized_symbol.ilike(f"%{symbol}%"),
                CurrentPosition.symbol.ilike(f"%{symbol}%"),
                and_(
                    CurrentPosition.exchange == "POLYMARKET",
                    exists(
                        select(1).where(
                            PolymarketTranslation.asset_id
                            == CurrentPosition.source_record_id,
                            PolymarketTranslation.translated_display.ilike(
                                f"%{symbol}%"
                            ),
                        )
                    ),
                ),
            )
        )
    if side:
        query = query.where(CurrentPosition.side == side.upper())
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = (
        await db.scalars(
            query.order_by(desc(CurrentPosition.position_value_usd))
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    translations = await _polymarket_translation_map(db, rows)
    return envelope(
        {
            "items": [
                _position_dict(row, translations.get(_polymarket_asset_id(row) or ""))
                for row in rows
            ],
            "total": total,
        }
    )


@router.get("/positions/snapshots")
async def position_snapshots(
    exchange: str | None = None,
    account_id: uuid.UUID | None = None,
    symbol: str | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=500),
    _: AppSession = Depends(require_session),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    query = (
        select(PositionSnapshot)
        .join(ExchangeAccount)
        .where(ExchangeAccount.is_active.is_(True))
    )
    if exchange:
        query = query.where(PositionSnapshot.exchange == exchange.upper())
    if account_id:
        query = query.where(PositionSnapshot.exchange_account_id == account_id)
    if symbol:
        query = query.where(
            PositionSnapshot.normalized_symbol.ilike(f"%{symbol}%")
        )
    if start_time:
        query = query.where(PositionSnapshot.recorded_at >= start_time)
    if end_time:
        query = query.where(PositionSnapshot.recorded_at <= end_time)
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = (
        await db.scalars(
            query.order_by(PositionSnapshot.recorded_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return envelope(
        {
            "items": [
                {
                    "id": row.id,
                    "exchange": row.exchange,
                    "exchange_account_id": row.exchange_account_id,
                    "normalized_symbol": row.normalized_symbol,
                    "side": row.side,
                    "position_size": _num(row.position_size),
                    "mark_price": _num(row.mark_price),
                    "unrealized_pnl": _num(row.unrealized_pnl),
                    "recorded_at": row.recorded_at,
                }
                for row in rows
            ],
            "total": total or 0,
        }
    )


def _closed_dict(
    row: ClosedPosition,
    translation: PolymarketTranslation | None = None,
) -> dict[str, Any]:
    return {
        "id": row.id,
        "exchange": row.exchange,
        "exchange_account_id": row.exchange_account_id,
        "tracking_period_id": row.tracking_period_id,
        "symbol": row.symbol,
        "normalized_symbol": row.normalized_symbol,
        "side": row.side,
        "open_time": row.open_time,
        "close_time": row.close_time,
        "average_entry_price": _num(row.average_entry_price),
        "average_exit_price": _num(row.average_exit_price),
        "max_position_size": _num(row.max_position_size),
        "realized_pnl": _num(row.realized_pnl),
        "funding_fee": _num(row.funding_fee),
        "trading_fee": _num(row.trading_fee),
        "net_pnl": _num(row.net_pnl),
        "leverage": _num(row.leverage),
        "margin_used": _num(row.margin_used),
        "return_percent": _num(row.return_percent),
        "data_source": row.data_source,
        "data_completeness": row.data_completeness,
        "tracking_started_at": row.tracking_started_at,
        **_translation_fields(row, translation),
    }


def _history_query(
    exchange: str | None,
    account_id: uuid.UUID | None,
    symbol: str | None,
    side: str | None,
    pnl_result: str | None,
    completeness: str | None,
    start_time: datetime | None,
    end_time: datetime | None,
):
    query = (
        select(ClosedPosition)
        .join(ExchangeAccount)
        .where(
            ExchangeAccount.is_active.is_(True),
            ClosedPosition.close_time >= ClosedPosition.tracking_started_at,
        )
    )
    if exchange:
        query = query.where(ClosedPosition.exchange == exchange.upper())
    if account_id:
        query = query.where(ClosedPosition.exchange_account_id == account_id)
    if symbol:
        query = query.where(
            or_(
                ClosedPosition.normalized_symbol.ilike(f"%{symbol}%"),
                ClosedPosition.symbol.ilike(f"%{symbol}%"),
                and_(
                    ClosedPosition.exchange == "POLYMARKET",
                    exists(
                        select(1).where(
                            ClosedPosition.source_record_id
                            == func.concat(
                                "poly-closed:",
                                PolymarketTranslation.asset_id,
                            ),
                            PolymarketTranslation.translated_display.ilike(
                                f"%{symbol}%"
                            ),
                        )
                    ),
                ),
            )
        )
    if side:
        query = query.where(ClosedPosition.side == side.upper())
    if pnl_result:
        normalized_result = pnl_result.upper()
        if normalized_result == "PROFIT":
            query = query.where(ClosedPosition.net_pnl > 0)
        elif normalized_result == "LOSS":
            query = query.where(ClosedPosition.net_pnl < 0)
        elif normalized_result == "BREAKEVEN":
            query = query.where(ClosedPosition.net_pnl == 0)
    if completeness:
        query = query.where(
            ClosedPosition.data_completeness == completeness.upper()
        )
    if start_time:
        query = query.where(ClosedPosition.close_time >= start_time)
    if end_time:
        query = query.where(ClosedPosition.close_time <= end_time)
    return query


@router.get("/positions/history")
async def position_history(
    exchange: str | None = None,
    account_id: uuid.UUID | None = None,
    tracking_period_id: uuid.UUID | None = None,
    symbol: str | None = None,
    side: str | None = None,
    pnl_result: str | None = Query(
        default=None, pattern="^(PROFIT|LOSS|BREAKEVEN)$"
    ),
    completeness: str | None = Query(
        default=None, pattern="^(COMPLETE|PARTIAL)$"
    ),
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    _: AppSession = Depends(require_session),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    query = _history_query(
        exchange,
        account_id,
        symbol,
        side,
        pnl_result,
        completeness,
        start_time,
        end_time,
    )
    if tracking_period_id:
        query = query.where(ClosedPosition.tracking_period_id == tracking_period_id)
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = (
        await db.scalars(
            query.order_by(ClosedPosition.close_time.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    translations = await _polymarket_translation_map(db, rows)
    return envelope(
        {
            "items": [
                _closed_dict(row, translations.get(_polymarket_asset_id(row) or ""))
                for row in rows
            ],
            "total": total,
        }
    )


def _safe_csv(value: Any) -> Any:
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")):
        return f"'{value}"
    return value


@router.get("/positions/history/export")
async def export_history(
    exchange: str | None = None,
    account_id: uuid.UUID | None = None,
    symbol: str | None = None,
    side: str | None = None,
    pnl_result: str | None = Query(
        default=None, pattern="^(PROFIT|LOSS|BREAKEVEN)$"
    ),
    completeness: str | None = Query(
        default=None, pattern="^(COMPLETE|PARTIAL)$"
    ),
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    _: AppSession = Depends(require_session),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    rows = (
        await db.scalars(
            _history_query(
                exchange,
                account_id,
                symbol,
                side,
                pnl_result,
                completeness,
                start_time,
                end_time,
            )
            .order_by(ClosedPosition.close_time.desc())
            .limit(10_000)
        )
    ).all()
    translations = await _polymarket_translation_map(db, rows)
    output = io.StringIO()
    writer = csv.writer(output)
    headers = [
        "exchange",
        "symbol",
        "side",
        "open_time",
        "close_time",
        "entry_price",
        "exit_price",
        "net_pnl",
        "return_percent",
        "data_source",
    ]
    writer.writerow(headers)
    for row in rows:
        item = _closed_dict(
            row,
            translations.get(_polymarket_asset_id(row) or ""),
        )
        writer.writerow(
            [
                _safe_csv(item["exchange"]),
                _safe_csv(item["display_symbol"]),
                item["side"],
                item["open_time"],
                item["close_time"],
                item["average_entry_price"],
                item["average_exit_price"],
                item["net_pnl"],
                item["return_percent"],
                item["data_source"],
            ]
        )
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="position-history.csv"'},
    )


@router.get("/accounting/records")
async def accounting_records(
    exchange: str | None = None,
    account_id: uuid.UUID | None = None,
    record_type: str | None = Query(
        default=None,
        pattern="^(REALIZED_PNL|FUNDING_FEE|TRADING_FEE|DEPOSIT|WITHDRAWAL|CASH_FLOW)$",
    ),
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    _: AppSession = Depends(require_session),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return envelope(
        await list_accounting_records(
            db,
            exchange=exchange,
            account_id=account_id,
            record_type=record_type,
            start_time=start_time,
            end_time=end_time,
            offset=(page - 1) * page_size,
            limit=page_size,
        )
    )


@router.get("/accounting/bootstrap")
async def accounting_bootstrap(
    exchange: str | None = None,
    account_id: uuid.UUID | None = None,
    record_type: str | None = Query(
        default=None,
        pattern="^(REALIZED_PNL|FUNDING_FEE|TRADING_FEE|DEPOSIT|WITHDRAWAL|CASH_FLOW)$",
    ),
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    _: AppSession = Depends(require_session),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return envelope(
        {
            "records": await list_accounting_records(
                db,
                exchange=exchange,
                account_id=account_id,
                record_type=record_type,
                start_time=start_time,
                end_time=end_time,
                offset=(page - 1) * page_size,
                limit=page_size,
            ),
            "completeness": await build_data_completeness(db),
        }
    )


@router.get("/accounting/records/export")
async def export_accounting_records(
    exchange: str | None = None,
    account_id: uuid.UUID | None = None,
    record_type: str | None = Query(
        default=None,
        pattern="^(REALIZED_PNL|FUNDING_FEE|TRADING_FEE|DEPOSIT|WITHDRAWAL|CASH_FLOW)$",
    ),
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    _: AppSession = Depends(require_session),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    result = await list_accounting_records(
        db,
        exchange=exchange,
        account_id=account_id,
        record_type=record_type,
        start_time=start_time,
        end_time=end_time,
        offset=0,
        limit=10_000,
    )
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "record_time",
            "exchange",
            "connection_name",
            "record_type",
            "subtype",
            "asset",
            "signed_amount_usd",
            "symbol",
            "source_record_id",
        ]
    )
    for item in result["items"]:
        writer.writerow(
            [
                item["record_time"],
                _safe_csv(item["exchange"]),
                _safe_csv(item["connection_name"]),
                item["record_type"],
                _safe_csv(item["subtype"]),
                _safe_csv(item["asset"]),
                item["signed_amount_usd"],
                _safe_csv(item["symbol"] or ""),
                _safe_csv(item["source_record_id"]),
            ]
        )
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="accounting-records.csv"'},
    )


async def _pnl_series(db: AsyncSession, bucket: str) -> list[dict[str, Any]]:
    return _bucket_pnl_points(await _daily_pnl_points(db), bucket)


async def _pnl_summary_data(
    db: AsyncSession,
    daily: list[dict[str, Any]],
) -> dict[str, Any]:
    latest_initial = (
        await db.scalars(
            select(InitialAccountSnapshot)
            .join(
                TrackingPeriod,
                TrackingPeriod.id == InitialAccountSnapshot.tracking_period_id,
            )
            .join(
                ExchangeAccount,
                ExchangeAccount.id == InitialAccountSnapshot.exchange_account_id,
            )
            .where(
                TrackingPeriod.is_active.is_(True),
                ExchangeAccount.is_active.is_(True),
            )
        )
    ).all()
    values = [row["investment_return"] for row in daily]
    realized_pnl = sum(row["realized_pnl"] for row in daily)
    funding_fee = sum(row["funding_fee"] for row in daily)
    trading_fee = sum(row["trading_fee"] for row in daily)
    current_position_pnl = await db.scalar(
        select(func.coalesce(func.sum(CurrentPosition.unrealized_pnl), 0))
        .join(ExchangeAccount)
        .where(ExchangeAccount.is_active.is_(True))
    )
    return {
        "period_initial_equity": sum(_num(row.initial_equity) for row in latest_initial),
        # Daily points store period deltas; the summary needs the period-to-date
        # value from the cumulative curve rather than only the final day's delta.
        "period_investment_return": daily[-1]["cumulative_return"] if daily else 0,
        "period_realized_pnl": realized_pnl,
        "period_net_realized_pnl": realized_pnl + funding_fee - trading_fee,
        "current_position_pnl": _num(current_position_pnl),
        "period_unrealized_pnl_change": (
            daily[-1]["cumulative_unrealized_pnl_change"] if daily else 0
        ),
        "period_funding_fee": funding_fee,
        "period_trading_fee": trading_fee,
        "best_day": max(values, default=0),
        "worst_day": min(values, default=0),
        "profitable_days": sum(value > 0 for value in values),
        "losing_days": sum(value < 0 for value in values),
        "notice": "仅统计添加 API Key 后产生的数据",
    }


async def _pnl_by_exchange_data(
    db: AsyncSession,
    rows: list[DailyPnlSnapshot],
) -> list[dict[str, Any]]:
    exchanges = list(
        await db.scalars(
            select(ExchangeAccount.exchange)
            .where(ExchangeAccount.is_active.is_(True))
            .distinct()
            .order_by(ExchangeAccount.exchange)
        )
    )
    result = []
    for exchange in exchanges:
        daily = _daily_pnl_points_from_rows(rows, exchange)
        result.append(
            {
                "exchange": exchange,
                "realized_pnl": sum(row["realized_pnl"] for row in daily),
                "funding_fee": sum(row["funding_fee"] for row in daily),
                "trading_fee": sum(row["trading_fee"] for row in daily),
                "investment_return": (
                    daily[-1]["cumulative_return"] if daily else 0
                ),
            }
        )
    return result


async def _pnl_by_side_data(db: AsyncSession) -> dict[str, Any]:
    rows = (
        await db.execute(
            select(
                ClosedPosition.side,
                func.count(ClosedPosition.id),
                func.coalesce(func.sum(ClosedPosition.net_pnl), 0),
            )
            .join(ExchangeAccount)
            .join(TrackingPeriod)
            .where(
                ExchangeAccount.is_active.is_(True),
                TrackingPeriod.is_active.is_(True),
                ClosedPosition.side.in_(("LONG", "SHORT")),
            )
            .group_by(ClosedPosition.side)
        )
    ).all()
    totals = {side: {"count": 0, "net_pnl": 0.0} for side in ("LONG", "SHORT")}
    for side, count, net_pnl in rows:
        totals[side] = {"count": int(count), "net_pnl": _num(net_pnl)}

    for values in totals.values():
        values["average_net_pnl"] = (
            values["net_pnl"] / values["count"] if values["count"] else 0.0
        )
    short_pnl = totals["SHORT"]["net_pnl"]
    short_count = totals["SHORT"]["count"]
    return {
        "long": totals["LONG"],
        "short": totals["SHORT"],
        "pnl_ratio": totals["LONG"]["net_pnl"] / short_pnl if short_pnl else None,
        "count_ratio": totals["LONG"]["count"] / short_count if short_count else None,
    }


async def _pnl_bootstrap_data(db: AsyncSession) -> dict[str, Any]:
    rows = await _daily_pnl_rows(db)
    daily = _daily_pnl_points_from_rows(rows)
    return {
        "summary": await _pnl_summary_data(db, daily),
        "daily": daily,
        "weekly": _bucket_pnl_points(daily, "week"),
        "monthly": _bucket_pnl_points(daily, "month"),
        "by_exchange": await _pnl_by_exchange_data(db, rows),
        "by_side": await _pnl_by_side_data(db),
    }


@router.get("/pnl/bootstrap")
async def pnl_bootstrap(
    _: AppSession = Depends(require_session), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return envelope(await _pnl_bootstrap_data(db))


@router.get("/pnl/summary")
async def pnl_summary(
    _: AppSession = Depends(require_session), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    daily = await _pnl_series(db, "daily")
    return envelope(await _pnl_summary_data(db, daily))


@router.get("/pnl/daily")
async def pnl_daily(
    _: AppSession = Depends(require_session), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return envelope(await _pnl_series(db, "daily"))


@router.get("/pnl/weekly")
async def pnl_weekly(
    _: AppSession = Depends(require_session), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return envelope(await _pnl_series(db, "week"))


@router.get("/pnl/monthly")
async def pnl_monthly(
    _: AppSession = Depends(require_session), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return envelope(await _pnl_series(db, "month"))


@router.get("/pnl/by-exchange")
async def pnl_by_exchange(
    _: AppSession = Depends(require_session), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    rows = await _daily_pnl_rows(db)
    return envelope(await _pnl_by_exchange_data(db, rows))


@router.get("/sync/status")
async def sync_status(
    _: AppSession = Depends(require_session), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return envelope(await build_sync_status(db))


@router.get("/data-completeness")
async def data_completeness(
    _: AppSession = Depends(require_session), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return envelope(await build_data_completeness(db))


@router.get("/analytics/reconciliation")
async def reconciliation(
    _: AppSession = Depends(require_session), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return envelope(await build_reconciliation(db))


@router.get("/analytics/risk")
async def risk_metrics(
    _: AppSession = Depends(require_session), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    return envelope(await build_risk_metrics(db))


@router.get("/analytics/bootstrap")
async def analytics_bootstrap(
    _: AppSession = Depends(require_session),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return envelope(
        {
            "reconciliation": await build_reconciliation(db),
            "risk": await build_risk_metrics(db),
        }
    )


@router.post("/sync/refresh")
async def refresh_all(
    _: AppSession = Depends(require_csrf), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    accounts = (
        await db.scalars(select(ExchangeAccount).where(ExchangeAccount.is_active.is_(True)))
    ).all()
    results = []
    for account in accounts:
        results.append(
            {
                "account_id": account.id,
                "exchange": account.exchange,
                **await sync_account(db, account),
            }
        )
    return envelope(results)


@router.get("/sync/events")
async def sync_events(_: AppSession = Depends(require_session)) -> StreamingResponse:
    async def stream():
        while True:
            yield f"event: heartbeat\ndata: {datetime.now(UTC).isoformat()}\n\n"
            await asyncio.sleep(15)

    return StreamingResponse(stream(), media_type="text/event-stream")
