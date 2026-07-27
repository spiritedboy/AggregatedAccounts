import asyncio
import hashlib
import time
import uuid
from datetime import UTC, datetime, timedelta
from datetime import time as dt_time
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters import ADAPTERS
from app.adapters.base import AdapterError, ExchangeAdapter
from app.config import settings
from app.models import (
    AccountBalanceSnapshot,
    AssetBalanceSnapshot,
    CashFlowRecord,
    ClosedPosition,
    CurrentPosition,
    DailyPnlSnapshot,
    EncryptedCredential,
    ExchangeAccount,
    FundingRecord,
    IncomeRecord,
    InitialAccountSnapshot,
    PositionSnapshot,
    SecurityAuditLog,
    SyncError,
    SyncJob,
    TrackingPeriod,
    TradingFeeRecord,
)
from app.schemas import ExchangeAccountCreate
from app.security import CredentialCipher, EncryptedField, mask_identifier

cipher = CredentialCipher(settings.app_encryption_key)
_account_locks: dict[uuid.UUID, asyncio.Lock] = {}
PUBLIC_ADDRESS_EXCHANGES = {"HYPERLIQUID", "POLYMARKET"}
HISTORY_STREAMS = frozenset({"income", "funding", "fees", "cash_flows"})
COMPLETENESS_KEYS = frozenset(
    {"equity", "balances", "positions", "closed_positions", *HISTORY_STREAMS}
)


def _make_adapter(payload: ExchangeAccountCreate) -> ExchangeAdapter:
    adapter_type = ADAPTERS[payload.exchange]
    return adapter_type(
        api_key=payload.api_key,
        api_secret=payload.api_secret,
        passphrase=payload.passphrase,
        wallet_address=payload.wallet_address,
        timeout=settings.request_timeout_seconds,
    )


def _encrypt_optional(value: str | None, context: str) -> EncryptedField | None:
    return cipher.encrypt(value, context) if value else None


def _credential_field(credential: EncryptedCredential, name: str, context: str) -> str | None:
    ciphertext = getattr(credential, f"{name}_ciphertext")
    if not ciphertext:
        return None
    field = EncryptedField(
        ciphertext=ciphertext,
        nonce=getattr(credential, f"{name}_nonce"),
        tag=getattr(credential, f"{name}_tag"),
        version=credential.encryption_version,
    )
    return cipher.decrypt(field, context)


