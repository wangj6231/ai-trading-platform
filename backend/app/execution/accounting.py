"""Provider-independent, pure one-way basis allocator. Never sizes orders."""

from decimal import Decimal
from typing import Literal

from app.execution.decimal_policy import add, divide, multiply, subtract
from app.execution.models import Account, ExecutionEvent, InstrumentProfile, Position, Side, Trade


def apply_fill(account: Account, event: ExecutionEvent, profile: InstrumentProfile,
               *, plan_reference: str | None = None) -> Account:
    account = Account.model_validate(account.model_dump(mode='python'))
    event = ExecutionEvent.model_validate(event.model_dump(mode='python'))
    profile = InstrumentProfile.model_validate(profile.model_dump(mode='python'))
    if (event.trading_account_id != account.account_id
            or event.execution_source != account.execution_source
            or event.instrument_reference != profile.reference or event.symbol != profile.symbol):
        raise ValueError('execution scope/profile mismatch')
    profile.validate_units(event.price, event.quantity)
    if (event.filled_at < account.created_at or event.received_at < account.created_at
            or (account.updated_at is not None and event.received_at < account.updated_at)):
        raise ValueError('unordered admission requires reconciliation')
    if (event.provenance.sequence <= account.last_sequence
            or (account.last_filled_at is not None and event.filled_at < account.last_filled_at)):
        raise ValueError('unordered fill requires reconciliation')
    positions, trades = list(account.positions), list(account.trades)
    index = next((i for i, p in enumerate(positions) if p.symbol == event.symbol), None)
    current = positions[index] if index is not None else None
    direction: Literal['LONG', 'SHORT'] = 'LONG' if event.side is Side.BUY else 'SHORT'
    increasing = current is None or current.quantity == 0 or current.direction == direction
    notional = multiply(event.price, event.quantity)
    fees = event.total_fee
    gross = Decimal('0')
    if increasing:
        if account.available_balance < add(notional, fees):
            raise ValueError('insufficient available balance')
        if current is None or current.quantity == 0:
            trade = Trade(trade_id=event.event_id, symbol=event.symbol, direction=direction,
                          opened_at=event.filled_at, total_entry_notional=notional,
                          plan_reference=plan_reference)
            trades.append(trade)
            current = Position(symbol=event.symbol, instrument_reference=profile.reference,
                               direction=direction, trade_id=trade.trade_id,
                               quantity=Decimal('0'), remaining_cost_basis=Decimal('0'))
        else:
            if current.instrument_reference != profile.reference:
                raise ValueError('instrument profile changed while position open')
            trade = next(t for t in trades if t.trade_id == current.trade_id)
            trade = trade.model_copy(update={
                'total_entry_notional': add(trade.total_entry_notional, notional)})
        position = current.model_copy(update={
            'quantity': add(current.quantity, event.quantity),
            'remaining_cost_basis': add(current.remaining_cost_basis, notional)})
    else:
        assert current is not None
        if event.quantity > current.quantity:
            raise ValueError('over-close / implicit reversal rejected')
        closed = event.quantity == current.quantity
        allocated = (current.remaining_cost_basis if closed else
                     multiply(divide(current.remaining_cost_basis, current.quantity), event.quantity))
        gross = (subtract(notional, allocated) if current.direction == 'LONG'
                 else subtract(allocated, notional))
        position = current.model_copy(update={
            'quantity': subtract(current.quantity, event.quantity),
            'remaining_cost_basis': Decimal('0') if closed else subtract(current.remaining_cost_basis, allocated)})
        trade = next(t for t in trades if t.trade_id == current.trade_id)
        trade = trade.model_copy(update={'gross_pnl': add(trade.gross_pnl, gross),
                                        'closed_at': event.filled_at if closed else None})
    trade = trade.model_copy(update={'total_fees': add(trade.total_fees, fees)})
    trades = [trade if t.trade_id == trade.trade_id else t for t in trades]
    if index is None:
        positions.append(position)
    else:
        positions[index] = position
    return Account.model_validate(account.model_copy(update={
        'positions': tuple(positions), 'trades': tuple(trades),
        'cash_balance': add(account.cash_balance, subtract(gross, fees)),
        'last_sequence': event.provenance.sequence, 'last_filled_at': event.filled_at,
        'updated_at': event.received_at}).model_dump(mode='python'))
