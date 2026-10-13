"""Scoped read/command transport over frozen domain services, without PnL math."""
from collections.abc import Mapping
from datetime import datetime
from secrets import token_bytes
from typing import Literal

from pydantic import Field
from sqlalchemy import select

from app.core.time import normalize_utc_datetime
from app.execution.gateway import ExecutionGateway
from app.execution.models import Account, Identifier, Order, StrictModel, content_hash, Environment
from app.execution.records import ExecutionOrderRecord
from app.journal.analytics import JournalAnalyticsService
from app.journal.analytics_models import AnalyticsQuery
from app.journal.attachments import AttachmentCursor, AttachmentQuery
from app.journal.models import AnnotationPatch, FillReference, JournalTrade
from app.journal.service import JournalService
from app.paper_http.errors import ErrorCode, MESSAGES, error, order_error
from app.paper_http.models import (
    AccountDTO, AnalyticsDTO, AttachmentDTO, Capabilities, FillDTO, ListQuery,
    MetadataDTO, MetadataPatch, OrderDTO, Page, PositionDTO, SubmitOrder, TradeDTO, ValuationDTO,
    MAX_DETAIL_FILLS,
)
from app.paper_http.pagination import Cursor, CursorCodec


class TrustedPrincipal(StrictModel):
    """Only an authenticated SERVER dependency may construct this grant."""
    subject: Identifier
    account_ids: tuple[Identifier, ...] = Field(max_length=1000)


class TradeAccountMetadata(StrictModel):
    """Immutable presentation metadata only; never an accounting Account."""
    execution_provider: Identifier
    environment: Environment
    reporting_currency: Literal['USDT'] = 'USDT'


class PaperHttpService:
    def __init__(self, gateway: ExecutionGateway, *, cursor_key: bytes | None = None,
                 capabilities: Mapping[str, Capabilities] | None = None):
        self.gateway = gateway
        from app.retention.service import FinancialRetentionService
        self.retention = FinancialRetentionService(gateway)
        self.journal = JournalService(gateway.database, clock=gateway.clock)
        self.analytics = JournalAnalyticsService(gateway.database, clock=gateway.clock)
        self.codec = CursorCodec(cursor_key if cursor_key is not None else token_bytes(32))
        # An explicit binding, not duck-typing or assumed future broker support.
        self.capabilities = dict(capabilities) if capabilities is not None else {
            'PAPER': Capabilities(supports_market_order=True, supports_limit_order=True,
                supports_short=True, supports_scale_in=True, supports_partial_close=True)}

    def scoped(self, principal: TrustedPrincipal, account_id: str) -> 'AccountScope':
        principal = TrustedPrincipal.model_validate(principal.model_dump(mode='python'))
        if account_id not in principal.account_ids:
            raise error(ErrorCode.FORBIDDEN, 403)
        return AccountScope(self, principal.subject, account_id)


