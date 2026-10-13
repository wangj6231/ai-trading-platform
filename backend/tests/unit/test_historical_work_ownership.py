"""Cache validation/write scheduling and cancellation ownership."""
import asyncio
import threading

import pytest

from app.market_data.historical import FileHistoricalCandleCache, HistoricalBootstrapService, _owned_cache_work
from app.schemas.types import MarketSymbol, Timeframe
from tests.unit.test_historical_bootstrap import START, FakeRangeProvider, make_candle
from app.market_data.timeframes import timeframe_duration


@pytest.mark.parametrize('operation', ['load', 'save'])
def test_cache_file_operations_do_not_run_on_the_event_loop(tmp_path, monkeypatch, operation):
    async def exercise():
        loop_thread = threading.get_ident()
        cache = FileHistoricalCandleCache(tmp_path)
        original = getattr(cache, operation)
        threads = []
        def measured(*args, **kwargs):
            threads.append(threading.get_ident())
            return original(*args, **kwargs)
        monkeypatch.setattr(cache, operation, measured)
        candles = tuple(make_candle(index) for index in range(4))
        end = START+4*timeframe_duration(Timeframe.FIFTEEN_MINUTES)
        service = HistoricalBootstrapService(FakeRangeProvider(candles), cache, now=lambda: end)
        first = await service.ensure_history(symbol=MarketSymbol.BTCUSDT,
            timeframe=Timeframe.FIFTEEN_MINUTES, required_candles=4, end_at=end)
        second = await service.ensure_history(symbol=MarketSymbol.BTCUSDT,
            timeframe=Timeframe.FIFTEEN_MINUTES, required_candles=4, end_at=end)
        assert first.candles == second.candles == candles
        assert first.provenance.content_hash == second.provenance.content_hash
        assert second.provenance.cache_hit
        assert threads and loop_thread not in threads
    asyncio.run(exercise())


def test_repeated_cancellation_waits_for_owned_work_and_keeps_loop_usable():
    async def exercise():
        entered, finish, exited = threading.Event(), threading.Event(), threading.Event()
        def work():
            entered.set()
            try:
                assert finish.wait(5)
            finally:
                exited.set()
        task = asyncio.create_task(_owned_cache_work(work))
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            task.cancel()
            await asyncio.sleep(.01)
            task.cancel()
            await asyncio.sleep(.01)
            assert not task.done() and not exited.is_set()
            finish.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert exited.is_set()
        finally:
            finish.set()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(exercise())
