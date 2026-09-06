from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.engines.structure import analyze_liquidity
from app.schemas.candle import Candle
from app.schemas.indicator import ATRConfig, ATRPoint, ATRResult
from app.schemas.liquidity import (
    LiquidityConfig,
    LiquidityConfirmation,
    LiquidityDirection,
    LiquidityEventType,
    LiquidityFormation,
    LiquidityInteractionType,
    LiquidityPoolState,
    LiquidityPoolHistoryEventType,
    LiquidityTerminationReason,
)
from app.schemas.structure import ConfirmedSwing, SwingKind
from app.schemas.types import Timeframe


START = datetime(2025, 5, 1, tzinfo=UTC)


def candle(
    index: int,
    *,
    open_: str = "10",
    high: str = "11",
    low: str = "9",
    close: str = "10",
) -> Candle:
    return Candle(
        timestamp=START + timedelta(minutes=index),
        open=Decimal(open_),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal("1"),
    )


def swing(
    name: str,
    kind: SwingKind,
    price: str,
    *,
    pivot_index: int,
    confirmed_minute: int,
) -> ConfirmedSwing:
    pivot_timestamp = START + timedelta(minutes=pivot_index)
    confirmed_at = START + timedelta(minutes=confirmed_minute)
    return ConfirmedSwing(
        swing_id=name,
        source_candidate_id=f"candidate:{name}",
        kind=kind,
        pivot_index=pivot_index,
        pivot_timestamp=pivot_timestamp,
        price=Decimal(price),
        candidate_at=pivot_timestamp + timedelta(minutes=1),
        confirmed_at=confirmed_at,
        left_evidence_timestamps=(pivot_timestamp - timedelta(minutes=1),),
        right_evidence_timestamps=(confirmed_at - timedelta(minutes=1),),
    )


def liquidity_config(
    *,
    include_single: bool = False,
    equal_tolerance: str = "0",
    relative_atr_ratio: str = "0",
    min_touches: int = 2,
    max_age: int = 100,
) -> LiquidityConfig:
    return LiquidityConfig(
        tick_size=Decimal("1"),
        liquidity_include_single_swing_pools=include_single,
        liquidity_single_pool_half_width_ticks=1,
        liquidity_equal_tolerance_ticks=Decimal(equal_tolerance),
        liquidity_relative_equal_atr_ratio=Decimal(relative_atr_ratio),
        liquidity_cluster_min_touches=min_touches,
        liquidity_cluster_padding_ticks=0,
        liquidity_sweep_min_penetration_ticks=0,
        liquidity_taken_buffer_ticks=0,
        liquidity_pool_max_age_bars=max_age,
        signal_allow_dual_sweep=False,
    )


def base_candles(count: int = 8) -> list[Candle]:
    return [candle(index) for index in range(count)]


def equal_highs() -> list[ConfirmedSwing]:
    return [
        swing("high-1", SwingKind.HIGH, "12", pivot_index=1, confirmed_minute=2),
        swing("high-2", SwingKind.HIGH, "12", pivot_index=3, confirmed_minute=4),
    ]


def equal_lows() -> list[ConfirmedSwing]:
    return [
        swing("low-1", SwingKind.LOW, "8", pivot_index=1, confirmed_minute=2),
        swing("low-2", SwingKind.LOW, "8", pivot_index=3, confirmed_minute=4),
    ]


def atr_result(candles: list[Candle], value: str) -> ATRResult:
    return ATRResult(
        config=ATRConfig(period=1, smoothing="WILDER"),
        points=[
            ATRPoint(timestamp=bar.timestamp, true_range=Decimal("2"), atr=Decimal(value))
            for bar in candles
        ],
    )


def test_single_swings_are_not_labeled_when_disabled() -> None:
    result = analyze_liquidity(
        base_candles(),
        Timeframe.ONE_MINUTE,
        [swing("only-high", SwingKind.HIGH, "12", pivot_index=1, confirmed_minute=2)],
        liquidity_config(include_single=False),
    )

    assert result.pools == []
    assert result.interactions == []


def test_confirmed_swing_creates_single_pool_only_when_enabled() -> None:
    source = swing("only-high", SwingKind.HIGH, "12", pivot_index=1, confirmed_minute=2)
    result = analyze_liquidity(
        base_candles(),
        Timeframe.ONE_MINUTE,
        [source],
        liquidity_config(include_single=True),
    )

    pool = result.pools[0]
    assert pool.type is LiquidityEventType.BUY_SIDE_LIQUIDITY
    assert pool.direction is LiquidityDirection.BUY_SIDE
    assert pool.formation is LiquidityFormation.SWING
    assert (pool.lower_bound, pool.level, pool.upper_bound) == (
        Decimal("11"),
        Decimal("12"),
        Decimal("13"),
    )
    assert pool.created_at == source.confirmed_at
    assert pool.swept_at is None
    assert pool.confirmation is LiquidityConfirmation.CONFIRMED_SWING
    assert pool.source_structure == (source.swing_id,)


