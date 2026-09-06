from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.engines.structure import analyze_multi_timeframe, resample_closed_candles
from app.schemas.candle import Candle
from app.schemas.multi_timeframe import (
    MTFAlignmentStatus,
    MTFConfig,
    MTFDirection,
    MTFEligibility,
    MTFGapPolicy,
    MTFPriceArray,
    MTFPriceArrayProbe,
    MTFReasonCode,
    MTFRole,
    MTFStructureStateEvent,
)
from app.schemas.signal import EntryZone
from app.schemas.structure import ConfirmedSwing, SwingKind, TrendState
from app.schemas.types import Timeframe


START = datetime(2025, 9, 1, tzinfo=UTC)
HIERARCHY = (
    Timeframe.ONE_HOUR,
    Timeframe.FIFTEEN_MINUTES,
    Timeframe.FIVE_MINUTES,
    Timeframe.THREE_MINUTES,
    Timeframe.ONE_MINUTE,
)


def minute_candles(count: int) -> list[Candle]:
    return [
        Candle(
            timestamp=START + timedelta(minutes=index),
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100"),
            volume=Decimal("1"),
        )
        for index in range(count)
    ]


def mtf_config(
    *,
    minimum: int = 3,
    veto: tuple[Timeframe, ...] = (
        Timeframe.ONE_HOUR,
        Timeframe.FIFTEEN_MINUTES,
    ),
    require_signal: bool = True,
    max_ages: dict[Timeframe, int] | None = None,
    price_gate: bool = False,
    probe: MTFPriceArrayProbe = MTFPriceArrayProbe.MIDPOINT,
) -> MTFConfig:
    return MTFConfig(
        mtf_source_timeframe=Timeframe.ONE_MINUTE,
        mtf_target_timeframes=HIERARCHY,
        mtf_gap_policy=MTFGapPolicy.REQUIRE_CONTIGUOUS,
        mtf_session_calendar_id=None,
        mtf_required_timeframes=(
            Timeframe.ONE_HOUR,
            Timeframe.FIFTEEN_MINUTES,
            Timeframe.FIVE_MINUTES,
            Timeframe.THREE_MINUTES,
        ),
        mtf_min_aligned_timeframes=minimum,
        mtf_veto_timeframes=veto,
        mtf_signal_timeframe=Timeframe.THREE_MINUTES,
        mtf_require_signal_timeframe_alignment=require_signal,
        mtf_state_max_age_bars=max_ages
        or {timeframe: 100 for timeframe in HIERARCHY},
        mtf_require_price_array_gate=price_gate,
        mtf_dealing_range_timeframe=Timeframe.FIFTEEN_MINUTES,
        mtf_dealing_range_max_span_bars=3,
        mtf_price_array_probe=probe,
    )


def latest_source_timestamp(timeframe: Timeframe, decision_minute: int = 60) -> datetime:
    duration_minutes = {
        Timeframe.ONE_HOUR: 60,
        Timeframe.FIFTEEN_MINUTES: 15,
        Timeframe.FIVE_MINUTES: 5,
        Timeframe.THREE_MINUTES: 3,
        Timeframe.ONE_MINUTE: 1,
    }[timeframe]
    return START + timedelta(minutes=decision_minute - duration_minutes)


def state_event(
    timeframe: Timeframe,
    state: TrendState,
    *,
    source_minute: int | None = None,
    confirmed_minute: int = 60,
    suffix: str = "latest",
) -> MTFStructureStateEvent:
    source_timestamp = (
        START + timedelta(minutes=source_minute)
        if source_minute is not None
        else latest_source_timestamp(timeframe, confirmed_minute)
    )
    return MTFStructureStateEvent(
        event_id=f"{timeframe.value}-{state.value}-{suffix}",
        timeframe=timeframe,
        state=state,
        source_bar_timestamp=source_timestamp,
        source_bar_close_time=START + timedelta(minutes=confirmed_minute),
        confirmed_at=START + timedelta(minutes=confirmed_minute),
    )


def aligned_states(state: TrendState = TrendState.BULLISH) -> list[MTFStructureStateEvent]:
    return [state_event(timeframe, state) for timeframe in HIERARCHY]


