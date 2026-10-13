"""Exact leaf reuse retains complete snapshot validation and private ownership."""
from decimal import Decimal
import json

import pytest

from app.market_data.historical import FileHistoricalCandleCache
from app.market_data.exceptions import HistoricalCacheCorruptionError, HistoricalPaginationError
from app.schemas.candle import Candle
from app.schemas.types import MarketSymbol, Timeframe
from tests.unit.test_historical_bootstrap import START, make_candle


def cache_with_history(tmp_path, size=20):
    cache = FileHistoricalCandleCache(tmp_path)
    candles = tuple(make_candle(index) for index in range(size))
    cache.save(provider='explicit_unit_provider', symbol=MarketSymbol.BTCUSDT,
        timeframe=Timeframe.FIFTEEN_MINUTES, retrieved_at=candles[-1].timestamp,
        candles=candles)
    return cache, candles


def test_identical_rows_are_validated_once_and_new_rows_still_validate(tmp_path, monkeypatch):
    cache, candles = cache_with_history(tmp_path)
    original = Candle.model_validate
    calls = []
    def measured(cls, row, *args, **kwargs):
        calls.append(row)
        return original(row, *args, **kwargs)
    monkeypatch.setattr(Candle, 'model_validate', classmethod(measured))
    first = cache.load(MarketSymbol.BTCUSDT, Timeframe.FIFTEEN_MINUTES)
    second = cache.load(MarketSymbol.BTCUSDT, Timeframe.FIFTEEN_MINUTES)
    assert first == second and first.candles == candles
    assert len(calls) == len(candles)
    extended = (*candles, make_candle(len(candles)))
    cache.save(provider='explicit_unit_provider', symbol=MarketSymbol.BTCUSDT,
        timeframe=Timeframe.FIFTEEN_MINUTES, retrieved_at=extended[-1].timestamp, candles=extended)
    third = cache.load(MarketSymbol.BTCUSDT, Timeframe.FIFTEEN_MINUTES)
    assert third.candles == extended and len(calls) == len(extended)


def test_returned_candle_mutation_cannot_change_validated_private_rows(tmp_path):
    cache, candles = cache_with_history(tmp_path)
    first = cache.load(MarketSymbol.BTCUSDT, Timeframe.FIFTEEN_MINUTES)
    # Candle is already frozen. Even an explicit dictionary-level bypass on a
    # caller's separate copy must not corrupt the cache's private validated row.
    first.candles[0].__dict__['open'] = Decimal('-100')
    first.candles[0].__dict__['volume'] = Decimal('-100')
    second = cache.load(MarketSymbol.BTCUSDT, Timeframe.FIFTEEN_MINUTES)
    assert second.candles == candles
    assert first.candles[0] is not second.candles[0]


@pytest.mark.parametrize('defect', ['hash', 'row', 'order', 'identity'])
def test_complete_snapshot_still_rejects_corruption_after_leaf_hits(tmp_path, defect):
    cache, _ = cache_with_history(tmp_path)
    cache.load(MarketSymbol.BTCUSDT, Timeframe.FIFTEEN_MINUTES)
    path = cache.path_for(MarketSymbol.BTCUSDT, Timeframe.FIFTEEN_MINUTES)
    payload = json.loads(path.read_text())
    if defect == 'hash':
        payload['content_hash'] = 'a'*64
    elif defect == 'row':
        payload['candles'][0]['high'] = '-1'
    elif defect == 'order':
        payload['candles'][0], payload['candles'][1] = payload['candles'][1], payload['candles'][0]
    else:
        payload['symbol'] = 'ETHUSDT'
    path.write_text(json.dumps(payload))
    # Original complete-range validation exposes this existing pagination error.
    error = HistoricalPaginationError if defect == 'order' else HistoricalCacheCorruptionError
    with pytest.raises(error):
        cache.load(MarketSymbol.BTCUSDT, Timeframe.FIFTEEN_MINUTES)


def test_validator_generation_and_provider_identity_do_not_reuse_leaf_values(tmp_path, monkeypatch):
    cache, candles = cache_with_history(tmp_path)
    original = Candle.model_validate
    calls = 0
    def counted(cls, row, *args, **kwargs):
        nonlocal calls
        calls += 1
        return original(row, *args, **kwargs)
    monkeypatch.setattr(Candle, 'model_validate', classmethod(counted))
    cache.load(MarketSymbol.BTCUSDT, Timeframe.FIFTEEN_MINUTES)
    def new_generation(cls, row, *args, **kwargs):
        return counted(cls, row, *args, **kwargs)
    monkeypatch.setattr(Candle, 'model_validate', classmethod(new_generation))
    cache.load(MarketSymbol.BTCUSDT, Timeframe.FIFTEEN_MINUTES)
    assert calls == 2*len(candles)
    cache.save(provider='another_explicit_unit_provider', symbol=MarketSymbol.BTCUSDT,
        timeframe=Timeframe.FIFTEEN_MINUTES, retrieved_at=START, candles=candles)
    cache.load(MarketSymbol.BTCUSDT, Timeframe.FIFTEEN_MINUTES)
    assert calls == 3*len(candles)
