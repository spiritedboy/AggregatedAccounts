import asyncio
import csv
import io
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import desc, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    AccountBalanceSnapshot,
    AppSession,
    ClosedPosition,
    CurrentPosition,
    DailyPnlSnapshot,
    ExchangeAccount,
    InitialAccountSnapshot,
    SyncJob,
)
from app.schemas import AccountResponse, ExchangeAccountCreate, envelope
from app.security.session import (
    client_ip,
    require_csrf,
    require_session,
)
from app.services.accounts import (
    adapter_for_account,
    create_account,
    delete_account,
    sync_account,
)

router = APIRouter(prefix="/api")


def _num(value: Decimal | float | None) -> float:
    return float(value or 0)


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
    accounts = (
        await db.scalars(
            select(ExchangeAccount)
            .where(ExchangeAccount.is_active.is_(True))
            .order_by(ExchangeAccount.is_demo.desc(), ExchangeAccount.created_at)
        )
    ).all()
    return envelope([AccountResponse.model_validate(item).model_dump() for item in accounts])


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
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    account = await _active_account(db, account_id)
    if account.is_demo:
        return envelope({"connected": True, "mode": "DEMO"})
    adapter = await adapter_for_account(db, account)
    try:
        connected = await adapter.test_connection()
        permissions = await adapter.get_permissions()
    except Exception:
        raise HTTPException(status_code=400, detail="连接测试失败") from None
    finally:
        await adapter.close()
    account.permission_status = permissions
    account.connection_status = "CONNECTED" if connected else "ERROR"
    await db.commit()
    return envelope({"connected": connected, "permissions": permissions})