def test_exact_one_minute_to_three_minute_aggregation() -> None:
    candles = [
        Candle(
            timestamp=START,
            open=Decimal("10"),
            high=Decimal("12"),
            low=Decimal("9"),
            close=Decimal("11"),
            volume=Decimal("1"),
        ),
        Candle(
            timestamp=START + timedelta(minutes=1),
            open=Decimal("11"),
            high=Decimal("13"),
            low=Decimal("10"),
            close=Decimal("12"),
            volume=Decimal("2"),
        ),
        Candle(
            timestamp=START + timedelta(minutes=2),
            open=Decimal("12"),
            high=Decimal("14"),
            low=Decimal("11"),
            close=Decimal("13"),
            volume=Decimal("3"),
        ),
    ]
    result = resample_closed_candles(
        candles,
        START + timedelta(minutes=3),
        mtf_config(),
    )

    derived = result.bars["3m"][0]
    assert (derived.open, derived.high, derived.low, derived.close) == (
        Decimal("10"),
        Decimal("14"),
        Decimal("9"),
        Decimal("13"),
    )
    assert derived.volume == Decimal("6")
    assert derived.close_time == START + timedelta(minutes=3)
    assert derived.source_bar_timestamps == tuple(candle.timestamp for candle in candles)


def test_hour_bucket_is_withheld_until_utc_bucket_end() -> None:
    candles = minute_candles(60)
    before_close = resample_closed_candles(
        candles,
        START + timedelta(minutes=59, seconds=59),
        mtf_config(),
    )
    at_close = resample_closed_candles(
        candles,
        START + timedelta(hours=1),
        mtf_config(),
    )

    assert before_close.bars["1h"] == []
    assert len(at_close.bars["1h"]) == 1
    assert at_close.bars["1h"][0].close_time == START + timedelta(hours=1)


def test_missing_constituent_rejects_contiguous_bucket() -> None:
    candles = [minute_candles(3)[0], minute_candles(3)[2]]
    result = resample_closed_candles(
        candles,
        START + timedelta(minutes=3),
        mtf_config(),
    )

    assert result.bars["3m"] == []
    assert any(
        issue.code is MTFReasonCode.MTF_INCOMPLETE_BUCKET
        and issue.timeframe is Timeframe.THREE_MINUTES
        for issue in result.issues
    )


def test_historical_incomplete_required_bucket_blocks_later_alignment() -> None:
    candles = minute_candles(120)
    del candles[1]
    states = [
        state_event(timeframe, TrendState.BULLISH, confirmed_minute=120)
        for timeframe in HIERARCHY
    ]

    result = analyze_multi_timeframe(
        candles,
        START + timedelta(hours=2),
        MTFDirection.BULLISH,
        states,
        mtf_config(),
    )

    assert result.trade_allowed is False
    assert result.eligibility is MTFEligibility.NO_TRADE
    assert result.alignment is MTFAlignmentStatus.PARTIALLY_ALIGNED
    assert MTFReasonCode.MTF_INCOMPLETE_BUCKET in result.reason_codes


def test_aligned_long_hierarchy_is_structured_by_role() -> None:
    result = analyze_multi_timeframe(
        minute_candles(60),
        START + timedelta(hours=1),
        MTFDirection.BULLISH,
        aligned_states(),
        mtf_config(),
    )

    assert result.alignment is MTFAlignmentStatus.ALIGNED
    assert result.eligibility is MTFEligibility.LONG_ELIGIBLE
    assert result.trade_allowed is True
    assert result.bullish_count == 4
    assert list(result.timeframes) == ["1h", "15m", "5m", "3m", "1m"]
    assert result.timeframes["1h"].role is MTFRole.MARKET_BIAS
    assert result.timeframes["15m"].role is MTFRole.MARKET_STRUCTURE
    assert result.timeframes["5m"].role is MTFRole.SETUP
    assert result.timeframes["3m"].role is MTFRole.TRIGGER


def test_aligned_short_is_directionally_symmetric() -> None:
    result = analyze_multi_timeframe(
        minute_candles(60),
        START + timedelta(hours=1),
        MTFDirection.BEARISH,
        aligned_states(TrendState.BEARISH),
        mtf_config(),
    )

    assert result.alignment is MTFAlignmentStatus.ALIGNED
    assert result.eligibility is MTFEligibility.SHORT_ELIGIBLE
    assert result.trade_allowed is True


