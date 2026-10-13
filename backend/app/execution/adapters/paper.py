"""PAPER_V1: closed-1m simulator, not Spot inventory or broker fallback."""

from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from app.execution.decimal_policy import multiply, subtract
from app.execution.models import (
    Account, Cancellation, ExecutionEvent, Fee, Order, OrderKind, OrderSubmission,
    Position, Provenance, Side, SubmissionStatus, content_hash,
)
from app.schemas.candle import Candle

PAPER_EXECUTION_POLICY = 'PAPER_CLOSED_1M_V1'
PAPER_FEE_POLICY = 'PAPER_FEE_V1'
PAPER_FEE_RATE = Decimal('0.001')


class PaperExecutionAdapter:
    provider = 'PAPER'
    adapter_version = 'PAPER_V1'
    accepts_external_fills = False

    def submit_order(self, order: Order) -> OrderSubmission:
        return OrderSubmission(status=SubmissionStatus.ACKNOWLEDGED, external_order_id=order.order_id)

    def cancel_order(self, order: Order) -> Cancellation:
        return Cancellation(status='CANCELLED')

    def get_order(self, order: Order) -> OrderSubmission:
        return self.submit_order(order)

    def get_positions(self, account: Account) -> tuple[Position, ...]:
        return self.get_account(account).positions

    def get_account(self, account: Account) -> Account:
        return Account.model_validate(account.model_dump(mode='python'))

    def normalize_event(self, payload: object) -> ExecutionEvent:
        parsed = ExecutionEvent.model_validate(
            payload.model_dump(mode='python') if isinstance(payload, ExecutionEvent) else payload)
        expected = multiply(multiply(parsed.price, parsed.quantity), PAPER_FEE_RATE)
        if (parsed.provenance.provider != self.provider
                or parsed.provenance.adapter_version != self.adapter_version
                or parsed.provenance.execution_policy_version != PAPER_EXECUTION_POLICY
                or parsed.provenance.observation_hash is None
                or len(parsed.fees) != 1 or parsed.total_fee != expected):
            raise ValueError('invalid PAPER policy evidence')
        return parsed

    def propose_fill(self, order: Order, candle: Candle, *, execution_source: str,
                     received_at: datetime, sequence: int, market_source: str) -> ExecutionEvent | None:
        if candle.timestamp <= order.accepted_at:
            return None
        if order.intent.kind is OrderKind.LIMIT:
            price = order.intent.limit_price
            assert price is not None
            if ((order.intent.side is Side.BUY and candle.low > price)
                    or (order.intent.side is Side.SELL and candle.high < price)):
                return None
        else:
            price = candle.close
        quantity = subtract(order.intent.quantity, order.filled_quantity)
        if quantity <= 0:
            return None
        assert order.external_order_id is not None
        return ExecutionEvent(
            event_id=str(uuid4()), execution_source=execution_source,
            trading_account_id=order.account_id, internal_order_id=order.order_id,
            external_order_id=order.external_order_id,
            external_fill_id=f'{order.order_id}/complete', symbol=order.intent.symbol,
            instrument_reference=order.instrument_reference, side=order.intent.side,
            price=price, quantity=quantity,
            fees=(Fee(amount=multiply(multiply(price, quantity), PAPER_FEE_RATE)),),
            filled_at=candle.timestamp + timedelta(minutes=1), received_at=received_at,
            provenance=Provenance(provider=self.provider, adapter_version=self.adapter_version,
                sequence=sequence, execution_policy_version=PAPER_EXECUTION_POLICY,
                observation_hash=content_hash({'candle': candle, 'market_source': market_source})))