@router.post("/exchange-accounts/{account_id}/sync")
async def sync_one_account(
    account_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    account = await _active_account(db, account_id)
    return envelope(await sync_account(db, account))


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
    query = (
        select(AccountBalanceSnapshot, ExchangeAccount)
        .join(ExchangeAccount, ExchangeAccount.id == AccountBalanceSnapshot.exchange_account_id)
        .where(ExchangeAccount.is_active.is_(True))
        .order_by(AccountBalanceSnapshot.recorded_at.desc())
    )
    if exchange:
        query = query.where(ExchangeAccount.exchange == exchange.upper())
    rows = (await db.execute(query)).all()
    latest: dict[uuid.UUID, tuple[AccountBalanceSnapshot, ExchangeAccount]] = {}
    for snapshot, account in rows:
        latest.setdefault(account.id, (snapshot, account))
    return list(latest.values())


@router.get("/dashboard/summary")
async def dashboard_summary(
    _: AppSession = Depends(require_session), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    latest = await _latest_balances(db)
    current_positions = (
        await db.scalars(
            select(CurrentPosition).join(ExchangeAccount).where(ExchangeAccount.is_active.is_(True))
        )
    ).all()
    daily_rows = (
        await db.execute(
            select(
                DailyPnlSnapshot.snapshot_date,
                func.sum(DailyPnlSnapshot.investment_return),
                func.sum(DailyPnlSnapshot.equity_usd),
            )
            .group_by(DailyPnlSnapshot.snapshot_date)
            .order_by(DailyPnlSnapshot.snapshot_date)
        )
    ).all()
    total_equity = sum(_num(row.total_equity_usd) for row, _ in latest)
    available = sum(_num(row.available_balance_usd) for row, _ in latest)
    margin = sum(_num(row.margin_balance_usd) for row, _ in latest)
    unrealized_change = sum(_num(pos.tracking_unrealized_pnl_change) for pos in current_positions)
    cumulative = sum(_num(row[1]) for row in daily_rows[-1:])
    today_return = sum(_num(row[1]) for row in daily_rows if row[0] == datetime.now(UTC).date())
    return envelope(
        {
            "estimated_total_equity": total_equity,
            "available_balance": available,
            "margin_used": margin,
            "unrealized_pnl_change": unrealized_change,
            "today_pnl": today_return,
            "cumulative_pnl": cumulative,
            "unvalued_asset_count": sum(row.unvalued_asset_count for row, _ in latest),
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
                {"date": str(row[0]), "pnl": _num(row[1]), "equity": _num(row[2])}
                for row in daily_rows
            ],
            "positions": [_position_dict(item) for item in current_positions[:6]],
            "notice": "仅统计添加 API Key 后产生的数据",
            "demo_mode": any(account.is_demo for _, account in latest),
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


@router.get("/balances")
async def balances(
    exchange: str | None = None,
    _: AppSession = Depends(require_session),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    latest = await _latest_balances(db, exchange)
    return envelope(
        [
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
            }
            for row, account in latest
        ]
    )


def _position_dict(row: CurrentPosition) -> dict[str, Any]:
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
        "leverage": _num(row.leverage),
        "margin_mode": row.margin_mode,
        "margin_used": _num(row.margin_used),
        "unrealized_pnl": _num(row.unrealized_pnl),
        "tracking_unrealized_pnl_change": _num(row.tracking_unrealized_pnl_change),
        "unrealized_pnl_percent": _num(row.unrealized_pnl_percent),
        "realized_pnl": _num(row.realized_pnl),
        "funding_fee": _num(row.funding_fee),
        "trading_fee": _num(row.trading_fee),
        "open_time": row.open_time,
        "tracking_started_at": row.tracking_started_at,
        "is_initial_position": row.is_initial_position,
        "update_time": row.updated_at,
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
    return envelope({"items": [_position_dict(row) for row in rows], "total": total})


def _closed_dict(row: ClosedPosition) -> dict[str, Any]:
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
        "return_percent": _num(row.return_percent),
        "data_source": row.data_source,
        "data_completeness": row.data_completeness,
        "tracking_started_at": row.tracking_started_at,
    }


def _history_query(
    exchange: str | None,
    account_id: uuid.UUID | None,
    symbol: str | None,
    side: str | None,
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
            )
        )
    if side:
        query = query.where(ClosedPosition.side == side.upper())
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
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    _: AppSession = Depends(require_session),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    query = _history_query(exchange, account_id, symbol, side, start_time, end_time)
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
    return envelope({"items": [_closed_dict(row) for row in rows], "total": total})


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
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    _: AppSession = Depends(require_session),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    rows = (
        await db.scalars(
            _history_query(exchange, account_id, symbol, side, start_time, end_time)
            .order_by(ClosedPosition.close_time.desc())
            .limit(10_000)
        )
    ).all()
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
        item = _closed_dict(row)
        writer.writerow(
            [
                _safe_csv(item["exchange"]),
                _safe_csv(item["symbol"]),
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


async def _pnl_series(db: AsyncSession, bucket: str) -> list[dict[str, Any]]:
    if bucket == "daily":
        bucket_expr = DailyPnlSnapshot.snapshot_date
    else:
        bucket_expr = func.date_trunc(bucket, DailyPnlSnapshot.snapshot_date)
    rows = (
        await db.execute(
            select(
                bucket_expr.label("period"),
                func.sum(DailyPnlSnapshot.investment_return),
                func.sum(DailyPnlSnapshot.realized_pnl),
                func.sum(DailyPnlSnapshot.funding_fee),
                func.sum(DailyPnlSnapshot.trading_fee),
            )
            .group_by(bucket_expr)
            .order_by(bucket_expr)
        )
    ).all()
    return [
        {
            "period": str(row[0]),
            "investment_return": _num(row[1]),
            "realized_pnl": _num(row[2]),
            "funding_fee": _num(row[3]),
            "trading_fee": _num(row[4]),
        }
        for row in rows
    ]


@router.get("/pnl/summary")
async def pnl_summary(
    _: AppSession = Depends(require_session), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    daily = await _pnl_series(db, "daily")
    latest_initial = (await db.scalars(select(InitialAccountSnapshot))).all()
    positions = (await db.scalars(select(CurrentPosition))).all()
    values = [row["investment_return"] for row in daily]
    return envelope(
        {
            "period_initial_equity": sum(_num(row.initial_equity) for row in latest_initial),
            "period_investment_return": sum(values[-1:]),
            "period_realized_pnl": sum(row["realized_pnl"] for row in daily),
            "period_unrealized_pnl_change": sum(
                _num(row.tracking_unrealized_pnl_change) for row in positions
            ),
            "period_funding_fee": sum(row["funding_fee"] for row in daily),
            "period_trading_fee": sum(row["trading_fee"] for row in daily),
            "best_day": max(values, default=0),
            "worst_day": min(values, default=0),
            "profitable_days": sum(value > 0 for value in values),
            "losing_days": sum(value < 0 for value in values),
            "notice": "仅统计添加 API Key 后产生的数据",
        }
    )


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
    rows = (
        await db.execute(
            select(
                DailyPnlSnapshot.exchange,
                func.sum(DailyPnlSnapshot.realized_pnl),
                func.sum(DailyPnlSnapshot.funding_fee),
                func.sum(DailyPnlSnapshot.trading_fee),
                func.max(DailyPnlSnapshot.investment_return),
            ).group_by(DailyPnlSnapshot.exchange)
        )
    ).all()
    return envelope(
        [
            {
                "exchange": row[0],
                "realized_pnl": _num(row[1]),
                "funding_fee": _num(row[2]),
                "trading_fee": _num(row[3]),
                "investment_return": _num(row[4]),
            }
            for row in rows
        ]
    )


@router.get("/sync/status")
async def sync_status(
    _: AppSession = Depends(require_session), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    rows = (await db.scalars(select(SyncJob).order_by(SyncJob.started_at.desc()).limit(50))).all()
    return envelope(
        [
            {
                "id": row.id,
                "account_id": row.exchange_account_id,
                "type": row.job_type,
                "status": row.status,
                "started_at": row.started_at,
                "finished_at": row.finished_at,
                "duration_ms": row.duration_ms,
                "records_written": row.records_written,
            }
            for row in rows
        ]
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
