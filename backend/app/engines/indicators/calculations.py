from collections.abc import Sequence
from decimal import Context, Decimal, localcontext

from app.market_data.timeframes import timeframe_duration
from app.schemas.candle import Candle
from app.schemas.indicator import (
    ATRConfig,
    ATRPoint,
    ATRResult,
    ATRSmoothing,
    IndicatorAnalysis,
    MACDConfig,
    MACDPoint,
    MACDResult,
)
from app.schemas.types import Timeframe


INDICATOR_DECIMAL_CONTEXT = Context(prec=34)


class IndicatorInputError(ValueError):
    pass


def _validate_candle_order(candles: Sequence[Candle]) -> None:
    for previous, current in zip(candles, candles[1:], strict=False):
        if current.timestamp <= previous.timestamp:
            raise IndicatorInputError("candles must have unique timestamps in ascending order")


def calculate_ema(values: Sequence[Decimal], period: int) -> list[Decimal | None]:
    """Calculate EMA using an SMA seed at index period - 1."""

    if period < 1:
        raise ValueError("period must be at least 1")

    output: list[Decimal | None] = [None] * len(values)
    if len(values) < period:
        return output

    with localcontext(INDICATOR_DECIMAL_CONTEXT):
        period_decimal = Decimal(period)
        seed = sum(values[:period], start=Decimal(0)) / period_decimal
        output[period - 1] = +seed
        alpha = Decimal(2) / Decimal(period + 1)
        previous = seed
        for index in range(period, len(values)):
            previous = previous + alpha * (values[index] - previous)
            output[index] = +previous

    return output


def calculate_macd(candles: Sequence[Candle], config: MACDConfig) -> MACDResult:
    """Calculate MACD from closed candles without mutating or reordering input."""

    resolved_config = config
    _validate_candle_order(candles)
    closes = [candle.close for candle in candles]

    fast_ema = calculate_ema(closes, resolved_config.fast_period)
    slow_ema = calculate_ema(closes, resolved_config.slow_period)

    macd_line: list[Decimal | None] = [None] * len(candles)
    macd_start = resolved_config.slow_period - 1
    with localcontext(INDICATOR_DECIMAL_CONTEXT):
        for index in range(macd_start, len(candles)):
            fast_value = fast_ema[index]
            slow_value = slow_ema[index]
            assert fast_value is not None
            assert slow_value is not None
            macd_line[index] = +(fast_value - slow_value)

    compact_macd = [value for value in macd_line if value is not None]
    compact_signal = calculate_ema(compact_macd, resolved_config.signal_period)
    signal_line: list[Decimal | None] = [None] * len(candles)
    for compact_index, value in enumerate(compact_signal):
        signal_line[macd_start + compact_index] = value

    histogram: list[Decimal | None] = [None] * len(candles)
    with localcontext(INDICATOR_DECIMAL_CONTEXT):
        for index, (macd_value, signal_value) in enumerate(zip(macd_line, signal_line, strict=True)):
            if macd_value is not None and signal_value is not None:
                histogram[index] = +(macd_value - signal_value)

    points: list[MACDPoint] = []
    for index, candle in enumerate(candles):
        previous_index = index - 1
        previous_macd = macd_line[previous_index] if previous_index >= 0 else None
        previous_signal = signal_line[previous_index] if previous_index >= 0 else None
        current_macd = macd_line[index]
        current_signal = signal_line[index]
        if (
            previous_macd is not None
            and previous_signal is not None
            and current_macd is not None
            and current_signal is not None
        ):
            bullish_crossover = (
                previous_macd <= previous_signal and current_macd > current_signal
            )
            bearish_crossover = (
                previous_macd >= previous_signal and current_macd < current_signal
            )
        else:
            bullish_crossover = False
            bearish_crossover = False

        previous_histogram = histogram[previous_index] if previous_index >= 0 else None
        current_histogram = histogram[index]
        if previous_histogram is not None and current_histogram is not None:
            histogram_increasing = current_histogram > previous_histogram
            histogram_decreasing = current_histogram < previous_histogram
        else:
            histogram_increasing = False
            histogram_decreasing = False

        points.append(
            MACDPoint(
                timestamp=candle.timestamp,
                fast_ema=fast_ema[index],
                slow_ema=slow_ema[index],
                macd_line=macd_line[index],
                signal_line=signal_line[index],
                histogram=histogram[index],
                bullish_crossover=bullish_crossover,
                bearish_crossover=bearish_crossover,
                histogram_increasing=histogram_increasing,
                histogram_decreasing=histogram_decreasing,
            )
        )

    return MACDResult(config=resolved_config, points=points)


def _true_ranges(candles: Sequence[Candle]) -> list[Decimal]:
    true_ranges: list[Decimal] = []
    for index, candle in enumerate(candles):
        high_low = candle.high - candle.low
        if index == 0:
            true_ranges.append(high_low)
            continue
        previous_close = candles[index - 1].close
        true_ranges.append(
            max(
                high_low,
                abs(candle.high - previous_close),
                abs(candle.low - previous_close),
            )
        )
    return true_ranges


def calculate_atr(candles: Sequence[Candle], config: ATRConfig) -> ATRResult:
    """Calculate True Range and ATR using Wilder or rolling-SMA smoothing."""

    resolved_config = config
    _validate_candle_order(candles)
    true_ranges = _true_ranges(candles)
    atr_values: list[Decimal | None] = [None] * len(candles)
    period = resolved_config.period

    if len(candles) >= period:
        with localcontext(INDICATOR_DECIMAL_CONTEXT):
            period_decimal = Decimal(period)
            if resolved_config.smoothing is ATRSmoothing.SMA:
                for index in range(period - 1, len(candles)):
                    window = true_ranges[index - period + 1 : index + 1]
                    atr_values[index] = +(sum(window, start=Decimal(0)) / period_decimal)
            else:
                previous_atr = sum(true_ranges[:period], start=Decimal(0)) / period_decimal
                atr_values[period - 1] = +previous_atr
                for index in range(period, len(candles)):
                    previous_atr = (
                        previous_atr * Decimal(period - 1) + true_ranges[index]
                    ) / period_decimal
                    atr_values[index] = +previous_atr

    points = [
        ATRPoint(timestamp=candle.timestamp, true_range=true_ranges[index], atr=atr_values[index])
        for index, candle in enumerate(candles)
    ]
    return ATRResult(config=resolved_config, points=points)


def calculate_indicators(
    candles: Sequence[Candle],
    *,
    timeframe: Timeframe,
    macd_config: MACDConfig,
    atr_config: ATRConfig,
) -> IndicatorAnalysis:
    """Return a structured deterministic indicator snapshot for the supplied cutoff."""

    _validate_candle_order(candles)
    return IndicatorAnalysis(
        candle_count=len(candles),
        data_cutoff_at=(
            candles[-1].timestamp + timeframe_duration(timeframe)
            if candles
            else None
        ),
        macd=calculate_macd(candles, macd_config),
        atr=calculate_atr(candles, atr_config),
    )
