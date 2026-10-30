# Frozen pre-F4 canonical Analytics oracle; never production fallback.
"""Account-scoped actual-trade analytics. No writes or trade PnL calculation."""
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal

from app.core.time import normalize_utc_datetime, utc_now
from app.database.db import Database
from app.execution.decimal_policy import add, divide, multiply
from app.execution.repository import ExecutionRepository
from app.journal.analytics_models import AnalyticsQuery, AnalyticsScope, AnalyticsStats, JournalAnalytics, SymbolStats, TradeSummary
from app.journal.models import JournalResult, JournalTrade
from tests.fixtures.f4_canonical_journal_oracle import JournalService


class AnalyticsNotReady(ValueError):
    """An explicit unsupported evidence/currency scope, not zero performance."""


def _total(values) -> Decimal:
    total = Decimal('0')
    for value in values:
        total = add(total, value)
    return total


def _mean(values) -> Decimal | None:
    return divide(_total(values), Decimal(len(values))) if values else None


def _summary(trade: JournalTrade) -> TradeSummary:
    if trade.closed_at is None or trade.pnl_percent is None:
        raise ValueError('unresolved trade summary')
    return TradeSummary(trade_id=trade.trade_id, symbol=trade.symbol, side=trade.side,
        opened_at=trade.opened_at, closed_at=trade.closed_at, gross_pnl=trade.gross_pnl,
        total_fees=trade.total_fees, net_pnl=trade.net_pnl, pnl_percent=trade.pnl_percent)


def _stats(trades: tuple[JournalTrade, ...]) -> AnalyticsStats:
    if not trades:
        return AnalyticsStats()
    wins = tuple(t.net_pnl for t in trades if t.result == JournalResult.WIN)
    losses = tuple(t.net_pnl for t in trades if t.result == JournalResult.LOSS)
    profit, loss = _total(wins), _total(v.copy_abs() for v in losses)
    best = min(trades, key=lambda t: (t.net_pnl.copy_negate(), t.closed_at, t.trade_id))
    worst = min(trades, key=lambda t: (t.net_pnl, t.closed_at, t.trade_id))
    return AnalyticsStats(total_trades=len(trades), wins=len(wins), losses=len(losses),
        breakeven=len(trades)-len(wins)-len(losses),
        win_rate=multiply(divide(Decimal(len(wins)), Decimal(len(trades))), Decimal('100')),
        gross_profit=profit, gross_loss=loss, gross_pnl=_total(t.gross_pnl for t in trades),
        total_fees=_total(t.total_fees for t in trades), net_pnl=_total(t.net_pnl for t in trades),
        average_win=_mean(wins), average_loss=_mean(losses),
        average_pnl_percent=_mean(tuple(t.pnl_percent for t in trades)),
        profit_factor=divide(profit, loss) if loss else None,
        best_trade=_summary(best), worst_trade=_summary(worst))


class JournalAnalyticsService:
    def __init__(self, database: Database, *, clock: Callable[[], datetime] = utc_now):
        self.database, self.clock = database, clock
        self.journal = JournalService(database, clock=clock)

    def evaluate(self, account_id: str, query: AnalyticsQuery | None = None) -> JournalAnalytics:
        query = AnalyticsQuery.model_validate((query or AnalyticsQuery()).model_dump(mode='python'))
        now = normalize_utc_datetime(self.clock())
        cutoff = query.as_of or now
        if cutoff > now:
            raise ValueError('analytics cutoff exceeds server knowledge time')
        repository = ExecutionRepository()
        with self.database.read_session() as session:
            record = repository.read_account(session, account_id)
            if record is None:
                raise ValueError('analytics account not found')
            account = repository.parse_account(session, record)
            if account.settlement_currency != 'USDT' or account.reporting_currency != 'USDT':
                raise AnalyticsNotReady('unsupported reporting currency')
        if query.strategy is not None:
            raise AnalyticsNotReady('strategy attribution NOT_READY')
        trades = tuple(sorted((t for t in self.journal.list_trades(account_id, as_of=cutoff)
            if t.status == 'CLOSED'), key=lambda t: (t.closed_at, t.trade_id)))
        if any(t.closed_at is None or t.result is None or t.pnl_percent is None or not t.fills for t in trades):
            raise ValueError('CLOSED trade lacks resolved execution evidence')
        trades = tuple(t for t in trades if
            (query.closed_from is None or (t.closed_at is not None and t.closed_at >= query.closed_from)) and
            (query.closed_to is None or (t.closed_at is not None and t.closed_at < query.closed_to)) and
            (query.symbol is None or t.symbol == query.symbol) and
            (query.side is None or t.side == query.side) and
            (query.result is None or t.result == query.result))
        return JournalAnalytics(scope=AnalyticsScope(trading_account_id=account_id, query=query),
            as_of=cutoff, currency=account.reporting_currency, overall=_stats(trades),
            long_stats=_stats(tuple(t for t in trades if t.side == 'LONG')),
            short_stats=_stats(tuple(t for t in trades if t.side == 'SHORT')),
            by_symbol=tuple(SymbolStats(symbol=symbol, stats=_stats(tuple(t for t in trades if t.symbol == symbol)))
                for symbol in sorted({t.symbol for t in trades})))
