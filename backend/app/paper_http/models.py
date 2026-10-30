"""Provider-neutral transport DTOs; no accounting algorithms live here."""
import json
from decimal import DecimalException
from typing import Literal

from pydantic import Field, field_validator, model_serializer, model_validator

from app.core.time import UtcDateTime
from app.execution.models import Identifier, Money, OrderIntent, OrderKind, Side, StrictModel, canonical_json, parse_decimal
from app.journal.analytics_models import JournalAnalytics
from app.journal.attachments import AttachmentRead
from app.journal.models import AnnotationPatch, Annotations, JournalResult, MAX_TAG_LENGTH
from app.execution.models import Provenance
from app.retention.models import AccountLifecycle, RetentionEvaluation

MAX_PAGE_SIZE = 100
MAX_DETAIL_FILLS = 1000
MAX_CURSOR_LENGTH = 4096
MAX_DECIMAL_INPUT_TEXT = 2048


class HttpModel(StrictModel):
    @model_serializer(mode='wrap')
    def serialize_http(self, handler, info):
        # Preserve nested Decimal precision and fixed-point form, including the
        # existing Analytics result. Python mode remains native domain types.
        if info.mode == 'json':
            return json.loads(canonical_json(self.model_dump(mode='python')))
        return handler(self)


class LifecycleCommand(HttpModel):
    """No caller-owned timestamp, policy, owner or admin fields."""


class AccountLifecycleDTO(HttpModel, AccountLifecycle):
    pass


class RetentionEvaluationDTO(HttpModel, RetentionEvaluation):
    pass


class Capabilities(HttpModel):
    supports_market_order: bool
    supports_limit_order: bool
    supports_short: bool
    supports_scale_in: bool
    supports_partial_close: bool


class AccountDTO(HttpModel):
    account_id: Identifier
    name: None = None
    environment: Literal['PAPER', 'LIVE']
    execution_provider: Identifier
    accounting_profile: Identifier
    numeric_policy_version: Identifier
    position_model: Identifier
    status: Literal['ACTIVE', 'CLOSED']
    currency: Literal['USDT']
    initial_balance: Money
    cash_balance: Money
    reserved_collateral: Money
    available_balance: Money
    equity: Money | None
    realized_pnl: Money
    unrealized_pnl: Money | None
    valuation_price: None = None
    valuation_at: None = None
    valuation_status: Literal['READY', 'NOT_READY', 'STALE']
    valuations: tuple['ValuationDTO', ...]
    capabilities: Capabilities
    created_at: UtcDateTime
    updated_at: UtcDateTime | None


class ValuationDTO(HttpModel):
    symbol: Identifier
    valuation_price: Money
    valuation_at: UtcDateTime
    received_at: UtcDateTime


class SubmitOrder(HttpModel):
    command_id: Identifier
    symbol: Identifier
    side: Literal['BUY', 'SELL']
    order_type: Literal['MARKET', 'LIMIT']
    quantity: Money = Field(gt=0)
    limit_price: Money | None = Field(default=None, gt=0)

    @field_validator('quantity', 'limit_price', mode='before')
    @classmethod
    def safe_decimal_input(cls, value):
        if value is None:
            return value
        if isinstance(value, str) and len(value) > MAX_DECIMAL_INPUT_TEXT:
            raise ValueError('decimal text exceeds transport bound')
        try:
            return parse_decimal(value)  # same frozen numeric rules; no rounding
        except DecimalException:
            raise ValueError('valid finite decimal text is required') from None

    def intent(self) -> OrderIntent:
        return OrderIntent(command_id=self.command_id, symbol=self.symbol, side=Side(self.side),
                           kind=OrderKind(self.order_type), quantity=self.quantity, limit_price=self.limit_price)

    @model_validator(mode='after')
    def valid_intent(self):
        self.intent()
        return self


class OrderDTO(HttpModel):
    order_id: Identifier
    account_id: Identifier
    command_id: Identifier
    symbol: Identifier
    side: Literal['BUY', 'SELL']
    order_type: Literal['MARKET', 'LIMIT']
    quantity: Money
    filled_quantity: Money
    average_fill_price: None = None
    limit_price: Money | None
    submission_status: Literal['ACKNOWLEDGED', 'REJECTED', 'UNKNOWN']
    cancellation_status: Literal['CANCELLED', 'REJECTED', 'UNKNOWN'] | None
    status: Literal['ACKNOWLEDGED', 'REJECTED', 'UNKNOWN', 'PARTIALLY_FILLED', 'FILLED', 'CANCELLED']
    cancelled_at: UtcDateTime | None
    execution_provider: Identifier
    environment: Literal['PAPER', 'LIVE']
    accepted_at: UtcDateTime
    message: str | None = Field(default=None, max_length=128)
    error_code: str | None = None
    strategy_attribution: None = None


