"""Flush-only ledger repository. Gateway owns commit and per-account locking."""

import json
from collections.abc import Iterator
from typing import TypeVar

from sqlalchemy import Engine, inspect, select, text, tuple_
from sqlalchemy.orm import Session
from app.database.db import Base

from app.execution.accounting import apply_fill
from app.execution.decimal_policy import add
from app.execution.models import Account, ExecutionEvent, InstrumentProfile, Order, canonical_json, content_hash
from app.execution.records import (
    TABLES, ExecutionAccountRecord, ExecutionFillRecord, ExecutionOrderRecord,
    ExecutionPositionRecord, ExecutionTradeRecord,
)

# Operational IO bound only; not an accounting/strategy parameter or cache.
ACCOUNT_MIRROR_FETCH_SIZE = 100
Mirror = TypeVar('Mirror', ExecutionPositionRecord, ExecutionTradeRecord)


def _referenced_mirrors(session: Session, model: type[Mirror],
                        identities: list[tuple[str, ...]]) -> Iterator[Mirror | None]:
    """Batch cold references, retaining Session.get's transaction-local semantics.

    Callers supply at most ACCOUNT_MIRROR_FETCH_SIZE canonical references.
    Do not refresh unexpired/dirty persistent objects or include session.new.
    Persistent identity keys (not potentially dirty PK attributes) own lookup.
    Expired objects are reloaded lazily in canonical validation order, as before.
    """
    if len(identities) > ACCOUNT_MIRROR_FETCH_SIZE:
        raise ValueError('mirror fetch exceeds operational batch bound')
    rows: dict[tuple[str, ...], Mirror] = {}
    missing = []
    for identity in identities:
        cached = session.identity_map.get(session.identity_key(model, identity))
        if cached is None:
            missing.append(identity)
        else:
            rows[identity] = cached
    if missing:
        columns = inspect(model).primary_key
        predicate = (columns[0].in_([key[0] for key in missing]) if len(columns) == 1
                     else tuple_(*columns).in_(missing))
        result = session.scalars(select(model).where(predicate).execution_options(
            yield_per=ACCOUNT_MIRROR_FETCH_SIZE))
        try:
            for loaded_row in result:
                persistent_identity = inspect(loaded_row).identity
                assert persistent_identity is not None
                rows[persistent_identity] = loaded_row
        finally:
            result.close()
    for identity in identities:
        referenced_row = rows.get(identity)
        if referenced_row is not None and inspect(referenced_row).expired:
            referenced_row = session.get(model, identity)
        yield referenced_row


def document(value: object) -> dict:
    return json.loads(canonical_json(value))


def create_test_schema(engine: Engine) -> None:
    """SQLite seam-test helper only. Production schema is Alembic-owned."""
    if engine.dialect.name != 'sqlite':
        raise ValueError('use Alembic for PostgreSQL')
    Base.metadata.create_all(engine, tables=TABLES)
    from app.journal.records import TABLES as journal_tables
    Base.metadata.create_all(engine, tables=journal_tables)
    from app.auth.records import AuthSubjectRecord  # Register the FK target only.
    from app.retention.records import AccountLifecycleEventRecord
    _ = AuthSubjectRecord
    Base.metadata.tables[AccountLifecycleEventRecord.__tablename__].create(engine, checkfirst=True)