async def create_account(
    db: AsyncSession, payload: ExchangeAccountCreate, ip: str
) -> ExchangeAccount:
    adapter = _make_adapter(payload)
    try:
        await adapter.test_connection()
        permissions = await adapter.get_permissions()
        dangerous = [
            name
            for name in ("spot_trade", "futures_trade", "transfer", "withdraw")
            if permissions.get(name) is True
        ]
        if dangerous:
            raise ValueError(f"检测到高风险权限（{', '.join(dangerous)}），请创建纯只读 API Key")
        summary, positions = await asyncio.gather(
            adapter.get_account_summary(),
            adapter.get_open_positions(),
        )
        balances = await adapter.get_balances()
    finally:
        await adapter.close()

    started_at = datetime.now(UTC)
    identifier = adapter.wallet_address or payload.wallet_address or payload.api_key or ""
    account = ExchangeAccount(
        exchange=payload.exchange,
        connection_name=payload.connection_name,
        public_identifier=adapter.wallet_address if payload.wallet_address else None,
        masked_identifier=mask_identifier(identifier),
        permission_status=permissions,
        connection_status="CONNECTED",
        data_completeness="PARTIAL",
        data_completeness_details={
            "equity": "COMPLETE",
            "balances": "COMPLETE",
            "positions": "COMPLETE",
            "closed_positions": "UNKNOWN",
            **{stream: "UNSUPPORTED" if payload.exchange == "POLYMARKET" else "UNKNOWN"
               for stream in HISTORY_STREAMS},
            "asset_coverage_version": 2,
        },
        tracking_started_at=started_at,
        last_synced_at=started_at,
    )
    db.add(account)
    await db.flush()

    period = TrackingPeriod(
        exchange=account.exchange,
        exchange_account_id=account.id,
        started_at=started_at,
        is_active=True,
    )
    db.add(period)
    await db.flush()

    if payload.exchange not in PUBLIC_ADDRESS_EXCHANGES:
        api_key = _encrypt_optional(payload.api_key, f"{account.id}:api_key")
        secret = _encrypt_optional(payload.api_secret, f"{account.id}:secret")
        passphrase = _encrypt_optional(payload.passphrase, f"{account.id}:passphrase")
        db.add(
            EncryptedCredential(
                exchange_account_id=account.id,
                api_key_ciphertext=api_key.ciphertext if api_key else None,
                api_key_nonce=api_key.nonce if api_key else None,
                api_key_tag=api_key.tag if api_key else None,
                secret_ciphertext=secret.ciphertext if secret else None,
                secret_nonce=secret.nonce if secret else None,
                secret_tag=secret.tag if secret else None,
                passphrase_ciphertext=passphrase.ciphertext if passphrase else None,
                passphrase_nonce=passphrase.nonce if passphrase else None,
                passphrase_tag=passphrase.tag if passphrase else None,
            )
        )

    db.add(
        InitialAccountSnapshot(
            exchange=account.exchange,
            exchange_account_id=account.id,
            tracking_period_id=period.id,
            source_record_id=f"initial-{started_at.timestamp()}",
            initial_equity=Decimal(str(summary.get("total_equity_usd", 0))),
            initial_available_balance=Decimal(str(summary.get("available_balance_usd", 0))),
            initial_margin_balance=Decimal(str(summary.get("margin_balance_usd", 0))),
            initial_unrealized_pnl=Decimal(str(summary.get("unrealized_pnl_usd", 0))),
            initial_positions=positions,
            tracking_started_at=started_at,
        )
    )
    await _write_summary(db, account, period, summary, started_at)
    await _write_asset_balances(db, account, period, balances, started_at)
    await _replace_positions(db, account, period, positions, started_at, initial=True)
    await _write_position_snapshots(db, account, period, positions, started_at)
    db.add(
        SecurityAuditLog(
            action="EXCHANGE_ACCOUNT_CREATED",
            outcome="SUCCESS",
            client_ip=ip,
            details={"exchange": account.exchange, "account_id": str(account.id)},
        )
    )
    await db.commit()
    return account


async def adapter_for_account(db: AsyncSession, account: ExchangeAccount) -> ExchangeAdapter:
    if account.exchange in PUBLIC_ADDRESS_EXCHANGES:
        return ADAPTERS[account.exchange](
            wallet_address=account.public_identifier,
            timeout=settings.request_timeout_seconds,
        )
    credential = await db.scalar(
        select(EncryptedCredential).where(EncryptedCredential.exchange_account_id == account.id)
    )
    if not credential:
        raise AdapterError("凭证已删除")
    return ADAPTERS[account.exchange](
        api_key=_credential_field(credential, "api_key", f"{account.id}:api_key"),
        api_secret=_credential_field(credential, "secret", f"{account.id}:secret"),
        passphrase=_credential_field(credential, "passphrase", f"{account.id}:passphrase"),
        timeout=settings.request_timeout_seconds,
    )


