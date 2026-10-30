"""PRIVATE TEST orchestration, never an HTTP endpoint or production worker.

Synthetic market observations are permitted only inside tests. All fills,
accounting, Journal and Analytics remain production-domain derived.
"""
from datetime import datetime, timedelta

from app.execution.gateway import ExecutionGateway
from app.schemas.candle import Candle
from app.schemas.market import MarketDataProvenance, ValidatedMarketData


class OwnedObservationDriver:
    def __init__(self, gateway: ExecutionGateway, clock: list[datetime]):
        self.gateway, self.clock = gateway, clock
        self.accounts: set[str] = set()
        self.last_observation: dict[str, ValidatedMarketData] = {}

    def register(self, account_id: str) -> None:
        self.gateway.get_account(account_id)
        self.accounts.add(account_id)

    def observe(self, account_id: str, price: str, *, order_id: str | None = None,
                low: str | None = None, high: str | None = None,
                eligibility_probe: bool = False):
        if account_id not in self.accounts:
            raise ValueError('observation account outside owned test scope')
        # Probe interval begins at acceptance, so it cannot legitimately fill.
        start = self.clock[0].replace(second=0, microsecond=0)
        if order_id is not None:
            order = self.gateway.get_order(account_id, order_id)
            start = (order.last_observation_at or order.accepted_at).replace(second=0, microsecond=0)
        if not eligibility_probe:
            start += timedelta(minutes=1)
        close = start + timedelta(minutes=1)
        candle = Candle(timestamp=start, open=price, high=high or price,
                        low=low or price, close=price, volume='1')
        market = ValidatedMarketData(symbol='BTCUSDT', timeframe='1m',
            source='paper-e2e-test-observation', retrieved_at=close, candles=(candle,),
            provenance=MarketDataProvenance(provider='paper-e2e-test-observation',
                data_mode='SERVER_PROVIDER', symbol='BTCUSDT', timeframe='1m',
                first_candle_at=start, last_candle_at=start, data_cutoff_at=close,
                expected_latest_closed_candle_at=close, retrieved_at=close,
                requested_candles=1, received_candles=1, lag_seconds=0))
        self.clock[0] = close
        self.last_observation[account_id] = market
        return self.gateway.observe(account_id, market)

    def repeat(self, account_id: str):
        if account_id not in self.accounts:
            raise ValueError('observation account outside owned test scope')
        return self.gateway.observe(account_id, self.last_observation[account_id])
