from decimal import Decimal
from enum import Enum


class FinancialOutcome(str, Enum):
    PROFIT = "PROFIT"
    LOSS = "LOSS"
    FLAT = "FLAT"


def classify_financial_outcome(net_pnl: Decimal) -> FinancialOutcome:
    """Classify one canonical finite Decimal net result without tolerance rules."""

    if not isinstance(net_pnl, Decimal):
        raise TypeError("net_pnl must be a Decimal")
    if not net_pnl.is_finite():
        raise ValueError("net_pnl must be finite")
    if net_pnl > 0:
        return FinancialOutcome.PROFIT
    if net_pnl < 0:
        return FinancialOutcome.LOSS
    return FinancialOutcome.FLAT
