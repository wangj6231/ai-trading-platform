import json
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from app.engines.structure import analyze_market_structure
from app.schemas.candle import Candle
from app.schemas.structure import (
    MarketStructureConfig,
    StructureBreakBasis,
    StructureDirection,
    StructureDisplayAlias,
    StructureEventType,
    SwingTiePolicy,
    TrendState,
)
from app.schemas.types import Timeframe


FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "market_structure_scenarios.json"


@pytest.fixture(scope="module")
def scenarios() -> dict[str, list[Candle]]:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return {
        name: [Candle.model_validate(candle) for candle in candles]
        for name, candles in payload.items()
    }


def break_config(basis: StructureBreakBasis) -> MarketStructureConfig:
    return MarketStructureConfig(
        tick_size=Decimal("0.5"),
        swing_left_bars=1,
        swing_right_bars=1,
        swing_tie_policy=SwingTiePolicy.STRICT,
        trend_points_per_side=2,
        structure_equality_tolerance_ticks=0,
        structure_break_basis=basis,
        structure_break_buffer_ticks=0,
        zone_merge_tolerance_ticks=0,
        zone_padding_ticks=1,
    )


def append_candle(
    candles: list[Candle],
    *,
    open_price: str,
    high: str,
    low: str,
    close: str,
) -> list[Candle]:
    return candles + [
        Candle(
            timestamp=candles[-1].timestamp + timedelta(minutes=1),
            open=Decimal(open_price),
            high=Decimal(high),
            low=Decimal(low),
            close=Decimal(close),
            volume=Decimal("1"),
        )
    ]


def events_on_last_candle(candles: list[Candle], basis: StructureBreakBasis):
    result = analyze_market_structure(candles, Timeframe.ONE_MINUTE, break_config(basis))
    return result, [event for event in result.structure_events if event.timestamp == candles[-1].timestamp]


def test_bullish_bos_contains_required_metadata(scenarios) -> None:
    candles = append_candle(
        scenarios["uptrend"],
        open_price="16",
        high="18",
        low="15",
        close="17",
    )

    _, events = events_on_last_candle(candles, StructureBreakBasis.CLOSE)

    assert len(events) == 1
    event = events[0]
    assert event.type is StructureEventType.BOS
    assert event.direction is StructureDirection.BULLISH
    assert event.price == Decimal("17")
    assert event.broken_structure_id.endswith("2025-02-01T00:05:00+00:00")
    assert event.confirmation_type is StructureBreakBasis.CLOSE
    assert event.confirmed_at == candles[-1].timestamp + timedelta(minutes=1)
    assert event.display_alias is None
    assert event.trend_before_break is TrendState.BULLISH
    assert {
        "type",
        "direction",
        "price",
        "timestamp",
        "broken_structure_id",
        "confirmation_type",
        "confirmed_at",
    }.issubset(event.model_dump())


def test_bearish_bos(scenarios) -> None:
    candles = append_candle(
        scenarios["downtrend"],
        open_price="9",
        high="10",
        low="7",
        close="8",
    )

    _, events = events_on_last_candle(candles, StructureBreakBasis.CLOSE)

    assert len(events) == 1
    assert events[0].type is StructureEventType.BOS
    assert events[0].direction is StructureDirection.BEARISH
    assert events[0].price == Decimal("8")
    assert events[0].trend_before_break is TrendState.BEARISH


def test_bullish_mss_exposes_choch_alias_without_duplicate_event(scenarios) -> None:
    candles = append_candle(
        scenarios["downtrend"],
        open_price="10",
        high="17",
        low="9.5",
        close="16",
    )

    _, events = events_on_last_candle(candles, StructureBreakBasis.CLOSE)

    assert len(events) == 1
    event = events[0]
    assert event.type is StructureEventType.MSS
    assert event.direction is StructureDirection.BULLISH
    assert event.display_alias is StructureDisplayAlias.CHOCH
    assert event.trend_before_break is TrendState.BEARISH


def test_bearish_mss_exposes_choch_alias_without_duplicate_event(scenarios) -> None:
    candles = append_candle(
        scenarios["uptrend"],
        open_price="12",
        high="15",
        low="9",
        close="10",
    )

    _, events = events_on_last_candle(candles, StructureBreakBasis.CLOSE)

    assert len(events) == 1
    event = events[0]
    assert event.type is StructureEventType.MSS
    assert event.direction is StructureDirection.BEARISH
    assert event.display_alias is StructureDisplayAlias.CHOCH
    assert event.trend_before_break is TrendState.BULLISH


