import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from app.engines.indicators import calculate_atr
from app.engines.smc import FVGInputError, analyze_fvg
from app.schemas.candle import Candle
from app.schemas.fvg import (
    FVGConfig,
    FVGFillBasis,
    GapDirection,
    GapLifecycleEventType,
    GapLifecycleState,
    GapZoneStatus,
    GapZoneType,
)
from app.schemas.indicator import ATRConfig
from app.schemas.types import Timeframe


FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "fvg_scenarios.json"


@pytest.fixture(scope="module")
def scenarios() -> dict[str, list[Candle]]:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return {
        name: [Candle.model_validate(candle) for candle in candles]
        for name, candles in payload.items()
    }


def fvg_config(
    *,
    fill_basis: FVGFillBasis = FVGFillBasis.WICK,
    min_gap_ticks: int = 1,
    atr_ratio: str = "0",
    require_middle_direction: bool = True,
    ifvg_enabled: bool = True,
    max_age: int = 100,
    max_retests: int = 100,
) -> FVGConfig:
    return FVGConfig(
        tick_size=Decimal("1"),
        fvg_min_gap_ticks=min_gap_ticks,
        fvg_min_gap_atr_ratio=Decimal(atr_ratio),
        fvg_require_middle_candle_direction=require_middle_direction,
        fvg_fill_basis=fill_basis,
        fvg_full_fill_fraction=Decimal("1"),
        fvg_max_age_bars=max_age,
        fvg_max_retests=max_retests,
        ifvg_enabled=ifvg_enabled,
        ifvg_inversion_buffer_ticks=0,
    )


def original_zone(result, direction: GapDirection):
    return next(
        zone
        for zone in result.zones
        if zone.type is GapZoneType.FVG
        and zone.direction is direction
        and zone.source_candle_timestamps[0] == datetime(2025, 4, 1, tzinfo=UTC)
    )


def test_bullish_fvg_forms_only_after_third_candle_closes(scenarios) -> None:
    config = fvg_config()

    prefix = analyze_fvg(scenarios["bullish"][:2], Timeframe.ONE_MINUTE, config)
    formed = analyze_fvg(scenarios["bullish"][:3], Timeframe.ONE_MINUTE, config)

    assert prefix.zones == []
    zone = original_zone(formed, GapDirection.BULLISH)
    assert zone.type is GapZoneType.FVG
    assert zone.direction is GapDirection.BULLISH
    assert zone.lower == Decimal("101")
    assert zone.upper == Decimal("103")
    assert zone.created_at == datetime(2025, 4, 1, 0, 3, tzinfo=UTC)
    assert zone.status is GapZoneStatus.OPEN
    assert zone.lifecycle_state is GapLifecycleState.ACTIVE
    assert zone.fill_fraction == 0
    assert zone.lifecycle[0].event_type is GapLifecycleEventType.FVG_CREATED


def test_bearish_fvg_has_symmetric_bounds(scenarios) -> None:
    result = analyze_fvg(scenarios["bearish"][:3], Timeframe.ONE_MINUTE, fvg_config())

    zone = original_zone(result, GapDirection.BEARISH)
    assert zone.lower == Decimal("103")
    assert zone.upper == Decimal("105")
    assert zone.status is GapZoneStatus.OPEN


def test_partial_mitigation_updates_zone_without_deleting_it(scenarios) -> None:
    result = analyze_fvg(scenarios["bullish"][:4], Timeframe.ONE_MINUTE, fvg_config())

    zone = original_zone(result, GapDirection.BULLISH)
    assert zone.status is GapZoneStatus.PARTIAL
    assert zone.lifecycle_state is GapLifecycleState.PARTIALLY_FILLED
    assert zone.fill_fraction == Decimal("0.5")
    assert zone.retest_count == 1
    assert [event.event_type for event in zone.lifecycle] == [
        GapLifecycleEventType.FVG_CREATED,
        GapLifecycleEventType.FVG_RETEST,
    ]


def test_full_mitigation_is_terminal_and_historical_zone_is_retained(scenarios) -> None:
    result = analyze_fvg(scenarios["bullish"], Timeframe.ONE_MINUTE, fvg_config())

    zone = original_zone(result, GapDirection.BULLISH)
    assert zone in result.zones
    assert zone.status is GapZoneStatus.FILLED
    assert zone.lifecycle_state is GapLifecycleState.FILLED
    assert zone.fill_fraction == Decimal("1")
    assert zone.retest_count == 2
    assert zone.lifecycle[-1].event_type is GapLifecycleEventType.FVG_FILLED