def test_partial_alignment_does_not_become_a_trade() -> None:
    states = [
        state_event(Timeframe.ONE_HOUR, TrendState.BULLISH),
        state_event(Timeframe.FIFTEEN_MINUTES, TrendState.RANGE),
        state_event(Timeframe.FIVE_MINUTES, TrendState.BULLISH),
        state_event(Timeframe.THREE_MINUTES, TrendState.INSUFFICIENT_DATA),
        state_event(Timeframe.ONE_MINUTE, TrendState.BULLISH),
    ]
    result = analyze_multi_timeframe(
        minute_candles(60),
        START + timedelta(hours=1),
        MTFDirection.BULLISH,
        states,
        mtf_config(),
    )

    assert result.alignment is MTFAlignmentStatus.PARTIALLY_ALIGNED
    assert result.eligibility is MTFEligibility.NO_TRADE
    assert result.trade_allowed is False
    assert MTFReasonCode.MTF_NOT_ALIGNED in result.reason_codes


def test_one_hour_veto_blocks_three_lower_bullish_states_without_majority_vote() -> None:
    states = [
        state_event(Timeframe.ONE_HOUR, TrendState.BEARISH),
        state_event(Timeframe.FIFTEEN_MINUTES, TrendState.BULLISH),
        state_event(Timeframe.FIVE_MINUTES, TrendState.BULLISH),
        state_event(Timeframe.THREE_MINUTES, TrendState.BULLISH),
        state_event(Timeframe.ONE_MINUTE, TrendState.BULLISH),
    ]
    result = analyze_multi_timeframe(
        minute_candles(60),
        START + timedelta(hours=1),
        MTFDirection.BULLISH,
        states,
        mtf_config(),
    )

    assert result.bullish_count == 3
    assert result.alignment is MTFAlignmentStatus.CONFLICTING
    assert result.eligibility is MTFEligibility.NO_TRADE
    assert result.trade_allowed is False
    assert result.reason_codes == (MTFReasonCode.MTF_VETO_CONFLICT,)


def test_bidirectional_low_threshold_is_rejected() -> None:
    states = [
        state_event(Timeframe.ONE_HOUR, TrendState.BULLISH),
        state_event(Timeframe.FIFTEEN_MINUTES, TrendState.BEARISH),
        state_event(Timeframe.FIVE_MINUTES, TrendState.RANGE),
        state_event(Timeframe.THREE_MINUTES, TrendState.RANGE),
        state_event(Timeframe.ONE_MINUTE, TrendState.RANGE),
    ]
    result = analyze_multi_timeframe(
        minute_candles(60),
        START + timedelta(hours=1),
        MTFDirection.BULLISH,
        states,
        mtf_config(minimum=1, veto=(), require_signal=False),
    )

    assert result.alignment is MTFAlignmentStatus.CONFLICTING
    assert result.reason_codes == (MTFReasonCode.MTF_BIDIRECTIONAL_ALIGNMENT,)


def test_stale_veto_timeframe_becomes_insufficient_and_cannot_silently_pass() -> None:
    max_ages = {timeframe: 100 for timeframe in HIERARCHY}
    max_ages[Timeframe.ONE_HOUR] = 1
    states = [
        state_event(
            Timeframe.ONE_HOUR,
            TrendState.BULLISH,
            source_minute=0,
            confirmed_minute=60,
            suffix="old",
        ),
        state_event(Timeframe.FIFTEEN_MINUTES, TrendState.BULLISH, confirmed_minute=180),
        state_event(Timeframe.FIVE_MINUTES, TrendState.BULLISH, confirmed_minute=180),
        state_event(Timeframe.THREE_MINUTES, TrendState.BULLISH, confirmed_minute=180),
        state_event(Timeframe.ONE_MINUTE, TrendState.BULLISH, confirmed_minute=180),
    ]
    result = analyze_multi_timeframe(
        minute_candles(180),
        START + timedelta(hours=3),
        MTFDirection.BULLISH,
        states,
        mtf_config(max_ages=max_ages),
    )

    one_hour = result.timeframes["1h"]
    assert one_hour.stale is True
    assert one_hour.state is TrendState.INSUFFICIENT_DATA
    assert one_hour.bars_since_state == 2
    assert result.trade_allowed is False
    assert result.alignment is MTFAlignmentStatus.PARTIALLY_ALIGNED
    assert MTFReasonCode.MTF_STATE_UNAVAILABLE in result.reason_codes


def early_lower_timeframe_states() -> list[MTFStructureStateEvent]:
    return [
        state_event(
            Timeframe.FIFTEEN_MINUTES,
            TrendState.BULLISH,
            source_minute=15,
            confirmed_minute=30,
        ),
        state_event(
            Timeframe.FIVE_MINUTES,
            TrendState.BULLISH,
            source_minute=25,
            confirmed_minute=30,
        ),
        state_event(
            Timeframe.THREE_MINUTES,
            TrendState.BULLISH,
            source_minute=27,
            confirmed_minute=30,
        ),
        state_event(
            Timeframe.ONE_MINUTE,
            TrendState.BULLISH,
            source_minute=29,
            confirmed_minute=30,
        ),
    ]