def test_false_wick_break_is_not_close_confirmed(scenarios) -> None:
    candles = scenarios["uptrend"]

    _, events = events_on_last_candle(candles, StructureBreakBasis.CLOSE)

    assert events == []


def test_wick_only_break_is_detected_in_wick_mode(scenarios) -> None:
    candles = scenarios["uptrend"]

    _, events = events_on_last_candle(candles, StructureBreakBasis.WICK)

    assert len(events) == 1
    assert events[0].type is StructureEventType.BOS
    assert events[0].direction is StructureDirection.BULLISH
    assert events[0].price == Decimal("17")
    assert events[0].confirmation_type is StructureBreakBasis.WICK


def test_close_confirmed_break_uses_close_not_extreme(scenarios) -> None:
    candles = append_candle(
        scenarios["uptrend"],
        open_price="16",
        high="19",
        low="15",
        close="17",
    )

    _, events = events_on_last_candle(candles, StructureBreakBasis.CLOSE)

    assert len(events) == 1
    assert events[0].price == Decimal("17")
    assert events[0].price != candles[-1].high
    assert events[0].confirmation_type is StructureBreakBasis.CLOSE


@pytest.mark.parametrize(
    ("basis", "expected_count"),
    [
        (StructureBreakBasis.CLOSE, 0),
        (StructureBreakBasis.WICK, 1),
    ],
)
def test_wick_vs_close_behavior_is_configurable(scenarios, basis, expected_count) -> None:
    _, events = events_on_last_candle(scenarios["uptrend"], basis)
    assert len(events) == expected_count


def test_dual_wick_break_is_rejected_without_directional_event(scenarios) -> None:
    candles = append_candle(
        scenarios["range"],
        open_price="10",
        high="13",
        low="7",
        close="10",
    )

    result, events = events_on_last_candle(candles, StructureBreakBasis.WICK)

    assert events == []
    rejection = next(
        rejection
        for rejection in result.structure_rejections
        if rejection.timestamp == candles[-1].timestamp
    )
    assert rejection.code == "AMBIGUOUS_DUAL_STRUCTURE_BREAK"


def test_future_break_does_not_change_preexisting_event_history(scenarios) -> None:
    prefix_candles = scenarios["downtrend"]
    full_candles = append_candle(
        prefix_candles,
        open_price="10",
        high="17",
        low="9.5",
        close="16",
    )
    config = break_config(StructureBreakBasis.CLOSE)

    prefix = analyze_market_structure(prefix_candles, Timeframe.ONE_MINUTE, config)
    full = analyze_market_structure(full_candles, Timeframe.ONE_MINUTE, config)

    visible_in_full = [
        event for event in full.structure_events if event.confirmed_at <= prefix.data_cutoff_at
    ]
    assert prefix.structure_events == visible_in_full


def test_each_structure_level_break_is_emitted_at_most_once(scenarios) -> None:
    candles = append_candle(
        scenarios["uptrend"],
        open_price="16",
        high="18",
        low="15",
        close="17",
    )
    candles = append_candle(
        candles,
        open_price="17",
        high="19",
        low="16",
        close="18",
    )

    result = analyze_market_structure(
        candles,
        Timeframe.ONE_MINUTE,
        break_config(StructureBreakBasis.CLOSE),
    )
    broken_ids = [event.broken_structure_id for event in result.structure_events]

    assert len(broken_ids) == len(set(broken_ids))


def test_break_buffer_uses_strict_beyond_comparison(scenarios) -> None:
    exact_boundary = append_candle(
        scenarios["uptrend"],
        open_price="16",
        high="18",
        low="15",
        close="17",
    )
    beyond_boundary = append_candle(
        scenarios["uptrend"],
        open_price="16",
        high="18",
        low="15",
        close="17.5",
    )
    config = break_config(StructureBreakBasis.CLOSE).model_copy(
        update={"structure_break_buffer_ticks": 2}
    )

    exact_result = analyze_market_structure(exact_boundary, Timeframe.ONE_MINUTE, config)
    beyond_result = analyze_market_structure(beyond_boundary, Timeframe.ONE_MINUTE, config)
    exact_events = [
        event
        for event in exact_result.structure_events
        if event.timestamp == exact_boundary[-1].timestamp
    ]
    beyond_events = [
        event
        for event in beyond_result.structure_events
        if event.timestamp == beyond_boundary[-1].timestamp
    ]

    assert exact_events == []
    assert len(beyond_events) == 1