def test_fill_fraction_is_monotonic(scenarios) -> None:
    partial = analyze_fvg(scenarios["bullish"][:4], Timeframe.ONE_MINUTE, fvg_config())
    full = analyze_fvg(scenarios["bullish"], Timeframe.ONE_MINUTE, fvg_config())

    assert original_zone(partial, GapDirection.BULLISH).fill_fraction == Decimal("0.5")
    assert original_zone(full, GapDirection.BULLISH).fill_fraction == Decimal("1")


def test_wick_and_close_fill_modes_differ_on_wick_only_touch(scenarios) -> None:
    candles = scenarios["bullish"][:4]
    wick = analyze_fvg(candles, Timeframe.ONE_MINUTE, fvg_config(fill_basis=FVGFillBasis.WICK))
    close = analyze_fvg(candles, Timeframe.ONE_MINUTE, fvg_config(fill_basis=FVGFillBasis.CLOSE))

    assert original_zone(wick, GapDirection.BULLISH).fill_fraction == Decimal("0.5")
    assert original_zone(close, GapDirection.BULLISH).fill_fraction == Decimal("0")


def test_bullish_fvg_inverts_to_bearish_ifvg(scenarios) -> None:
    result = analyze_fvg(
        scenarios["bullish_inversion"][:4],
        Timeframe.ONE_MINUTE,
        fvg_config(),
    )

    fvg = original_zone(result, GapDirection.BULLISH)
    ifvg = next(zone for zone in result.zones if zone.type is GapZoneType.IFVG)
    assert fvg.status is GapZoneStatus.INVALIDATED
    assert fvg.lifecycle_state is GapLifecycleState.INVERTED
    assert fvg.lifecycle[-1].event_type is GapLifecycleEventType.FVG_INVERTED
    assert ifvg.direction is GapDirection.BEARISH
    assert (ifvg.lower, ifvg.upper) == (fvg.lower, fvg.upper)
    assert ifvg.origin_fvg_id == fvg.zone_id
    assert ifvg.status is GapZoneStatus.OPEN
    assert ifvg.fill_fraction == 0


def test_ifvg_is_first_retestable_on_bar_after_inversion(scenarios) -> None:
    inversion = analyze_fvg(
        scenarios["bullish_inversion"][:4],
        Timeframe.ONE_MINUTE,
        fvg_config(),
    )
    next_bar = analyze_fvg(
        scenarios["bullish_inversion"][:5],
        Timeframe.ONE_MINUTE,
        fvg_config(),
    )

    at_inversion = next(zone for zone in inversion.zones if zone.type is GapZoneType.IFVG)
    after_inversion = next(
        zone
        for zone in next_bar.zones
        if zone.type is GapZoneType.IFVG and zone.origin_fvg_id == at_inversion.origin_fvg_id
    )
    assert at_inversion.fill_fraction == 0
    assert at_inversion.retest_count == 0
    assert after_inversion.status is GapZoneStatus.PARTIAL
    assert after_inversion.fill_fraction == Decimal("0.5")
    assert after_inversion.retest_count == 1


def test_ifvg_invalidation_is_terminal_without_recursive_ifvg(scenarios) -> None:
    result = analyze_fvg(
        scenarios["bullish_inversion"],
        Timeframe.ONE_MINUTE,
        fvg_config(),
    )

    origin = original_zone(result, GapDirection.BULLISH)
    ifvg = next(
        zone
        for zone in result.zones
        if zone.type is GapZoneType.IFVG and zone.origin_fvg_id == origin.zone_id
    )
    assert ifvg.status is GapZoneStatus.INVALIDATED
    assert ifvg.lifecycle_state is GapLifecycleState.INVALIDATED
    assert ifvg.lifecycle[-1].event_type is GapLifecycleEventType.IFVG_INVALIDATED
    assert len([zone for zone in result.zones if zone.origin_fvg_id == ifvg.zone_id]) == 0


def test_ifvg_can_be_fully_mitigated_and_remains_in_history(scenarios) -> None:
    candles = list(scenarios["bullish_inversion"][:5])
    candles.append(
        Candle(
            timestamp=candles[-1].timestamp + timedelta(minutes=1),
            open=Decimal("100"),
            high=Decimal("103"),
            low=Decimal("99"),
            close=Decimal("102"),
            volume=Decimal("1"),
        )
    )

    result = analyze_fvg(candles, Timeframe.ONE_MINUTE, fvg_config())

    origin = original_zone(result, GapDirection.BULLISH)
    ifvg = next(
        zone
        for zone in result.zones
        if zone.type is GapZoneType.IFVG and zone.origin_fvg_id == origin.zone_id
    )
    assert ifvg in result.zones
    assert ifvg.status is GapZoneStatus.FILLED
    assert ifvg.lifecycle_state is GapLifecycleState.FILLED
    assert ifvg.fill_fraction == Decimal("1")
    assert ifvg.lifecycle[-1].event_type is GapLifecycleEventType.IFVG_FILLED


