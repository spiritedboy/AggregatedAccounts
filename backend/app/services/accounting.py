import uuid
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import String, case, cast, func, literal, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AccountBalanceSnapshot,
    AssetBalanceSnapshot,
    CashFlowRecord,
    ClosedPosition,
    CurrentPosition,
    ExchangeAccount,
    FundingRecord,
    IncomeRecord,
    SyncJob,
    TradingFeeRecord,
)


def _num(value: Any) -> float:
    return float(value or 0)


def _ledger_union():
    empty_symbol = cast(literal(None), String(80))
    return union_all(
        select(
            IncomeRecord.id.label("id"),
            IncomeRecord.exchange_account_id.label("exchange_account_id"),
            IncomeRecord.exchange.label("exchange"),
            literal("REALIZED_PNL").label("record_type"),
            IncomeRecord.income_type.label("subtype"),
            IncomeRecord.asset.label("asset"),
            IncomeRecord.amount_usd.label("amount_usd"),
            IncomeRecord.amount_usd.label("signed_amount_usd"),
            empty_symbol.label("symbol"),
            IncomeRecord.record_time.label("record_time"),
            IncomeRecord.source_record_id.label("source_record_id"),
        ),
        select(
            FundingRecord.id.label("id"),
            FundingRecord.exchange_account_id.label("exchange_account_id"),
            FundingRecord.exchange.label("exchange"),
            literal("FUNDING_FEE").label("record_type"),
            literal("FUNDING_FEE").label("subtype"),
            FundingRecord.asset.label("asset"),
            FundingRecord.amount_usd.label("amount_usd"),
            FundingRecord.amount_usd.label("signed_amount_usd"),
            FundingRecord.symbol.label("symbol"),
            FundingRecord.record_time.label("record_time"),
            FundingRecord.source_record_id.label("source_record_id"),
        ),
        select(
            TradingFeeRecord.id.label("id"),
            TradingFeeRecord.exchange_account_id.label("exchange_account_id"),
            TradingFeeRecord.exchange.label("exchange"),
            literal("TRADING_FEE").label("record_type"),
            literal("TRADING_FEE").label("subtype"),
            TradingFeeRecord.asset.label("asset"),
            TradingFeeRecord.amount_usd.label("amount_usd"),
            (-TradingFeeRecord.amount_usd).label("signed_amount_usd"),
            TradingFeeRecord.symbol.label("symbol"),
            TradingFeeRecord.record_time.label("record_time"),
            TradingFeeRecord.source_record_id.label("source_record_id"),
        ),
        select(
            CashFlowRecord.id.label("id"),
            CashFlowRecord.exchange_account_id.label("exchange_account_id"),
            CashFlowRecord.exchange.label("exchange"),
            func.upper(CashFlowRecord.flow_type).label("record_type"),
            func.upper(CashFlowRecord.flow_type).label("subtype"),
            CashFlowRecord.asset.label("asset"),
            CashFlowRecord.amount_usd.label("amount_usd"),
            case(
                (
                    func.upper(CashFlowRecord.flow_type).in_(
                        {"WITHDRAW", "WITHDRAWAL"}
                    ),
                    -CashFlowRecord.amount_usd,
                ),
                else_=CashFlowRecord.amount_usd,
            ).label("signed_amount_usd"),
            empty_symbol.label("symbol"),
            CashFlowRecord.record_time.label("record_time"),
            CashFlowRecord.source_record_id.label("source_record_id"),
        ),
    ).subquery("ledger_records")


def _filtered_ledger_query(
    *,
    exchange: str | None,
    account_id: uuid.UUID | None,
    record_type: str | None,
    start_time: datetime | None,
    end_time: datetime | None,
):
    ledger = _ledger_union()
    query = (
        select(
            ledger,
            ExchangeAccount.connection_name.label("connection_name"),
        )
        .join(
            ExchangeAccount,
            ExchangeAccount.id == ledger.c.exchange_account_id,
        )
        .where(ExchangeAccount.is_active.is_(True))
    )
    if exchange:
        query = query.where(ledger.c.exchange == exchange.upper())
    if account_id:
        query = query.where(ledger.c.exchange_account_id == account_id)
    if record_type:
        normalized_type = record_type.upper()
        if normalized_type == "CASH_FLOW":
            query = query.where(
                ledger.c.record_type.in_(
                    {"DEPOSIT", "WITHDRAW", "WITHDRAWAL"}
                )
            )
        else:
            query = query.where(ledger.c.record_type == normalized_type)
    if start_time:
        query = query.where(ledger.c.record_time >= start_time)
    if end_time:
        query = query.where(ledger.c.record_time <= end_time)
    return query


