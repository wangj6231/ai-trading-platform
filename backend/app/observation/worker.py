"""Continuous closed-minute delivery. No order submission or financial formula."""
import asyncio
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import partial
from typing import Literal
from time import perf_counter

import anyio
from app.core.telemetry import DEFAULT_TELEMETRY, Telemetry

from app.core.time import normalize_utc_datetime, utc_now
from app.core.errors import MarketDataProviderNotConfiguredError, MarketDataRateLimitedError
from app.execution.gateway import ExecutionGateway
from app.market_data.base import HistoricalRangeMarketDataProvider
from app.market_data.normalization import validate_candle_order
from app.market_data.service import MarketDataService
from app.market_data.timeframes import timeframe_bucket_start
from app.observation.repository import ActiveWorkNotReady, ObservationRepository
from app.schemas.market import MarketDataMode, ValidatedMarketData
from app.schemas.types import MarketSymbol, Timeframe


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ObservationStatus:
    state: Literal['IDLE', 'READY', 'NOT_READY', 'UNAVAILABLE', 'BUSY']
    code: str
    cutoff_at: datetime | None = None


async def _owned_work(function, *args, on_cancel=None):
    # DB/CPU work stays off ASGI; cancellation waits for owned finite transaction.
    task = asyncio.create_task(asyncio.to_thread(partial(function, *args)))
    cancelled = False
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        cancelled = True
        raise
    finally:
        with anyio.CancelScope(shield=True):
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            if not task.cancelled():
                task.exception()
            if cancelled and on_cancel is not None and task.exception() is None:
                result = task.result()
                if result is not None:
                    await _owned_work(on_cancel, result)