async def _write_summary(
    db: AsyncSession,
    account: ExchangeAccount,
    period: TrackingPeriod,
    summary: dict[str, Any],
    recorded_at: datetime,
) -> None:
    source_id = f"balance-{recorded_at:%Y%m%d%H%M%S}"
    db.add(
        AccountBalanceSnapshot(
            exchange=account.exchange,
            exchange_account_id=account.id,
            tracking_period_id=period.id,
            source_record_id=source_id,
            total_equity_usd=Decimal(str(summary.get("total_equity_usd", 0))),
            available_balance_usd=Decimal(str(summary.get("available_balance_usd", 0))),
            margin_balance_usd=Decimal(str(summary.get("margin_balance_usd", 0))),
            unrealized_pnl_usd=Decimal(str(summary.get("unrealized_pnl_usd", 0))),
            unvalued_asset_count=int(summary.get("unvalued_asset_count", 0)),
            price_source=summary.get("price_source", "EXCHANGE_API"),
            recorded_at=recorded_at,
        )
    )


def _snapshot_source(prefix: str, recorded_at: datetime, key: str) -> str:
    digest = hashlib.sha256(key.encode()).hexdigest()[:20]
    return f"{prefix}-{recorded_at:%Y%m%d%H%M%S}-{digest}"


async def _write_asset_balances(
    db: AsyncSession,
    account: ExchangeAccount,
    period: TrackingPeriod,
    balances: list[dict[str, Any]],
    recorded_at: datetime,
) -> None:
    for item in balances:
        asset = str(item.get("asset") or "UNKNOWN").upper()
        account_type = str(item.get("account_type") or "SPOT").upper()
        value = item.get("value_usd")
        db.add(
            AssetBalanceSnapshot(
                exchange=account.exchange,
                exchange_account_id=account.id,
                tracking_period_id=period.id,
                source_record_id=_snapshot_source(
                    "asset", recorded_at, f"{account_type}:{asset}"
                ),
                asset=asset,
                account_type=account_type,
                available=Decimal(str(item.get("available", 0))),
                locked=Decimal(str(item.get("locked", 0))),
                value_usd=Decimal(str(value)) if value is not None else None,
                price_source=str(item.get("price_source") or "EXCHANGE_API"),
                recorded_at=recorded_at,
            )
        )


async def _write_position_snapshots(
    db: AsyncSession,
    account: ExchangeAccount,
    period: TrackingPeriod,
    positions: list[dict[str, Any]],
    recorded_at: datetime,
) -> None:
    for item in positions:
        db.add(
            PositionSnapshot(
                exchange=account.exchange,
                exchange_account_id=account.id,
                tracking_period_id=period.id,
                source_record_id=_snapshot_source(
                    "position", recorded_at, str(item["source_record_id"])
                ),
                normalized_symbol=item["normalized_symbol"],
                side=item["side"],
                position_size=Decimal(str(item.get("position_size", 0))),
                mark_price=Decimal(str(item.get("mark_price", 0))),
                unrealized_pnl=Decimal(str(item.get("unrealized_pnl", 0))),
                recorded_at=recorded_at,
            )
        )


def update_completeness(
    account: ExchangeAccount,
    updates: dict[str, str],
    *,
    authoritative: bool = False,
) -> None:
    details = dict(account.data_completeness_details or {})
    for key, status in updates.items():
        if key not in COMPLETENESS_KEYS:
            continue
        current = details.get(key)
        if (
            not authoritative
            and current == "PARTIAL"
            and status == "COMPLETE"
        ):
            continue
        details[key] = status
    account.data_completeness_details = details
    relevant = [
        details.get(key, "UNKNOWN")
        for key in COMPLETENESS_KEYS
        if details.get(key) != "UNSUPPORTED"
    ]
    account.data_completeness = (
        "COMPLETE"
        if relevant
        and all(status == "COMPLETE" for status in relevant)
        else "PARTIAL"
    )


