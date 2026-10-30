"""Display-only immutable snapshots and revocable source-validation admission.

Canonical Account/mirror validation remains at financial writes and controlled
recovery. PostgreSQL invalidates admission on source changes. SQLite is a test
adapter and retains canonical audit validation, not a production shortcut.
"""
from datetime import datetime
from decimal import Decimal
import json
from typing import Literal

from pydantic import Field, model_validator
from sqlalchemy import and_, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.time import UtcDateTime
from app.execution.models import Account, Identifier, InstrumentProfile, Money, Position, StrictModel, Valuation, canonical_json, content_hash
from app.execution.decimal_policy import add, multiply, subtract
from app.execution.records import ExecutionAccountRecord, ExecutionFillRecord, ExecutionMarkRecord, ExecutionOrderRecord
from app.execution.repository import ExecutionRepository
from app.journal.records import DashboardReadAdmissionRecord, DashboardReadStateRecord, JournalFillRecord
from app.journal.readmodel import JournalReadNotReady
from app.market_data.timeframes import timeframe_bucket_start
from app.schemas.types import Timeframe

SNAPSHOT_SCHEMA_VERSION = 1
DISPLAY_SOURCE_BATCH_ROWS = 100
ADMISSION_SOURCE_TABLES = (
    'execution_accounts', 'execution_positions', 'execution_trades',
    'execution_fills', 'execution_orders', 'journal_trades', 'journal_fill_refs',
    'journal_read_states', 'dashboard_read_states', 'dashboard_read_admissions',
)


class PositionDisplay(StrictModel):
    trade_id: Identifier
    opened_at: UtcDateTime
    closed_at: UtcDateTime | None
    gross_pnl: Money
    quantity: Money
    remaining_quantity: Money
    average_entry_price: Money
    average_exit_price: Money | None
    status: Literal['OPEN', 'PARTIALLY_CLOSED', 'CLOSED']


class DisplayAccountState(StrictModel):
    """Not interchangeable with an accounting Account; no trades/fill history."""
    schema_version: Literal[1] = 1
    account_id: Identifier
    execution_source: Identifier
    execution_provider: Identifier
    environment: Literal['PAPER']
    accounting_profile_version: Literal['PAPER_DIRECTIONAL_V1']
    numeric_policy_version: Literal['PAPER_DECIMAL_V1']
    position_model: Literal['ONE_WAY_NET_POSITION']
    reporting_currency: Literal['USDT']
    status: Literal['ACTIVE']
    initial_balance: Money = Field(gt=0)
    cash_balance: Money
    reserved_collateral: Money = Field(ge=0)
    available_balance: Money
    realized_pnl: Money
    created_at: UtcDateTime
    updated_at: UtcDateTime | None
    positions: tuple[Position, ...]
    position_displays: dict[str, PositionDisplay] = Field(default_factory=dict)

    @model_validator(mode='after')
    def display_membership(self):
        if len({p.symbol for p in self.positions}) != len(self.positions):
            raise ValueError('duplicate display position')
        if set(self.position_displays) != {p.trade_id for p in self.positions}:
            raise ValueError('display position membership mismatch')
        for position in self.positions:
            display = self.position_displays[position.trade_id]
            if (display.trade_id != position.trade_id or display.remaining_quantity != position.quantity or
                (display.status == 'CLOSED') != (position.quantity == 0)):
                raise ValueError('display position state mismatch')
        return self


def display_state(account: Account, displays: dict[str, PositionDisplay] | None = None) -> DisplayAccountState:
    fields = DisplayAccountState.model_fields.keys() - {'schema_version', 'position_displays'}
    return DisplayAccountState.model_validate({name: getattr(account, name) for name in fields}
        | {'position_displays': displays or {}})