def test_disabled_ifvg_uses_ordinary_full_fill(scenarios) -> None:
    result = analyze_fvg(
        scenarios["bullish_inversion"][:4],
        Timeframe.ONE_MINUTE,
        fvg_config(ifvg_enabled=False),
    )

    fvg = original_zone(result, GapDirection.BULLISH)
    assert fvg.status is GapZoneStatus.FILLED
    assert fvg.lifecycle_state is GapLifecycleState.FILLED
    assert all(zone.type is GapZoneType.FVG for zone in result.zones)


def test_tick_threshold_rejects_small_gap(scenarios) -> None:
    result = analyze_fvg(
        scenarios["bullish"][:3],
        Timeframe.ONE_MINUTE,
        fvg_config(min_gap_ticks=3),
    )
    assert result.zones == []


def test_atr_threshold_uses_value_available_before_third_bar(scenarios) -> None:
    candles = scenarios["bullish"][:3]
    atr = calculate_atr(candles, ATRConfig(period=1, smoothing="WILDER"))
    result = analyze_fvg(
        candles,
        Timeframe.ONE_MINUTE,
        fvg_config(atr_ratio="0.5"),
        atr_result=atr,
    )

    assert result.zones == []


def test_missing_atr_is_recorded_when_ratio_is_positive(scenarios) -> None:
    result = analyze_fvg(
        scenarios["bullish"][:3],
        Timeframe.ONE_MINUTE,
        fvg_config(atr_ratio="0.5"),
    )

    assert result.zones == []
    assert result.rejections[-1].code == "FVG_ATR_UNAVAILABLE"


def test_middle_candle_direction_toggle(scenarios) -> None:
    candles = list(scenarios["bullish"][:3])
    candles[1] = candles[1].model_copy(
        update={"open": Decimal("104"), "close": Decimal("100")}
    )

    required = analyze_fvg(
        candles,
        Timeframe.ONE_MINUTE,
        fvg_config(require_middle_direction=True),
    )
    optional = analyze_fvg(
        candles,
        Timeframe.ONE_MINUTE,
        fvg_config(require_middle_direction=False),
    )

    assert required.zones == []
    assert len(optional.zones) == 1


def test_expired_zone_remains_in_history(scenarios) -> None:
    candles = scenarios["bullish"][:3]
    for _ in range(2):
        candles = candles + [
            Candle(
                timestamp=candles[-1].timestamp + timedelta(minutes=1),
                open=Decimal("105"),
                high=Decimal("106"),
                low=Decimal("104"),
                close=Decimal("105"),
                volume=Decimal("1"),
            )
        ]

    result = analyze_fvg(
        candles,
        Timeframe.ONE_MINUTE,
        fvg_config(max_age=1),
    )

    zone = original_zone(result, GapDirection.BULLISH)
    assert zone in result.zones
    assert zone.status is GapZoneStatus.INVALIDATED
    assert zone.lifecycle_state is GapLifecycleState.EXPIRED
    assert zone.lifecycle[-1].event_type is GapLifecycleEventType.FVG_EXPIRED


def test_future_candles_do_not_rewrite_prior_lifecycle(scenarios) -> None:
    prefix = analyze_fvg(
        scenarios["bullish"][:4],
        Timeframe.ONE_MINUTE,
        fvg_config(),
    )
    full = analyze_fvg(
        scenarios["bullish"],
        Timeframe.ONE_MINUTE,
        fvg_config(),
    )

    prefix_zone = original_zone(prefix, GapDirection.BULLISH)
    full_zone = original_zone(full, GapDirection.BULLISH)
    visible_events = tuple(
        event
        for event in full_zone.lifecycle
        if event.occurred_at <= prefix.data_cutoff_at
    )
    assert prefix_zone.lifecycle == visible_events
    assert prefix_zone.fill_fraction == visible_events[-1].fill_fraction


def test_timeframe_gap_is_rejected(scenarios) -> None:
    candles = [scenarios["bullish"][0], scenarios["bullish"][2]]

    with pytest.raises(FVGInputError, match="timeframe gap"):
        analyze_fvg(candles, Timeframe.ONE_MINUTE, fvg_config())
