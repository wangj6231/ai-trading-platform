"""Execution ledger tables; unrelated to planned signal/backtest persistence."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (JSON, Boolean, CheckConstraint, ForeignKeyConstraint,
                        Integer, String, UniqueConstraint, event, inspect)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base
from app.database.types import CanonicalDecimal, UtcTimestamp

DOCUMENT = JSON().with_variant(JSONB(), 'postgresql')


class ExecutionAccountRecord(Base):
    __tablename__ = 'execution_accounts'
    __table_args__ = (
        UniqueConstraint('account_id', 'execution_source'),
        CheckConstraint("environment = 'PAPER'", name='execution_environment_paper'),
        CheckConstraint('initial_balance > 0', name='execution_initial_positive'),
        CheckConstraint('last_sequence >= 0 AND command_sequence >= 0', name='execution_sequences_nonnegative'),
    )
    account_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    execution_source: Mapped[str] = mapped_column(String(128), nullable=False)
    execution_provider: Mapped[str] = mapped_column(String(128), nullable=False)
    environment: Mapped[str] = mapped_column(String(16), nullable=False)
    accounting_profile_version: Mapped[str] = mapped_column(String(64), nullable=False)
    numeric_policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    initial_balance: Mapped[Decimal] = mapped_column(CanonicalDecimal(), nullable=False)
    cash_balance: Mapped[Decimal] = mapped_column(CanonicalDecimal(), nullable=False)
    reserved_collateral: Mapped[Decimal] = mapped_column(CanonicalDecimal(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UtcTimestamp(), nullable=False)
    last_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    command_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    state: Mapped[dict] = mapped_column(DOCUMENT, nullable=False)
    state_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class ExecutionOrderRecord(Base):
    __tablename__ = 'execution_orders'
    __table_args__ = (
        UniqueConstraint('account_id', 'command_id'),
        UniqueConstraint('account_id', 'command_sequence'),
        UniqueConstraint('order_id', 'account_id', 'execution_source'),
        ForeignKeyConstraint(['account_id', 'execution_source'],
                             ['execution_accounts.account_id', 'execution_accounts.execution_source']),
        CheckConstraint('command_sequence > 0', name='execution_command_positive'),
    )
    order_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(128), nullable=False)
    execution_source: Mapped[str] = mapped_column(String(128), nullable=False)
    command_id: Mapped[str] = mapped_column(String(128), nullable=False)
    command_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    intent: Mapped[dict] = mapped_column(DOCUMENT, nullable=False)
    instrument_profile: Mapped[dict] = mapped_column(DOCUMENT, nullable=False)
    accepted_at: Mapped[datetime] = mapped_column(UtcTimestamp(), nullable=False)
    state: Mapped[dict] = mapped_column(DOCUMENT, nullable=False)


class ExecutionFillRecord(Base):
    __tablename__ = 'execution_fills'
    __table_args__ = (
        UniqueConstraint('execution_source', 'account_id', 'external_fill_id', name='execution_fill_identity'),
        UniqueConstraint('execution_source', 'account_id', 'execution_sequence', name='execution_fill_sequence'),
        ForeignKeyConstraint(['order_id', 'account_id', 'execution_source'],
            ['execution_orders.order_id', 'execution_orders.account_id', 'execution_orders.execution_source']),
        CheckConstraint('price > 0 AND quantity > 0 AND fee >= 0', name='execution_fill_positive'),
        CheckConstraint('filled_at <= received_at', name='execution_fill_visible'),
        CheckConstraint("side IN ('BUY', 'SELL') AND fee_currency = 'USDT'", name='execution_fill_units'),
        CheckConstraint('execution_sequence > 0 AND processed', name='execution_fill_processed'),
    )
    event_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(128), nullable=False)
    execution_source: Mapped[str] = mapped_column(String(128), nullable=False)
    order_id: Mapped[str] = mapped_column(String(128), nullable=False)
    external_fill_id: Mapped[str] = mapped_column(String(128), nullable=False)
    execution_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    price: Mapped[Decimal] = mapped_column(CanonicalDecimal(), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(CanonicalDecimal(), nullable=False)
    fee: Mapped[Decimal] = mapped_column(CanonicalDecimal(), nullable=False)
    fee_currency: Mapped[str] = mapped_column(String(16), nullable=False)
    filled_at: Mapped[datetime] = mapped_column(UtcTimestamp(), nullable=False)
    received_at: Mapped[datetime] = mapped_column(UtcTimestamp(), nullable=False)
    economic_content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(DOCUMENT, nullable=False)
    processed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class ExecutionPositionRecord(Base):
    __tablename__ = 'execution_positions'
    __table_args__ = (
        ForeignKeyConstraint(['account_id'], ['execution_accounts.account_id']),
        CheckConstraint('quantity >= 0 AND remaining_cost_basis >= 0', name='execution_position_nonnegative'),
    )
    account_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(128), primary_key=True)
    quantity: Mapped[Decimal] = mapped_column(CanonicalDecimal(), nullable=False)
    remaining_cost_basis: Mapped[Decimal] = mapped_column(CanonicalDecimal(), nullable=False)
    average_entry_price: Mapped[Decimal | None] = mapped_column(CanonicalDecimal())
    state: Mapped[dict] = mapped_column(DOCUMENT, nullable=False)


class ExecutionTradeRecord(Base):
    __tablename__ = 'execution_trades'
    __table_args__ = (
        ForeignKeyConstraint(['account_id'], ['execution_accounts.account_id']),
        CheckConstraint('total_fees >= 0 AND total_entry_notional > 0', name='execution_trade_units'),
    )
    trade_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(128), nullable=False)
    gross_pnl: Mapped[Decimal] = mapped_column(CanonicalDecimal(), nullable=False)
    total_fees: Mapped[Decimal] = mapped_column(CanonicalDecimal(), nullable=False)
    net_pnl: Mapped[Decimal] = mapped_column(CanonicalDecimal(), nullable=False)
    total_entry_notional: Mapped[Decimal] = mapped_column(CanonicalDecimal(), nullable=False)
    pnl_percent: Mapped[Decimal | None] = mapped_column(CanonicalDecimal())
    closed_at: Mapped[datetime | None] = mapped_column(UtcTimestamp())
    state: Mapped[dict] = mapped_column(DOCUMENT, nullable=False)


class ExecutionMarkRecord(Base):
    __tablename__ = 'execution_marks'
    __table_args__ = (
        ForeignKeyConstraint(['account_id'], ['execution_accounts.account_id']),
        CheckConstraint('price > 0 AND valuation_at <= received_at', name='execution_mark_valid'),
    )
    account_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(128), primary_key=True)
    valuation_at: Mapped[datetime] = mapped_column(UtcTimestamp(), primary_key=True)
    price: Mapped[Decimal] = mapped_column(CanonicalDecimal(), nullable=False)
    received_at: Mapped[datetime] = mapped_column(UtcTimestamp(), nullable=False)
    observation_hash: Mapped[str] = mapped_column(String(64), nullable=False)


TABLES = [Base.metadata.tables[name] for name in (
    'execution_accounts', 'execution_orders', 'execution_fills',
    'execution_positions', 'execution_trades', 'execution_marks')]


def _guard_update(_mapper, _connection, target) -> None:
    state = inspect(target)
    if isinstance(target, (ExecutionFillRecord, ExecutionMarkRecord)):
        immutable = [attribute.key for attribute in state.mapper.column_attrs]
    elif isinstance(target, ExecutionAccountRecord):
        immutable = ['account_id', 'execution_source', 'execution_provider', 'environment',
                     'accounting_profile_version', 'numeric_policy_version', 'initial_balance', 'created_at']
    elif isinstance(target, ExecutionOrderRecord):
        immutable = ['order_id', 'account_id', 'execution_source', 'command_id', 'command_sequence',
                     'request_hash', 'intent', 'instrument_profile', 'accepted_at']
    else:
        history = state.attrs.closed_at.history
        was_closed = history.deleted[0] if history.deleted else target.closed_at
        immutable = [attribute.key for attribute in state.mapper.column_attrs] if was_closed is not None else ['trade_id', 'account_id']
    if any(state.attrs[key].history.has_changes() for key in immutable):
        raise ValueError('immutable execution history')
    if isinstance(target, (ExecutionOrderRecord, ExecutionTradeRecord)):
        history = state.attrs.state.history
        if history.deleted:
            previous = history.deleted[0]
            keys = (['order_id', 'account_id', 'intent', 'instrument_reference', 'accepted_at',
                     'reduce_only', 'bound_trade_id'] if isinstance(target, ExecutionOrderRecord)
                    else ['trade_id', 'symbol', 'direction', 'opened_at', 'accounting_profile_version',
                          'numeric_policy_version', 'plan_reference', 'r_multiple'])
            if any(previous.get(key) != target.state.get(key) for key in keys):
                raise ValueError('immutable execution origin')


def _guard_delete(*_args) -> None:
    raise ValueError('execution ledger cannot be deleted')


for _model in (ExecutionAccountRecord, ExecutionOrderRecord, ExecutionFillRecord,
               ExecutionTradeRecord, ExecutionMarkRecord):
    event.listen(_model, 'before_update', _guard_update)
    event.listen(_model, 'before_delete', _guard_delete)
