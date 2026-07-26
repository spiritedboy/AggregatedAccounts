import asyncio
import time
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters import ADAPTERS
from app.adapters.base import AdapterError, ExchangeAdapter
from app.config import settings
from app.models import (
    AccountBalanceSnapshot,
    CurrentPosition,
    EncryptedCredential,
    ExchangeAccount,
    InitialAccountSnapshot,
    SecurityAuditLog,
    SyncError,
    SyncJob,
    TrackingPeriod,
)
from app.schemas import ExchangeAccountCreate
from app.security import CredentialCipher, EncryptedField, mask_identifier

cipher = CredentialCipher(settings.app_encryption_key)
_account_locks: dict[uuid.UUID, asyncio.Lock] = {}


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
            adapter.get_account_summary(), adapter.get_open_positions()
        )
    finally:
        await adapter.close()

    started_at = datetime.now(UTC)
    identifier = payload.wallet_address or payload.api_key or ""
    account = ExchangeAccount(
        exchange=payload.exchange,
        connection_name=payload.connection_name,
        public_identifier=payload.wallet_address,
        masked_identifier=mask_identifier(identifier),
        permission_status=permissions,
        connection_status="CONNECTED",
        data_completeness="COMPLETE",
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

    if payload.exchange != "HYPERLIQUID":
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
    await _replace_positions(db, account, period, positions, started_at, initial=True)
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
    if account.exchange == "HYPERLIQUID":
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
                tracking_initial_unrealized_pnl=Decimal(str(item.get("unrealized_pnl", 0))),
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
        row.margin_mode = item.get("margin_mode", "UNKNOWN")
        row.unrealized_pnl = current_pnl
        row.tracking_unrealized_pnl_change = current_pnl - initial_pnl
        row.unrealized_pnl_percent = (
            current_pnl / row.position_value_usd * 100 if row.position_value_usd else Decimal("0")
        )
        row.updated_at = recorded_at


async def sync_account(db: AsyncSession, account: ExchangeAccount) -> dict[str, Any]:
    lock = _account_locks.setdefault(account.id, asyncio.Lock())
    if lock.locked():
        return {"status": "SKIPPED", "reason": "sync_in_progress"}
    async with lock:
        started = datetime.now(UTC)
        timer = time.monotonic()
        job = SyncJob(
            exchange_account_id=account.id,
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
                adapter = await adapter_for_account(db, account)
                try:
                    summary, positions = await asyncio.gather(
                        adapter.get_account_summary(),
                        adapter.get_open_positions(),
                    )
                finally:
                    await adapter.close()
                await _write_summary(db, account, period, summary, started)
                await _replace_positions(db, account, period, positions, started)
                job.records_written = len(positions) + 1
                account.last_synced_at = started
                account.connection_status = "CONNECTED"
            job.status = "SUCCESS"
            return {"status": "SUCCESS", "records_written": job.records_written}
        except Exception as exc:
            account.connection_status = "ERROR"
            job.status = "FAILED"
            db.add(
                SyncError(
                    exchange_account_id=account.id,
                    error_type=type(exc).__name__,
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
