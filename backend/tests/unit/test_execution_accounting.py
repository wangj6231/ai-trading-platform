from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_DOWN, localcontext

import pytest

from app.execution.models import Account, ExecutionEvent, Fee, InstrumentProfile, Provenance
from app.execution.accounting import apply_fill

AT = datetime(2026, 10, 8, tzinfo=UTC)
PROFILE = InstrumentProfile(reference='test-units-v1', symbol='BTCUSDT',
                            price_tick=Decimal('.01'), quantity_step=Decimal('.001'),
                            minimum_quantity=Decimal('.001'))


def account(source='PAPER:test', account_id='account'):
    return Account(account_id=account_id, execution_source=source,
                   execution_provider='PAPER', created_at=AT)


def fill(sequence, side, quantity, price, *, source='PAPER:test', account_id='account'):
    price, quantity = Decimal(price), Decimal(quantity)
    # Fixture fee is independent exact literal policy at ordinary precision.
    from app.execution.decimal_policy import multiply
    return ExecutionEvent(
        event_id=f'event-{sequence}', execution_source=source,
        trading_account_id=account_id, internal_order_id=f'order-{sequence}',
        external_order_id=f'order-{sequence}', external_fill_id=f'fill-{sequence}',
        symbol='BTCUSDT', instrument_reference=PROFILE.reference,
        side=side, price=price, quantity=quantity,
        fees=(Fee(amount=multiply(multiply(price, quantity), Decimal('.001'))),),
        filled_at=AT + timedelta(minutes=sequence),
        received_at=AT + timedelta(minutes=sequence, seconds=1),
        provenance=Provenance(provider='PAPER', adapter_version='PAPER_V1', sequence=sequence),
    )


def test_golden_repeating_average_and_final_residual_reconcile():
    sequences = [fill(1, 'BUY', '1', '100'), fill(2, 'BUY', '2', '101'),
                 fill(3, 'SELL', '1', '102'), fill(4, 'SELL', '1', '103'),
                 fill(5, 'SELL', '1', '104')]
    outputs = []
    for precision in (3, 28, 80):
        with localcontext() as context:
            context.prec = precision
            context.rounding = ROUND_DOWN
            state = account()
            for index, event in enumerate(sequences):
                state = apply_fill(state, event, PROFILE)
                if index == 1:
                    assert state.positions[0].remaining_cost_basis == Decimal('302')
                    assert state.positions[0].average_entry_price == Decimal(
                        '100.66666666666666666666666666666666666666666666667')
                if index == 2:
                    assert state.positions[0].remaining_cost_basis == Decimal(
                        '201.33333333333333333333333333333333333333333333333')
            outputs.append(state)
    assert outputs[0] == outputs[1] == outputs[2]
    state = outputs[0]
    assert state.positions[0].quantity == state.positions[0].remaining_cost_basis == 0
    assert state.positions[0].average_entry_price is None
    assert state.reserved_collateral == 0
    assert state.trades[0].gross_pnl == Decimal('7')
    assert state.trades[0].total_fees == Decimal('.611')
    assert state.trades[0].net_pnl == Decimal('6.389')
    assert state.cash_balance == Decimal('10006.389')
    assert state.trades[0].r_multiple is None


def test_short_partial_and_close_use_same_generic_reducer():
    state = account()
    for event in [fill(1, 'SELL', '2', '100'), fill(2, 'BUY', '1', '90'),
                  fill(3, 'BUY', '1', '80')]:
        state = apply_fill(state, event, PROFILE)
    assert state.trades[0].gross_pnl == Decimal('30')
    assert state.trades[0].net_pnl == Decimal('29.63')
    assert state.cash_balance == Decimal('10029.63')


def test_insufficient_funds_and_overclose_fail_without_mutating_state():
    state = account().model_copy(update={'initial_balance': Decimal('100'), 'cash_balance': Decimal('100')})
    with pytest.raises(ValueError, match='insufficient'):
        apply_fill(state, fill(1, 'BUY', '1', '100'), PROFILE)
    assert not state.positions
    state = apply_fill(account(), fill(1, 'BUY', '1', '100'), PROFILE)
    with pytest.raises(ValueError, match='over-close'):
        apply_fill(state, fill(2, 'SELL', '2', '101'), PROFILE)
    assert state.positions[0].quantity == 1
