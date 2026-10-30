import asyncio
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest

from app.market_data.base import ParsedProviderCandle
from app.market_data.exceptions import (
    HistoricalOverlapConflictError,
    HistoricalPaginationError,
)
from app.market_data.historical import (
    FileHistoricalCandleCache,
    HistoricalBootstrapService,
)
from app.market_data.providers.binance import BinancePublicMarketDataProvider
from app.market_data.timeframes import timeframe_duration
from app.schemas.candle import Candle
from app.schemas.types import MarketSymbol, Timeframe


START = datetime(2025, 1, 1, tzinfo=UTC)


def make_candle(index: int, timeframe: Timeframe = Timeframe.FIFTEEN_MINUTES) -> Candle:
    timestamp = START + index * timeframe_duration(timeframe)
    price = Decimal(100) + Decimal(index) / Decimal(100)
    return Candle(
        timestamp=timestamp,
        open=price,
        high=price + Decimal("0.2"),
        low=price - Decimal("0.1"),
        close=price + Decimal("0.1"),
        volume=Decimal("1"),
    )


def to_provider(candle: Candle) -> ParsedProviderCandle:
    return ParsedProviderCandle(
        timestamp=candle.timestamp,
        open=candle.open,
        high=candle.high,
        low=candle.low,
        close=candle.close,
        volume=candle.volume,
    )


class FakeRangeProvider:
    name = "fake_binance_range"
    supported_symbols = frozenset({MarketSymbol.BTCUSDT})

    def __init__(self, candles: tuple[Candle, ...], *, mode: str = "normal") -> None:
        self.candles = candles
        self.mode = mode
        self.calls: list[tuple[datetime, datetime, int]] = []

    async def get_historical_candles_between(
        self,
        symbol: MarketSymbol,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
        limit: int,
    ) -> list[ParsedProviderCandle]:
        assert symbol is MarketSymbol.BTCUSDT
        self.calls.append((start, end, limit))
        visible = [
            candle
            for candle in self.candles
            if start <= candle.timestamp < end
        ]
        if self.mode == "gap" and visible:
            visible.pop(min(1, len(visible) - 1))
        if self.mode == "overlap" and start > self.candles[0].timestamp:
            prior = self.candles[
                max(0, self.candles.index(visible[0]) - 1)
            ]
            visible.insert(0, prior)
        if self.mode == "conflict" and start > self.candles[0].timestamp and visible:
            prior = self.candles[max(0, self.candles.index(visible[0]) - 1)]
            altered_high = prior.high + Decimal("10")
            visible.insert(
                0,
                prior.model_copy(
                    update={
                        "high": altered_high,
                        "close": prior.close + Decimal("9"),
                    }
                ),
            )
        overlap_page = self.mode == "overlap" and start > self.candles[0].timestamp
        if len(visible) <= limit:
            page = visible
        elif overlap_page:
            # Keep the newest rows so a duplicate at the front cannot consume
            # the entire final one-row page.
            page = visible[-limit:]
        else:
            page = visible[:limit]
        return [to_provider(candle) for candle in page]


def run(coro):
    return asyncio.run(coro)


def test_bootstrap_fetches_more_than_35000_closed_15m_bars_and_reuses_cache(tmp_path) -> None:
    candles = tuple(make_candle(index) for index in range(34_944))
    end = START + len(candles) * timeframe_duration(Timeframe.FIFTEEN_MINUTES)
    provider = FakeRangeProvider(candles)
    service = HistoricalBootstrapService(
        provider,
        FileHistoricalCandleCache(tmp_path),
        page_limit=1000,
        now=lambda: end + timedelta(minutes=15),
    )

    first = run(
        service.ensure_history(
            symbol=MarketSymbol.BTCUSDT,
            timeframe=Timeframe.FIFTEEN_MINUTES,
            required_candles=34_944,
            end_at=end,
        )
    )
    calls_after_bootstrap = len(provider.calls)
    second = run(
        service.ensure_history(
            symbol=MarketSymbol.BTCUSDT,
            timeframe=Timeframe.FIFTEEN_MINUTES,
            required_candles=34_944,
            end_at=end,
        )
    )

    assert len(first.candles) == 34_944
    assert first.candles[0].timestamp == START
    assert first.candles[-1].timestamp + timeframe_duration(Timeframe.FIFTEEN_MINUTES) == end
    assert first.provenance.page_count == 35
    assert second.provenance.cache_hit is True
    assert second.provenance.content_hash == first.provenance.content_hash
    assert len(provider.calls) == calls_after_bootstrap


