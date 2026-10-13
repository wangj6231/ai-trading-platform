"""SQL aggregates over canonical terminal trades with receipt-time admission.

No allocator/replay, no float arithmetic, no fill/Account history hydration.
The read index supplies visibility only; financial columns come from Trade.
"""
from decimal import Decimal

from sqlalchemy import and_, case, func, or_, select

from app.execution.decimal_policy import divide, multiply
from app.execution.records import ExecutionTradeRecord as T
from app.journal.analytics_models import AnalyticsStats, TradeSummary
from app.journal.readmodel import JournalReadNotReady, READ_BATCH_SIZE, ready_account
from app.journal.records import JournalReadStateRecord as R

# Reporting resource guard, not a trading or account-history truncation policy.
# Matches the approved foundation's up-to-100-symbol shape; overflow is explicit.
MAX_ANALYTICS_SYMBOL_GROUPS = 100


def closed_query(account_id, cutoff, query):
    conditions = [R.account_id == account_id, R.closed_at.is_not(None), R.known_at <= cutoff]
    for value, clause in (
        (query.closed_from, R.closed_at >= query.closed_from if query.closed_from is not None else None),
        (query.closed_to, R.closed_at < query.closed_to if query.closed_to is not None else None),
        (query.symbol, R.symbol == query.symbol), (query.side, R.side == query.side),
        (query.result, R.result == query.result)):
        if value is not None:
            conditions.append(clause)
    return conditions


def summary(row):
    return TradeSummary(trade_id=row.trade_id, symbol=row.symbol, side=row.side, opened_at=row.opened_at,
        closed_at=row.closed_at, gross_pnl=row.gross_pnl, total_fees=row.total_fees,
        net_pnl=row.net_pnl, pnl_percent=row.pnl_percent)


def stats(session, conditions):
    source = T.__table__.join(R, and_(T.trade_id == R.trade_id, T.account_id == R.account_id))
    positive, negative = T.net_pnl > 0, T.net_pnl < 0
    zero = Decimal('0')
    counts = session.execute(select(func.count(), func.count(case((positive, 1))),
        func.count(case((negative, 1))), func.sum(case((positive, T.net_pnl), else_=zero)),
        func.sum(case((negative, -T.net_pnl), else_=zero)), func.sum(T.gross_pnl), func.sum(T.total_fees),
        func.sum(T.net_pnl), func.sum(T.pnl_percent)).select_from(source).where(*conditions)).one()
    count, wins, losses, profit, loss, gross, fees, net, percentages = counts
    if not count:
        return AnalyticsStats()
    columns = (T.trade_id, R.symbol, R.side, R.opened_at, T.closed_at, T.gross_pnl,
               T.total_fees, T.net_pnl, T.pnl_percent)
    # Explicit byte/Unicode-codepoint ordering, independent of PG locale.
    identifier = T.trade_id.collate('C' if session.bind.dialect.name == 'postgresql' else 'BINARY')
    base = select(*columns).select_from(source).where(*conditions)
    best = session.execute(base.order_by(T.net_pnl.desc(), T.closed_at, identifier).limit(1)).one()
    worst = session.execute(base.order_by(T.net_pnl, T.closed_at, identifier).limit(1)).one()
    return AnalyticsStats(total_trades=count, wins=wins, losses=losses, breakeven=count-wins-losses,
        win_rate=multiply(divide(Decimal(wins), Decimal(count)), Decimal('100')),
        gross_profit=profit, gross_loss=loss, gross_pnl=gross, total_fees=fees, net_pnl=net,
        average_win=divide(profit, Decimal(wins)) if wins else None,
        average_loss=divide(loss.copy_negate(), Decimal(losses)) if losses else None,
        average_pnl_percent=divide(percentages, Decimal(count)),
        profit_factor=divide(profit, loss) if loss else None, best_trade=summary(best), worst_trade=summary(worst))