def capture_dashboard(session: Session, account: Account, event) -> None:
    """Capture already validated allocator output; never compute execution truth."""
    previous = session.scalar(select(DashboardReadStateRecord).where(
        DashboardReadStateRecord.account_id == account.account_id,
        DashboardReadStateRecord.execution_sequence < event.provenance.sequence).order_by(
            DashboardReadStateRecord.execution_sequence.desc()).limit(1))
    prior_displays = {}
    if previous is not None:
        if previous.state_hash != content_hash(previous.state):
            raise JournalReadNotReady('immutable prior display state mismatch')
        prior_displays = DisplayAccountState.model_validate(previous.state).position_displays
    displays = {}
    from app.execution.trade_projection import fill_display
    for position in account.positions:
        if position.symbol != event.symbol and position.trade_id in prior_displays:
            displays[position.trade_id] = prior_displays[position.trade_id]
            continue
        trade = next(t for t in account.trades if t.trade_id == position.trade_id)
        source = session.scalars(select(ExecutionFillRecord).join(JournalFillRecord,
            JournalFillRecord.event_id == ExecutionFillRecord.event_id).where(
                ExecutionFillRecord.account_id == account.account_id, JournalFillRecord.trade_id == trade.trade_id,
                ExecutionFillRecord.execution_sequence <= event.provenance.sequence).order_by(
                    ExecutionFillRecord.filled_at, ExecutionFillRecord.execution_sequence).execution_options(yield_per=DISPLAY_SOURCE_BATCH_ROWS))
        events = (ExecutionRepository().parse_fill(row) for row in source)
        displays[position.trade_id] = PositionDisplay(trade_id=trade.trade_id, opened_at=trade.opened_at,
            closed_at=trade.closed_at, gross_pnl=trade.gross_pnl, **fill_display(trade, events))
    presentation = display_state(account, displays)
    state = json.loads(canonical_json(presentation))
    prior = session.get(DashboardReadStateRecord, event.event_id)
    if prior is None:
        session.add(DashboardReadStateRecord(event_id=event.event_id, account_id=account.account_id,
            execution_sequence=event.provenance.sequence, known_at=event.received_at,
            state=state, state_hash=content_hash(state)))
    elif (prior.account_id, prior.execution_sequence, prior.known_at, prior.state_hash) != (
            account.account_id, event.provenance.sequence, event.received_at, content_hash(state)):
        raise JournalReadNotReady('conflicting immutable display state')
    session.flush()
    if session.get_bind().dialect.name != 'postgresql':
        return
    from app.journal.readmodel import audit_ready_account
    current = session.scalar(select(ExecutionAccountRecord).where(ExecutionAccountRecord.account_id == account.account_id))
    if current is None:
        raise JournalReadNotReady('missing canonical display account')
    if current.last_sequence != account.last_sequence:
        return  # intermediate historical recovery states cannot admit current reads
    admission = session.get(DashboardReadAdmissionRecord, account.account_id)
    if admission is None:
        admission = DashboardReadAdmissionRecord(account_id=account.account_id, source_hash=current.state_hash,
            execution_sequence=account.last_sequence, ready=False, recovery_required=True)
        session.add(admission)
    # Validate ALL canonical references at the trusted writer/recovery seam.
    # Do not replace canonical membership with a SUM over extra mirror rows.
    verified = ExecutionRepository().parse_account(session, current)
    if content_hash(verified) != content_hash(account):
        raise JournalReadNotReady('canonical/display source mismatch')
    try:
        audit_ready_account(session, account.account_id, None)
        expected = session.scalar(select(func.count()).select_from(ExecutionFillRecord).where(
            ExecutionFillRecord.account_id == account.account_id,
            ExecutionFillRecord.execution_source == account.execution_source))
        present, last = session.execute(select(func.count(), func.max(DashboardReadStateRecord.execution_sequence)).where(
            DashboardReadStateRecord.account_id == account.account_id)).one()
        if present != expected or last != account.last_sequence:
            raise JournalReadNotReady('display prefix incomplete; controlled recovery required')
        if expected == 1:
            # First admission must agree with receipt replay from the immutable
            # initial balance, not merely with a self-consistent altered JSON.
            from app.execution.trade_projection import replay_steps
            order_row = session.get(ExecutionOrderRecord, event.internal_order_id)
            if order_row is None:
                raise JournalReadNotReady('missing first display source order')
            order = ExecutionRepository().parse_order(order_row)
            replayed, *_ = next(replay_steps(account, ((event,
                InstrumentProfile.model_validate(order_row.instrument_profile), order.intent.plan_reference),)))
            if content_hash(replayed) != content_hash(account):
                raise JournalReadNotReady('initial source/replay mismatch; controlled recovery required')
            admission.recovery_required = False  # complete first-ever canonical fill
    except JournalReadNotReady:
        admission.ready = False
        admission.recovery_required = True
    else:
        admission.source_hash, admission.execution_sequence = current.state_hash, account.last_sequence
        admission.ready = not admission.recovery_required
    session.flush()


