from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.engines.smc import analyze_displacement
from app.schemas.candle import Candle
from app.schemas.displacement import (
    DisplacementCandidateStatus,
    DisplacementConfig,
    DisplacementDirection,
    DisplacementRejectionCode,
)
from app.schemas.fvg import (
    GapDirection,
    GapLifecycleState,
    GapZone,
    GapZoneStatus,
    GapZoneType,
)
from app.schemas.structure import (
    StructureBreakBasis,
    StructureBreakEvent,
    StructureDirection,
    StructureEventType,
    TrendState,
)
from app.schemas.types import Timeframe


START = datetime(2025, 7, 1, tzinfo=UTC)


def bar(index: int, open_: str, high: str, low: str, close: str) -> Candle:
    return Candle(
        timestamp=START + timedelta(minutes=index),
        open=Decimal(open_),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal("1"),
    )


def baseline() -> list[Candle]:
    return [
        bar(0, "10", "11", "9", "10"),
        bar(1, "10", "11", "9", "10"),
        bar(2, "10", "11", "9", "10"),
    ]


def structure_event(
    direction: StructureDirection,
    *,
    index: int = 3,
    event_type: StructureEventType = StructureEventType.BOS,
) -> StructureBreakEvent:
    return StructureBreakEvent(
        type=event_type,
        direction=direction,
        price=Decimal("12" if direction is StructureDirection.BULLISH else "8"),
        timestamp=START + timedelta(minutes=index),
        broken_structure_id=f"broken-{direction.value}-{index}",
        confirmation_type=StructureBreakBasis.CLOSE,
        confirmed_at=START + timedelta(minutes=index + 1),
        display_alias=None,
        trend_before_break=(
            TrendState.BULLISH
            if direction is StructureDirection.BULLISH
            else TrendState.BEARISH
        ),
    )


def config(
    *,
    period: int = 2,
    max_bars: int = 1,
    net_ratio: str = "1",
    body_ratio: str = "1",
    efficiency: str = "1",
    adverse_ratio: str = "0",
    require_fvg: bool = False,
) -> DisplacementConfig:
    return DisplacementConfig(
        tick_size=Decimal("0.5"),
        displacement_atr_period=period,
        displacement_max_bars=max_bars,
        displacement_net_atr_ratio=Decimal(net_ratio),
        displacement_body_atr_ratio=Decimal(body_ratio),
        displacement_min_body_efficiency=Decimal(efficiency),
        displacement_max_adverse_atr_ratio=Decimal(adverse_ratio),
        displacement_require_fvg=require_fvg,
    )


def fvg(
    zone_id: str,
    direction: GapDirection,
    source_indices: tuple[int, int, int] = (1, 2, 3),
    confirmed_minute: int = 4,
) -> GapZone:
    confirmed_at = START + timedelta(minutes=confirmed_minute)
    return GapZone(
        zone_id=zone_id,
        type=GapZoneType.FVG,
        direction=direction,
        lower=Decimal("10.5"),
        upper=Decimal("11"),
        created_at=confirmed_at,
        confirmed_at=confirmed_at,
        status=GapZoneStatus.OPEN,
        lifecycle_state=GapLifecycleState.ACTIVE,
        source_candle_timestamps=tuple(
            START + timedelta(minutes=index) for index in source_indices
        ),
        origin_fvg_id=None,
        fill_fraction=Decimal("0"),
        retest_count=0,
        last_updated_at=confirmed_at,
        lifecycle=(),
    )


def test_valid_bullish_displacement_returns_exact_strength_metrics() -> None:
    candles = baseline() + [bar(3, "10", "12", "10", "12")]
    result = analyze_displacement(
        candles,
        Timeframe.ONE_MINUTE,
        [structure_event(StructureDirection.BULLISH)],
        config(),
    )

    leg = result.legs[0]
    metrics = leg.strength_metrics
    assert leg.direction is DisplacementDirection.BULLISH
    assert leg.start_bar_index == leg.end_bar_index == 3
    assert leg.timestamp == START + timedelta(minutes=3)
    assert leg.confirmed_at == START + timedelta(minutes=4)
    assert leg.associated_structure_break.startswith("BOS:bullish:")
    assert leg.associated_fvg == ()
    assert metrics.atr_baseline == Decimal("2")
    assert metrics.net_move == Decimal("2")
    assert metrics.directional_body_sum == Decimal("2")
    assert metrics.opposing_body_sum == Decimal("0")
    assert metrics.total_body_sum == Decimal("2")
    assert metrics.body_efficiency == Decimal("1")
    assert metrics.net_atr_ratio == Decimal("1")
    assert metrics.body_atr_ratio == Decimal("1")
    assert metrics.adverse_price == Decimal("0")
    assert metrics.adverse_atr_ratio == Decimal("0")