def evaluate(session, account_id, cutoff, query):
    ready_account(session, account_id, cutoff)
    conditions = closed_query(account_id, cutoff, query)
    mismatch = or_(T.trade_id.is_(None), T.account_id != R.account_id, T.closed_at != R.closed_at,
        T.gross_pnl != R.gross_pnl, T.total_fees != R.total_fees, T.net_pnl != R.net_pnl,
        T.pnl_percent != R.pnl_percent, T.state != R.state,
        R.result != case((T.net_pnl > 0, 'WIN'), (T.net_pnl < 0, 'LOSS'), else_='BREAKEVEN'),
        R.symbol != T.state['symbol'].as_string(), R.side != T.state['direction'].as_string())
    if session.scalar(select(R.event_id).outerjoin(T, T.trade_id == R.trade_id).where(
            R.account_id == account_id, R.closed_at.is_not(None), R.known_at <= cutoff, mismatch).limit(1)) is not None:
        raise JournalReadNotReady('canonical Analytics/read model mismatch; rebuild required')
    symbols = session.scalars(select(R.symbol).where(*conditions).distinct().order_by(R.symbol).limit(
        MAX_ANALYTICS_SYMBOL_GROUPS+1)).all()
    if len(symbols) > MAX_ANALYTICS_SYMBOL_GROUPS:
        raise JournalReadNotReady('Analytics symbol group budget exceeded; NOT_READY')
    # Canonical output uses Python codepoint order, never deployment collation.
    # This is only the bounded distinct-symbol set, not historical trade rows.
    symbols = sorted(symbols)
    if session.bind.dialect.name != 'postgresql':
        return sqlite_stats(session, account_id, cutoff, query)
    overall = stats(session, conditions)
    long_stats = stats(session, [*conditions, R.side == 'LONG'])
    short_stats = stats(session, [*conditions, R.side == 'SHORT'])
    return overall, long_stats, short_stats, tuple((symbol, stats(session, [*conditions, R.symbol == symbol])) for symbol in symbols)


def sqlite_stats(session, account_id, cutoff, query):
    """SQLite stores Decimal as text: never use its binary-float SUM.

    Streaming exact Decimal reducer, one scalar accumulator per output group.
    SQLite is a unit-test adapter, not the commercial capacity target.
    """
    from app.execution.decimal_policy import add
    conditions = closed_query(account_id, cutoff, query)
    rows = session.execute(select(T.trade_id, R.symbol, R.side, R.opened_at, T.closed_at, T.gross_pnl,
        T.total_fees, T.net_pnl, T.pnl_percent).join(R, and_(T.trade_id == R.trade_id, T.account_id == R.account_id)).where(
            *conditions).execution_options(yield_per=READ_BATCH_SIZE))
    groups: dict = {}
    for row in rows:
        for key in ('overall', row.side, ('symbol', row.symbol)):
            g = groups.setdefault(key, dict(count=0, wins=0, losses=0, profit=Decimal(0), loss=Decimal(0),
                gross=Decimal(0), fees=Decimal(0), net=Decimal(0), percentages=Decimal(0), best=None, worst=None))
            g['count'] += 1
            g['wins'] += row.net_pnl > 0
            g['losses'] += row.net_pnl < 0
            for name, value in (('gross', row.gross_pnl), ('fees', row.total_fees), ('net', row.net_pnl),
                                ('percentages', row.pnl_percent), ('profit', max(row.net_pnl, Decimal(0))),
                                ('loss', min(row.net_pnl, Decimal(0)).copy_abs())):
                g[name] = add(g[name], value)
            if g['best'] is None or (row.net_pnl.copy_negate(), row.closed_at, row.trade_id) < (g['best'].net_pnl.copy_negate(), g['best'].closed_at, g['best'].trade_id):
                g['best'] = row
            if g['worst'] is None or (row.net_pnl, row.closed_at, row.trade_id) < (g['worst'].net_pnl, g['worst'].closed_at, g['worst'].trade_id):
                g['worst'] = row
    def result(key):
        g = groups.get(key)
        if g is None:
            return AnalyticsStats()
        return AnalyticsStats(total_trades=g['count'], wins=g['wins'], losses=g['losses'],
            breakeven=g['count']-g['wins']-g['losses'],
            win_rate=multiply(divide(Decimal(g['wins']), Decimal(g['count'])), Decimal(100)),
            gross_profit=g['profit'], gross_loss=g['loss'], gross_pnl=g['gross'], total_fees=g['fees'], net_pnl=g['net'],
            average_win=divide(g['profit'], Decimal(g['wins'])) if g['wins'] else None,
            average_loss=divide(g['loss'].copy_negate(), Decimal(g['losses'])) if g['losses'] else None,
            average_pnl_percent=divide(g['percentages'], Decimal(g['count'])),
            profit_factor=divide(g['profit'], g['loss']) if g['loss'] else None,
            best_trade=summary(g['best']), worst_trade=summary(g['worst']))
    symbols = sorted(k[1] for k in groups if isinstance(k, tuple))
    return result('overall'), result('LONG'), result('SHORT'), tuple((s, result(('symbol', s))) for s in symbols)
