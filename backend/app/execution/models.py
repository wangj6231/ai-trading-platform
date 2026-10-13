"""Strict, provider-neutral execution facts and reconstructible projections."""

from __future__ import annotations

from decimal import Decimal
from enum import Enum
from hashlib import sha256
import json
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from app.core.time import UtcDateTime
from app.execution.decimal_policy import add, decimal_text, divide, multiply, subtract


def parse_decimal(value: object) -> Decimal:
    if not isinstance(value, (Decimal, str)):
        raise ValueError('execution money requires Decimal or decimal text, never float')
    parsed = Decimal(value)
    if (not parsed.is_finite() or len(parsed.as_tuple().digits) > 512
            or abs(int(parsed.as_tuple().exponent)) > 512):
        raise ValueError('execution decimal outside finite schema bounds')
    return parsed


Money = Annotated[Decimal, BeforeValidator(parse_decimal)]
Positive = Annotated[Money, Field(gt=0)]
NonNegative = Annotated[Money, Field(ge=0)]
Identifier = Annotated[str, Field(min_length=1, max_length=128, pattern=r'^[\w.:/\-]+$')]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, revalidate_instances='always')


class Side(str, Enum):
    BUY = 'BUY'
    SELL = 'SELL'


class Environment(str, Enum):
    PAPER = 'PAPER'
    LIVE = 'LIVE'


class OrderKind(str, Enum):
    MARKET = 'MARKET'
    LIMIT = 'LIMIT'


class SubmissionStatus(str, Enum):
    ACKNOWLEDGED = 'ACKNOWLEDGED'
    REJECTED = 'REJECTED'
    UNKNOWN = 'UNKNOWN'


class InstrumentProfile(StrictModel):
    reference: Identifier
    symbol: Identifier
    quote_currency: Literal['USDT'] = 'USDT'
    quantity_unit: Literal['BASE_UNITS'] = 'BASE_UNITS'
    price_tick: Positive
    quantity_step: Positive
    minimum_quantity: Positive
    maximum_decimal_places: int = Field(default=18, ge=0, le=128, strict=True)
    maximum_significant_digits: int = Field(default=18, ge=1, le=50, strict=True)

    def validate_units(self, price: Decimal | None, quantity: Decimal) -> None:
        for value, step in ((quantity, self.quantity_step), (price, self.price_tick)):
            if value is None:
                continue
            value = parse_decimal(value)
            # Exact integer-ratio check is validation, not financial rounding.
            numerator, denominator = value.as_integer_ratio()
            step_numerator, step_denominator = step.as_integer_ratio()
            if (value <= 0 or (numerator * step_denominator) % (denominator * step_numerator)
                    or max(0, -int(value.as_tuple().exponent)) > self.maximum_decimal_places
                    or len(value.as_tuple().digits) > self.maximum_significant_digits):
                raise ValueError('unsupported instrument precision/increment')
        if quantity < self.minimum_quantity:
            raise ValueError('quantity below instrument minimum')


class OrderIntent(StrictModel):
    command_id: Identifier
    symbol: Identifier
    side: Side
    kind: OrderKind
    quantity: Positive
    limit_price: Positive | None = None
    plan_reference: Identifier | None = None

    @model_validator(mode='after')
    def check_limit(self) -> OrderIntent:
        if (self.kind is OrderKind.LIMIT) != (self.limit_price is not None):
            raise ValueError('only LIMIT requires limit_price')
        return self


class Order(StrictModel):
    order_id: Identifier
    account_id: Identifier
    intent: OrderIntent
    instrument_reference: Identifier
    accepted_at: UtcDateTime
    submission_status: SubmissionStatus
    external_order_id: Identifier | None = None
    rejection_reason: str | None = Field(default=None, max_length=128)
    reduce_only: bool = False
    bound_trade_id: Identifier | None = None
    filled_quantity: NonNegative = Decimal('0')
    cancelled_at: UtcDateTime | None = None
    cancellation_status: Literal['CANCELLED', 'REJECTED', 'UNKNOWN'] | None = None
    last_observation_at: UtcDateTime | None = None


class OrderSubmission(StrictModel):
    status: SubmissionStatus
    external_order_id: Identifier | None = None
    reason: str | None = Field(default=None, max_length=128)


class Cancellation(StrictModel):
    status: Literal['CANCELLED', 'REJECTED', 'UNKNOWN']


class Fee(StrictModel):
    amount: NonNegative
    currency: Literal['USDT'] = 'USDT'


class Provenance(StrictModel):
    provider: Identifier
    adapter_version: Identifier
    sequence: int = Field(gt=0, strict=True)
    execution_policy_version: Identifier | None = None
    observation_hash: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')