def require_admission(session: Session, account_id: str, cutoff: datetime | None):
    row = session.execute(select(ExecutionAccountRecord.account_id, ExecutionAccountRecord.execution_source,
        ExecutionAccountRecord.execution_provider, ExecutionAccountRecord.environment, ExecutionAccountRecord.created_at,
        ExecutionAccountRecord.last_sequence, ExecutionAccountRecord.state_hash,
        and_(*(func.to_regclass(name).is_not(None) for name in ADMISSION_SOURCE_TABLES)).label('storage_available')).where(
            ExecutionAccountRecord.account_id == account_id).with_for_update(read=True)).one_or_none()
    if row is None:
        raise ValueError('journal account not found')
    if not row.storage_available:
        raise JournalReadNotReady('dashboard source storage NOT_READY; controlled rebuild required')
    if cutoff is not None and cutoff < row.created_at:
        raise ValueError('account not yet visible')
    try:
        admission = session.get(DashboardReadAdmissionRecord, account_id)
    except SQLAlchemyError as exc:
        raise JournalReadNotReady('dashboard admission storage NOT_READY') from exc
    if row.last_sequence == 0 and admission is None:
        # Empty canonical documents are bounded; no lazy persistence on a read.
        record = session.get(ExecutionAccountRecord, account_id)
        if record is None:
            raise JournalReadNotReady('missing canonical display account')
        empty = ExecutionRepository().parse_account(session, record)
        if empty.positions or empty.trades:
            raise JournalReadNotReady('empty account source mismatch')
        from app.journal.readmodel import audit_ready_account
        audit_ready_account(session, account_id, cutoff)
        return row
    if admission is None or not admission.ready or admission.recovery_required or (admission.source_hash, admission.execution_sequence) != (
            row.state_hash, row.last_sequence):
        raise JournalReadNotReady('dashboard admission NOT_READY; controlled rebuild required')
    return row


def admit_rebuilt(session: Session, account: Account) -> None:
    """Only after a locked complete canonical replay/hash comparison succeeds."""
    from app.journal.readmodel import audit_ready_account
    audit_ready_account(session, account.account_id, None)
    expected = session.scalar(select(func.count()).select_from(ExecutionFillRecord).where(
        ExecutionFillRecord.account_id == account.account_id,
        ExecutionFillRecord.execution_source == account.execution_source))
    present, last = session.execute(select(func.count(), func.max(DashboardReadStateRecord.execution_sequence)).where(
        DashboardReadStateRecord.account_id == account.account_id)).one()
    if present != expected or (last or 0) != account.last_sequence:
        raise JournalReadNotReady('recovery display prefix incomplete')
    admission = session.get(DashboardReadAdmissionRecord, account.account_id)
    if admission is None:
        admission = DashboardReadAdmissionRecord(account_id=account.account_id)
        session.add(admission)
    admission.source_hash, admission.execution_sequence = content_hash(account), account.last_sequence
    admission.ready, admission.recovery_required = True, False
    session.flush()


def account_state(session: Session, account_id: str, cutoff: datetime) -> DisplayAccountState:
    identity = require_admission(session, account_id, cutoff)
    try:
        row = session.scalar(select(DashboardReadStateRecord).where(
            DashboardReadStateRecord.account_id == account_id, DashboardReadStateRecord.known_at <= cutoff).order_by(
                DashboardReadStateRecord.execution_sequence.desc()).limit(1))
    except SQLAlchemyError as exc:
        raise JournalReadNotReady('dashboard display storage NOT_READY; controlled rebuild required') from exc
    if row is None:
        # Initial point-in-time state, including a cutoff before the first fill.
        initial = session.execute(select(ExecutionAccountRecord.initial_balance).where(
            ExecutionAccountRecord.account_id == account_id)).scalar_one()
        return display_state(Account(account_id=account_id, execution_source=identity.execution_source,
            execution_provider=identity.execution_provider, created_at=identity.created_at, updated_at=identity.created_at,
            initial_balance=initial, cash_balance=initial))
    parsed = DisplayAccountState.model_validate(row.state)
    if row.state_hash != content_hash(row.state) or parsed.account_id != account_id:
        raise JournalReadNotReady('immutable display snapshot mismatch')
    return parsed


def valuations(session: Session, state: DisplayAccountState, cutoff: datetime):
    """Frozen AccountView display valuation semantics; no accounting writes."""
    marks, unrealized = [], Decimal('0')
    status: Literal['READY', 'STALE', 'NOT_READY'] = 'READY'
    for position in state.positions:
        if not position.quantity:
            continue
        row = session.scalar(select(ExecutionMarkRecord).where(ExecutionMarkRecord.account_id == state.account_id,
            ExecutionMarkRecord.symbol == position.symbol, ExecutionMarkRecord.received_at <= cutoff,
            ExecutionMarkRecord.valuation_at <= cutoff).order_by(ExecutionMarkRecord.valuation_at.desc()).limit(1))
        if row is None:
            status = 'NOT_READY'
            continue
        marks.append(Valuation(symbol=row.symbol, valuation_price=row.price,
            valuation_at=row.valuation_at, received_at=row.received_at))
        if row.valuation_at != timeframe_bucket_start(cutoff, Timeframe.ONE_MINUTE):
            if status != 'NOT_READY':
                status = 'STALE'
            continue
        marked = multiply(row.price, position.quantity)
        unrealized = add(unrealized, subtract(marked, position.remaining_cost_basis) if position.direction == 'LONG'
            else subtract(position.remaining_cost_basis, marked))
    return status, tuple(marks), unrealized if status == 'READY' else None, add(state.cash_balance, unrealized) if status == 'READY' else None