async def _apply_asset_coverage_baseline(
    db: AsyncSession,
    account: ExchangeAccount,
    period: TrackingPeriod,
    summary: dict[str, Any],
) -> None:
    details = dict(account.data_completeness_details or {})
    if int(details.get("asset_coverage_version") or 0) >= 2:
        return
    initial = await db.scalar(
        select(InitialAccountSnapshot).where(
            InitialAccountSnapshot.tracking_period_id == period.id
        )
    )
    if initial:
        initial.initial_equity += Decimal(
            str(summary.get("legacy_excluded_equity_usd", 0))
        )
        initial.initial_available_balance += Decimal(
            str(summary.get("legacy_excluded_available_usd", 0))
        )
        initial.initial_margin_balance += Decimal(
            str(summary.get("legacy_excluded_margin_usd", 0))
        )
        initial.initial_unrealized_pnl += Decimal(
            str(summary.get("legacy_excluded_unrealized_pnl_usd", 0))
        )
    details["asset_coverage_version"] = 2
    account.data_completeness_details = details


async def _replace_positions(
    db: AsyncSession,
    account: ExchangeAccount,
    period: TrackingPeriod,
    positions: list[dict[str, Any]],
    recorded_at: datetime,
    initial: bool = False,
) -> None:
    existing_rows = (
        await db.scalars(
            select(CurrentPosition).where(
                CurrentPosition.exchange_account_id == account.id,
                CurrentPosition.tracking_period_id == period.id,
            )
        )
    ).all()
    existing = {(row.normalized_symbol, row.side): row for row in existing_rows}
    incoming_keys = {(row["normalized_symbol"], row["side"]) for row in positions}
    for key, row in existing.items():
        if key not in incoming_keys:
            await db.delete(row)
    for item in positions:
        key = (item["normalized_symbol"], item["side"])
        row = existing.get(key)
        if row is None:
            row = CurrentPosition(
                exchange=account.exchange,
                exchange_account_id=account.id,
                tracking_period_id=period.id,
                source_record_id=str(item["source_record_id"]),
                symbol=item["symbol"],
                normalized_symbol=item["normalized_symbol"],
                side=item["side"],
                tracking_started_at=account.tracking_started_at,
                is_initial_position=initial,
                tracking_entry_price=Decimal(str(item.get("entry_price", 0))),
                tracking_initial_mark_price=Decimal(str(item.get("mark_price", 0))),
                tracking_initial_unrealized_pnl=Decimal(
                    str(item.get("unrealized_pnl", 0) if initial else 0)
                ),
            )
            db.add(row)
        initial_pnl = row.tracking_initial_unrealized_pnl or Decimal("0")
        current_pnl = Decimal(str(item.get("unrealized_pnl", 0)))
        for field in (
            "position_size",
            "position_value_usd",
            "entry_price",
            "mark_price",
            "margin_used",
        ):
            setattr(row, field, Decimal(str(item.get(field, 0))))
        row.liquidation_price = (
            Decimal(str(item["liquidation_price"])) if item.get("liquidation_price") else None
        )
        row.leverage = Decimal(str(item["leverage"])) if item.get("leverage") else None
        row.source_record_id = str(item["source_record_id"])
        row.symbol = item["symbol"]
        row.market_type = item.get("market_type", "PERPETUAL")
        row.margin_mode = item.get("margin_mode", "UNKNOWN")
        row.unrealized_pnl = current_pnl
        row.tracking_unrealized_pnl_change = current_pnl - initial_pnl
        row.unrealized_pnl_percent = Decimal(
            str(
                item.get(
                    "unrealized_pnl_percent",
                    current_pnl / row.position_value_usd * 100
                    if row.position_value_usd
                    else 0,
                )
            )
        )
        row.realized_pnl = Decimal(str(item.get("realized_pnl", 0)))
        row.open_time = item.get("open_time")
        row.updated_at = recorded_at


