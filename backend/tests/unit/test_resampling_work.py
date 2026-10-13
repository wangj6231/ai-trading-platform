"""MTF buckets retain the reference projection with bounded boundary work."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.engines.structure import multi_timeframe as mtf
from app.schemas.candle import Candle
from tests.unit import test_multi_timeframe as fixtures


def test_bucket_boundary_is_calculated_once_per_bucket(monkeypatch):
    start = datetime(2025, 1, 1, tzinfo=UTC)
    candles = [Candle(timestamp=start+timedelta(minutes=index), open=Decimal(10),
        high=Decimal(11), low=Decimal(9), close=Decimal(10), volume=Decimal(1))
        for index in range(1000)]
    config = fixtures.mtf_config()
    original = mtf.timeframe_bucket_start
    calls = 0
    def measured(*args):
        nonlocal calls
        calls += 1
        return original(*args)
    monkeypatch.setattr(mtf, 'timeframe_bucket_start', measured)
    result = mtf.resample_closed_candles(candles, start+timedelta(minutes=1000), config)
    bucket_bound = sum(1+1000//int(mtf.timeframe_duration(target)/timedelta(minutes=1))
        for target in config.mtf_target_timeframes)
    assert calls <= bucket_bound
    assert result.bars
