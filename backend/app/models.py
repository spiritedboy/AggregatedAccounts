import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def new_uuid() -> uuid.UUID:
    return uuid.uuid4()


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        onupdate=lambda: datetime.now(UTC),
    )


class ExchangeAccount(Base, TimestampMixin):
    __tablename__ = "exchange_accounts"
    __table_args__ = (
        Index("ix_exchange_accounts_exchange_active", "exchange", "is_active"),
        Index(
            "uq_active_connection",
            "exchange",
            "connection_name",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    exchange: Mapped[str] = mapped_column(String(24), nullable=False)
    connection_name: Mapped[str] = mapped_column(String(80), nullable=False)
    public_identifier: Mapped[str | None] = mapped_column(String(160))
    masked_identifier: Mapped[str] = mapped_column(String(160), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    connection_status: Mapped[str] = mapped_column(String(24), default="CONNECTED", nullable=False)
    permission_status: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    data_completeness: Mapped[str] = mapped_column(String(24), default="COMPLETE", nullable=False)
    tracking_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    credentials: Mapped["EncryptedCredential | None"] = relationship(
        back_populates="account", cascade="all, delete-orphan", uselist=False
    )
    periods: Mapped[list["TrackingPeriod"]] = relationship(back_populates="account")


class TrackingPeriod(Base, TimestampMixin):
    __tablename__ = "tracking_periods"
    __table_args__ = (
        Index("ix_tracking_period_account_active", "exchange_account_id", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    exchange: Mapped[str] = mapped_column(String(24), nullable=False)
    exchange_account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exchange_accounts.id"), nullable=False
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    account: Mapped[ExchangeAccount] = relationship(back_populates="periods")


class EncryptedCredential(Base, TimestampMixin):
    __tablename__ = "encrypted_credentials"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    exchange_account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exchange_accounts.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    api_key_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary)
    api_key_nonce: Mapped[bytes | None] = mapped_column(LargeBinary)
    api_key_tag: Mapped[bytes | None] = mapped_column(LargeBinary)
    secret_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary)
    secret_nonce: Mapped[bytes | None] = mapped_column(LargeBinary)
    secret_tag: Mapped[bytes | None] = mapped_column(LargeBinary)
    passphrase_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary)
    passphrase_nonce: Mapped[bytes | None] = mapped_column(LargeBinary)
    passphrase_tag: Mapped[bytes | None] = mapped_column(LargeBinary)
    encryption_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    account: Mapped[ExchangeAccount] = relationship(back_populates="credentials")


class BusinessMixin(TimestampMixin):
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    exchange: Mapped[str] = mapped_column(String(24), nullable=False)
    exchange_account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exchange_accounts.id"), nullable=False
    )
    tracking_period_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tracking_periods.id"), nullable=False
    )
    source_record_id: Mapped[str] = mapped_column(String(160), nullable=False)


