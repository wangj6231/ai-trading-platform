"""Internal-only gateway: server context, atomic ledger, provider IO outside locks."""

from collections.abc import Callable
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import normalize_utc_datetime, utc_now
from app.database.db import Database
from app.execution.accounting import apply_fill
from app.execution.adapters.paper import PaperExecutionAdapter
from app.execution.decimal_policy import add, subtract
from app.execution.models import (
    Account, AccountView, Cancellation, Environment, ExecutionEvent, InstrumentProfile,
    Order, OrderIntent, OrderSubmission, SubmissionStatus, Valuation, content_hash, parse_decimal,
)
from app.execution.records import (
    ExecutionAccountRecord, ExecutionFillRecord, ExecutionMarkRecord, ExecutionOrderRecord,
)
from app.execution.registry import ExecutionRegistry
from app.execution.repository import ExecutionRepository, document
from app.market_data.normalization import validate_candle_order
from app.market_data.timeframes import timeframe_bucket_start
from app.schemas.market import ValidatedMarketData
from app.schemas.types import Timeframe

# Operational batch size, not a financial/strategy parameter. One transaction
# still owns the entire observation; batches never independently commit.
OBSERVATION_BATCH_SIZE = 100


class ExecutionGateway:
    def __init__(self, database: Database, registry: ExecutionRegistry,
                 instruments: tuple[InstrumentProfile, ...], *,
                 clock: Callable[[], datetime] = utc_now,
                 repository: ExecutionRepository | None = None) -> None:
        self.database, self.registry, self.clock = database, registry, clock
        self.repository = repository or ExecutionRepository()
        self.instruments = {p.symbol: InstrumentProfile.model_validate(p.model_dump(mode='python')) for p in instruments}
        if len(self.instruments) != len(instruments):
            raise ValueError('ambiguous instrument registry')

    def _now(self) -> datetime:
        return normalize_utc_datetime(self.clock())

    def _profile(self, symbol: str) -> InstrumentProfile:
        if symbol not in self.instruments:
            raise ValueError('instrument UNSUPPORTED / NOT_READY')
        return self.instruments[symbol]

    def create_account(self, *, execution_source: str, execution_provider: str = 'PAPER',
                       environment: Environment = Environment.PAPER,
                       initial_balance: Decimal = Decimal('10000')) -> Account:
        if Environment(environment) is not Environment.PAPER:
            raise ValueError('LIVE execution is not enabled')
        self.registry.resolve(execution_provider)
        initial_balance = parse_decimal(initial_balance)
        now = self._now()
        account = Account(account_id=str(uuid4()), execution_source=execution_source,
                          execution_provider=execution_provider, created_at=now,
                          updated_at=now, initial_balance=initial_balance, cash_balance=initial_balance)
        with self.database.transaction() as session:
            session.add(ExecutionAccountRecord(
                account_id=account.account_id, execution_source=account.execution_source,
                execution_provider=account.execution_provider, environment=account.environment.value,
                accounting_profile_version=account.accounting_profile_version,
                numeric_policy_version=account.numeric_policy_version, initial_balance=initial_balance,
                cash_balance=initial_balance, reserved_collateral=Decimal('0'), created_at=now,
                last_sequence=0, command_sequence=0, state=document(account), state_hash=content_hash(account)))
        return account

    def get_account(self, account_id: str, *, as_of: datetime | None = None) -> Account:
        with self.database.read_session() as session:
            record = self.repository.read_account(session, account_id)
            if record is None:
                raise ValueError('execution account not found')
            current = self.repository.parse_account(session, record)
            if as_of is None:
                from app.retention.repository import account_status
                return Account.model_validate(current.model_copy(update={
                    'status': account_status(session, account_id, self._now())}).model_dump(mode='python'))
            cutoff = normalize_utc_datetime(as_of)
            if cutoff < current.created_at:
                raise ValueError('account not yet visible')
            state = Account(account_id=current.account_id, execution_source=current.execution_source,
                            execution_provider=current.execution_provider, initial_balance=current.initial_balance,
                            cash_balance=current.initial_balance, created_at=current.created_at,
                            updated_at=current.created_at)
            rows = session.scalars(select(ExecutionFillRecord).where(
                ExecutionFillRecord.account_id == account_id,
                ExecutionFillRecord.received_at <= cutoff).order_by(
                    ExecutionFillRecord.filled_at, ExecutionFillRecord.execution_sequence)).all()
            for row in rows:
                fill = self.repository.parse_fill(row)
                order_row = session.get(ExecutionOrderRecord, fill.internal_order_id)
                assert order_row is not None
                order = self.repository.parse_order(order_row)
                frozen_profile = InstrumentProfile.model_validate(order_row.instrument_profile)
                state = apply_fill(state, fill, frozen_profile, plan_reference=order.intent.plan_reference)
            from app.retention.repository import account_status
            return Account.model_validate(state.model_copy(update={
                'status': account_status(session, account_id, cutoff)}).model_dump(mode='python'))

    def get_order(self, account_id: str, order_id: str) -> Order:
        with self.database.read_session() as session:
            row = session.get(ExecutionOrderRecord, order_id)
            if row is None or row.account_id != account_id:
                raise ValueError('scoped order not found')
            return self.repository.parse_order(row)

    def submit_order(self, account_id: str, intent: OrderIntent) -> Order:
        intent = OrderIntent.model_validate(intent.model_dump(mode='python'))
        profile = self._profile(intent.symbol)
        profile.validate_units(intent.limit_price, intent.quantity)
        now = self._now()
        with self.database.transaction() as session:
            record = self.repository.lock_account(session, account_id)
            account = self.repository.parse_account(session, record)
            prior = session.scalar(select(ExecutionOrderRecord).where(
                ExecutionOrderRecord.account_id == account_id, ExecutionOrderRecord.command_id == intent.command_id))
            if prior is not None:
                if prior.request_hash != content_hash(intent):
                    raise ValueError('CONFLICT: command changed')
                return self.repository.parse_order(prior)
            from app.retention.repository import require_active_account
            require_active_account(session, account_id)
            position = next((p for p in account.positions if p.symbol == intent.symbol and p.quantity), None)
            reduce_only = position is not None and position.direction != ('LONG' if intent.side == 'BUY' else 'SHORT')
            rejected = reduce_only and position is not None and intent.quantity > position.quantity
            order = Order(order_id=str(uuid4()), account_id=account_id, intent=intent,
                          instrument_reference=profile.reference, accepted_at=now,
                          submission_status=SubmissionStatus.REJECTED if rejected else SubmissionStatus.UNKNOWN,
                          reduce_only=reduce_only, bound_trade_id=position.trade_id if reduce_only and position else None,
                          rejection_reason='over-close / implicit reversal' if rejected else None)
            record.command_sequence += 1
            session.add(ExecutionOrderRecord(order_id=order.order_id, account_id=account_id,
                execution_source=account.execution_source, command_id=intent.command_id,
                command_sequence=record.command_sequence, request_hash=content_hash(intent),
                intent=document(intent), instrument_profile=document(profile), accepted_at=now, state=document(order)))
        if rejected:
            return order
        adapter = self.registry.resolve(account.execution_provider)
        try:
            receipt = OrderSubmission.model_validate(adapter.submit_order(order).model_dump(mode='python'))
        except Exception:
            # Dispatch may have succeeded: UNKNOWN is not rejection and retry
            # does not submit again. Reconcile through the provider separately.
            receipt = OrderSubmission(status=SubmissionStatus.UNKNOWN, reason='provider submission unavailable')
        return self._save_submission(account_id, order.order_id, receipt)

    def _save_submission(self, account_id: str, order_id: str, receipt: OrderSubmission) -> Order:
        if receipt.status is SubmissionStatus.ACKNOWLEDGED and receipt.external_order_id is None:
            receipt = OrderSubmission(status=SubmissionStatus.UNKNOWN, reason='invalid provider acknowledgment')
        with self.database.transaction() as session:
            self.repository.lock_account(session, account_id)
            row = session.get(ExecutionOrderRecord, order_id)
            assert row is not None
            order = self.repository.parse_order(row)
            if order.submission_status is not SubmissionStatus.UNKNOWN:
                return order
            order = Order.model_validate(order.model_copy(update={
                'submission_status': receipt.status, 'external_order_id': receipt.external_order_id,
                'rejection_reason': receipt.reason}).model_dump(mode='python'))
            row.state = document(order)
        return order

    def reconcile_submission(self, account_id: str, order_id: str) -> Order:
        order = self.get_order(account_id, order_id)
        account = self.get_account(account_id)
        adapter = self.registry.resolve(account.execution_provider)
        try:
            receipt = OrderSubmission.model_validate(adapter.get_order(order).model_dump(mode='python'))
        except Exception:
            receipt = OrderSubmission(status=SubmissionStatus.UNKNOWN, reason='provider reconciliation unavailable')
        return self._save_submission(account_id, order_id, receipt)

    def cancel_order(self, account_id: str, order_id: str) -> Order:
        order = self.get_order(account_id, order_id)
        with self.database.transaction() as session:
            self.repository.lock_account(session, account_id)
            if order.cancelled_at is not None:
                return order
            from app.retention.repository import require_active_account
            require_active_account(session, account_id)
        adapter = self.registry.resolve(self.get_account(account_id).execution_provider)
        try:
            result = Cancellation.model_validate(adapter.cancel_order(order).model_dump(mode='python'))
        except Exception:
            result = Cancellation(status='UNKNOWN')
        with self.database.transaction() as session:
            self.repository.lock_account(session, account_id)
            row = session.get(ExecutionOrderRecord, order_id)
            assert row is not None
            order = self.repository.parse_order(row)
            order = order.model_copy(update={'cancellation_status': result.status})
            from app.retention.repository import require_active_account
            require_active_account(session, account_id)
            if result.status == 'CANCELLED' and order.filled_quantity < order.intent.quantity:
                order = order.model_copy(update={'cancelled_at': order.cancelled_at or self._now()})
            row.state = document(order)
        return order

    def admit_event(self, account_id: str, payload: object) -> ExecutionEvent:
        account = self.get_account(account_id)
        adapter = self.registry.resolve(account.execution_provider)
        event = adapter.normalize_event(payload)
        event = ExecutionEvent.model_validate(event.model_copy(update={'received_at': self._now()}).model_dump(mode='python'))
        if event.provenance.provider != adapter.provider or event.provenance.adapter_version != adapter.adapter_version:
            raise ValueError('provider binding mismatch')
        with self.database.transaction() as session:
            record = self.repository.lock_account(session, account_id)
            result = self.repository.admit(session, record, event, self._profile(event.symbol),
                                           allow_new_fill=adapter.accepts_external_fills)
        return result

    def observe(self, account_id: str, market: ValidatedMarketData) -> tuple[ExecutionEvent, ...]:
        now = self._now()
        market = ValidatedMarketData.model_validate(market.model_dump(mode='python'))
        if (market.timeframe is not Timeframe.ONE_MINUTE or market.provenance.lag_seconds
                or market.retrieved_at > now or market.provenance.data_cutoff_at != timeframe_bucket_start(now, Timeframe.ONE_MINUTE)
                or market.candles[-1].timestamp + timedelta(minutes=1) != market.provenance.data_cutoff_at):
            raise ValueError('execution observation STALE / NOT_READY')
        validate_candle_order(market.candles, Timeframe.ONE_MINUTE)
        if any(c.timestamp + timedelta(minutes=1) > now for c in market.candles):
            raise ValueError('future/partial execution observation')
        self._profile(market.symbol.value)
        account = self.get_account(account_id)
        adapter = self.registry.resolve(account.execution_provider)
        if not isinstance(adapter, PaperExecutionAdapter):
            raise ValueError('closed-candle observation requires PAPER execution capability')
        fills: list[ExecutionEvent] = []
        with self.database.transaction() as session:
            record = self.repository.lock_account(session, account_id)
            from app.retention.repository import require_active_account
            require_active_account(session, account_id)
            orders = self._observation_orders(session, account_id, market.symbol.value)
            for start in range(0, len(market.candles), OBSERVATION_BATCH_SIZE):
                candles = market.candles[start:start + OBSERVATION_BATCH_SIZE]
                marks = {mark.valuation_at: mark for mark in session.scalars(
                    select(ExecutionMarkRecord).where(
                        ExecutionMarkRecord.account_id == account_id,
                        ExecutionMarkRecord.symbol == market.symbol.value,
                        ExecutionMarkRecord.valuation_at.in_(
                            [c.timestamp + timedelta(minutes=1) for c in candles])))}
                changed: dict[str, tuple[ExecutionOrderRecord, Order]] = {}
                for candle in candles:
                    terminal = []
                    for identifier, (order_row, order) in orders.items():
                        if (candle.timestamp <= order.accepted_at or
                                (order.last_observation_at is not None and candle.timestamp <= order.last_observation_at)):
                            continue
                        expected = (order.last_observation_at + timedelta(minutes=1) if order.last_observation_at is not None
                                    else timeframe_bucket_start(order.accepted_at, Timeframe.ONE_MINUTE) + timedelta(minutes=1))
                        if candle.timestamp != expected:
                            raise ValueError('missing first/next eligible observation; no hidden gap')
                        proposal = adapter.propose_fill(order, candle, execution_source=record.execution_source,
                            received_at=now, sequence=record.last_sequence + 1, market_source=market.source)
                        if proposal is not None:
                            # Admission sees the exact latest cursor. It still reparses
                            # persisted order/account/position/evidence and owns all money.
                            order_row.state = document(order)
                            try:
                                event = self.repository.admit(session, record, adapter.normalize_event(proposal),
                                                              self._profile(proposal.symbol), allow_new_fill=True)
                            except ValueError as error:
                                if str(error) not in {'insufficient available balance', 'stale reduction / reversal rejected',
                                                      'stale opening intent / implicit reversal rejected', 'over-close / implicit reversal rejected'}:
                                    raise
                                order_row.state = document(order.model_copy(update={
                                    'submission_status': SubmissionStatus.REJECTED, 'rejection_reason': str(error)}))
                            else:
                                fills.append(event)
                            # Financial/rejection transitions are NEVER reused unchecked.
                            order = self.repository.parse_order(order_row)
                        order = order.model_copy(update={'last_observation_at': candle.timestamp})
                        changed[identifier] = (order_row, order)
                        orders[identifier] = (order_row, order)
                        if order.submission_status is not SubmissionStatus.ACKNOWLEDGED or order.filled_quantity == order.intent.quantity:
                            terminal.append(identifier)
                    for identifier in terminal:
                        del orders[identifier]
                    valuation_at = candle.timestamp + timedelta(minutes=1)
                    mark = marks.get(valuation_at)
                    mark_hash = content_hash({'candle': candle, 'source': market.source})
                    if mark is None:
                        session.add(ExecutionMarkRecord(account_id=account_id, symbol=market.symbol.value,
                            valuation_at=valuation_at, price=candle.close, received_at=now, observation_hash=mark_hash))
                    elif mark.observation_hash != mark_hash or mark.price != candle.close:
                        raise ValueError('CONFLICT: immutable market valuation observation')
                for order_row, order in changed.values():
                    order_row.state = document(order)
                session.flush()
        return tuple(fills)

    def _observation_orders(self, session: Session, account_id: str,
                            symbol: str) -> dict[str, tuple[ExecutionOrderRecord, Order]]:
        """Validate ALL canonical orders, retain only hot state under account lock.

        Immutable inactive history is streamed, not hydrated into a full archive.
        This request-local state cannot outlive the transaction or authorize fills.
        """
        rows = session.scalars(select(ExecutionOrderRecord).where(
            ExecutionOrderRecord.account_id == account_id).order_by(
                ExecutionOrderRecord.command_sequence).execution_options(yield_per=OBSERVATION_BATCH_SIZE))
        orders = {}
        try:
            for row in rows:
                order = self.repository.parse_order(row)
                if (order.intent.symbol == symbol and order.submission_status is SubmissionStatus.ACKNOWLEDGED
                        and order.cancelled_at is None and order.filled_quantity != order.intent.quantity):
                    orders[row.order_id] = (row, order)
        finally:
            rows.close()
        return orders

    def account_view(self, account_id: str, *, as_of: datetime | None = None) -> AccountView:
        cutoff = normalize_utc_datetime(as_of) if as_of is not None else self._now()
        account = self.get_account(account_id, as_of=cutoff)
        valuations = []
        unrealized = Decimal('0')
        status: Literal['READY', 'NOT_READY', 'STALE'] = 'READY'
        with self.database.read_session() as session:
            for position in account.positions:
                if not position.quantity:
                    continue
                row = session.scalar(select(ExecutionMarkRecord).where(
                    ExecutionMarkRecord.account_id == account_id, ExecutionMarkRecord.symbol == position.symbol,
                    ExecutionMarkRecord.received_at <= cutoff, ExecutionMarkRecord.valuation_at <= cutoff).order_by(
                        ExecutionMarkRecord.valuation_at.desc()).limit(1))
                if row is None:
                    status = 'NOT_READY'
                    continue
                valuations.append(Valuation(symbol=row.symbol, valuation_price=row.price,
                    valuation_at=row.valuation_at, received_at=row.received_at))
                if row.valuation_at != timeframe_bucket_start(cutoff, Timeframe.ONE_MINUTE):
                    if status != 'NOT_READY':
                        status = 'STALE'
                    continue
                from app.execution.decimal_policy import multiply
                marked = multiply(row.price, position.quantity)
                pnl = (subtract(marked, position.remaining_cost_basis) if position.direction == 'LONG'
                       else subtract(position.remaining_cost_basis, marked))
                unrealized = add(unrealized, pnl)
        return AccountView(account=account, valuation_status=status, valuations=tuple(valuations),
                           unrealized_pnl=unrealized if status == 'READY' else None,
                           equity=add(account.cash_balance, unrealized) if status == 'READY' else None)
