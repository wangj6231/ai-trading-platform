import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.engines.indicators import (
    IndicatorInputError,
    calculate_atr,
    calculate_ema,
    calculate_indicators,
    calculate_macd,
)
from app.schemas.candle import Candle
from app.schemas.indicator import ATRConfig, ATRSmoothing, MACDConfig
from app.schemas.types import Timeframe


FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "indicator_candles.json"


@pytest.fixture
def candles() -> list[Candle]:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return [Candle.model_validate(item) for item in payload]


def assert_decimal_close(actual: Decimal | None, expected: str) -> None:
    assert actual is not None
    assert float(actual) == pytest.approx(float(Decimal(expected)), abs=1e-12)


def test_ema_uses_sma_seed_and_configurable_period() -> None:
    values = [Decimal(value) for value in (10, 11, 12, 11)]

    result = calculate_ema(values, period=2)

    assert result[0] is None
    assert result[1] == Decimal("10.5")
    assert result[2] == Decimal("11.5")
    assert_decimal_close(result[3], "11.16666666666666666666666667")


def test_macd_components_warm_up_without_backfill(candles: list[Candle]) -> None:
    result = calculate_macd(candles, MACDConfig(fast_period=2, slow_period=3, signal_period=2))

    assert len(result.points) == len(candles)
    assert result.points[0].fast_ema is None
    assert result.points[1].fast_ema == Decimal("10.5")
    assert result.points[1].slow_ema is None
    assert result.points[2].slow_ema == Decimal("11")
    assert result.points[2].macd_line == Decimal("0.5")
    assert result.points[2].signal_line is None
    assert result.points[2].histogram is None
    assert_decimal_close(result.points[3].signal_line, "0.3333333333333333333333333333")
    assert_decimal_close(result.points[3].histogram, "-0.1666666666666666666666666667")


def test_macd_crossovers_and_histogram_directions(candles: list[Candle]) -> None:
    points = calculate_macd(
        candles,
        MACDConfig(fast_period=2, slow_period=3, signal_period=2),
    ).points

    assert points[3].bullish_crossover is False
    assert points[3].bearish_crossover is False
    assert points[3].histogram_increasing is False
    assert points[3].histogram_decreasing is False

    assert points[4].bullish_crossover is True
    assert points[4].bearish_crossover is False
    assert points[4].histogram_increasing is True
    assert points[4].histogram_decreasing is False

    assert points[6].bullish_crossover is False
    assert points[6].bearish_crossover is True
    assert points[6].histogram_increasing is False
    assert points[6].histogram_decreasing is True

    assert points[8].histogram_increasing is True
    assert points[8].histogram_decreasing is False


def test_unchanged_histogram_is_neither_increasing_nor_decreasing(candles: list[Candle]) -> None:
    flat_candles = [
        candle.model_copy(update={"open": Decimal("10"), "high": Decimal("10"), "low": Decimal("10"), "close": Decimal("10")})
        for candle in candles[:3]
    ]

    points = calculate_macd(
        flat_candles,
        MACDConfig(fast_period=1, slow_period=2, signal_period=1),
    ).points

    assert points[2].histogram == Decimal("0")
    assert points[2].histogram_increasing is False
    assert points[2].histogram_decreasing is False


def test_atr_true_range_and_wilder_smoothing(candles: list[Candle]) -> None:
    result = calculate_atr(candles, ATRConfig(period=3, smoothing="WILDER"))

    assert [point.true_range for point in result.points[:5]] == [
        Decimal("2"),
        Decimal("2.5"),
        Decimal("3"),
        Decimal("2"),
        Decimal("3.5"),
    ]
    assert result.points[0].atr is None
    assert result.points[1].atr is None
    assert result.points[2].atr == Decimal("2.5")
    assert_decimal_close(result.points[3].atr, "2.333333333333333333333333333")
    assert_decimal_close(result.points[4].atr, "2.722222222222222222222222222")


def test_atr_sma_smoothing_is_configurable(candles: list[Candle]) -> None:
    result = calculate_atr(candles, ATRConfig(period=3, smoothing=ATRSmoothing.SMA))

    assert result.points[2].atr == Decimal("2.5")
    assert result.points[3].atr == Decimal("2.5")
    assert_decimal_close(result.points[4].atr, "2.833333333333333333333333333")


def test_indicator_analysis_is_structured(candles: list[Candle]) -> None:
    result = calculate_indicators(
        candles,
        timeframe=Timeframe.ONE_MINUTE,
        macd_config=MACDConfig(fast_period=2, slow_period=3, signal_period=2),
        atr_config=ATRConfig(period=3, smoothing="WILDER"),
    )

    assert result.candle_count == 9
    assert result.data_cutoff_at == datetime(2025, 1, 1, 0, 9, tzinfo=UTC)
    assert result.macd.config.fast_period == 2
    assert result.atr.config.period == 3
    assert isinstance(result.model_dump(), dict)


def test_prefix_results_do_not_change_when_future_candles_are_added(candles: list[Candle]) -> None:
    config = MACDConfig(fast_period=2, slow_period=3, signal_period=2)
    prefix = calculate_macd(candles[:6], config)
    full = calculate_macd(candles, config)

    assert prefix.points == full.points[:6]

    atr_config = ATRConfig(period=3, smoothing="WILDER")
    prefix_atr = calculate_atr(candles[:6], atr_config)
    full_atr = calculate_atr(candles, atr_config)
    assert prefix_atr.points == full_atr.points[:6]


def test_unsorted_or_duplicate_candles_are_rejected(candles: list[Candle]) -> None:
    with pytest.raises(IndicatorInputError):
        calculate_macd([candles[1], candles[0]], MACDConfig(fast_period=2, slow_period=3, signal_period=2))
    with pytest.raises(IndicatorInputError):
        calculate_atr(
            [candles[0], candles[0]],
            ATRConfig(period=2, smoothing="WILDER"),
        )


def test_periods_are_validated() -> None:
    with pytest.raises(ValidationError, match="fast_period must be less than slow_period"):
        MACDConfig(fast_period=3, slow_period=3, signal_period=2)
    with pytest.raises(ValidationError):
        ATRConfig(period=0, smoothing="WILDER")