def test_future_one_hour_close_cannot_leak_into_earlier_lower_timeframe_decision() -> None:
    future_hour = state_event(Timeframe.ONE_HOUR, TrendState.BEARISH)
    full_candles = minute_candles(60)
    early_with_future_input = analyze_multi_timeframe(
        full_candles,
        START + timedelta(minutes=30),
        MTFDirection.BULLISH,
        early_lower_timeframe_states() + [future_hour],
        mtf_config(),
    )
    early_without_future_input = analyze_multi_timeframe(
        full_candles[:30],
        START + timedelta(minutes=30),
        MTFDirection.BULLISH,
        early_lower_timeframe_states(),
        mtf_config(),
    )

    assert early_with_future_input.timeframes["1h"].available is False
    assert early_with_future_input.timeframes["1h"].state is TrendState.INSUFFICIENT_DATA
    assert early_with_future_input.timeframes == early_without_future_input.timeframes
    assert early_with_future_input.trade_allowed is False  # missing veto state blocks release


def test_same_future_hour_becomes_conflict_only_after_it_closes() -> None:
    states = early_lower_timeframe_states() + [
        state_event(Timeframe.ONE_HOUR, TrendState.BEARISH),
        state_event(Timeframe.FIFTEEN_MINUTES, TrendState.BULLISH),
        state_event(Timeframe.FIVE_MINUTES, TrendState.BULLISH),
        state_event(Timeframe.THREE_MINUTES, TrendState.BULLISH),
    ]
    result = analyze_multi_timeframe(
        minute_candles(60),
        START + timedelta(hours=1),
        MTFDirection.BULLISH,
        states,
        mtf_config(),
    )

    assert result.timeframes["1h"].state is TrendState.BEARISH
    assert result.alignment is MTFAlignmentStatus.CONFLICTING
    assert MTFReasonCode.MTF_VETO_CONFLICT in result.reason_codes


def swing(
    name: str,
    kind: SwingKind,
    price: str,
    pivot_minute: int,
    confirmed_minute: int,
) -> ConfirmedSwing:
    pivot = START + timedelta(minutes=pivot_minute)
    return ConfirmedSwing(
        swing_id=name,
        source_candidate_id=f"candidate-{name}",
        kind=kind,
        pivot_index=pivot_minute // 15,
        pivot_timestamp=pivot,
        price=Decimal(price),
        candidate_at=pivot + timedelta(minutes=15),
        confirmed_at=START + timedelta(minutes=confirmed_minute),
        left_evidence_timestamps=(),
        right_evidence_timestamps=(),
    )


def test_price_array_midpoint_and_entire_zone_gates_differ() -> None:
    swings = {
        Timeframe.FIFTEEN_MINUTES: [
            swing("range-low", SwingKind.LOW, "90", 15, 45),
            swing("range-high", SwingKind.HIGH, "110", 30, 60),
        ]
    }
    entry = EntryZone(low=Decimal("99"), high=Decimal("101"))
    midpoint = analyze_multi_timeframe(
        minute_candles(60),
        START + timedelta(hours=1),
        MTFDirection.BULLISH,
        aligned_states(),
        mtf_config(price_gate=True, probe=MTFPriceArrayProbe.MIDPOINT),
        entry_zone=entry,
        swings_by_timeframe=swings,
    )
    entire = analyze_multi_timeframe(
        minute_candles(60),
        START + timedelta(hours=1),
        MTFDirection.BULLISH,
        aligned_states(),
        mtf_config(price_gate=True, probe=MTFPriceArrayProbe.ENTIRE_ZONE),
        entry_zone=entry,
        swings_by_timeframe=swings,
    )

    assert midpoint.dealing_range is not None
    assert midpoint.dealing_range.equilibrium == Decimal("100")
    assert midpoint.dealing_range.classification is MTFPriceArray.EQUILIBRIUM
    assert midpoint.trade_allowed is True
    assert entire.dealing_range is not None
    assert entire.dealing_range.classification is MTFPriceArray.PREMIUM
    assert entire.trade_allowed is False
    assert MTFReasonCode.PRICE_ARRAY_CONFLICT in entire.reason_codes