def test_equal_highs_and_equal_lows_activate_separate_pools() -> None:
    sources = sorted(equal_highs() + equal_lows(), key=lambda item: item.confirmed_at)
    result = analyze_liquidity(
        base_candles(),
        Timeframe.ONE_MINUTE,
        sources,
        liquidity_config(),
    )

    buy_pool = next(pool for pool in result.pools if pool.direction is LiquidityDirection.BUY_SIDE)
    sell_pool = next(pool for pool in result.pools if pool.direction is LiquidityDirection.SELL_SIDE)
    assert buy_pool.type is LiquidityEventType.EQUAL_HIGHS
    assert sell_pool.type is LiquidityEventType.EQUAL_LOWS
    assert buy_pool.level == Decimal("12")
    assert sell_pool.level == Decimal("8")
    assert buy_pool.source_structure == ("high-1", "high-2")
    assert sell_pool.source_structure == ("low-1", "low-2")
    assert buy_pool.created_at == START + timedelta(minutes=4)
    assert sell_pool.created_at == START + timedelta(minutes=4)


def test_equal_tolerance_is_configurable_in_ticks() -> None:
    sources = [
        swing("high-1", SwingKind.HIGH, "12", pivot_index=1, confirmed_minute=2),
        swing("high-2", SwingKind.HIGH, "13", pivot_index=3, confirmed_minute=4),
    ]

    strict = analyze_liquidity(
        base_candles(), Timeframe.ONE_MINUTE, sources, liquidity_config(equal_tolerance="0")
    )
    tolerant = analyze_liquidity(
        base_candles(), Timeframe.ONE_MINUTE, sources, liquidity_config(equal_tolerance="1")
    )

    assert strict.pools == []
    assert len(tolerant.pools) == 1
    assert tolerant.pools[0].formation is LiquidityFormation.EQUAL
    assert (tolerant.pools[0].lower_bound, tolerant.pools[0].upper_bound) == (
        Decimal("12"),
        Decimal("13"),
    )


def test_relative_equal_uses_atr_available_at_new_swing_confirmation() -> None:
    candles = base_candles()
    sources = [
        swing("high-1", SwingKind.HIGH, "12", pivot_index=1, confirmed_minute=2),
        swing("high-2", SwingKind.HIGH, "13", pivot_index=3, confirmed_minute=4),
    ]
    result = analyze_liquidity(
        candles,
        Timeframe.ONE_MINUTE,
        sources,
        liquidity_config(relative_atr_ratio="0.5"),
        atr_result(candles, "3"),
    )

    assert len(result.pools) == 1
    assert result.pools[0].formation is LiquidityFormation.RELATIVE_EQUAL
    assert result.pools[0].confirmation is LiquidityConfirmation.CONFIRMED_RELATIVE_EQUAL_CLUSTER


def test_zero_atr_cannot_create_relative_equal_pool() -> None:
    candles = base_candles()
    sources = [
        swing("high-1", SwingKind.HIGH, "12", pivot_index=1, confirmed_minute=2),
        swing("high-2", SwingKind.HIGH, "13", pivot_index=3, confirmed_minute=4),
    ]
    result = analyze_liquidity(
        candles,
        Timeframe.ONE_MINUTE,
        sources,
        liquidity_config(relative_atr_ratio="1"),
        atr_result(candles, "0"),
    )

    assert result.pools == []


def test_buy_side_sweep_requires_penetration_and_close_back() -> None:
    candles = base_candles()
    candles[4] = candle(4, high="13", close="12")
    result = analyze_liquidity(
        candles, Timeframe.ONE_MINUTE, equal_highs(), liquidity_config()
    )

    event = next(event for event in result.interactions if event.type is LiquidityInteractionType.SWEEP)
    pool = result.pools[0]
    assert event.direction is LiquidityDirection.BUY_SIDE
    assert event.level == Decimal("12")
    assert event.created_at == START + timedelta(minutes=4)
    assert event.swept_at == START + timedelta(minutes=5)
    assert event.confirmation is LiquidityConfirmation.CLOSE_BACK
    assert event.source_structure == ("high-1", "high-2")
    assert pool.state is LiquidityPoolState.SWEPT
    assert pool.swept_at == event.swept_at


def test_sell_side_sweep_is_symmetric() -> None:
    candles = base_candles()
    candles[4] = candle(4, low="7", close="8")
    result = analyze_liquidity(candles, Timeframe.ONE_MINUTE, equal_lows(), liquidity_config())

    event = next(event for event in result.interactions if event.type is LiquidityInteractionType.SWEEP)
    assert event.direction is LiquidityDirection.SELL_SIDE
    assert event.swept_at == START + timedelta(minutes=5)