async def _upsert_closed_positions(
    db: AsyncSession,
    account: ExchangeAccount,
    period: TrackingPeriod,
    positions: list[dict[str, Any]],
) -> int:
    if not positions:
        return 0
    source_ids = [str(item["source_record_id"]) for item in positions]
    existing_query = select(ClosedPosition).where(
        ClosedPosition.exchange_account_id == account.id,
        ClosedPosition.tracking_period_id == period.id,
    )
    if account.exchange != "POLYMARKET":
        existing_query = existing_query.where(ClosedPosition.source_record_id.in_(source_ids))
    existing_rows = (await db.scalars(existing_query)).all()
    existing = {row.source_record_id: row for row in existing_rows}
    polymarket_rows: dict[tuple[str, str], list[ClosedPosition]] = {}
    if account.exchange == "POLYMARKET":
        for existing_row in existing_rows:
            key = (existing_row.normalized_symbol, existing_row.side)
            polymarket_rows.setdefault(key, []).append(existing_row)
    for item in positions:
        source_id = str(item["source_record_id"])
        row = existing.get(source_id)
        if row is None and account.exchange == "POLYMARKET":
            legacy = polymarket_rows.get((item["normalized_symbol"], item["side"]), [])
            if legacy:
                row = max(
                    legacy,
                    key=lambda candidate: (
                        candidate.updated_at,
                        candidate.created_at,
                        candidate.close_time,
                    ),
                )
                for duplicate in legacy:
                    if duplicate.id != row.id:
                        await db.delete(duplicate)
                await db.flush()
                row.source_record_id = source_id
                existing[source_id] = row
        if row is None:
            row = ClosedPosition(
                exchange=account.exchange,
                exchange_account_id=account.id,
                tracking_period_id=period.id,
                source_record_id=source_id,
                symbol=item["symbol"],
                normalized_symbol=item["normalized_symbol"],
                side=item["side"],
                open_time=item["open_time"],
                close_time=item["close_time"],
                tracking_started_at=account.tracking_started_at,
            )
            db.add(row)
        row.symbol = item["symbol"]
        row.normalized_symbol = item["normalized_symbol"]
        row.side = item["side"]
        row.open_time = item["open_time"]
        row.close_time = item["close_time"]
        for field in (
            "average_entry_price",
            "average_exit_price",
            "max_position_size",
            "realized_pnl",
            "funding_fee",
            "trading_fee",
            "net_pnl",
            "return_percent",
        ):
            setattr(row, field, Decimal(str(item.get(field, 0))))
        row.data_source = item.get("data_source", "EXCHANGE_API")
        row.data_completeness = item.get("data_completeness", "PARTIAL")
    return len(positions)


async def _upsert_amount_records(
    db: AsyncSession,
    account: ExchangeAccount,
    period: TrackingPeriod,
    model: type[IncomeRecord | FundingRecord | TradingFeeRecord | CashFlowRecord],
    records: list[dict[str, Any]],
) -> int:
    valid_records = [
        item
        for item in records
        if period.started_at <= item["record_time"]
        and item["record_time"] <= datetime.now(UTC)
    ]
    if not valid_records:
        return 0
    source_ids = [str(item["source_record_id"])[:160] for item in valid_records]
    existing_rows = (
        await db.scalars(
            select(model).where(
                model.exchange_account_id == account.id,
                model.tracking_period_id == period.id,
                model.source_record_id.in_(source_ids),
            )
        )
    ).all()
    existing = {row.source_record_id: row for row in existing_rows}
    for item, source_id in zip(valid_records, source_ids, strict=True):
        row = existing.get(source_id)
        if row is None:
            kwargs: dict[str, Any] = {
                "exchange": account.exchange,
                "exchange_account_id": account.id,
                "tracking_period_id": period.id,
                "source_record_id": source_id,
            }
            if model is IncomeRecord:
                kwargs["income_type"] = item.get("income_type", "UNKNOWN")
            elif model is CashFlowRecord:
                kwargs["flow_type"] = item.get("flow_type", "UNKNOWN")
            elif model in {FundingRecord, TradingFeeRecord}:
                kwargs["symbol"] = item.get("symbol")
            row = model(**kwargs)
            db.add(row)
            existing[source_id] = row
        row.asset = str(item.get("asset") or "USD").upper()
        row.amount_usd = Decimal(str(item.get("amount_usd", 0)))
        row.record_time = item["record_time"]
        if model is IncomeRecord:
            row.income_type = item.get("income_type", "UNKNOWN")
        elif model is CashFlowRecord:
            row.flow_type = item.get("flow_type", "UNKNOWN")
        elif model in {FundingRecord, TradingFeeRecord}:
            row.symbol = item.get("symbol")
    return len(valid_records)