class FillDTO(HttpModel):
    fill_id: Identifier
    order_id: Identifier
    trade_id: Identifier
    account_id: Identifier
    execution_source: Identifier
    role: Literal['ENTRY', 'EXIT']
    symbol: Identifier
    side: Literal['BUY', 'SELL']
    price: Money
    quantity: Money
    fee: Money
    fee_currency: Literal['USDT']
    filled_at: UtcDateTime
    received_at: UtcDateTime
    provenance: Provenance


class PositionDTO(HttpModel):
    position_id: Identifier
    trade_id: Identifier
    account_id: Identifier
    symbol: Identifier
    direction: Literal['LONG', 'SHORT']
    status: Literal['OPEN', 'PARTIALLY_CLOSED', 'CLOSED']
    total_quantity: Money
    remaining_quantity: Money
    average_entry_price: Money | None
    valuation_price: Money | None
    valuation_at: UtcDateTime | None
    valuation_status: Literal['READY', 'NOT_READY', 'STALE']
    realized_pnl: Money
    unrealized_pnl: None = None
    unrealized_status: Literal['NOT_READY_NO_POSITION_PROJECTION'] = 'NOT_READY_NO_POSITION_PROJECTION'
    opened_at: UtcDateTime
    closed_at: UtcDateTime | None
    allowed_actions: tuple[Literal['SCALE_IN', 'PARTIAL_CLOSE', 'CLOSE'], ...]


class TradeDTO(HttpModel):
    trade_id: Identifier
    account_id: Identifier
    position_id: None = None
    symbol: Identifier
    side: Literal['LONG', 'SHORT']
    status: Literal['OPEN', 'PARTIALLY_CLOSED', 'CLOSED']
    opened_at: UtcDateTime
    closed_at: UtcDateTime | None
    average_entry_price: Money
    average_exit_price: Money | None
    total_quantity: Money
    remaining_quantity: Money
    gross_pnl: Money
    total_fees: Money
    net_pnl: Money
    pnl_percent: Money | None
    initial_risk: None = None
    r_multiple: None = None
    holding_duration: str | None
    result: JournalResult | None
    currency: Literal['USDT']
    execution_provider: Identifier
    environment: Literal['PAPER', 'LIVE']
    accounting_profile: Identifier
    numeric_policy_version: Identifier
    strategy_attribution: None = None
    fills: tuple[FillDTO, ...] = Field(max_length=MAX_DETAIL_FILLS)
    annotations: Annotations | None
    setup: None = None


class MetadataPatch(AnnotationPatch):
    expected_version: int = Field(ge=0, strict=True)


class MetadataDTO(HttpModel):
    annotations: Annotations


class AttachmentDTO(HttpModel):
    attachment: AttachmentRead
    url: None = None


class AnalyticsDTO(HttpModel):
    analytics: JournalAnalytics
    included_trade_ids: None = None
    membership_status: Literal['NOT_READY_NO_MEMBERSHIP_LIST'] = 'NOT_READY_NO_MEMBERSHIP_LIST'


class ListQuery(HttpModel):
    limit: int = Field(default=20, ge=1, le=MAX_PAGE_SIZE)
    cursor: str | None = Field(default=None, min_length=1, max_length=MAX_CURSOR_LENGTH)
    as_of: UtcDateTime | None = None
    symbol: Identifier | None = None
    side: Literal['LONG', 'SHORT'] | None = None
    result: JournalResult | None = None
    closed_from: UtcDateTime | None = None
    closed_to: UtcDateTime | None = None
    tag: str | None = Field(default=None, min_length=1, max_length=MAX_TAG_LENGTH)
    strategy: Identifier | None = None


class Page[T](HttpModel):
    items: tuple[T, ...] = Field(max_length=MAX_PAGE_SIZE)
    next_cursor: str | None = Field(default=None, max_length=MAX_CURSOR_LENGTH)
    has_more: bool
    as_of: UtcDateTime