class ExecutionRepository:
    def read_account(self, session: Session, account_id: str) -> ExecutionAccountRecord | None:
        # Account and its NUMERIC mirror rows are one projection. A consistent
        # read must not combine an old header with a just-committed position.
        # No commit or financial mutation occurs on this read path.
        if session.get_bind().dialect.name == 'sqlite':
            session.execute(text('BEGIN'))
        return session.scalar(select(ExecutionAccountRecord).where(
            ExecutionAccountRecord.account_id == account_id).with_for_update(read=True))

    def parse_order(self, row: ExecutionOrderRecord) -> Order:
        order = Order.model_validate(row.state)
        profile = InstrumentProfile.model_validate(row.instrument_profile)
        if (order.account_id != row.account_id or order.order_id != row.order_id
                or order.accepted_at != row.accepted_at or order.intent.command_id != row.command_id
                or document(order.intent) != row.intent or content_hash(order.intent) != row.request_hash
                or profile.symbol != order.intent.symbol or profile.reference != order.instrument_reference):
            raise ValueError('corrupt order intent')
        return order

    def lock_account(self, session: Session, account_id: str) -> ExecutionAccountRecord:
        if session.get_bind().dialect.name == 'sqlite':
            # Serialize writers across repository instances/processes, not merely
            # Python threads. PostgreSQL uses the account row lock below.
            session.execute(text('BEGIN IMMEDIATE'))
        record = session.scalar(select(ExecutionAccountRecord).where(
            ExecutionAccountRecord.account_id == account_id).with_for_update())
        if record is None:
            raise ValueError('execution account not found')
        return record

    def parse_account(self, session: Session, record: ExecutionAccountRecord) -> Account:
        account = Account.model_validate(record.state)
        if (account.status != 'ACTIVE' or content_hash(account) != record.state_hash or account.account_id != record.account_id
                or account.execution_source != record.execution_source
                or account.execution_provider != record.execution_provider
                or account.environment != record.environment
                or account.initial_balance != record.initial_balance
                or account.cash_balance != record.cash_balance
                or account.reserved_collateral != record.reserved_collateral
                or account.last_sequence != record.last_sequence
                or account.created_at != record.created_at
                or account.accounting_profile_version != record.accounting_profile_version
                or account.numeric_policy_version != record.numeric_policy_version):
            raise ValueError('corrupt execution account projection')
        for start in range(0, len(account.positions), ACCOUNT_MIRROR_FETCH_SIZE):
            positions = account.positions[start:start + ACCOUNT_MIRROR_FETCH_SIZE]
            position_mirrors = _referenced_mirrors(session, ExecutionPositionRecord,
                [(account.account_id, position.symbol) for position in positions])
            for position, row in zip(positions, position_mirrors, strict=True):
                if (row is None or row.state != document(position) or row.quantity != position.quantity
                        or row.remaining_cost_basis != position.remaining_cost_basis
                        or row.average_entry_price != position.average_entry_price):
                    raise ValueError('corrupt position projection')
        for start in range(0, len(account.trades), ACCOUNT_MIRROR_FETCH_SIZE):
            trades = account.trades[start:start + ACCOUNT_MIRROR_FETCH_SIZE]
            trade_mirrors = _referenced_mirrors(session, ExecutionTradeRecord,
                [(trade.trade_id,) for trade in trades])
            for trade, trade_row in zip(trades, trade_mirrors, strict=True):
                if (trade_row is None or trade_row.account_id != account.account_id or trade_row.state != document(trade)
                        or trade_row.gross_pnl != trade.gross_pnl or trade_row.net_pnl != trade.net_pnl
                        or trade_row.total_fees != trade.total_fees
                        or trade_row.total_entry_notional != trade.total_entry_notional
                        or trade_row.pnl_percent != trade.pnl_percent or trade_row.closed_at != trade.closed_at):
                    raise ValueError('corrupt trade projection')
        return account

    def save_account(self, session: Session, record: ExecutionAccountRecord, account: Account) -> None:
        record.state, record.state_hash = document(account), content_hash(account)
        record.cash_balance = account.cash_balance
        record.reserved_collateral = account.reserved_collateral
        record.last_sequence = account.last_sequence
        for position in account.positions:
            row = session.get(ExecutionPositionRecord, (account.account_id, position.symbol))
            if row is None:
                row = ExecutionPositionRecord(account_id=account.account_id, symbol=position.symbol)
                session.add(row)
            row.quantity, row.remaining_cost_basis = position.quantity, position.remaining_cost_basis
            row.average_entry_price, row.state = position.average_entry_price, document(position)
        for trade in account.trades:
            trade_row = session.get(ExecutionTradeRecord, trade.trade_id)
            if trade_row is not None and trade_row.state == document(trade):
                continue
            if trade_row is None:
                trade_row = ExecutionTradeRecord(trade_id=trade.trade_id, account_id=account.account_id)
                session.add(trade_row)
            trade_row.gross_pnl, trade_row.total_fees, trade_row.net_pnl = trade.gross_pnl, trade.total_fees, trade.net_pnl
            trade_row.total_entry_notional, trade_row.pnl_percent = trade.total_entry_notional, trade.pnl_percent
            trade_row.closed_at, trade_row.state = trade.closed_at, document(trade)
        session.flush()

    def admit(self, session: Session, record: ExecutionAccountRecord,
              event: ExecutionEvent, profile: InstrumentProfile, *, allow_new_fill: bool) -> ExecutionEvent:
        event = ExecutionEvent.model_validate(event.model_dump(mode='python'))
        if event.execution_source != record.execution_source or event.trading_account_id != record.account_id:
            raise ValueError('execution scope mismatch')
        prior = session.scalar(select(ExecutionFillRecord).where(
            ExecutionFillRecord.account_id == record.account_id,
            ExecutionFillRecord.execution_source == record.execution_source,
            ExecutionFillRecord.external_fill_id == event.external_fill_id))
        if prior is not None:
            original = self.parse_fill(prior)
            if original.economic_content_hash != event.economic_content_hash:
                raise ValueError('CONFLICT: changed economic fill')
            return original
        from app.retention.repository import require_active_account
        require_active_account(session, record.account_id)
        if not allow_new_fill:
            raise ValueError('new simulated fill requires validated observation')
        order_record = session.get(ExecutionOrderRecord, event.internal_order_id)
        if order_record is None or order_record.account_id != record.account_id:
            raise ValueError('unknown scoped order requires reconciliation')
        order = self.parse_order(order_record)
        frozen_profile = InstrumentProfile.model_validate(order_record.instrument_profile)
        if profile.reference != frozen_profile.reference:
            raise ValueError('instrument binding mismatch')
        if (order.external_order_id != event.external_order_id or order.intent.symbol != event.symbol
                or order.instrument_reference != event.instrument_reference
                or order.intent.side != event.side or event.filled_at <= order.accepted_at
                or add(order.filled_quantity, event.quantity) > order.intent.quantity):
            raise ValueError('fill/order contract mismatch')
        account = self.parse_account(session, record)
        position = next((p for p in account.positions if p.symbol == event.symbol and p.quantity), None)
        if order.reduce_only and (position is None or position.trade_id != order.bound_trade_id
                                  or position.quantity < event.quantity):
            raise ValueError('stale reduction / reversal rejected')
        if not order.reduce_only and position is not None and position.direction != ('LONG' if event.side == 'BUY' else 'SHORT'):
            raise ValueError('stale opening intent / implicit reversal rejected')
        updated = apply_fill(account, event, frozen_profile, plan_reference=order.intent.plan_reference)
        row = ExecutionFillRecord(
            event_id=event.event_id, account_id=record.account_id, execution_source=record.execution_source,
            order_id=event.internal_order_id, external_fill_id=event.external_fill_id,
            execution_sequence=event.provenance.sequence, side=event.side.value, price=event.price,
            quantity=event.quantity, fee=event.total_fee, fee_currency='USDT',
            filled_at=event.filled_at, received_at=event.received_at,
            economic_content_hash=event.economic_content_hash, payload=document(event), processed=True)
        session.add(row)
        order_record.state = document(order.model_copy(update={
            'filled_quantity': add(order.filled_quantity, event.quantity)}))
        self.save_account(session, record, updated)
        from app.journal.capture import capture_fill
        capture_fill(session, updated, event)
        return event

    def parse_fill(self, record: ExecutionFillRecord) -> ExecutionEvent:
        event = ExecutionEvent.model_validate(record.payload)
        if (event.economic_content_hash != record.economic_content_hash
                or event.price != record.price or event.quantity != record.quantity
                or event.total_fee != record.fee or record.fee_currency != 'USDT'
                or event.filled_at != record.filled_at or event.received_at != record.received_at
                or event.trading_account_id != record.account_id or event.execution_source != record.execution_source
                or event.internal_order_id != record.order_id or event.external_fill_id != record.external_fill_id
                or event.event_id != record.event_id or event.side != record.side
                or event.provenance.sequence != record.execution_sequence or not record.processed):
            raise ValueError('corrupt canonical fill')
        return event