async def _last_full_history_sync(
    db: AsyncSession, account: ExchangeAccount
) -> SyncJob | None:
    return await db.scalar(
        select(SyncJob)
        .where(
            SyncJob.exchange_account_id == account.id,
            SyncJob.job_type == "FULL_ACCOUNT",
            SyncJob.status == "SUCCESS",
        )
        .order_by(SyncJob.finished_at.desc())
        .limit(1)
    )


async def _write_daily_snapshot(
    db: AsyncSession,
    account: ExchangeAccount,
    period: TrackingPeriod,
    summary: dict[str, Any],
    recorded_at: datetime,
) -> None:
    initial = await db.scalar(
        select(InitialAccountSnapshot).where(
            InitialAccountSnapshot.tracking_period_id == period.id
        )
    )
    if not initial:
        return
    cash_flows = (
        await db.scalars(
            select(CashFlowRecord).where(
                CashFlowRecord.exchange_account_id == account.id,
                CashFlowRecord.tracking_period_id == period.id,
                CashFlowRecord.record_time >= period.started_at,
                CashFlowRecord.record_time <= recorded_at,
            )
        )
    ).all()
    net_cash_flow = sum(
        (
            -row.amount_usd
            if row.flow_type.upper() in {"WITHDRAW", "WITHDRAWAL"}
            else row.amount_usd
        )
        for row in cash_flows
    )
    day_start = datetime.combine(recorded_at.date(), dt_time.min, tzinfo=UTC)
    realized_today = await db.scalar(
        select(func.sum(ClosedPosition.realized_pnl)).where(
            ClosedPosition.exchange_account_id == account.id,
            ClosedPosition.tracking_period_id == period.id,
            ClosedPosition.close_time >= day_start,
            ClosedPosition.close_time <= recorded_at,
        )
    )
    income_count, income_today = (
        await db.execute(
            select(func.count(IncomeRecord.id), func.sum(IncomeRecord.amount_usd)).where(
                IncomeRecord.exchange_account_id == account.id,
                IncomeRecord.tracking_period_id == period.id,
                IncomeRecord.record_time >= day_start,
                IncomeRecord.record_time <= recorded_at,
                IncomeRecord.income_type == "REALIZED_PNL",
            )
        )
    ).one()
    funding_today = await db.scalar(
        select(func.sum(FundingRecord.amount_usd)).where(
            FundingRecord.exchange_account_id == account.id,
            FundingRecord.tracking_period_id == period.id,
            FundingRecord.record_time >= day_start,
            FundingRecord.record_time <= recorded_at,
        )
    )
    fees_today = await db.scalar(
        select(func.sum(TradingFeeRecord.amount_usd)).where(
            TradingFeeRecord.exchange_account_id == account.id,
            TradingFeeRecord.tracking_period_id == period.id,
            TradingFeeRecord.record_time >= day_start,
            TradingFeeRecord.record_time <= recorded_at,
        )
    )
    row = await db.scalar(
        select(DailyPnlSnapshot).where(
            DailyPnlSnapshot.exchange_account_id == account.id,
            DailyPnlSnapshot.tracking_period_id == period.id,
            DailyPnlSnapshot.snapshot_date == recorded_at.date(),
        )
    )
    if row is None:
        row = DailyPnlSnapshot(
            exchange=account.exchange,
            exchange_account_id=account.id,
            tracking_period_id=period.id,
            source_record_id=f"daily-{recorded_at.date()}",
            snapshot_date=recorded_at.date(),
        )
        db.add(row)
    current_equity = Decimal(str(summary.get("total_equity_usd", 0)))
    current_unrealized = Decimal(str(summary.get("unrealized_pnl_usd", 0)))
    row.equity_usd = current_equity
    row.realized_pnl = (
        income_today or Decimal("0") if income_count else realized_today or Decimal("0")
    )
    row.unrealized_pnl_change = current_unrealized - initial.initial_unrealized_pnl
    row.funding_fee = funding_today or Decimal("0")
    row.trading_fee = fees_today or Decimal("0")
    row.net_cash_flow = net_cash_flow
    row.investment_return = current_equity - initial.initial_equity - net_cash_flow