def test_incremental_refresh_appends_only_new_range(tmp_path) -> None:
    candles = tuple(make_candle(index) for index in range(2_000))
    duration = timeframe_duration(Timeframe.FIFTEEN_MINUTES)
    first_end = START + 1_000 * duration
    second_end = START + 2_000 * duration
    provider = FakeRangeProvider(candles)
    service = HistoricalBootstrapService(
        provider,
        FileHistoricalCandleCache(tmp_path),
        page_limit=1000,
        now=lambda: second_end + duration,
    )

    first = run(
        service.ensure_history(
            symbol=MarketSymbol.BTCUSDT,
            timeframe=Timeframe.FIFTEEN_MINUTES,
            required_candles=1_000,
            end_at=first_end,
        )
    )
    second = run(
        service.ensure_history(
            symbol=MarketSymbol.BTCUSDT,
            timeframe=Timeframe.FIFTEEN_MINUTES,
            required_candles=1_000,
            end_at=second_end,
        )
    )

    assert len(first.candles) == len(second.candles) == 1_000
    assert second.provenance.page_count == 1
    assert second.candles[0].timestamp == first.candles[-1].timestamp + duration


def test_old_slice_hash_survives_forward_refresh_and_restart(tmp_path) -> None:
    candles = tuple(make_candle(index) for index in range(12))
    step = timedelta(minutes=15)
    early, late = START + 10 * step, START + 12 * step
    cache = FileHistoricalCandleCache(tmp_path)
    provider = FakeRangeProvider(candles)
    service = HistoricalBootstrapService(provider, cache, now=lambda: late)
    arguments = dict(symbol=MarketSymbol.BTCUSDT, timeframe=Timeframe.FIFTEEN_MINUTES,
                     required_candles=10, end_at=early)
    original = run(service.ensure_history(**arguments))
    cache_before = cache.load(MarketSymbol.BTCUSDT, Timeframe.FIFTEEN_MINUTES)
    run(service.ensure_history(**{**arguments, "end_at": late}))
    cache_after = cache.load(MarketSymbol.BTCUSDT, Timeframe.FIFTEEN_MINUTES)
    warm = run(service.ensure_history(**arguments))
    restarted = run(HistoricalBootstrapService(provider, cache, now=lambda: late).ensure_history(**arguments))
    assert cache_before.content_hash != cache_after.content_hash
    assert original.candles == warm.candles == restarted.candles
    assert original.provenance.content_hash == warm.provenance.content_hash == restarted.provenance.content_hash


def test_slice_hash_independent_of_backfill_cold_cache_and_observation_metadata(tmp_path) -> None:
    candles = tuple(make_candle(index) for index in range(20))
    end = START + timedelta(minutes=300)
    provider = FakeRangeProvider(candles)
    cache = FileHistoricalCandleCache(tmp_path / "warm")
    service = HistoricalBootstrapService(provider, cache, page_limit=3, now=lambda: end)
    arguments = dict(symbol=MarketSymbol.BTCUSDT, timeframe=Timeframe.FIFTEEN_MINUTES,
                     required_candles=10, end_at=end)
    original = run(service.ensure_history(**arguments))
    run(service.ensure_history(**{**arguments, "required_candles": 20}))
    hit = run(service.ensure_history(**arguments))
    cold = run(HistoricalBootstrapService(provider, FileHistoricalCandleCache(tmp_path / "cold"),
               page_limit=1000, now=lambda: end + timedelta(days=1)).ensure_history(**arguments))
    assert original.candles == hit.candles == cold.candles
    assert original.provenance.content_hash == hit.provenance.content_hash == cold.provenance.content_hash
    assert original.provenance.page_count != cold.provenance.page_count
    assert original.provenance.retrieved_at != cold.provenance.retrieved_at
    assert hit.provenance.cache_hit and not cold.provenance.cache_hit


