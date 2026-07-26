import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AccountBalanceSnapshot,
    ClosedPosition,
    CurrentPosition,
    DailyPnlSnapshot,
    ExchangeAccount,
    InitialAccountSnapshot,
    TrackingPeriod,
)
from app.services.normalizer import SymbolNormalizer

DEMO_EXCHANGES = ("BINANCE", "OKX", "BITGET", "HYPERLIQUID")


async def seed_demo_data(db: AsyncSession) -> None:
    if await db.scalar(
        select(ExchangeAccount.id).where(ExchangeAccount.is_demo.is_(True)).limit(1)
    ):
        return

    now = datetime.now(UTC)
    started = (now - timedelta(days=30)).replace(hour=0, minute=0, second=0, microsecond=0)
    equities = [42180.0, 28740.0, 19420.0, 13660.0]
    accounts: list[tuple[ExchangeAccount, TrackingPeriod]] = []

    for index, exchange in enumerate(DEMO_EXCHANGES):
        account = ExchangeAccount(
            exchange=exchange,
            connection_name=f"{exchange.title()} 演示账户",
            public_identifier=None,
            masked_identifier=f"demo••••{index + 1001}",
            is_demo=True,
            connection_status="CONNECTED" if index != 2 else "DEGRADED",
            permission_status={
                "read": True,
                "spot_trade": False,
                "futures_trade": False,
                "transfer": False,
                "withdraw": False,
            },
            data_completeness="PARTIAL" if index == 2 else "COMPLETE",
            tracking_started_at=started,
            last_synced_at=now - timedelta(seconds=index * 18),
        )
        db.add(account)
        await db.flush()
        period = TrackingPeriod(
            exchange=exchange,
            exchange_account_id=account.id,
            started_at=started,
            is_active=True,
        )
        db.add(period)
        await db.flush()
        initial_equity = equities[index] - (900 + index * 230)
        db.add(
            InitialAccountSnapshot(
                exchange=exchange,
                exchange_account_id=account.id,
                tracking_period_id=period.id,
                source_record_id=f"demo-initial-{index}",
                initial_equity=Decimal(str(initial_equity)),
                initial_available_balance=Decimal(str(initial_equity * 0.57)),
                initial_margin_balance=Decimal(str(initial_equity * 0.18)),
                initial_unrealized_pnl=Decimal(str(80 - index * 35)),
                initial_positions=[],
                tracking_started_at=started,
            )
        )
        db.add(
            AccountBalanceSnapshot(
                exchange=exchange,
                exchange_account_id=account.id,
                tracking_period_id=period.id,
                source_record_id=f"demo-balance-{now:%Y%m%d%H%M}",
                total_equity_usd=Decimal(str(equities[index])),
                available_balance_usd=Decimal(str(equities[index] * 0.61)),
                margin_balance_usd=Decimal(str(equities[index] * 0.17)),
                unrealized_pnl_usd=Decimal(str([486.2, -122.4, 219.8, 94.6][index])),
                unvalued_asset_count=1 if index == 2 else 0,
                price_source="DEMO_MARK_PRICE",
                recorded_at=now,
            )
        )
        for day in range(30):
            snapshot_date = (started + timedelta(days=day)).date()
            trend = day * (26 + index * 7)
            wave = math.sin(day / 2.7 + index) * (115 + index * 20)
            equity = initial_equity + trend + wave
            daily_return = (26 + index * 7) + math.cos(day / 2.7 + index) * 42
            db.add(
                DailyPnlSnapshot(
                    exchange=exchange,
                    exchange_account_id=account.id,
                    tracking_period_id=period.id,
                    source_record_id=f"demo-daily-{snapshot_date}",
                    snapshot_date=snapshot_date,
                    equity_usd=Decimal(str(round(equity, 2))),
                    realized_pnl=Decimal(str(round(daily_return, 2))),
                    unrealized_pnl_change=Decimal(str(round(wave * 0.08, 2))),
                    funding_fee=Decimal(str(round((-1) ** day * (2.4 + index), 2))),
                    trading_fee=Decimal(str(round(4.2 + index * 0.8, 2))),
                    net_cash_flow=Decimal("0"),
                    investment_return=Decimal(str(round(equity - initial_equity, 2))),
                )
            )
        accounts.append((account, period))

    current_specs = [
        (0, "BTCUSDT", "LONG", 0.42, 68250, 69580, 29223.6, 558.6),
        (0, "ETHUSDT", "SHORT", 3.2, 3820, 3745, 11984.0, 240.0),
        (1, "SOL-USDT-SWAP", "LONG", 82, 168.4, 173.2, 14202.4, 393.6),
        (2, "ETHUSDT", "LONG", 4.6, 3680, 3745, 17227.0, 299.0),
        (3, "BTC", "SHORT", 0.18, 70200, 69580, 12524.4, 111.6),
    ]
    for pos_index, spec in enumerate(current_specs):
        account_index, symbol, side, size, entry, mark, value, pnl = spec
        account, period = accounts[account_index]
        db.add(
            CurrentPosition(
                exchange=account.exchange,
                exchange_account_id=account.id,
                tracking_period_id=period.id,
                source_record_id=f"demo-current-{pos_index}",
                symbol=symbol,
                normalized_symbol=SymbolNormalizer.normalize(symbol),
                side=side,
                position_size=Decimal(str(size)),
                position_value_usd=Decimal(str(value)),
                entry_price=Decimal(str(entry)),
                mark_price=Decimal(str(mark)),
                liquidation_price=Decimal(str(mark * (0.68 if side == "LONG" else 1.32))),
                leverage=Decimal("5"),
                margin_mode="CROSS" if pos_index % 2 == 0 else "ISOLATED",
                margin_used=Decimal(str(value / 5)),
                unrealized_pnl=Decimal(str(pnl if side == "LONG" else -pnl / 2)),
                tracking_unrealized_pnl_change=Decimal(str(pnl * 0.72)),
                unrealized_pnl_percent=Decimal(str(round(pnl / value * 100, 4))),
                realized_pnl=Decimal(str(35 * pos_index)),
                funding_fee=Decimal(str(-3.2 * (pos_index + 1))),
                trading_fee=Decimal(str(7.4 + pos_index)),
                open_time=now - timedelta(days=pos_index + 1),
                tracking_started_at=started,
                is_initial_position=pos_index in {0, 3},
                tracking_entry_price=Decimal(str(entry)),
                tracking_initial_mark_price=Decimal(str(entry * 1.002)),
                tracking_initial_unrealized_pnl=Decimal(str(pnl * 0.28)),
            )
        )

    symbols = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT")
    for index in range(16):
        account, period = accounts[index % 4]
        side = "LONG" if index % 3 else "SHORT"
        entry = 100 + index * 12
        pnl = round(((-1) ** (index % 4)) * (42 + index * 17.3), 2)
        db.add(
            ClosedPosition(
                exchange=account.exchange,
                exchange_account_id=account.id,
                tracking_period_id=period.id,
                source_record_id=f"demo-closed-{index}",
                symbol=symbols[index % len(symbols)],
                normalized_symbol=SymbolNormalizer.normalize(symbols[index % len(symbols)]),
                side=side,
                open_time=started + timedelta(days=index),
                close_time=started + timedelta(days=index, hours=8 + index % 7),
                average_entry_price=Decimal(str(entry)),
                average_exit_price=Decimal(str(entry * (1 + pnl / 10000))),
                max_position_size=Decimal(str(1 + index / 5)),
                realized_pnl=Decimal(str(pnl)),
                funding_fee=Decimal(str(round(-1.2 - index / 10, 2))),
                trading_fee=Decimal(str(round(2.5 + index / 8, 2))),
                net_pnl=Decimal(str(round(pnl - 3.7 - index / 40, 2))),
                return_percent=Decimal(str(round(pnl / 100, 3))),
                data_source="EXCHANGE_API" if index % 3 else "RECONSTRUCTED",
                data_completeness="COMPLETE" if index % 3 else "PARTIAL",
                tracking_started_at=started,
            )
        )
    await db.commit()