async def list_accounting_records(
    db: AsyncSession,
    *,
    exchange: str | None = None,
    account_id: uuid.UUID | None = None,
    record_type: str | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    offset: int = 0,
    limit: int = 50,
) -> dict[str, Any]:
    filtered = _filtered_ledger_query(
        exchange=exchange,
        account_id=account_id,
        record_type=record_type,
        start_time=start_time,
        end_time=end_time,
    ).subquery("filtered_ledger")
    total = await db.scalar(select(func.count()).select_from(filtered))
    rows = (
        await db.execute(
            select(filtered)
            .order_by(filtered.c.record_time.desc(), filtered.c.id)
            .offset(offset)
            .limit(limit)
        )
    ).mappings()
    summary_row = (
        await db.execute(
            select(
                func.coalesce(
                    func.sum(
                        case(
                            (
                                filtered.c.record_type == "REALIZED_PNL",
                                filtered.c.signed_amount_usd,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("realized_pnl"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                filtered.c.record_type == "FUNDING_FEE",
                                filtered.c.signed_amount_usd,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("funding_fee"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                filtered.c.record_type == "TRADING_FEE",
                                filtered.c.amount_usd,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("trading_fee"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                filtered.c.record_type == "DEPOSIT",
                                filtered.c.amount_usd,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("deposits"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                filtered.c.record_type.in_(
                                    {"WITHDRAW", "WITHDRAWAL"}
                                ),
                                filtered.c.amount_usd,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("withdrawals"),
                func.coalesce(func.sum(filtered.c.signed_amount_usd), 0).label(
                    "net_effect"
                ),
            )
        )
    ).mappings().one()
    summary = {key: _num(value) for key, value in summary_row.items()}
    closed_query = (
        select(func.coalesce(func.sum(ClosedPosition.realized_pnl), 0))
        .join(
            ExchangeAccount,
            ExchangeAccount.id == ClosedPosition.exchange_account_id,
        )
        .where(ExchangeAccount.is_active.is_(True))
    )
    if exchange:
        closed_query = closed_query.where(ClosedPosition.exchange == exchange.upper())
    if account_id:
        closed_query = closed_query.where(
            ClosedPosition.exchange_account_id == account_id
        )
    if start_time:
        closed_query = closed_query.where(ClosedPosition.close_time >= start_time)
    if end_time:
        closed_query = closed_query.where(ClosedPosition.close_time <= end_time)
    summary["realized_pnl"] = (
        _num(await db.scalar(closed_query))
        if record_type is None or record_type.upper() == "REALIZED_PNL"
        else 0.0
    )
    summary["net_cash_flow"] = summary["deposits"] - summary["withdrawals"]
    summary["net_realized_pnl"] = (
        summary["realized_pnl"]
        + summary["funding_fee"]
        - summary["trading_fee"]
    )
    return {
        "items": [
            {
                "id": row["id"],
                "exchange_account_id": row["exchange_account_id"],
                "exchange": row["exchange"],
                "connection_name": row["connection_name"],
                "record_type": row["record_type"],
                "subtype": row["subtype"],
                "asset": row["asset"],
                "amount_usd": _num(row["amount_usd"]),
                "signed_amount_usd": _num(row["signed_amount_usd"]),
                "symbol": row["symbol"],
                "record_time": row["record_time"],
                "source_record_id": row["source_record_id"],
            }
            for row in rows
        ],
        "total": total or 0,
        "summary": summary,
    }


async def _record_stats(
    db: AsyncSession,
    model: Any,
    account_ids: list[uuid.UUID],
    time_column: Any,
) -> dict[uuid.UUID, tuple[int, datetime | None]]:
    if not account_ids:
        return {}
    rows = (
        await db.execute(
            select(
                model.exchange_account_id,
                func.count(model.id),
                func.max(time_column),
            )
            .where(model.exchange_account_id.in_(account_ids))
            .group_by(model.exchange_account_id)
        )
    ).all()
    return {row[0]: (int(row[1]), row[2]) for row in rows}


def _component(
    *,
    status: str,
    last_synced_at: datetime | None,
    record_count: int,
    latest_record_at: datetime | None,
    reason: str,
) -> dict[str, Any]:
    return {
        "status": status,
        "last_synced_at": last_synced_at,
        "record_count": record_count,
        "latest_record_at": latest_record_at,
        "reason": reason,
    }


async def build_data_completeness(db: AsyncSession) -> dict[str, Any]:
    accounts = list(
        (
            await db.scalars(
                select(ExchangeAccount)
                .where(ExchangeAccount.is_active.is_(True))
                .order_by(ExchangeAccount.created_at)
            )
        ).all()
    )
    account_ids = [account.id for account in accounts]
    balance_stats = await _record_stats(
        db, AccountBalanceSnapshot, account_ids, AccountBalanceSnapshot.recorded_at
    )
    asset_balance_stats = await _record_stats(
        db, AssetBalanceSnapshot, account_ids, AssetBalanceSnapshot.recorded_at
    )
    position_stats = await _record_stats(
        db, CurrentPosition, account_ids, CurrentPosition.updated_at
    )
    income_stats = await _record_stats(
        db, IncomeRecord, account_ids, IncomeRecord.record_time
    )
    closed_stats = await _record_stats(
        db, ClosedPosition, account_ids, ClosedPosition.close_time
    )
    funding_stats = await _record_stats(
        db, FundingRecord, account_ids, FundingRecord.record_time
    )
    fee_stats = await _record_stats(
        db, TradingFeeRecord, account_ids, TradingFeeRecord.record_time
    )
    cash_stats = await _record_stats(
        db, CashFlowRecord, account_ids, CashFlowRecord.record_time
    )
    full_jobs = (
        await db.scalars(
            select(SyncJob)
            .where(
                SyncJob.exchange_account_id.in_(account_ids),
                SyncJob.job_type == "FULL_ACCOUNT",
                SyncJob.status == "SUCCESS",
            )
            .order_by(
                SyncJob.exchange_account_id,
                func.coalesce(SyncJob.finished_at, SyncJob.started_at).desc(),
                SyncJob.id.desc(),
            )
            .distinct(SyncJob.exchange_account_id)
        )
    ).all()
    latest_full_job = {job.exchange_account_id: job for job in full_jobs}

    items: list[dict[str, Any]] = []
    status_counts: dict[str, int] = defaultdict(int)
    for account in accounts:
        full_job = latest_full_job.get(account.id)
        full_synced_at = (
            full_job.finished_at or full_job.started_at if full_job else None
        )
        balance_count, latest_balance = balance_stats.get(account.id, (0, None))
        asset_balance_count, latest_asset_balance = asset_balance_stats.get(
            account.id, (0, None)
        )
        position_count, latest_position = position_stats.get(account.id, (0, None))
        income_count, latest_income = income_stats.get(account.id, (0, None))
        closed_count, latest_closed = closed_stats.get(account.id, (0, None))
        funding_count, latest_funding = funding_stats.get(account.id, (0, None))
        fee_count, latest_fee = fee_stats.get(account.id, (0, None))
        cash_count, latest_cash = cash_stats.get(account.id, (0, None))
        details = dict(account.data_completeness_details or {})
        primary_status = (
            "COMPLETE"
            if account.connection_status == "CONNECTED" and account.last_synced_at
            else "PARTIAL"
        )
        primary_reason = (
            "账户权益已成功刷新"
            if primary_status == "COMPLETE"
            else "账户尚未成功完成资产刷新"
        )
        components = {
            "equity": _component(
                status=details.get("equity", primary_status),
                last_synced_at=account.last_synced_at,
                record_count=balance_count,
                latest_record_at=latest_balance,
                reason=primary_reason,
            ),
            "positions": _component(
                status=details.get("positions", primary_status),
                last_synced_at=account.last_synced_at,
                record_count=position_count,
                latest_record_at=latest_position,
                reason=(
                    "当前仓位已成功刷新；0 条表示当前没有未平仓仓位"
                    if primary_status == "COMPLETE"
                    else "当前仓位尚未成功刷新"
                ),
            ),
            "balances": _component(
                status=details.get(
                    "balances",
                    "COMPLETE"
                    if asset_balance_count and primary_status == "COMPLETE"
                    else "PARTIAL",
                ),
                last_synced_at=account.last_synced_at,
                record_count=asset_balance_count,
                latest_record_at=latest_asset_balance,
                reason=(
                    "逐资产余额已落库且可美元估值"
                    if details.get("balances") == "COMPLETE"
                    else "逐资产余额尚未落库，或存在无法可靠美元估值的资产"
                ),
            ),
            "closed_positions": _component(
                status=details.get(
                    "closed_positions",
                    "PARTIAL",
                ),
                last_synced_at=account.last_synced_at,
                record_count=closed_count,
                latest_record_at=latest_closed,
                reason=(
                    "已平仓接口已成功拉取；0 条表示统计期内没有已平仓仓位"
                    if details.get("closed_positions") == "COMPLETE"
                    else "已平仓记录存在字段缺失，或尚未完成能力验证"
                ),
            ),
        }
        if account.exchange == "POLYMARKET":
            components["realized_pnl"] = _component(
                status="PARTIAL",
                last_synced_at=account.last_synced_at,
                record_count=closed_count,
                latest_record_at=latest_closed,
                reason="公开已平仓接口不提供完整原始开仓时间，按部分完整处理",
            )
            for key, reason in (
                ("funding_fee", "Polymarket 没有永续合约资金费口径"),
                ("trading_fee", "公开接口不提供完整的账户级交易手续费流水"),
                ("cash_flow", "公开接口不能完整确认所有充值和提现流水"),
            ):
                components[key] = _component(
                    status="UNSUPPORTED",
                    last_synced_at=None,
                    record_count=0,
                    latest_record_at=None,
                    reason=reason,
                )
        else:
            components.update(
                {
                    "realized_pnl": _component(
                        status=details.get("income", "PARTIAL"),
                        last_synced_at=full_synced_at,
                        record_count=income_count,
                        latest_record_at=latest_income,
                        reason=(
                            "最近一次账务拉取成功；0 条表示统计期内没有该类记录"
                            if details.get("income") == "COMPLETE"
                            else "账务接口存在未识别流水，或尚未完成首次完整拉取"
                        ),
                    ),
                    "funding_fee": _component(
                        status=details.get("funding", "PARTIAL"),
                        last_synced_at=full_synced_at,
                        record_count=funding_count,
                        latest_record_at=latest_funding,
                        reason=(
                            "最近一次资金费拉取成功"
                            if details.get("funding") == "COMPLETE"
                            else "资金费流水覆盖不完整或尚未验证"
                        ),
                    ),
                    "trading_fee": _component(
                        status=details.get("fees", "PARTIAL"),
                        last_synced_at=full_synced_at,
                        record_count=fee_count,
                        latest_record_at=latest_fee,
                        reason=(
                            "最近一次手续费拉取成功"
                            if details.get("fees") == "COMPLETE"
                            else "手续费流水覆盖不完整或尚未验证"
                        ),
                    ),
                    "cash_flow": _component(
                        status=details.get("cash_flows", "PARTIAL"),
                        last_synced_at=full_synced_at,
                        record_count=cash_count,
                        latest_record_at=latest_cash,
                        reason=(
                            "最近一次资金流水拉取成功"
                            if details.get("cash_flows") == "COMPLETE"
                            else "资金流水存在未识别类型或尚未验证"
                        ),
                    ),
                }
            )
        for component in components.values():
            status_counts[component["status"]] += 1
        items.append(
            {
                "account_id": account.id,
                "exchange": account.exchange,
                "connection_name": account.connection_name,
                "overall_status": account.data_completeness,
                "components": components,
            }
        )
    return {
        "summary": {
            "total_accounts": len(items),
            "complete_components": status_counts["COMPLETE"],
            "partial_components": status_counts["PARTIAL"],
            "unsupported_components": status_counts["UNSUPPORTED"],
            "checked_at": datetime.now(UTC),
        },
        "accounts": items,
    }