def test_valid_bearish_displacement_is_symmetric() -> None:
    candles = baseline() + [bar(3, "10", "10", "8", "8")]
    result = analyze_displacement(
        candles,
        Timeframe.ONE_MINUTE,
        [structure_event(StructureDirection.BEARISH)],
        config(),
    )

    leg = result.legs[0]
    assert leg.direction is DisplacementDirection.BEARISH
    assert leg.strength_metrics.net_move == Decimal("2")
    assert leg.strength_metrics.body_atr_ratio == Decimal("1")


def test_true_range_atr_baseline_uses_only_bars_before_leg_start() -> None:
    candles = [
        bar(0, "10", "11", "9", "10"),
        bar(1, "11", "14", "11", "12"),
        bar(2, "12", "13", "9", "10"),
        bar(3, "10", "14", "10", "14"),
    ]
    result = analyze_displacement(
        candles,
        Timeframe.ONE_MINUTE,
        [structure_event(StructureDirection.BULLISH)],
        config(net_ratio="1", body_ratio="1", adverse_ratio="0"),
    )

    assert result.legs[0].strength_metrics.atr_baseline == Decimal("4")


def test_insufficient_pre_break_atr_history_rejects_candidate() -> None:
    candles = [
        bar(0, "10", "11", "9", "10"),
        bar(1, "10", "12", "10", "12"),
    ]
    result = analyze_displacement(
        candles,
        Timeframe.ONE_MINUTE,
        [structure_event(StructureDirection.BULLISH, index=1)],
        config(period=2),
    )

    evaluation = result.evaluations[0]
    assert evaluation.status is DisplacementCandidateStatus.REJECTED
    assert evaluation.reason_codes == (DisplacementRejectionCode.ATR_UNAVAILABLE,)


@pytest.mark.parametrize(
    ("resolved_config", "event_bar", "expected_reason"),
    [
        (
            config(net_ratio="1", body_ratio="0.25", efficiency="1"),
            bar(3, "10", "11", "10", "11"),
            DisplacementRejectionCode.NET_MOVE_BELOW_THRESHOLD,
        ),
        (
            config(net_ratio="0.25", body_ratio="1", efficiency="1"),
            bar(3, "10", "11", "10", "11"),
            DisplacementRejectionCode.BODY_MOVE_BELOW_THRESHOLD,
        ),
        (
            config(adverse_ratio="1"),
            bar(3, "10", "12", "7", "12"),
            DisplacementRejectionCode.ADVERSE_MOVE_ABOVE_THRESHOLD,
        ),
    ],
)
def test_each_quantitative_threshold_has_a_reason_code(
    resolved_config: DisplacementConfig,
    event_bar: Candle,
    expected_reason: DisplacementRejectionCode,
) -> None:
    result = analyze_displacement(
        baseline() + [event_bar],
        Timeframe.ONE_MINUTE,
        [structure_event(StructureDirection.BULLISH)],
        resolved_config,
    )

    evaluation = result.evaluations[0]
    assert evaluation.status is DisplacementCandidateStatus.EXPIRED
    assert expected_reason in evaluation.reason_codes


def test_efficiency_threshold_uses_directional_share_of_all_bodies() -> None:
    candles = baseline() + [
        bar(3, "10", "12", "10", "12"),
        bar(4, "14", "14", "12", "13"),
    ]
    result = analyze_displacement(
        candles,
        Timeframe.ONE_MINUTE,
        [structure_event(StructureDirection.BULLISH)],
        config(
            max_bars=2,
            net_ratio="1.5",
            body_ratio="1",
            efficiency="0.75",
            adverse_ratio="0",
        ),
    )

    evaluation = result.evaluations[0]
    assert evaluation.status is DisplacementCandidateStatus.EXPIRED
    assert evaluation.strength_metrics.body_efficiency == Decimal(
        "0.6666666666666666666666666666666667"
    )
    assert evaluation.reason_codes == (
        DisplacementRejectionCode.EFFICIENCY_BELOW_THRESHOLD,
    )


