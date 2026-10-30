"""Execution-owned fill membership and descriptive price/quantity projection.

No independent PnL formula: replay uses the canonical allocator; averages are
lifetime fill VWAP, not a replacement for remaining inventory cost basis.
"""
from decimal import Decimal
from collections.abc import Iterable

from app.execution.accounting import apply_fill
from app.execution.decimal_policy import add, divide, multiply, subtract
from app.execution.models import Account, ExecutionEvent, InstrumentProfile, Trade


def empty_projection(origin: Account) -> Account:
    return Account.model_validate(origin.model_copy(update={
        'positions': (), 'trades': (), 'cash_balance': origin.initial_balance,
        'last_sequence': 0, 'last_filled_at': None, 'updated_at': origin.created_at,
    }).model_dump(mode='python'))


def replay_steps(origin: Account, inputs: Iterable[tuple[ExecutionEvent, InstrumentProfile, str | None]]):
    state = empty_projection(origin)
    for event, profile, plan_reference in inputs:
        state = apply_fill(state, event, profile, plan_reference=plan_reference)
        position = next(p for p in state.positions if p.symbol == event.symbol)
        trade = next(t for t in state.trades if t.trade_id == position.trade_id)
        role = 'ENTRY' if event.side == ('BUY' if trade.direction == 'LONG' else 'SELL') else 'EXIT'
        yield state, event, trade.trade_id, role


def replay_memberships(origin: Account, inputs: Iterable[tuple[ExecutionEvent, InstrumentProfile, str | None]]):
    state = empty_projection(origin)
    memberships: list[tuple[ExecutionEvent, str, str]] = []
    for state, event, trade_id, role in replay_steps(origin, inputs):
        memberships.append((event, trade_id, role))
    return state, memberships


def fill_display(trade: Trade, events: Iterable[ExecutionEvent]) -> dict:
    entered, exited, exit_notional = Decimal('0'), Decimal('0'), Decimal('0')
    for event in events:
        if event.side == ('BUY' if trade.direction == 'LONG' else 'SELL'):
            entered = add(entered, event.quantity)
        else:
            exited = add(exited, event.quantity)
            exit_notional = add(exit_notional, multiply(event.price, event.quantity))
    remaining = subtract(entered, exited)
    if entered <= 0 or remaining < 0 or ((remaining == 0) != (trade.closed_at is not None)):
        raise ValueError('inconsistent execution trade membership')
    return dict(quantity=entered, remaining_quantity=remaining,
                average_entry_price=divide(trade.total_entry_notional, entered),
                average_exit_price=divide(exit_notional, exited) if exited else None,
                status='CLOSED' if trade.closed_at is not None else 'PARTIALLY_CLOSED' if exited else 'OPEN')