def test_close_through_is_taken_not_sweep() -> None:
    candles = base_candles()
    candles[4] = candle(4, open_="12", high="13", low="11", close="13")
    result = analyze_liquidity(
        candles, Timeframe.ONE_MINUTE, equal_highs(), liquidity_config()
    )

    assert [event.type for event in result.interactions] == [LiquidityInteractionType.TAKEN]
    assert result.pools[0].state is LiquidityPoolState.TAKEN
    assert result.pools[0].terminal_reason is LiquidityTerminationReason.CLOSE_THROUGH


def test_exact_boundary_is_touch_but_not_sweep() -> None:
    candles = base_candles()
    candles[4] = candle(4, high="12", close="11")
    result = analyze_liquidity(
        candles, Timeframe.ONE_MINUTE, equal_highs(), liquidity_config()
    )

    assert result.interactions[0].type is LiquidityInteractionType.TOUCH
    assert all(event.type is not LiquidityInteractionType.SWEEP for event in result.interactions)


def test_same_bar_opposite_side_sweeps_emit_individual_events_and_group() -> None:
    candles = base_candles()
    candles[4] = candle(4, high="13", low="7", close="10")
    sources = sorted(equal_highs() + equal_lows(), key=lambda item: item.confirmed_at)
    result = analyze_liquidity(candles, Timeframe.ONE_MINUTE, sources, liquidity_config())

    sweeps = [event for event in result.interactions if event.type is LiquidityInteractionType.SWEEP]
    assert {event.direction for event in sweeps} == {
        LiquidityDirection.BUY_SIDE,
        LiquidityDirection.SELL_SIDE,
    }
    assert len(result.dual_sweeps) == 1
    assert result.dual_sweeps[0].type == "DUAL_SWEEP"
    assert set(result.dual_sweeps[0].buy_side_event_ids) == {
        event.event_id for event in sweeps if event.direction is LiquidityDirection.BUY_SIDE
    }


def test_expiry_is_terminal_and_prevents_later_sweep() -> None:
    candles = base_candles()
    candles[6] = candle(6, high="13", close="12")
    result = analyze_liquidity(
        candles,
        Timeframe.ONE_MINUTE,
        equal_highs(),
        liquidity_config(max_age=1),
    )

    pool = result.pools[0]
    assert pool.state is LiquidityPoolState.EXPIRED
    assert pool.terminal_reason is LiquidityTerminationReason.MAX_AGE_EXCEEDED
    assert all(event.type is not LiquidityInteractionType.SWEEP for event in result.interactions)


def test_future_confirmed_swing_is_not_consumed_before_data_cutoff() -> None:
    future_sources = equal_highs()
    result = analyze_liquidity(
        base_candles(3),
        Timeframe.ONE_MINUTE,
        future_sources,
        liquidity_config(),
    )

    assert result.data_cutoff_at == START + timedelta(minutes=3)
    assert result.pools == []
    assert result.interactions == []


def test_cluster_history_preserves_bounds_members_and_state_at_each_cutoff() -> None:
    candles = base_candles(9)
    candles[7] = candle(7, open_="10", high="15", low="9", close="14")
    sources = [
        swing("high-1", SwingKind.HIGH, "12", pivot_index=1, confirmed_minute=2),
        swing("high-2", SwingKind.HIGH, "13", pivot_index=3, confirmed_minute=4),
        swing("high-3", SwingKind.HIGH, "14", pivot_index=5, confirmed_minute=6),
    ]
    config = liquidity_config(equal_tolerance="2")
    prefix = analyze_liquidity(
        candles[:5],
        Timeframe.ONE_MINUTE,
        sources[:2],
        config,
    )
    full = analyze_liquidity(
        candles,
        Timeframe.ONE_MINUTE,
        sources,
        config,
    )

    prefix_pool = prefix.pools[0]
    full_pool = full.pools[0]
    historical = full_pool.snapshot_at(START + timedelta(minutes=5))

    assert historical == prefix_pool
    assert historical is not None
    assert historical.source_structure == ("high-1", "high-2")
    assert historical.members_available_at == (
        START + timedelta(minutes=2),
        START + timedelta(minutes=4),
    )
    assert (historical.lower_bound, historical.upper_bound) == (
        Decimal("12"),
        Decimal("13"),
    )
    assert historical.state is LiquidityPoolState.ACTIVE

    assert full_pool.source_structure == ("high-1", "high-2", "high-3")
    assert (full_pool.lower_bound, full_pool.upper_bound) == (
        Decimal("12"),
        Decimal("14"),
    )
    assert full_pool.state is LiquidityPoolState.SWEPT
    assert full_pool.swept_at == START + timedelta(minutes=8)
    assert [entry.event_type for entry in full_pool.history] == [
        LiquidityPoolHistoryEventType.CREATED,
        LiquidityPoolHistoryEventType.MEMBERS_UPDATED,
        LiquidityPoolHistoryEventType.SWEPT,
    ]