def test_gap_only_net_move_does_not_satisfy_body_requirement() -> None:
    candles = baseline() + [
        bar(3, "10", "10", "10", "10"),
        bar(4, "12", "12", "12", "12"),
    ]
    result = analyze_displacement(
        candles,
        Timeframe.ONE_MINUTE,
        [structure_event(StructureDirection.BULLISH)],
        config(
            max_bars=2,
            net_ratio="1",
            body_ratio="0.5",
            efficiency="0.5",
            adverse_ratio="0",
        ),
    )

    evaluation = result.evaluations[0]
    assert evaluation.strength_metrics.net_atr_ratio == Decimal("1")
    assert evaluation.strength_metrics.body_atr_ratio == Decimal("0")
    assert DisplacementRejectionCode.BODY_MOVE_BELOW_THRESHOLD in evaluation.reason_codes


def test_candidate_remains_pending_until_full_window_is_available() -> None:
    event = structure_event(StructureDirection.BULLISH)
    prefix_candles = baseline() + [bar(3, "10", "11", "10", "11")]
    prefix = analyze_displacement(
        prefix_candles,
        Timeframe.ONE_MINUTE,
        [event],
        config(max_bars=2, net_ratio="1", body_ratio="1", efficiency="1"),
    )
    completed = analyze_displacement(
        prefix_candles + [bar(4, "11", "12", "11", "12")],
        Timeframe.ONE_MINUTE,
        [event],
        config(max_bars=2, net_ratio="1", body_ratio="1", efficiency="1"),
    )

    assert prefix.legs == []
    assert prefix.evaluations[0].status is DisplacementCandidateStatus.CANDIDATE
    assert completed.legs[0].end_bar_index == 4
    assert completed.legs[0].confirmed_at == START + timedelta(minutes=5)


def test_earliest_qualifying_leg_is_immutable_when_later_bars_arrive() -> None:
    event = structure_event(StructureDirection.BULLISH)
    first = baseline() + [bar(3, "10", "12", "10", "12")]
    initial = analyze_displacement(
        first,
        Timeframe.ONE_MINUTE,
        [event],
        config(max_bars=3),
    )
    extended = analyze_displacement(
        first + [bar(4, "12", "15", "11", "15"), bar(5, "15", "18", "14", "18")],
        Timeframe.ONE_MINUTE,
        [event],
        config(max_bars=3),
    )

    assert initial.legs[0] == extended.legs[0]
    assert extended.legs[0].end_bar_index == 3


def test_required_matching_fvg_is_linked_to_leg() -> None:
    candles = baseline() + [bar(3, "10", "12", "10", "12")]
    matching = fvg("bullish-fvg", GapDirection.BULLISH)
    result = analyze_displacement(
        candles,
        Timeframe.ONE_MINUTE,
        [structure_event(StructureDirection.BULLISH)],
        config(require_fvg=True),
        fvg_zones=[matching],
    )

    assert result.legs[0].associated_fvg == ("bullish-fvg",)


def test_missing_wrong_direction_and_out_of_window_fvgs_do_not_qualify() -> None:
    candles = baseline() + [bar(3, "10", "12", "10", "12")]
    wrong_direction = fvg("bearish-fvg", GapDirection.BEARISH)
    outside_window = fvg(
        "outside-fvg", GapDirection.BULLISH, source_indices=(0, 1, 2)
    )
    result = analyze_displacement(
        candles,
        Timeframe.ONE_MINUTE,
        [structure_event(StructureDirection.BULLISH)],
        config(require_fvg=True),
        fvg_zones=[wrong_direction, outside_window],
    )

    assert result.legs == []
    assert result.evaluations[0].status is DisplacementCandidateStatus.EXPIRED
    assert result.evaluations[0].reason_codes == (
        DisplacementRejectionCode.FVG_REQUIRED,
    )


def test_break_event_is_not_substituted_for_approved_bos_or_mss() -> None:
    candles = baseline() + [bar(3, "10", "12", "10", "12")]
    result = analyze_displacement(
        candles,
        Timeframe.ONE_MINUTE,
        [
            structure_event(
                StructureDirection.BULLISH,
                event_type=StructureEventType.BREAK,
            )
        ],
        config(),
    )

    assert result.legs == []
    assert result.evaluations[0].reason_codes == (
        DisplacementRejectionCode.UNSUPPORTED_STRUCTURE_EVENT,
    )