class ObservationWorker:
    def __init__(self, gateway: ExecutionGateway, market_data: MarketDataService, *,
                 clock: Callable[[], datetime] = utc_now, poll_seconds: float = 5,
                 page_limit: int = 1000, max_catchup_candles: int = 100000,
                 max_work_items: int = 100000, max_accounts: int = 10000,
                 checkpoint_page_size: int = 100,
                 telemetry: Telemetry | None = None) -> None:
        if poll_seconds <= 0 or not 1 <= page_limit <= 1000 or max_catchup_candles < 1:
            raise ValueError('invalid observation infrastructure limits')
        self.gateway, self.market_data, self.clock = gateway, market_data, clock
        self.repository = ObservationRepository(gateway.database, max_work_items=max_work_items,
            max_accounts=max_accounts, checkpoint_page_size=checkpoint_page_size)
        self.poll_seconds, self.page_limit, self.max_catchup_candles = poll_seconds, page_limit, max_catchup_candles
        self.status: dict[str, ObservationStatus] = {}
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._cycle = asyncio.Lock()
        self._retry_at: dict[str, datetime] = {}
        self.telemetry = telemetry or DEFAULT_TELEMETRY

    def checkpoint(self, account_id: str, symbol: str) -> datetime | None:
        return self.repository.checkpoint(account_id, symbol)

    async def start(self) -> None:
        if self._task is not None:
            raise ValueError('observation worker already started')
        self._task = asyncio.create_task(self._run(), name='closed-1m-observation-worker')

    async def aclose(self) -> None:
        self._stop.set()
        if self._task is not None:
            # Cancel provider IO, but let a running gateway transaction finish.
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run(self) -> None:
        while not self._stop.is_set():
            await self.tick()
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.poll_seconds)
            except TimeoutError:
                pass

    def _state(self, symbol: str, state, code: str, cutoff: datetime | None = None) -> None:
        previous = self.status.get(symbol)
        self.status[symbol] = ObservationStatus(state, code, cutoff)
        if (previous is None or previous.code != code) and state in {'NOT_READY', 'UNAVAILABLE'}:
            # Fixed categories only, never exception/provider payload/account tokens.
            logger.warning('Observation worker unavailable', extra={'symbol': symbol, 'category': code})

    async def tick(self) -> None:
        async with self._cycle:
            for raw_symbol in sorted(self.gateway.instruments):
                if self._retry_at.get(raw_symbol, datetime.min.replace(tzinfo=normalize_utc_datetime(self.clock()).tzinfo)) > normalize_utc_datetime(self.clock()):
                    continue
                try:
                    await self._symbol(MarketSymbol(raw_symbol))
                except asyncio.CancelledError:
                    raise
                except ActiveWorkNotReady:
                    self._state(raw_symbol, 'NOT_READY', 'ACTIVE_WORK_NOT_READY')
                except MarketDataProviderNotConfiguredError:
                    self._state(raw_symbol, 'NOT_READY', 'MARKET_PROVIDER_NOT_READY')
                except MarketDataRateLimitedError as error:
                    delay = (error.details.get('retry_after_seconds', self.poll_seconds)
                             if isinstance(error.details, Mapping) else self.poll_seconds)
                    if not isinstance(delay, (int, float)) or isinstance(delay, bool):
                        delay = self.poll_seconds
                    self._retry_at[raw_symbol] = normalize_utc_datetime(self.clock()) + timedelta(seconds=max(self.poll_seconds, min(delay, 86400)))
                    self._state(raw_symbol, 'UNAVAILABLE', 'MARKET_RATE_LIMITED')
                except Exception:
                    self._state(raw_symbol, 'UNAVAILABLE', 'OBSERVATION_UNAVAILABLE')

    async def _symbol(self, symbol: MarketSymbol) -> None:
        provider = self.market_data.provider_for(symbol)
        if not isinstance(provider, HistoricalRangeMarketDataProvider):
            self._state(symbol.value, 'NOT_READY', 'RANGE_PROVIDER_NOT_READY')
            return
        lock_started = perf_counter()
        connection = await _owned_work(self.repository.acquire, provider.name, symbol.value,
            on_cancel=lambda conn: self.repository.release(conn, provider.name, symbol.value))
        self.telemetry.emit('worker', symbol=symbol.value, lock_seconds=perf_counter() - lock_started,
                            outcome='busy' if connection is None else 'ok')
        if connection is None:
            self._state(symbol.value, 'BUSY', 'STREAM_ALREADY_OWNED')
            return
        try:
            now = normalize_utc_datetime(self.clock())
            cutoff = timeframe_bucket_start(now, Timeframe.ONE_MINUTE)
            targets = await _owned_work(self.repository.targets, self.gateway, symbol.value, cutoff)
            available = {}
            selected = len(targets)
            checkpoints = await _owned_work(self.repository.checkpoints, list(targets), symbol.value, provider.name)
            for account, first_at in targets.items():
                checkpoint = checkpoints[account]
                if checkpoint is None or checkpoint < cutoff:
                    available[account] = first_at
            targets = available
            self.telemetry.emit('worker', symbol=symbol.value, targets=len(targets),
                                replay_suppressed=selected - len(targets), outcome='ok')
            if not targets:
                self._state(symbol.value, 'IDLE', 'NO_ELIGIBLE_OBSERVATION', cutoff)
                return
            start = min(targets.values())
            self.telemetry.emit('worker', symbol=symbol.value,
                backlog_candles=int((cutoff - start) / timedelta(minutes=1)), outcome='ok')
            if int((cutoff - start) / timedelta(minutes=1)) > self.max_catchup_candles:
                self._state(symbol.value, 'NOT_READY', 'CATCHUP_LIMIT_EXCEEDED', cutoff)
                return
            market = await self.market_data.get_closed_range(symbol, Timeframe.ONE_MINUTE, start, cutoff,
                                                          page_limit=self.page_limit)
            market = ValidatedMarketData.model_validate(market.model_dump(mode='python'))
            current = normalize_utc_datetime(self.clock())
            if (market.source != provider.name or market.symbol is not symbol or market.timeframe is not Timeframe.ONE_MINUTE
                    or market.provenance.data_mode is not MarketDataMode.SERVER_PROVIDER
                    or market.provenance.lag_seconds or market.retrieved_at > current
                    or market.provenance.data_cutoff_at != timeframe_bucket_start(current, Timeframe.ONE_MINUTE)
                    or market.candles[0].timestamp != start or market.candles[-1].timestamp + timedelta(minutes=1) != cutoff):
                self._state(symbol.value, 'NOT_READY', 'OBSERVATION_STALE', cutoff)
                return
            validate_candle_order(market.candles, Timeframe.ONE_MINUTE)
            observed_available = perf_counter()
            self.telemetry.emit('worker', symbol=symbol.value,
                lag_seconds=max(0, (current - cutoff).total_seconds()), outcome='ok')
            await _owned_work(self.repository.capture, market)
            delivery_failed = False
            for account in sorted(targets):
                # Same canonical batch, gateway owns per-order eligibility and fees.
                try:
                    admission_started = perf_counter()
                    events = await _owned_work(self.gateway.observe, account, market)
                    self.telemetry.emit('worker', symbol=symbol.value, admissions=len(events),
                        duration_seconds=perf_counter() - admission_started,
                        admission_lag_seconds=perf_counter() - observed_available, outcome='ok')
                    await _owned_work(self.repository.delivered, account, market, normalize_utc_datetime(self.clock()))
                    self.telemetry.emit('worker', symbol=symbol.value, checkpoints=1, outcome='ok')
                except Exception:
                    self.telemetry.emit('worker', symbol=symbol.value, outcome='error')
                    delivery_failed = True
            self._state(symbol.value, 'UNAVAILABLE' if delivery_failed else 'READY',
                        'DELIVERY_RETRY_REQUIRED' if delivery_failed else 'OBSERVATION_DELIVERED', cutoff)
        finally:
            await _owned_work(self.repository.release, connection, provider.name, symbol.value)