async def sync_account(db: AsyncSession, account: ExchangeAccount) -> dict[str, Any]:
    account_id = account.id
    lock = _account_locks.setdefault(account_id, asyncio.Lock())
    if lock.locked():
        return {"status": "SKIPPED", "reason": "sync_in_progress"}
    async with lock:
        started = datetime.now(UTC)
        timer = time.monotonic()
        job = SyncJob(
            exchange_account_id=account_id,
            job_type="MANUAL_OR_SCHEDULED",
            status="RUNNING",
            started_at=started,
        )
        db.add(job)
        await db.flush()
        try:
            if account.is_demo:
                account.last_synced_at = started
                account.connection_status = "CONNECTED"
                job.records_written = 0
            else:
                period = await db.scalar(
                    select(TrackingPeriod).where(
                        TrackingPeriod.exchange_account_id == account.id,
                        TrackingPeriod.is_active.is_(True),
                    )
                )
                if not period:
                    raise AdapterError("没有启用中的统计周期")
                last_full_sync = await _last_full_history_sync(db, account)
                history_due = (
                    last_full_sync is None
                    or started
                    - (last_full_sync.finished_at or last_full_sync.started_at)
                    >= timedelta(seconds=max(settings.sync_history_seconds, 60))
                )
                if history_due:
                    job.job_type = "FULL_ACCOUNT"
                adapter = await adapter_for_account(db, account)
                try:
                    summary, positions, closed_positions = await asyncio.gather(
                        adapter.get_account_summary(),
                        adapter.get_open_positions(),
                        adapter.get_closed_positions(account.tracking_started_at, started),
                    )
                    balances = await adapter.get_balances()
                    history_bundle: dict[str, Any] | None = None
                    history_error: Exception | None = None
                    if history_due and adapter.history_streams:
                        history_start = account.tracking_started_at
                        if last_full_sync:
                            history_start = max(
                                account.tracking_started_at,
                                (last_full_sync.finished_at or last_full_sync.started_at)
                                - timedelta(minutes=5),
                            )
                        try:
                            history_bundle = await adapter.get_history_bundle(
                                history_start, started
                            )
                        except Exception as exc:
                            history_error = exc
                finally:
                    await adapter.close()
                await _apply_asset_coverage_baseline(
                    db, account, period, summary
                )
                await _write_summary(db, account, period, summary, started)
                await _write_asset_balances(db, account, period, balances, started)
                await _replace_positions(db, account, period, positions, started)
                await _write_position_snapshots(
                    db, account, period, positions, started
                )
                closed_count = await _upsert_closed_positions(
                    db, account, period, closed_positions
                )
                closed_status = (
                    "PARTIAL"
                    if account.exchange == "POLYMARKET"
                    or any(
                        item.get("data_completeness", "PARTIAL") != "COMPLETE"
                        for item in closed_positions
                    )
                    else "COMPLETE"
                )
                update_completeness(
                    account,
                    {
                        "equity": "COMPLETE",
                        "balances": (
                            "PARTIAL"
                            if int(summary.get("unvalued_asset_count", 0))
                            else "COMPLETE"
                        ),
                        "positions": "COMPLETE",
                        "closed_positions": closed_status,
                    },
                    authoritative=True,
                )
                history_count = 0
                if history_due:
                    if history_bundle is not None:
                        history_count += await _upsert_amount_records(
                            db, account, period, IncomeRecord, history_bundle["income"]
                        )
                        history_count += await _upsert_amount_records(
                            db, account, period, FundingRecord, history_bundle["funding"]
                        )
                        history_count += await _upsert_amount_records(
                            db, account, period, TradingFeeRecord, history_bundle["fees"]
                        )
                        history_count += await _upsert_amount_records(
                            db,
                            account,
                            period,
                            CashFlowRecord,
                            history_bundle["cash_flows"],
                        )
                        history_status = (
                            "COMPLETE"
                            if adapter.history_streams == HISTORY_STREAMS
                            and bool(history_bundle.get("complete"))
                            else "PARTIAL"
                        )
                        update_completeness(
                            account,
                            {
                                stream: (
                                    history_status
                                    if stream in adapter.history_streams
                                    else "UNSUPPORTED"
                                )
                                for stream in HISTORY_STREAMS
                            },
                        )
                    else:
                        update_completeness(
                            account,
                            {
                                stream: (
                                    "PARTIAL"
                                    if stream in adapter.history_streams
                                    else "UNSUPPORTED"
                                )
                                for stream in HISTORY_STREAMS
                            },
                        )
                    if history_error is not None:
                        db.add(
                            SyncError(
                                exchange_account_id=account.id,
                                error_type=type(history_error).__name__,
                                safe_message="资产同步成功，但账务流水同步不完整",
                                occurred_at=datetime.now(UTC),
                            )
                        )
                await _write_daily_snapshot(db, account, period, summary, started)
                job.records_written = len(positions) + closed_count + history_count + 2
                account.last_synced_at = started
                account.connection_status = "CONNECTED"
            job.status = "SUCCESS"
            return {"status": "SUCCESS", "records_written": job.records_written}
        except Exception as exc:
            # A database error during autoflush leaves the session in a failed
            # transaction. Roll it back before recording the failure, otherwise
            # the error status itself is lost and the scheduler appears healthy
            # while the account silently keeps an old snapshot.
            error_type = type(exc).__name__
            await db.rollback()
            failed_account = await db.get(ExchangeAccount, account_id)
            if failed_account is not None:
                failed_account.connection_status = "ERROR"
            job = SyncJob(
                exchange_account_id=account_id,
                job_type="MANUAL_OR_SCHEDULED",
                status="FAILED",
                started_at=started,
            )
            db.add(job)
            db.add(
                SyncError(
                    exchange_account_id=account_id,
                    error_type=error_type,
                    safe_message="同步失败，请测试连接或检查只读 API 权限",
                    occurred_at=datetime.now(UTC),
                )
            )
            return {"status": "FAILED", "error": "同步失败，请检查连接"}
        finally:
            job.finished_at = datetime.now(UTC)
            job.duration_ms = int((time.monotonic() - timer) * 1000)
            await db.commit()


async def delete_account(db: AsyncSession, account: ExchangeAccount, ip: str) -> None:
    now = datetime.now(UTC)
    await db.execute(
        delete(EncryptedCredential).where(EncryptedCredential.exchange_account_id == account.id)
    )
    periods = (
        await db.scalars(
            select(TrackingPeriod).where(
                TrackingPeriod.exchange_account_id == account.id,
                TrackingPeriod.is_active.is_(True),
            )
        )
    ).all()
    for period in periods:
        period.is_active = False
        period.ended_at = now
    account.is_active = False
    account.connection_status = "DELETED"
    account.deleted_at = now
    db.add(
        SecurityAuditLog(
            action="EXCHANGE_ACCOUNT_DELETED",
            outcome="SUCCESS",
            client_ip=ip,
            details={"exchange": account.exchange, "account_id": str(account.id)},
        )
    )
    await db.commit()