def test_slice_hash_changes_with_validated_candle_content(tmp_path) -> None:
    candles = tuple(make_candle(index) for index in range(10))
    changed = (*candles[:-1], candles[-1].model_copy(update={"volume": Decimal("2")}))
    end = START + timedelta(minutes=150)
    def fetch(rows, path):
        return run(HistoricalBootstrapService(FakeRangeProvider(rows), FileHistoricalCandleCache(path),
                   now=lambda: end).ensure_history(symbol=MarketSymbol.BTCUSDT,
                   timeframe=Timeframe.FIFTEEN_MINUTES, required_candles=10, end_at=end))
    assert fetch(candles, tmp_path / "a").provenance.content_hash != fetch(changed, tmp_path / "b").provenance.content_hash


def test_exact_boundary_overlap_is_deduplicated(tmp_path) -> None:
    candles = tuple(make_candle(index) for index in range(2_000))
    end = START + len(candles) * timeframe_duration(Timeframe.FIFTEEN_MINUTES)
    provider = FakeRangeProvider(candles, mode="overlap")
    service = HistoricalBootstrapService(
        provider,
        FileHistoricalCandleCache(tmp_path),
        page_limit=1000,
        now=lambda: end + timedelta(minutes=15),
    )

    result = run(
        service.ensure_history(
            symbol=MarketSymbol.BTCUSDT,
            timeframe=Timeframe.FIFTEEN_MINUTES,
            required_candles=len(candles),
            end_at=end,
        )
    )

    assert len(result.candles) == len(candles)
    assert len({candle.timestamp for candle in result.candles}) == len(candles)


def test_conflicting_overlap_is_rejected(tmp_path) -> None:
    candles = tuple(make_candle(index) for index in range(2_000))
    end = START + len(candles) * timeframe_duration(Timeframe.FIFTEEN_MINUTES)
    service = HistoricalBootstrapService(
        FakeRangeProvider(candles, mode="conflict"),
        FileHistoricalCandleCache(tmp_path),
        page_limit=1000,
        now=lambda: end + timedelta(minutes=15),
    )

    with pytest.raises(HistoricalOverlapConflictError):
        run(
            service.ensure_history(
                symbol=MarketSymbol.BTCUSDT,
                timeframe=Timeframe.FIFTEEN_MINUTES,
                required_candles=len(candles),
                end_at=end,
            )
        )


def test_missing_interval_is_not_hidden(tmp_path) -> None:
    candles = tuple(make_candle(index) for index in range(100))
    end = START + len(candles) * timeframe_duration(Timeframe.FIFTEEN_MINUTES)
    service = HistoricalBootstrapService(
        FakeRangeProvider(candles, mode="gap"),
        FileHistoricalCandleCache(tmp_path),
        page_limit=100,
        now=lambda: end + timedelta(minutes=15),
    )

    with pytest.raises(HistoricalPaginationError, match="gap|empty"):
        run(
            service.ensure_history(
                symbol=MarketSymbol.BTCUSDT,
                timeframe=Timeframe.FIFTEEN_MINUTES,
                required_candles=len(candles),
                end_at=end,
            )
        )