class ExecutionEvent(StrictModel):
    event_schema_version: Literal['EXECUTION_EVENT_V1'] = 'EXECUTION_EVENT_V1'
    event_type: Literal['FILL_CONFIRMED'] = 'FILL_CONFIRMED'
    event_id: Identifier
    execution_source: Identifier
    trading_account_id: Identifier
    internal_order_id: Identifier
    external_order_id: Identifier
    external_fill_id: Identifier
    symbol: Identifier
    instrument_reference: Identifier
    side: Side
    price: Positive
    quantity: Positive
    fees: tuple[Fee, ...] = Field(min_length=1, max_length=16)
    filled_at: UtcDateTime
    received_at: UtcDateTime
    provenance: Provenance

    @model_validator(mode='after')
    def check_time(self) -> ExecutionEvent:
        if self.filled_at > self.received_at:
            raise ValueError('fill cannot precede server visibility into the future')
        return self

    @property
    def economic_content_hash(self) -> str:
        # Delivery identity/time excluded; original receipt remains immutable.
        core = self.model_dump(mode='python', exclude={'event_id', 'received_at'})
        return content_hash(core)

    @property
    def total_fee(self) -> Decimal:
        result = Decimal('0')
        for fee in self.fees:
            result = add(result, fee.amount)
        return result


def canonical_json(value: object) -> str:
    from datetime import datetime
    from app.core.time import canonical_utc_iso

    def encode(item: object) -> object:
        if isinstance(item, Decimal):
            return decimal_text(item)
        if isinstance(item, datetime):
            return canonical_utc_iso(item)
        if isinstance(item, BaseModel):
            return encode(item.model_dump(mode='python'))
        if isinstance(item, dict):
            return {key: encode(member) for key, member in item.items()}
        if isinstance(item, (list, tuple)):
            return [encode(member) for member in item]
        return item
    return json.dumps(encode(value), sort_keys=True, separators=(',', ':'), allow_nan=False)


def content_hash(value: object) -> str:
    return sha256(canonical_json(value).encode('utf-8')).hexdigest()


class Position(StrictModel):
    symbol: Identifier
    instrument_reference: Identifier
    direction: Literal['LONG', 'SHORT']
    trade_id: Identifier
    quantity: NonNegative
    remaining_cost_basis: NonNegative

    @property
    def average_entry_price(self) -> Decimal | None:
        return divide(self.remaining_cost_basis, self.quantity) if self.quantity else None


class Trade(StrictModel):
    trade_id: Identifier
    symbol: Identifier
    direction: Literal['LONG', 'SHORT']
    opened_at: UtcDateTime
    closed_at: UtcDateTime | None = None
    gross_pnl: Money = Decimal('0')
    total_fees: NonNegative = Decimal('0')
    total_entry_notional: Positive
    accounting_profile_version: Literal['PAPER_DIRECTIONAL_V1'] = 'PAPER_DIRECTIONAL_V1'
    numeric_policy_version: Literal['PAPER_DECIMAL_V1'] = 'PAPER_DECIMAL_V1'
    plan_reference: Identifier | None = None
    r_multiple: None = None

    @property
    def net_pnl(self) -> Decimal:
        return subtract(self.gross_pnl, self.total_fees)

    @property
    def pnl_percent(self) -> Decimal | None:
        return (multiply(divide(self.net_pnl, self.total_entry_notional), Decimal('100'))
                if self.closed_at is not None else None)

    @property
    def financial_outcome(self):
        from app.core.financial import classify_financial_outcome
        return classify_financial_outcome(self.net_pnl) if self.closed_at is not None else None


class Account(StrictModel):
    account_id: Identifier
    execution_source: Identifier
    execution_provider: Identifier
    environment: Environment = Environment.PAPER
    accounting_profile_version: Literal['PAPER_DIRECTIONAL_V1'] = 'PAPER_DIRECTIONAL_V1'
    numeric_policy_version: Literal['PAPER_DECIMAL_V1'] = 'PAPER_DECIMAL_V1'
    account_model: Literal['SYNTHETIC_DIRECTIONAL'] = 'SYNTHETIC_DIRECTIONAL'
    position_model: Literal['ONE_WAY_NET_POSITION'] = 'ONE_WAY_NET_POSITION'
    settlement_currency: Literal['USDT'] = 'USDT'
    reporting_currency: Literal['USDT'] = 'USDT'
    status: Literal['ACTIVE', 'CLOSED'] = 'ACTIVE'
    initial_balance: Positive = Decimal('10000')
    cash_balance: Money = Decimal('10000')
    created_at: UtcDateTime
    updated_at: UtcDateTime | None = None
    last_sequence: int = Field(default=0, ge=0, strict=True)
    last_filled_at: UtcDateTime | None = None
    positions: tuple[Position, ...] = ()
    trades: tuple[Trade, ...] = ()

    @property
    def reserved_collateral(self) -> Decimal:
        total = Decimal('0')
        for position in self.positions:
            total = add(total, position.remaining_cost_basis)
        return total

    @property
    def available_balance(self) -> Decimal:
        return subtract(self.cash_balance, self.reserved_collateral)

    @property
    def realized_pnl(self) -> Decimal:
        total = Decimal('0')
        for trade in self.trades:
            total = add(total, trade.gross_pnl)
        return total


class Valuation(StrictModel):
    symbol: Identifier
    valuation_price: Positive
    valuation_at: UtcDateTime
    received_at: UtcDateTime


class AccountView(StrictModel):
    account: Account
    valuation_status: Literal['READY', 'NOT_READY', 'STALE']
    valuations: tuple[Valuation, ...] = ()
    unrealized_pnl: Money | None = None
    equity: Money | None = None
