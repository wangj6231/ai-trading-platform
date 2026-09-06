import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from app.engines.structure import MarketStructureInputError, analyze_market_structure
from app.schemas.candle import Candle
from app.schemas.structure import (
    CandidateResolution,
    MarketStructureConfig,
    SwingKind,
    StructureBreakBasis,
    SwingTiePolicy,
    TrendState,
    ZoneKind,
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


def structure_config(
    tie_policy: SwingTiePolicy = SwingTiePolicy.STRICT,
    *,
    trend_points: int = 3,
    right_bars: int = 1,
    break_basis: StructureBreakBasis = StructureBreakBasis.CLOSE,
) -> MarketStructureConfig:
    return MarketStructureConfig(
        tick_size=Decimal("0.5"),
        swing_left_bars=1,
        swing_right_bars=right_bars,
        swing_tie_policy=tie_policy,
        trend_points_per_side=trend_points,
        structure_equality_tolerance_ticks=0,
        structure_break_basis=break_basis,
        structure_break_buffer_ticks=0,
        zone_merge_tolerance_ticks=0,
        zone_padding_ticks=1,
    )


def confirmed_prices(result, kind: SwingKind) -> list[Decimal]:
    return [swing.price for swing in result.confirmed_swings if swing.kind is kind]


def make_plateau_candles(highs: list[str], lows: list[str]) -> list[Candle]:
    start = datetime(2025, 3, 1, tzinfo=UTC)
    candles: list[Candle] = []
    for index, (high, low) in enumerate(zip(highs, lows, strict=True)):
        high_value = Decimal(high)
        low_value = Decimal(low)
        candles.append(
            Candle(
                timestamp=start + timedelta(minutes=index),
                open=low_value,
                high=high_value,
                low=low_value,
                close=low_value,
                volume=Decimal("1"),
            )
        )
    return candles


def test_candidate_is_not_confirmed_before_right_candle_closes(scenarios) -> None:
    prefix = analyze_market_structure(
        scenarios["uptrend"][:2],
        Timeframe.ONE_MINUTE,
        structure_config(),
    )

    high_candidate = next(candidate for candidate in prefix.candidate_swings if candidate.kind is SwingKind.HIGH)
    assert high_candidate.resolution is CandidateResolution.PENDING
    assert high_candidate.candidate_at == datetime(2025, 2, 1, 0, 2, tzinfo=UTC)
    assert high_candidate.resolved_at is None
    assert prefix.confirmed_swings == []
    assert prefix.support_candidates == []
    assert prefix.resistance_candidates == []

    resolved = analyze_market_structure(
        scenarios["uptrend"][:3],
        Timeframe.ONE_MINUTE,
        structure_config(),
    )
    confirmed_high = next(swing for swing in resolved.confirmed_swings if swing.kind is SwingKind.HIGH)
    assert confirmed_high.pivot_timestamp == datetime(2025, 2, 1, 0, 1, tzinfo=UTC)
    assert confirmed_high.confirmed_at == datetime(2025, 2, 1, 0, 3, tzinfo=UTC)


def test_confirmation_waits_for_configured_n_right_candles() -> None:
    candles = make_plateau_candles(["10", "12", "11", "10"], ["8", "9", "8.5", "8"])
    config = structure_config(trend_points=2, right_bars=2)

    pending = analyze_market_structure(candles[:3], Timeframe.ONE_MINUTE, config)
    high_candidate = next(candidate for candidate in pending.candidate_swings if candidate.kind is SwingKind.HIGH)
    assert high_candidate.observed_right_bars == 1
    assert high_candidate.required_right_bars == 2
    assert high_candidate.resolution is CandidateResolution.PENDING
    assert pending.confirmed_swings == []

    confirmed = analyze_market_structure(candles, Timeframe.ONE_MINUTE, config)
    high = next(swing for swing in confirmed.confirmed_swings if swing.kind is SwingKind.HIGH)
    assert high.pivot_index == 1
    assert high.confirmed_at == datetime(2025, 3, 1, 0, 4, tzinfo=UTC)
    assert high.right_evidence_timestamps == (
        datetime(2025, 3, 1, 0, 2, tzinfo=UTC),
        datetime(2025, 3, 1, 0, 3, tzinfo=UTC),
    )


def test_uptrend_has_higher_confirmed_highs_and_lows(scenarios) -> None:
    result = analyze_market_structure(scenarios["uptrend"], Timeframe.ONE_MINUTE, structure_config())

    assert confirmed_prices(result, SwingKind.HIGH) == [Decimal("12"), Decimal("14"), Decimal("16")]
    assert confirmed_prices(result, SwingKind.LOW) == [Decimal("8.5"), Decimal("9.5"), Decimal("10.5")]
    assert result.trend_state is TrendState.BULLISH


def test_downtrend_has_lower_confirmed_highs_and_lows(scenarios) -> None:
    result = analyze_market_structure(scenarios["downtrend"], Timeframe.ONE_MINUTE, structure_config())

    assert confirmed_prices(result, SwingKind.HIGH) == [Decimal("17.5"), Decimal("16.5"), Decimal("15.5")]
    assert confirmed_prices(result, SwingKind.LOW) == [Decimal("13"), Decimal("11"), Decimal("9")]
    assert result.trend_state is TrendState.BEARISH


def test_range_groups_equal_highs_and_lows_into_metadata_zones(scenarios) -> None:
    result = analyze_market_structure(scenarios["range"], Timeframe.ONE_MINUTE, structure_config())

    assert result.trend_state is TrendState.RANGE
    assert len(result.resistance_candidates) == 1
    resistance = result.resistance_candidates[0]
    assert resistance.kind is ZoneKind.RESISTANCE
    assert resistance.lower_bound == Decimal("11.5")
    assert resistance.upper_bound == Decimal("12.5")
    assert resistance.touch_count == 3
    assert len(resistance.source_swing_ids) == 3
    assert resistance.updated_at > resistance.created_at

    assert len(result.support_candidates) == 1
    support = result.support_candidates[0]
    assert support.kind is ZoneKind.SUPPORT
    assert support.lower_bound == Decimal("7.5")
    assert support.upper_bound == Decimal("8.5")
    assert support.touch_count == 3
    assert len(support.source_pivot_timestamps) == 3


@pytest.mark.parametrize(
    ("policy", "expected_index"),
    [
        (SwingTiePolicy.STRICT, None),
        (SwingTiePolicy.EARLIEST, 1),
        (SwingTiePolicy.LATEST, 2),
    ],
)
def test_equal_highs_follow_configured_tie_policy(policy, expected_index) -> None:
    candles = make_plateau_candles(["10", "12", "12", "10"], ["8", "9", "9", "8"])
    result = analyze_market_structure(candles, Timeframe.ONE_MINUTE, structure_config(policy, trend_points=2))
    high_indices = [swing.pivot_index for swing in result.confirmed_swings if swing.kind is SwingKind.HIGH]

    assert high_indices == ([] if expected_index is None else [expected_index])


@pytest.mark.parametrize(
    ("policy", "expected_index"),
    [
        (SwingTiePolicy.STRICT, None),
        (SwingTiePolicy.EARLIEST, 1),
        (SwingTiePolicy.LATEST, 2),
    ],
)
def test_equal_lows_follow_configured_tie_policy(policy, expected_index) -> None:
    candles = make_plateau_candles(["12", "11", "11", "12"], ["10", "8", "8", "10"])
    result = analyze_market_structure(candles, Timeframe.ONE_MINUTE, structure_config(policy, trend_points=2))
    low_indices = [swing.pivot_index for swing in result.confirmed_swings if swing.kind is SwingKind.LOW]

    assert low_indices == ([] if expected_index is None else [expected_index])


def test_noisy_market_remains_range_with_traceable_zones(scenarios) -> None:
    result = analyze_market_structure(scenarios["noisy"], Timeframe.ONE_MINUTE, structure_config())

    assert result.trend_state is TrendState.RANGE
    assert len(result.confirmed_swings) > 4
    all_zone_ids = [zone.zone_id for zone in result.support_candidates + result.resistance_candidates]
    assert len(all_zone_ids) == len(set(all_zone_ids))
    assert all(zone.source_swing_ids for zone in result.support_candidates + result.resistance_candidates)


def test_future_candles_do_not_change_already_confirmed_swings(scenarios) -> None:
    prefix = analyze_market_structure(scenarios["uptrend"][:6], Timeframe.ONE_MINUTE, structure_config())
    full = analyze_market_structure(scenarios["uptrend"], Timeframe.ONE_MINUTE, structure_config())

    visible_in_full = [
        swing for swing in full.confirmed_swings if swing.confirmed_at <= prefix.data_cutoff_at
    ]
    assert prefix.confirmed_swings == visible_in_full


def test_timeframe_gap_is_rejected(scenarios) -> None:
    candles = [scenarios["range"][0], scenarios["range"][2]]

    with pytest.raises(MarketStructureInputError, match="timeframe gap"):
        analyze_market_structure(candles, Timeframe.ONE_MINUTE, structure_config())


def test_price_not_aligned_to_tick_size_is_rejected(scenarios) -> None:
    candles = list(scenarios["range"][:3])
    candles[1] = candles[1].model_copy(update={"high": Decimal("12.1")})

    with pytest.raises(MarketStructureInputError, match="not aligned to tick_size"):
        analyze_market_structure(candles, Timeframe.ONE_MINUTE, structure_config())
