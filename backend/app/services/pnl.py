from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class PeriodPnl:
    initial_equity: Decimal
    current_equity: Decimal
    deposit: Decimal = Decimal("0")
    withdrawal: Decimal = Decimal("0")
    realized_pnl: Decimal = Decimal("0")
    current_unrealized_pnl: Decimal = Decimal("0")
    initial_unrealized_pnl: Decimal = Decimal("0")
    funding_fee: Decimal = Decimal("0")
    trading_fee: Decimal = Decimal("0")

    @property
    def net_cash_flow(self) -> Decimal:
        return self.deposit - self.withdrawal

    @property
    def investment_return(self) -> Decimal:
        return self.current_equity - self.initial_equity - self.net_cash_flow

    @property
    def trading_return(self) -> Decimal:
        return self.realized_pnl + self.funding_fee - self.trading_fee

    @property
    def unrealized_pnl_change(self) -> Decimal:
        return self.current_unrealized_pnl - self.initial_unrealized_pnl