class AccountScope:
    def __init__(self, service: PaperHttpService, subject: str, account_id: str):
        self.service, self.subject, self.account_id = service, subject, account_id

    def _now(self) -> datetime:
        return normalize_utc_datetime(self.service.gateway.clock())

    def close_account(self):
        return self.service.retention.close_account(self.account_id, subject_id=self.subject)

    def request_deletion(self):
        return self.service.retention.request_deletion(self.account_id, subject_id=self.subject)

    def lifecycle(self, *, as_of=None):
        return self.service.retention.get_lifecycle(self.account_id, subject_id=self.subject, as_of=as_of)

    def retention_candidate(self):
        return self.service.retention.dry_run_candidate(self.account_id, subject_id=self.subject)

    def _capabilities(self, account) -> Capabilities:
        self.service.gateway.registry.resolve(account.execution_provider)
        if account.execution_provider not in self.service.capabilities:
            raise error(ErrorCode.PROVIDER_UNAVAILABLE, 503)
        return Capabilities.model_validate(self.service.capabilities[account.execution_provider].model_dump(mode='python'))

    def account(self) -> AccountDTO:
        if self.service.gateway.database.engine.dialect.name == 'postgresql':
            from app.journal.dashboard_reads import account_state, valuations
            cutoff = self._now()
            with self.service.gateway.database.read_session() as session:
                state = account_state(session, self.account_id, cutoff)
                from app.retention.repository import account_status
                status, marks, unrealized, equity = valuations(session, state, cutoff)
                return AccountDTO(account_id=state.account_id, environment=state.environment,
                    execution_provider=state.execution_provider, accounting_profile=state.accounting_profile_version,
                    numeric_policy_version=state.numeric_policy_version, position_model=state.position_model,
                    status=account_status(session, self.account_id, cutoff), currency=state.reporting_currency, initial_balance=state.initial_balance,
                    cash_balance=state.cash_balance, reserved_collateral=state.reserved_collateral,
                    available_balance=state.available_balance, equity=equity, realized_pnl=state.realized_pnl,
                    unrealized_pnl=unrealized, valuation_status=status,
                    valuations=tuple(ValuationDTO.model_validate(mark.model_dump(mode='python')) for mark in marks),
                    capabilities=self._capabilities(state), created_at=state.created_at, updated_at=state.updated_at)
        view = self.service.gateway.account_view(self.account_id)
        account = view.account
        return AccountDTO(account_id=account.account_id, environment=account.environment.value,
            execution_provider=account.execution_provider, accounting_profile=account.accounting_profile_version,
            numeric_policy_version=account.numeric_policy_version, position_model=account.position_model,
            status=account.status, currency=account.reporting_currency, initial_balance=account.initial_balance,
            cash_balance=account.cash_balance, reserved_collateral=account.reserved_collateral,
            available_balance=account.available_balance, equity=view.equity, realized_pnl=account.realized_pnl,
            unrealized_pnl=view.unrealized_pnl, valuation_status=view.valuation_status,
            valuations=tuple(ValuationDTO.model_validate(v.model_dump(mode='python')) for v in view.valuations),
            capabilities=self._capabilities(account), created_at=account.created_at, updated_at=account.updated_at)

    @staticmethod
    def _order(order: Order, account: Account | TradeAccountMetadata) -> OrderDTO:
        status: Literal['ACKNOWLEDGED', 'REJECTED', 'UNKNOWN', 'PARTIALLY_FILLED', 'FILLED', 'CANCELLED'] = ('FILLED' if order.filled_quantity == order.intent.quantity else
                  'CANCELLED' if order.cancelled_at is not None else
                  'PARTIALLY_FILLED' if order.filled_quantity > 0 else order.submission_status.value)
        code = order_error(order.submission_status.value, order.rejection_reason)
        return OrderDTO(order_id=order.order_id, account_id=order.account_id, command_id=order.intent.command_id,
            symbol=order.intent.symbol, side=order.intent.side.value, order_type=order.intent.kind.value,
            quantity=order.intent.quantity, filled_quantity=order.filled_quantity,
            limit_price=order.intent.limit_price, submission_status=order.submission_status.value,
            cancellation_status=order.cancellation_status, status=status, cancelled_at=order.cancelled_at,
            execution_provider=account.execution_provider, environment=account.environment.value,
            accepted_at=order.accepted_at, error_code=code.value if code else None,
            message=MESSAGES[code] if code else None)

    def submit(self, request: SubmitOrder) -> OrderDTO:
        intent = request.intent()
        account = self.service.gateway.get_account(self.account_id)
        caps = self._capabilities(account)
        if (intent.kind.value == 'MARKET' and not caps.supports_market_order
                or intent.kind.value == 'LIMIT' and not caps.supports_limit_order):
            raise error(ErrorCode.VALIDATION_ERROR, 422)
        order = self.service.gateway.submit_order(self.account_id, intent)
        return self._order(order, account)

    def order(self, order_id: str) -> OrderDTO:
        account: Account | TradeAccountMetadata
        if self.service.gateway.database.engine.dialect.name == 'postgresql':
            from app.journal.readmodel import ready_account
            with self.service.gateway.database.read_session() as session:
                identity = ready_account(session, self.account_id, self._now())
                record = session.get(ExecutionOrderRecord, order_id)
                if record is None or record.account_id != self.account_id:
                    raise ValueError('scoped order not found')
                account = TradeAccountMetadata(execution_provider=identity.execution_provider,
                    environment=identity.environment)
                return self._order(self.service.gateway.repository.parse_order(record), account)
        account = self.service.gateway.get_account(self.account_id)
        return self._order(self.service.gateway.get_order(self.account_id, order_id), account)

    def cancel(self, order_id: str) -> OrderDTO:
        current = self.service.gateway.get_order(self.account_id, order_id)
        # Confirmed terminal retry: do not redispatch cancellation or erase fills.
        if current.cancelled_at is None and current.filled_quantity < current.intent.quantity:
            if current.submission_status.value == 'REJECTED':
                raise error(ErrorCode.ORDER_ALREADY_TERMINAL, 409)
            self.service.gateway.cancel_order(self.account_id, order_id)
        # Command receipt stays canonical even when derived Dashboard storage
        # is NOT_READY; do not report a committed cancellation as a read failure.
        account = self.service.gateway.get_account(self.account_id)
        return self._order(self.service.gateway.get_order(self.account_id, order_id), account)

    def _pagination(self, resource: str, query: ListQuery):
        query = ListQuery.model_validate(query.model_dump(mode='python'))
        if query.closed_from is not None and query.closed_to is not None and query.closed_from >= query.closed_to:
            raise error(ErrorCode.VALIDATION_ERROR, 422)
        if query.strategy is not None:
            raise error(ErrorCode.CONFLICT, 409)  # attribution NOT_READY, not empty performance
        filters = query.model_dump(mode='python', exclude={'cursor', 'limit', 'as_of'})
        scope = content_hash(dict(subject=self.subject, account=self.account_id, resource=resource, filters=filters))
        now = self._now()
        cursor = self.service.codec.decode(query.cursor, scope=scope, now=now) if query.cursor else None
        cutoff = cursor.as_of if cursor else query.as_of or now
        if cutoff > now or (query.as_of is not None and query.as_of != cutoff):
            raise error(ErrorCode.VALIDATION_ERROR, 422)
        return scope, cutoff, cursor

    @staticmethod
    def _unfiltered(query: ListQuery) -> None:
        if any(getattr(query, key) is not None for key in ('symbol', 'side', 'result', 'closed_from', 'closed_to', 'tag', 'strategy')):
            raise error(ErrorCode.VALIDATION_ERROR, 422)

    def orders(self, query: ListQuery) -> Page[OrderDTO]:
        self._unfiltered(query)
        scope, cutoff, cursor = self._pagination('orders', query)
        repository = self.service.gateway.repository
        with self.service.gateway.database.read_session() as session:
            account: Account | TradeAccountMetadata
            if session.get_bind().dialect.name == 'postgresql':
                from app.journal.readmodel import ready_account
                identity = ready_account(session, self.account_id, cutoff)
                account = TradeAccountMetadata(execution_provider=identity.execution_provider, environment=identity.environment)
            else:
                record = repository.read_account(session, self.account_id)
                if record is None:
                    raise error(ErrorCode.NOT_FOUND, 404)
                account = repository.parse_account(session, record)
            statement = select(ExecutionOrderRecord).where(ExecutionOrderRecord.account_id == self.account_id,
                                                          ExecutionOrderRecord.accepted_at <= cutoff)
            if cursor:
                prior = session.get(ExecutionOrderRecord, cursor.after_id)
                if prior is None or prior.account_id != self.account_id or prior.accepted_at != cursor.after_at:
                    raise error(ErrorCode.VALIDATION_ERROR, 422)
                statement = statement.where((ExecutionOrderRecord.accepted_at > cursor.after_at) | (
                    (ExecutionOrderRecord.accepted_at == cursor.after_at) & (ExecutionOrderRecord.order_id > cursor.after_id)))
            rows = session.scalars(statement.order_by(ExecutionOrderRecord.accepted_at,
                ExecutionOrderRecord.order_id).limit(query.limit + 1)).all()
            items = tuple(self._order(repository.parse_order(r), account) for r in rows[:query.limit])
        more = len(rows) > query.limit
        next_cursor = self.service.codec.encode(Cursor(scope=scope, as_of=cutoff,
            after_at=items[-1].accepted_at, after_id=items[-1].order_id)) if more else None
        return Page[OrderDTO](items=items, next_cursor=next_cursor, has_more=more, as_of=cutoff)

    def positions(self) -> tuple[PositionDTO, ...]:
        cutoff = self._now()
        if self.service.gateway.database.engine.dialect.name == 'postgresql':
            from app.journal.dashboard_reads import account_state, valuations
            with self.service.gateway.database.read_session() as session:
                state = account_state(session, self.account_id, cutoff)
                status, marks, _unrealized, _equity = valuations(session, state, cutoff)
                caps = self._capabilities(state)
                items = []
                for position in state.positions:
                    display_trade = state.position_displays[position.trade_id]
                    mark = next((m for m in marks if m.symbol == position.symbol), None)
                    display_actions: tuple[Literal['SCALE_IN', 'PARTIAL_CLOSE', 'CLOSE'], ...] = ()
                    if position.quantity:
                        display_actions = ('CLOSE',)
                        if caps.supports_partial_close:
                            display_actions = ('PARTIAL_CLOSE',) + display_actions
                        if caps.supports_scale_in:
                            display_actions = ('SCALE_IN',) + display_actions
                    items.append(PositionDTO(position_id=content_hash((self.account_id, position.symbol)),
                        trade_id=display_trade.trade_id, account_id=self.account_id, symbol=position.symbol,
                        direction=position.direction, status=display_trade.status, total_quantity=display_trade.quantity,
                        remaining_quantity=position.quantity, average_entry_price=position.average_entry_price,
                        valuation_price=mark.valuation_price if mark else None,
                        valuation_at=mark.valuation_at if mark else None,
                        valuation_status=status if mark else 'NOT_READY', realized_pnl=display_trade.gross_pnl,
                        opened_at=display_trade.opened_at, closed_at=display_trade.closed_at, allowed_actions=display_actions))
                return tuple(items)
        view = self.service.gateway.account_view(self.account_id, as_of=cutoff)
        trades = {t.trade_id: t for t in self.service.journal.list_trades(self.account_id, as_of=cutoff)}
        caps = self._capabilities(view.account)
        items = []
        for position in view.account.positions:
            trade = trades[position.trade_id]
            valuation = next((v for v in view.valuations if v.symbol == position.symbol), None)
            actions: tuple[Literal['SCALE_IN', 'PARTIAL_CLOSE', 'CLOSE'], ...] = ()
            if position.quantity:
                actions = ('CLOSE',)
                if caps.supports_partial_close:
                    actions = ('PARTIAL_CLOSE',) + actions
                if caps.supports_scale_in:
                    actions = ('SCALE_IN',) + actions
            items.append(PositionDTO(position_id=content_hash((self.account_id, position.symbol)),
                trade_id=trade.trade_id, account_id=self.account_id, symbol=position.symbol,
                direction=position.direction, status=trade.status, total_quantity=trade.quantity,
                remaining_quantity=position.quantity, average_entry_price=position.average_entry_price,
                valuation_price=valuation.valuation_price if valuation else None,
                valuation_at=valuation.valuation_at if valuation else None,
                valuation_status=view.valuation_status if valuation else 'NOT_READY', realized_pnl=trade.gross_pnl,
                opened_at=trade.opened_at, closed_at=trade.closed_at,
                allowed_actions=actions))
        return tuple(items)

    @staticmethod
    def _fill(trade_id: str, reference: FillReference) -> FillDTO:
        event = reference.event
        return FillDTO(fill_id=event.event_id, order_id=event.internal_order_id, trade_id=trade_id,
            account_id=event.trading_account_id, execution_source=event.execution_source, role=reference.role,
            symbol=event.symbol, side=event.side.value, price=event.price, quantity=event.quantity,
            fee=event.total_fee, fee_currency='USDT', filled_at=event.filled_at, received_at=event.received_at,
            provenance=event.provenance)

    def _trade(self, trade: JournalTrade, account: Account | TradeAccountMetadata) -> TradeDTO:
        return TradeDTO(trade_id=trade.trade_id, account_id=self.account_id, symbol=trade.symbol, side=trade.side,
            status=trade.status, opened_at=trade.opened_at, closed_at=trade.closed_at,
            average_entry_price=trade.average_entry_price, average_exit_price=trade.average_exit_price,
            total_quantity=trade.quantity, remaining_quantity=trade.remaining_quantity, gross_pnl=trade.gross_pnl,
            total_fees=trade.total_fees, net_pnl=trade.net_pnl, pnl_percent=trade.pnl_percent,
            holding_duration=str(trade.holding_duration) if trade.holding_duration is not None else None,
            result=trade.result, currency=account.reporting_currency, execution_provider=account.execution_provider,
            environment=account.environment.value, accounting_profile=trade.accounting_profile_version,
            numeric_policy_version=trade.numeric_policy_version,
            fills=tuple(self._fill(trade.trade_id, f) for f in trade.fills), annotations=trade.annotations)

    def trade(self, trade_id: str) -> TradeDTO:
        from app.journal.readmodel import detail, ready_account
        cutoff = self._now()
        with self.service.gateway.database.read_session() as session:
            row = ready_account(session, self.account_id, cutoff)
            account = TradeAccountMetadata(execution_provider=row.execution_provider, environment=row.environment)
            return self._trade(detail(session, self.account_id, trade_id, cutoff, account=row,
                include_attachments=False, max_fills=MAX_DETAIL_FILLS), account)

    @staticmethod
    def _matches(trade: JournalTrade, query: ListQuery) -> bool:
        return ((query.symbol is None or trade.symbol == query.symbol) and
            (query.side is None or trade.side == query.side) and (query.result is None or trade.result == query.result) and
            (query.closed_from is None or trade.closed_at is not None and trade.closed_at >= query.closed_from) and
            (query.closed_to is None or trade.closed_at is not None and trade.closed_at < query.closed_to) and
            (query.tag is None or trade.annotations is not None and query.tag in trade.annotations.tags))

    def _page(self, rows, *, query: ListQuery, scope: str, cutoff: datetime, cursor: Cursor | None,
              key, convert, membership_hash: str | None = None):
        rows = sorted(rows, key=key)
        if cursor:
            if cursor.membership_hash != membership_hash:
                raise error(ErrorCode.CONFLICT, 409)
            anchor = (cursor.after_at, cursor.after_id)
            if not any(key(row) == anchor for row in rows):
                raise error(ErrorCode.VALIDATION_ERROR, 422)
            rows = [row for row in rows if key(row) > anchor]
        selected = rows[:query.limit]
        more = len(rows) > query.limit
        token = None
        if more:
            at, identifier = key(selected[-1])
            token = self.service.codec.encode(Cursor(scope=scope, as_of=cutoff, after_at=at,
                after_id=identifier, membership_hash=membership_hash))
        return Page(items=tuple(convert(row) for row in selected), next_cursor=token, has_more=more, as_of=cutoff)

    def trades(self, query: ListQuery, *, journal: bool = False) -> Page[TradeDTO]:
        from app.journal.readmodel import detail, page
        scope, cutoff, cursor = self._pagination('journal' if journal else 'trades', query)
        with self.service.gateway.database.read_session() as session:
            row, identifiers, more, membership = page(session, self.account_id, cutoff, query, cursor)
            account = TradeAccountMetadata(execution_provider=row.execution_provider, environment=row.environment)
            trades = tuple(detail(session, self.account_id, identifier, cutoff, account=row,
                include_attachments=False, max_fills=MAX_DETAIL_FILLS) for identifier in identifiers)
            token = (self.service.codec.encode(Cursor(scope=scope, as_of=cutoff, after_at=trades[-1].opened_at,
                after_id=trades[-1].trade_id, membership_hash=membership)) if more else None)
            return Page(items=tuple(self._trade(t, account) for t in trades), next_cursor=token, has_more=more, as_of=cutoff)

    def fills(self, trade_id: str, query: ListQuery) -> Page[FillDTO]:
        from app.journal.readmodel import fill_page
        self._unfiltered(query)
        scope, cutoff, cursor = self._pagination('fills:' + trade_id, query)
        with self.service.gateway.database.read_session() as session:
            fills, more = fill_page(session, self.account_id, trade_id, cutoff, query, cursor)
            token = (self.service.codec.encode(Cursor(scope=scope, as_of=cutoff,
                after_at=fills[-1].event.filled_at, after_id=fills[-1].event.event_id)) if more else None)
            return Page(items=tuple(self._fill(trade_id, f) for f in fills), next_cursor=token, has_more=more, as_of=cutoff)

    def metadata(self, trade_id: str, patch: MetadataPatch) -> MetadataDTO:
        result = self.service.journal.set_annotations(self.account_id, trade_id,
            AnnotationPatch.model_validate(patch.model_dump(mode='python', exclude={'expected_version'})),
            expected_version=patch.expected_version)
        return MetadataDTO(annotations=result)

    def analytics(self, query: AnalyticsQuery) -> AnalyticsDTO:
        if query.strategy is not None:
            raise error(ErrorCode.CONFLICT, 409)
        return AnalyticsDTO(analytics=self.service.analytics.evaluate(self.account_id, query))

    def attachments(self, trade_id: str, query: ListQuery) -> Page[AttachmentDTO]:
        self._unfiltered(query)
        scope, cutoff, cursor = self._pagination('attachments:' + trade_id, query)
        typed = AttachmentCursor(account_id=self.account_id, trade_id=trade_id, as_of=cutoff,
            after_created_at=cursor.after_at, after_attachment_id=cursor.after_id) if cursor else None
        result = self.service.journal.list_attachments(self.account_id, trade_id,
            AttachmentQuery(limit=query.limit, as_of=cutoff, cursor=typed))
        token = self.service.codec.encode(Cursor(scope=scope, as_of=cutoff,
            after_at=result.next_cursor.after_created_at, after_id=result.next_cursor.after_attachment_id)) if result.next_cursor else None
        return Page[AttachmentDTO](items=tuple(AttachmentDTO(attachment=a) for a in result.items),
            next_cursor=token, has_more=token is not None, as_of=cutoff)
