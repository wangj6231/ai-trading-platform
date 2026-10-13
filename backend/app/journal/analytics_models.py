"""Strict internal read-only analytics contracts, not financial input models."""
from typing import Literal
from decimal import Decimal

from pydantic import Field, model_validator

from app.core.time import UtcDateTime
from app.execution.models import Identifier, Money, StrictModel
from app.journal.models import JournalResult


class AnalyticsQuery(StrictModel):
    as_of: UtcDateTime | None = None
    closed_from: UtcDateTime | None = None
    closed_to: UtcDateTime | None = None
    symbol: Identifier | None = None
    side: Literal['LONG', 'SHORT'] | None = None
    result: JournalResult | None = None
    strategy: Identifier | None = None

    @model_validator(mode='after')
    def valid_range(self):
        if self.closed_from is not None and self.closed_to is not None and self.closed_from >= self.closed_to:
            raise ValueError('closed date range must be nonempty and ordered')
        return self


class AnalyticsScope(StrictModel):
    trading_account_id: Identifier
    query: AnalyticsQuery


class TradeSummary(StrictModel):
    trade_id: Identifier
    symbol: Identifier
    side: Literal['LONG', 'SHORT']
    opened_at: UtcDateTime
    closed_at: UtcDateTime
    gross_pnl: Money
    total_fees: Money
    net_pnl: Money
    pnl_percent: Money


class AnalyticsStats(StrictModel):
    total_trades: int = Field(default=0, ge=0, strict=True)
    wins: int = Field(default=0, ge=0, strict=True)
    losses: int = Field(default=0, ge=0, strict=True)
    breakeven: int = Field(default=0, ge=0, strict=True)
    win_rate: Money | None = None
    gross_profit: Money = Decimal('0')
    gross_loss: Money = Decimal('0')
    gross_pnl: Money = Decimal('0')
    total_fees: Money = Decimal('0')
    net_pnl: Money = Decimal('0')
    average_win: Money | None = None
    average_loss: Money | None = None
    average_pnl_percent: Money | None = None
    profit_factor: Money | None = None
    average_r: Money | None = None
    r_observations: int = Field(default=0, ge=0, strict=True)
    best_trade: TradeSummary | None = None
    worst_trade: TradeSummary | None = None


class SymbolStats(StrictModel):
    symbol: Identifier
    stats: AnalyticsStats


class StrategyStats(StrictModel):
    strategy_identity: Identifier
    stats: AnalyticsStats


class JournalAnalytics(StrictModel):
    schema_version: Literal['JOURNAL_ANALYTICS_V1'] = 'JOURNAL_ANALYTICS_V1'
    scope: AnalyticsScope
    as_of: UtcDateTime
    currency: Literal['USDT']
    overall: AnalyticsStats
    long_stats: AnalyticsStats
    short_stats: AnalyticsStats
    by_symbol: tuple[SymbolStats, ...] = ()
    by_strategy: tuple[StrategyStats, ...] = ()
    strategy_breakdown_status: Literal['NOT_READY_NO_VERIFIED_ATTRIBUTION'] = 'NOT_READY_NO_VERIFIED_ATTRIBUTION'
