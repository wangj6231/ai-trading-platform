"""Break detection must not rescan the complete swing history at every bar."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.engines.structure import primitives
from app.schemas.candle import Candle
from app.schemas.structure import StructureBreakBasis
from app.schemas.types import Timeframe
from tests.unit.test_structure_breaks import break_config


def test_break_trend_work_is_bounded_by_configured_points(monkeypatch):
    config = break_config(StructureBreakBasis.WICK)
    candles = []
    for index in range(1200):
        price = Decimal(100 + (index % 7) * 2)
        candles.append(Candle(timestamp=datetime(2025, 1, 1, tzinfo=UTC) + timedelta(minutes=index),
            open=price, close=price, high=price+1, low=price-1, volume=1))
    original = primitives._classify_trend
    work = []
    def measured(swings, config):
        work.append(len(swings))
        return original(swings, config)
    monkeypatch.setattr(primitives, "_classify_trend", measured)
    result = primitives.analyze_market_structure(candles, Timeframe.ONE_MINUTE, config)
    assert len(result.confirmed_swings) > 100
    # The last call is the whole-result trend; the preceding calls are per-bar.
    assert max(work[:-1]) <= 2 * config.trend_points_per_side


def test_unchanged_confirmed_frontier_does_not_reclassify_trend(monkeypatch):
    config = break_config(StructureBreakBasis.WICK)
    candles = [Candle(timestamp=datetime(2025, 1, 1, tzinfo=UTC) + timedelta(minutes=index),
        open=Decimal(100+index), close=Decimal(100+index),
        high=Decimal(101+index), low=Decimal(99+index), volume=1)
        for index in range(1200)]
    original = primitives._classify_trend
    work = []
    def measured(swings, config):
        work.append(len(swings))
        return original(swings, config)
    monkeypatch.setattr(primitives, '_classify_trend', measured)
    result = primitives.analyze_market_structure(candles, Timeframe.ONE_MINUTE, config)
    assert result.confirmed_swings == []
    assert result.structure_events == []
    assert result.structure_rejections == []
    # Once for the initial empty frontier, once for the whole-result trend.
    assert work == [0, 0]