def test_corrupt_cache_rebootstraps_and_preserves_hash(tmp_path) -> None:
    candles = tuple(make_candle(index) for index in range(100))
    end = START + len(candles) * timeframe_duration(Timeframe.FIFTEEN_MINUTES)
    provider = FakeRangeProvider(candles)
    cache = FileHistoricalCandleCache(tmp_path)
    service = HistoricalBootstrapService(
        provider,
        cache,
        page_limit=100,
        now=lambda: end + timedelta(minutes=15),
    )
    original = run(
        service.ensure_history(
            symbol=MarketSymbol.BTCUSDT,
            timeframe=Timeframe.FIFTEEN_MINUTES,
            required_candles=len(candles),
            end_at=end,
        )
    )
    path = cache.path_for(MarketSymbol.BTCUSDT, Timeframe.FIFTEEN_MINUTES)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["candles"][0]["close"] = "999"
    path.write_text(json.dumps(payload), encoding="utf-8")

    rebootstrapped = run(
        HistoricalBootstrapService(
            provider,
            cache,
            page_limit=100,
            now=lambda: end + timedelta(minutes=15),
        ).ensure_history(
            symbol=MarketSymbol.BTCUSDT,
            timeframe=Timeframe.FIFTEEN_MINUTES,
            required_candles=len(candles),
            end_at=end,
        )
    )

    assert rebootstrapped.provenance.rebootstrap is True
    assert rebootstrapped.provenance.content_hash == original.provenance.content_hash
    assert rebootstrapped.candles == original.candles


def test_future_or_partial_cutoff_is_rejected(tmp_path) -> None:
    end = START + 100 * timeframe_duration(Timeframe.FIFTEEN_MINUTES)
    service = HistoricalBootstrapService(
        FakeRangeProvider(tuple(make_candle(index) for index in range(100))),
        FileHistoricalCandleCache(tmp_path),
        now=lambda: end,
    )
    with pytest.raises(Exception):
        run(
            service.ensure_history(
                symbol=MarketSymbol.BTCUSDT,
                timeframe=Timeframe.FIFTEEN_MINUTES,
                required_candles=1,
                end_at=end + timedelta(minutes=1),
            )
        )


def _binance_row(candle: Candle, interval_ms: int) -> list[object]:
    open_ms = int(candle.timestamp.timestamp() * 1000)
    return [
        open_ms,
        str(candle.open),
        str(candle.high),
        str(candle.low),
        str(candle.close),
        str(candle.volume),
        open_ms + interval_ms - 1,
        "0",
        1,
        "0",
        "0",
        "0",
    ]


def test_binance_range_uses_half_open_exact_boundaries() -> None:
    captured: httpx.Request | None = None
    rows = tuple(make_candle(index, Timeframe.FIFTEEN_MINUTES) for index in range(2))
    interval_ms = int(timeframe_duration(Timeframe.FIFTEEN_MINUTES).total_seconds() * 1000)

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured
        captured = request
        return httpx.Response(200, json=[_binance_row(candle, interval_ms) for candle in rows])

    async def execute() -> list[ParsedProviderCandle]:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport, base_url="https://binance.test") as client:
            provider = BinancePublicMarketDataProvider(
                client=client,
                now=lambda: START + timedelta(hours=1),
            )
            return list(
                await provider.get_historical_candles_between(
                    MarketSymbol.BTCUSDT,
                    Timeframe.FIFTEEN_MINUTES,
                    START,
                    START + 2 * timeframe_duration(Timeframe.FIFTEEN_MINUTES),
                    2,
                )
            )

    result = asyncio.run(execute())
    assert captured is not None
    assert len(result) == 2
    assert captured.url.params["startTime"] == str(int(START.timestamp() * 1000))
    assert captured.url.params["endTime"] == str(
        int((START + 2 * timeframe_duration(Timeframe.FIFTEEN_MINUTES)).timestamp() * 1000) - 1
    )


def test_binance_range_rejects_a_provider_partial_row() -> None:
    end = START + timeframe_duration(Timeframe.FIFTEEN_MINUTES)
    interval_ms = int(timeframe_duration(Timeframe.FIFTEEN_MINUTES).total_seconds() * 1000)

    def handler(_request: httpx.Request) -> httpx.Response:
        partial = make_candle(1, Timeframe.FIFTEEN_MINUTES)
        return httpx.Response(200, json=[_binance_row(partial, interval_ms)])

    async def execute() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport, base_url="https://binance.test") as client:
            provider = BinancePublicMarketDataProvider(
                client=client,
                now=lambda: START + timedelta(hours=1),
            )
            await provider.get_historical_candles_between(
                MarketSymbol.BTCUSDT,
                Timeframe.FIFTEEN_MINUTES,
                START,
                end,
                1,
            )

    with pytest.raises(Exception):
        asyncio.run(execute())