class InitialAccountSnapshot(Base, BusinessMixin):
    __tablename__ = "initial_account_snapshots"
    __table_args__ = (UniqueConstraint("tracking_period_id", name="uq_initial_snapshot_period"),)
    initial_equity: Mapped[Decimal] = mapped_column(Numeric(30, 10), default=0)
    initial_available_balance: Mapped[Decimal] = mapped_column(Numeric(30, 10), default=0)
    initial_margin_balance: Mapped[Decimal] = mapped_column(Numeric(30, 10), default=0)
    initial_unrealized_pnl: Mapped[Decimal] = mapped_column(Numeric(30, 10), default=0)
    initial_positions: Mapped[list] = mapped_column(JSON, default=list)
    tracking_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AccountBalanceSnapshot(Base, BusinessMixin):
    __tablename__ = "account_balance_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "exchange_account_id",
            "tracking_period_id",
            "source_record_id",
            name="uq_balance_source",
        ),
        Index("ix_balance_snapshot_time", "exchange_account_id", "recorded_at"),
    )
    total_equity_usd: Mapped[Decimal] = mapped_column(Numeric(30, 10), default=0)
    available_balance_usd: Mapped[Decimal] = mapped_column(Numeric(30, 10), default=0)
    margin_balance_usd: Mapped[Decimal] = mapped_column(Numeric(30, 10), default=0)
    unrealized_pnl_usd: Mapped[Decimal] = mapped_column(Numeric(30, 10), default=0)
    unvalued_asset_count: Mapped[int] = mapped_column(Integer, default=0)
    price_source: Mapped[str] = mapped_column(String(80), default="EXCHANGE_API")
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CurrentPosition(Base, BusinessMixin):
    __tablename__ = "current_positions"
    __table_args__ = (
        UniqueConstraint(
            "exchange_account_id",
            "tracking_period_id",
            "normalized_symbol",
            "side",
            name="uq_current_position",
        ),
        Index("ix_current_position_filters", "exchange", "normalized_symbol", "side"),
    )
    symbol: Mapped[str] = mapped_column(String(80), nullable=False)
    normalized_symbol: Mapped[str] = mapped_column(String(80), nullable=False)
    market_type: Mapped[str] = mapped_column(String(24), default="PERPETUAL")
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    position_size: Mapped[Decimal] = mapped_column(Numeric(30, 10), default=0)
    position_value_usd: Mapped[Decimal] = mapped_column(Numeric(30, 10), default=0)
    entry_price: Mapped[Decimal] = mapped_column(Numeric(30, 10), default=0)
    mark_price: Mapped[Decimal] = mapped_column(Numeric(30, 10), default=0)
    liquidation_price: Mapped[Decimal | None] = mapped_column(Numeric(30, 10))
    leverage: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    margin_mode: Mapped[str] = mapped_column(String(12), default="UNKNOWN")
    margin_used: Mapped[Decimal] = mapped_column(Numeric(30, 10), default=0)
    unrealized_pnl: Mapped[Decimal] = mapped_column(Numeric(30, 10), default=0)
    tracking_unrealized_pnl_change: Mapped[Decimal] = mapped_column(Numeric(30, 10), default=0)
    unrealized_pnl_percent: Mapped[Decimal] = mapped_column(Numeric(18, 8), default=0)
    realized_pnl: Mapped[Decimal] = mapped_column(Numeric(30, 10), default=0)
    funding_fee: Mapped[Decimal] = mapped_column(Numeric(30, 10), default=0)
    trading_fee: Mapped[Decimal] = mapped_column(Numeric(30, 10), default=0)
    open_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    tracking_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_initial_position: Mapped[bool] = mapped_column(Boolean, default=False)
    tracking_entry_price: Mapped[Decimal | None] = mapped_column(Numeric(30, 10))
    tracking_initial_mark_price: Mapped[Decimal | None] = mapped_column(Numeric(30, 10))
    tracking_initial_unrealized_pnl: Mapped[Decimal] = mapped_column(Numeric(30, 10), default=0)


class PositionSnapshot(Base, BusinessMixin):
    __tablename__ = "position_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "exchange_account_id",
            "tracking_period_id",
            "source_record_id",
            name="uq_position_snapshot",
        ),
    )
    normalized_symbol: Mapped[str] = mapped_column(String(80), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    position_size: Mapped[Decimal] = mapped_column(Numeric(30, 10), default=0)
    mark_price: Mapped[Decimal] = mapped_column(Numeric(30, 10), default=0)
    unrealized_pnl: Mapped[Decimal] = mapped_column(Numeric(30, 10), default=0)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ClosedPosition(Base, BusinessMixin):
    __tablename__ = "closed_positions"
    __table_args__ = (
        UniqueConstraint(
            "exchange_account_id", "tracking_period_id", "source_record_id", name="uq_closed_source"
        ),
        Index("ix_closed_position_filters", "exchange", "normalized_symbol", "close_time"),
    )
    symbol: Mapped[str] = mapped_column(String(80), nullable=False)
    normalized_symbol: Mapped[str] = mapped_column(String(80), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    open_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    close_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    average_entry_price: Mapped[Decimal] = mapped_column(Numeric(30, 10), default=0)
    average_exit_price: Mapped[Decimal] = mapped_column(Numeric(30, 10), default=0)
    max_position_size: Mapped[Decimal] = mapped_column(Numeric(30, 10), default=0)
    realized_pnl: Mapped[Decimal] = mapped_column(Numeric(30, 10), default=0)
    funding_fee: Mapped[Decimal] = mapped_column(Numeric(30, 10), default=0)
    trading_fee: Mapped[Decimal] = mapped_column(Numeric(30, 10), default=0)
    net_pnl: Mapped[Decimal] = mapped_column(Numeric(30, 10), default=0)
    return_percent: Mapped[Decimal] = mapped_column(Numeric(18, 8), default=0)
    data_source: Mapped[str] = mapped_column(String(24), default="EXCHANGE_API")
    data_completeness: Mapped[str] = mapped_column(String(24), default="COMPLETE")
    tracking_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AmountRecordMixin(BusinessMixin):
    asset: Mapped[str] = mapped_column(String(24), default="USD")
    amount_usd: Mapped[Decimal] = mapped_column(Numeric(30, 10), default=0)
    record_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class IncomeRecord(Base, AmountRecordMixin):
    __tablename__ = "income_records"
    __table_args__ = (
        UniqueConstraint(
            "exchange_account_id", "tracking_period_id", "source_record_id", name="uq_income_source"
        ),
    )
    income_type: Mapped[str] = mapped_column(String(40), nullable=False)


class FundingRecord(Base, AmountRecordMixin):
    __tablename__ = "funding_records"
    __table_args__ = (
        UniqueConstraint(
            "exchange_account_id",
            "tracking_period_id",
            "source_record_id",
            name="uq_funding_source",
        ),
    )
    symbol: Mapped[str | None] = mapped_column(String(80))


class TradingFeeRecord(Base, AmountRecordMixin):
    __tablename__ = "trading_fee_records"
    __table_args__ = (
        UniqueConstraint(
            "exchange_account_id", "tracking_period_id", "source_record_id", name="uq_fee_source"
        ),
    )
    symbol: Mapped[str | None] = mapped_column(String(80))


class CashFlowRecord(Base, AmountRecordMixin):
    __tablename__ = "cash_flow_records"
    __table_args__ = (
        UniqueConstraint(
            "exchange_account_id", "tracking_period_id", "source_record_id", name="uq_cash_source"
        ),
    )
    flow_type: Mapped[str] = mapped_column(String(16), nullable=False)


class DailyPnlSnapshot(Base, BusinessMixin):
    __tablename__ = "daily_pnl_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "exchange_account_id", "tracking_period_id", "snapshot_date", name="uq_daily_pnl"
        ),
        Index("ix_daily_pnl_date", "snapshot_date"),
    )
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    equity_usd: Mapped[Decimal] = mapped_column(Numeric(30, 10), default=0)
    realized_pnl: Mapped[Decimal] = mapped_column(Numeric(30, 10), default=0)
    unrealized_pnl_change: Mapped[Decimal] = mapped_column(Numeric(30, 10), default=0)
    funding_fee: Mapped[Decimal] = mapped_column(Numeric(30, 10), default=0)
    trading_fee: Mapped[Decimal] = mapped_column(Numeric(30, 10), default=0)
    net_cash_flow: Mapped[Decimal] = mapped_column(Numeric(30, 10), default=0)
    investment_return: Mapped[Decimal] = mapped_column(Numeric(30, 10), default=0)


class SyncJob(Base, TimestampMixin):
    __tablename__ = "sync_jobs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    exchange_account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("exchange_accounts.id"))
    job_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    records_written: Mapped[int] = mapped_column(Integer, default=0)


class SyncError(Base, TimestampMixin):
    __tablename__ = "sync_errors"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    exchange_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("exchange_accounts.id")
    )
    error_type: Mapped[str] = mapped_column(String(80), nullable=False)
    safe_message: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SecurityAuditLog(Base):
    __tablename__ = "security_audit_logs"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    outcome: Mapped[str] = mapped_column(String(24), nullable=False)
    client_ip: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), server_default=func.now()
    )


class AppSession(Base):
    __tablename__ = "app_sessions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    csrf_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    client_ip: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), server_default=func.now()
    )


class AppSetting(Base, TimestampMixin):
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
