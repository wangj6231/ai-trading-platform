from bisect import bisect_left, bisect_right
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from heapq import heappop, heappush

from app.market_data.timeframes import timeframe_duration
from app.schemas.candle import Candle
from app.schemas.indicator import ATRResult
from app.schemas.liquidity import (
    DualSweepGroup,
    LiquidityAnalysisResult,
    LiquidityConfig,
    LiquidityConfirmation,
    LiquidityDirection,
    LiquidityEventType,
    LiquidityFormation,
    LiquidityInteraction,
    LiquidityInteractionType,
    LiquidityPool,
    LiquidityPoolHistoryEntry,
    LiquidityPoolHistoryEventType,
    LiquidityPoolState,
    LiquidityTerminationReason,
)
from app.schemas.structure import ConfirmedSwing, SwingKind
from app.schemas.types import Timeframe


class LiquidityInputError(ValueError):
    pass


TERMINAL_POOL_STATES = {LiquidityPoolState.TAKEN, LiquidityPoolState.EXPIRED}


@dataclass
class _ClusterState:
    direction: LiquidityDirection
    anchor_price: Decimal
    members: list[ConfirmedSwing] = field(default_factory=list)
    contains_relative_member: bool = False
    pool: "_PoolState | None" = None


@dataclass
class _PoolState:
    pool_id: str
    direction: LiquidityDirection
    formation: LiquidityFormation
    level: Decimal
    lower_bound: Decimal
    upper_bound: Decimal
    created_at: datetime
    updated_at: datetime
    created_bar_index: int
    confirmation: LiquidityConfirmation
    source_structure: list[str]
    source_prices: list[Decimal]
    source_pivot_timestamps: list[datetime]
    members_available_at: list[datetime]
    state: LiquidityPoolState = LiquidityPoolState.ACTIVE
    terminal_reason: LiquidityTerminationReason | None = None
    swept_at: datetime | None = None
    interactions: list[LiquidityInteraction] = field(default_factory=list)
    history: list[LiquidityPoolHistoryEntry] = field(default_factory=list)
    interaction_reach: Decimal | None = field(default=None, compare=False)


def _validate_inputs(
    candles: Sequence[Candle],
    timeframe: Timeframe,
    confirmed_swings: Sequence[ConfirmedSwing],
    config: LiquidityConfig,
    atr_result: ATRResult | None,
) -> None:
    interval = timeframe_duration(timeframe)
    for candle in candles:
        for field_name in ("open", "high", "low", "close"):
            if getattr(candle, field_name) % config.tick_size != 0:
                raise LiquidityInputError(f"candle {field_name} price is not aligned to tick_size")
    for previous, current in zip(candles, candles[1:], strict=False):
        delta = current.timestamp - previous.timestamp
        if delta <= timedelta(0):
            raise LiquidityInputError("candles must have unique timestamps in ascending order")
        if delta != interval:
            raise LiquidityInputError("candle sequence contains a timeframe gap")

    for previous_swing, current_swing in zip(
        confirmed_swings, confirmed_swings[1:], strict=False
    ):
        if current_swing.confirmed_at < previous_swing.confirmed_at:
            raise LiquidityInputError("confirmed swings must be in confirmation order")

    if atr_result is not None:
        if len(atr_result.points) != len(candles):
            raise LiquidityInputError("ATR points must align one-to-one with candles")
        for candle, point in zip(candles, atr_result.points, strict=True):
            if candle.timestamp != point.timestamp:
                raise LiquidityInputError("ATR timestamps must align with candle timestamps")


def _side_for(swing: ConfirmedSwing) -> LiquidityDirection:
    return (
        LiquidityDirection.BUY_SIDE
        if swing.kind is SwingKind.HIGH
        else LiquidityDirection.SELL_SIDE
    )


def _event_type(direction: LiquidityDirection, formation: LiquidityFormation) -> LiquidityEventType:
    if formation is LiquidityFormation.SWING:
        return (
            LiquidityEventType.BUY_SIDE_LIQUIDITY
            if direction is LiquidityDirection.BUY_SIDE
            else LiquidityEventType.SELL_SIDE_LIQUIDITY
        )
    return (
        LiquidityEventType.EQUAL_HIGHS
        if direction is LiquidityDirection.BUY_SIDE
        else LiquidityEventType.EQUAL_LOWS
    )


def _confirmation_for(formation: LiquidityFormation) -> LiquidityConfirmation:
    if formation is LiquidityFormation.SWING:
        return LiquidityConfirmation.CONFIRMED_SWING
    if formation is LiquidityFormation.RELATIVE_EQUAL:
        return LiquidityConfirmation.CONFIRMED_RELATIVE_EQUAL_CLUSTER
    return LiquidityConfirmation.CONFIRMED_EQUAL_CLUSTER


def _new_single_pool(
    swing: ConfirmedSwing,
    config: LiquidityConfig,
    created_bar_index: int,
) -> _PoolState:
    direction = _side_for(swing)
    half_width = Decimal(config.liquidity_single_pool_half_width_ticks) * config.tick_size
    pool = _PoolState(
        pool_id=f"LIQ:SWING:{direction.value}:{swing.swing_id}",
        direction=direction,
        formation=LiquidityFormation.SWING,
        level=swing.price,
        lower_bound=swing.price - half_width,
        upper_bound=swing.price + half_width,
        created_at=swing.confirmed_at,
        updated_at=swing.confirmed_at,
        created_bar_index=created_bar_index,
        confirmation=LiquidityConfirmation.CONFIRMED_SWING,
        source_structure=[swing.swing_id],
        source_prices=[swing.price],
        source_pivot_timestamps=[swing.pivot_timestamp],
        members_available_at=[swing.confirmed_at],
    )
    _record_history(pool, LiquidityPoolHistoryEventType.CREATED, swing.confirmed_at)
    return pool


def _record_history(
    pool: _PoolState,
    event_type: LiquidityPoolHistoryEventType,
    available_at: datetime,
    *,
    interaction_event_id: str | None = None,
) -> None:
    pool.history.append(
        LiquidityPoolHistoryEntry(
            sequence=len(pool.history),
            event_type=event_type,
            available_at=available_at,
            type=_event_type(pool.direction, pool.formation),
            formation=pool.formation,
            level=pool.level,
            lower_bound=pool.lower_bound,
            upper_bound=pool.upper_bound,
            state=pool.state,
            terminal_reason=pool.terminal_reason,
            confirmation=pool.confirmation,
            source_structure=tuple(pool.source_structure),
            source_prices=tuple(pool.source_prices),
            source_pivot_timestamps=tuple(pool.source_pivot_timestamps),
            members_available_at=tuple(pool.members_available_at),
            swept_at=pool.swept_at,
            interaction_event_id=interaction_event_id,
        )
    )


def _membership(
    cluster: _ClusterState,
    swing: ConfirmedSwing,
    atr: Decimal | None,
    config: LiquidityConfig,
) -> LiquidityFormation | None:
    distance = abs(swing.price - cluster.anchor_price)
    tick_distance = distance / config.tick_size
    if tick_distance <= config.liquidity_equal_tolerance_ticks:
        return LiquidityFormation.EQUAL
    if atr is not None and atr > 0:
        if distance / atr <= config.liquidity_relative_equal_atr_ratio:
            return LiquidityFormation.RELATIVE_EQUAL
    return None


def _matching_cluster_entry(entries: Sequence[tuple[Decimal, int, _ClusterState]],
    swing: ConfirmedSwing, atr: Decimal | None, config: LiquidityConfig,
) -> tuple[Decimal, int, _ClusterState] | None:
    """Find the match interval using the ORIGINAL monotone Decimal predicate.

    No multiplication/rounded-price approximation of the division thresholds.
    Distance decreases towards swing.price on the left and increases on the
    right. Among matches, original cluster creation order remains authoritative.
    """
    split = bisect_left(entries, swing.price, key=lambda item: item[0])
    low, high = 0, split
    while low < high:
        middle = (low + high) // 2
        if _membership(entries[middle][2], swing, atr, config) is not None:
            high = middle
        else:
            low = middle + 1
    first = low
    low, high = split, len(entries)
    while low < high:
        middle = (low + high) // 2
        if _membership(entries[middle][2], swing, atr, config) is not None:
            low = middle + 1
        else:
            high = middle
    return min(entries[first:low], key=lambda item: item[1], default=None)


def _update_cluster_pool(
    cluster: _ClusterState,
    config: LiquidityConfig,
    confirmed_bar_index: int,
) -> _PoolState | None:
    if len(cluster.members) < config.liquidity_cluster_min_touches:
        return None

    formation = (
        LiquidityFormation.RELATIVE_EQUAL
        if cluster.contains_relative_member
        else LiquidityFormation.EQUAL
    )
    padding = Decimal(config.liquidity_cluster_padding_ticks) * config.tick_size
    prices = [member.price for member in cluster.members]
    latest = cluster.members[-1]
    if cluster.pool is None:
        first = cluster.members[0]
        cluster.pool = _PoolState(
            pool_id=(
                f"LIQ:CLUSTER:{cluster.direction.value}:"
                f"{first.swing_id}:{latest.swing_id}"
            ),
            direction=cluster.direction,
            formation=formation,
            level=cluster.anchor_price,
            lower_bound=min(prices) - padding,
            upper_bound=max(prices) + padding,
            created_at=latest.confirmed_at,
            updated_at=latest.confirmed_at,
            created_bar_index=confirmed_bar_index,
            confirmation=_confirmation_for(formation),
            source_structure=[member.swing_id for member in cluster.members],
            source_prices=prices,
            source_pivot_timestamps=[member.pivot_timestamp for member in cluster.members],
            members_available_at=[member.confirmed_at for member in cluster.members],
        )
        _record_history(
            cluster.pool,
            LiquidityPoolHistoryEventType.CREATED,
            latest.confirmed_at,
        )
    else:
        pool = cluster.pool
        pool.formation = formation
        pool.lower_bound = min(prices) - padding
        pool.upper_bound = max(prices) + padding
        pool.interaction_reach = None
        pool.updated_at = latest.confirmed_at
        pool.confirmation = _confirmation_for(formation)
        pool.source_structure = [member.swing_id for member in cluster.members]
        pool.source_prices = prices
        pool.source_pivot_timestamps = [member.pivot_timestamp for member in cluster.members]
        pool.members_available_at = [member.confirmed_at for member in cluster.members]
        _record_history(
            pool,
            LiquidityPoolHistoryEventType.MEMBERS_UPDATED,
            latest.confirmed_at,
        )
    return cluster.pool


def _append_interaction(
    pool: _PoolState,
    interaction_type: LiquidityInteractionType,
    candle: Candle,
    confirmed_at: datetime,
    confirmation: LiquidityConfirmation,
) -> LiquidityInteraction:
    swept_at = confirmed_at if interaction_type is LiquidityInteractionType.SWEEP else None
    event = LiquidityInteraction(
        event_id=(
            f"LIQ:{interaction_type.value}:{pool.direction.value}:"
            f"{pool.pool_id}:{candle.timestamp.isoformat()}"
        ),
        type=interaction_type,
        direction=pool.direction,
        level=pool.level,
        created_at=pool.created_at,
        swept_at=swept_at,
        confirmation=confirmation,
        source_structure=tuple(pool.source_structure),
        pool_id=pool.pool_id,
        timestamp=candle.timestamp,
        confirmed_at=confirmed_at,
    )
    pool.interactions.append(event)
    return event


def _process_interaction(
    pool: _PoolState,
    candle: Candle,
    confirmed_at: datetime,
    config: LiquidityConfig,
) -> LiquidityInteraction | None:
    if pool.state in TERMINAL_POOL_STATES or pool.created_at > candle.timestamp:
        return None

    break_buffer = Decimal(config.liquidity_taken_buffer_ticks) * config.tick_size
    penetration = Decimal(config.liquidity_sweep_min_penetration_ticks) * config.tick_size

    if pool.direction is LiquidityDirection.BUY_SIDE:
        taken = candle.close > pool.upper_bound + break_buffer
        sweep = candle.high > pool.upper_bound + penetration and candle.close <= pool.upper_bound
        touch = candle.high >= pool.lower_bound
    else:
        taken = candle.close < pool.lower_bound - break_buffer
        sweep = candle.low < pool.lower_bound - penetration and candle.close >= pool.lower_bound
        touch = candle.low <= pool.upper_bound

    if taken:
        pool.state = LiquidityPoolState.TAKEN
        pool.terminal_reason = LiquidityTerminationReason.CLOSE_THROUGH
        pool.updated_at = confirmed_at
        event = _append_interaction(
            pool,
            LiquidityInteractionType.TAKEN,
            candle,
            confirmed_at,
            LiquidityConfirmation.CLOSE_THROUGH,
        )
        _record_history(
            pool,
            LiquidityPoolHistoryEventType.TAKEN,
            confirmed_at,
            interaction_event_id=event.event_id,
        )
        return event
    if sweep and pool.state is LiquidityPoolState.ACTIVE:
        pool.state = LiquidityPoolState.SWEPT
        pool.swept_at = confirmed_at
        pool.updated_at = confirmed_at
        event = _append_interaction(
            pool,
            LiquidityInteractionType.SWEEP,
            candle,
            confirmed_at,
            LiquidityConfirmation.CLOSE_BACK,
        )
        _record_history(
            pool,
            LiquidityPoolHistoryEventType.SWEPT,
            confirmed_at,
            interaction_event_id=event.event_id,
        )
        return event
    if touch:
        pool.updated_at = confirmed_at
        event = _append_interaction(
            pool,
            LiquidityInteractionType.TOUCH,
            candle,
            confirmed_at,
            LiquidityConfirmation.BOUNDARY_TOUCH,
        )
        _record_history(
            pool,
            LiquidityPoolHistoryEventType.TOUCHED,
            confirmed_at,
            interaction_event_id=event.event_id,
        )
        return event
    return None


def _interaction_reach(pool: _PoolState, config: LiquidityConfig) -> Decimal:
    """Conservative reach using the ORIGINAL rounded Decimal thresholds.

    A valid candle's close lies between its low and high. Below all buy-side
    thresholds (above all sell-side thresholds), none of taken/sweep/touch can
    hold. Bounds alone would be unsafe at low Decimal precision.
    """
    break_buffer = Decimal(config.liquidity_taken_buffer_ticks) * config.tick_size
    penetration = Decimal(config.liquidity_sweep_min_penetration_ticks) * config.tick_size
    if pool.direction is LiquidityDirection.BUY_SIDE:
        return min(pool.lower_bound, pool.upper_bound + break_buffer, pool.upper_bound + penetration)
    return max(pool.upper_bound, pool.lower_bound - break_buffer, pool.lower_bound - penetration)


class _PoolReachIndex:
    """Schedule the original predicates by conservative price and exact age."""

    def __init__(self, config: LiquidityConfig) -> None:
        self._config = config
        self._prices: dict[LiquidityDirection, list[tuple[Decimal, int, _PoolState]]] = {
            direction: [] for direction in LiquidityDirection}
        self._current: dict[int, tuple[Decimal, int, _PoolState]] = {}
        self._ages: list[tuple[int, int, _PoolState]] = []

    def contains(self, pool: _PoolState) -> bool:
        return id(pool) in self._current

    def update(self, pool: _PoolState, position: int | None = None) -> None:
        old = self._current.get(id(pool))
        if old is not None:
            if pool.interaction_reach is not None:
                return
            position = old[1]
            self.discard(pool)
        assert position is not None
        reach = _interaction_reach(pool, self._config)
        pool.interaction_reach = reach
        entry = (reach, position, pool)
        prices = self._prices[pool.direction]
        at = bisect_right(prices, entry[:2], key=lambda item: item[:2])
        prices.insert(at, entry)
        self._current[id(pool)] = entry
        if old is None:
            heappush(self._ages, (pool.created_bar_index+self._config.liquidity_pool_max_age_bars+1,
                position, pool))

    def discard(self, pool: _PoolState) -> None:
        old = self._current.pop(id(pool))
        prices = self._prices[pool.direction]
        at = bisect_left(prices, old[:2], key=lambda item: item[:2])
        prices.pop(at)

    def selected(self, candle: Candle, bar_index: int) -> list[tuple[_PoolState, bool]]:
        buy = self._prices[LiquidityDirection.BUY_SIDE]
        sell = self._prices[LiquidityDirection.SELL_SIDE]
        buy_end = bisect_right(buy, candle.high, key=lambda item: item[0])
        sell_start = bisect_left(sell, candle.low, key=lambda item: item[0])
        chosen = {id(entry[2]): (entry, True) for entry in (*buy[:buy_end], *sell[sell_start:])}
        while self._ages and self._ages[0][0] <= bar_index:
            _, _, pool = heappop(self._ages)
            entry = self._current.get(id(pool))
            if entry is not None and id(pool) not in chosen:
                chosen[id(pool)] = (entry, False)
        # The original active list is in archive creation order, even when
        # prices tie or both directions interact on the same candle.
        return [(entry[2], reachable) for entry, reachable in
            sorted(chosen.values(), key=lambda item: item[0][1])]


def _to_schema(pool: _PoolState) -> LiquidityPool:
    return LiquidityPool(
        pool_id=pool.pool_id,
        type=_event_type(pool.direction, pool.formation),
        direction=pool.direction,
        formation=pool.formation,
        level=pool.level,
        lower_bound=pool.lower_bound,
        upper_bound=pool.upper_bound,
        state=pool.state,
        terminal_reason=pool.terminal_reason,
        created_at=pool.created_at,
        confirmed_at=pool.created_at,
        updated_at=pool.updated_at,
        swept_at=pool.swept_at,
        confirmation=pool.confirmation,
        source_structure=tuple(pool.source_structure),
        source_prices=tuple(pool.source_prices),
        source_pivot_timestamps=tuple(pool.source_pivot_timestamps),
        members_available_at=tuple(pool.members_available_at),
        interactions=tuple(pool.interactions),
        history=tuple(pool.history),
    )


def analyze_liquidity(
    candles: Sequence[Candle],
    timeframe: Timeframe,
    confirmed_swings: Sequence[ConfirmedSwing],
    config: LiquidityConfig,
    atr_result: ATRResult | None = None,
) -> LiquidityAnalysisResult:
    """Build deterministic liquidity pools from confirmed structure only."""

    _validate_inputs(candles, timeframe, confirmed_swings, config, atr_result)
    if not candles:
        return LiquidityAnalysisResult(
            timeframe=timeframe,
            config=config,
            candle_count=0,
            data_cutoff_at=None,
            pools=[],
            interactions=[],
            dual_sweeps=[],
        )

    interval = timeframe_duration(timeframe)
    close_to_index = {candle.timestamp + interval: index for index, candle in enumerate(candles)}
    atr_by_confirmation: dict[datetime, Decimal | None] = {}
    if atr_result is not None:
        atr_by_confirmation = {
            candle.timestamp + interval: point.atr
            for candle, point in zip(candles, atr_result.points, strict=True)
        }

    cutoff = candles[-1].timestamp + interval
    usable_swings = [swing for swing in confirmed_swings if swing.confirmed_at <= cutoff]
    pools: list[_PoolState] = []
    pools_by_identity: dict[str, list[_PoolState]] = defaultdict(list)
    active_pools = _PoolReachIndex(config)
    clusters: dict[LiquidityDirection, list[_ClusterState]] = {
        LiquidityDirection.BUY_SIDE: [],
        LiquidityDirection.SELL_SIDE: [],
    }
    cluster_index: dict[LiquidityDirection, list[tuple[Decimal, int, _ClusterState]]] = {
        direction: [] for direction in LiquidityDirection
    }
    cluster_pool_keys: dict[int, tuple[LiquidityDirection, Decimal, int]] = {}
    interactions: list[LiquidityInteraction] = []
    dual_sweeps: list[DualSweepGroup] = []
    swing_index = 0

    def consume_swing(swing: ConfirmedSwing) -> None:
        confirmed_bar_index = close_to_index.get(swing.confirmed_at)
        if confirmed_bar_index is None:
            raise LiquidityInputError("swing confirmed_at must align with a candle close")
        if config.liquidity_include_single_swing_pools:
            single_pool = _new_single_pool(swing, config, confirmed_bar_index)
            pools.append(single_pool)
            pools_by_identity[single_pool.pool_id].append(single_pool)
            active_pools.update(single_pool, len(pools)-1)

        direction = _side_for(swing)
        atr = atr_by_confirmation.get(swing.confirmed_at)
        entries = cluster_index[direction]
        matching = _matching_cluster_entry(entries, swing, atr, config)
        if matching is None:
            ordinal = len(clusters[direction])
            cluster = _ClusterState(direction=direction, anchor_price=swing.price, members=[swing])
            clusters[direction].append(cluster)
            position = bisect_right(entries, (swing.price, ordinal), key=lambda item: item[:2])
            entries.insert(position, (swing.price, ordinal, cluster))
            return
        anchor, ordinal, matching_cluster = matching
        classification = _membership(matching_cluster, swing, atr, config)
        assert classification is not None
        matching_cluster.members.append(swing)
        if classification is LiquidityFormation.RELATIVE_EQUAL:
            matching_cluster.contains_relative_member = True
        pool = _update_cluster_pool(matching_cluster, config, confirmed_bar_index)
        # Dataclass equality requires the immutable pool_id to match first.
        # Keep the original equality/identity behavior inside collision buckets.
        if pool is not None and pool not in pools_by_identity[pool.pool_id]:
            pools.append(pool)
            pools_by_identity[pool.pool_id].append(pool)
            active_pools.update(pool, len(pools)-1)
            cluster_pool_keys[id(pool)] = (direction, anchor, ordinal)
        elif pool is not None and active_pools.contains(pool):
            # Membership updates can widen the existing cluster's bounds.
            active_pools.update(pool)

    for bar_index, candle in enumerate(candles):
        while swing_index < len(usable_swings) and usable_swings[swing_index].confirmed_at <= candle.timestamp:
            consume_swing(usable_swings[swing_index])
            swing_index += 1

        confirmed_at = candle.timestamp + interval
        bar_events: list[LiquidityInteraction] = []
        for pool, reachable in active_pools.selected(candle, bar_index):
            event = _process_interaction(pool, candle, confirmed_at, config) if reachable else None
            if event is not None:
                interactions.append(event)
                bar_events.append(event)
            if (
                pool.state not in TERMINAL_POOL_STATES
                and bar_index - pool.created_bar_index > config.liquidity_pool_max_age_bars
            ):
                pool.state = LiquidityPoolState.EXPIRED
                pool.terminal_reason = LiquidityTerminationReason.MAX_AGE_EXCEEDED
                pool.updated_at = confirmed_at
                _record_history(
                    pool,
                    LiquidityPoolHistoryEventType.EXPIRED,
                    confirmed_at,
                )
            if pool.state in TERMINAL_POOL_STATES:
                active_pools.discard(pool)
                key = cluster_pool_keys.pop(id(pool), None)
                if key is not None:
                    direction, anchor, ordinal = key
                    entries = cluster_index[direction]
                    position = bisect_left(entries, (anchor, ordinal), key=lambda item: item[:2])
                    entries.pop(position)

        buy_sweeps = [
            event.event_id
            for event in bar_events
            if event.type is LiquidityInteractionType.SWEEP
            and event.direction is LiquidityDirection.BUY_SIDE
        ]
        sell_sweeps = [
            event.event_id
            for event in bar_events
            if event.type is LiquidityInteractionType.SWEEP
            and event.direction is LiquidityDirection.SELL_SIDE
        ]
        if buy_sweeps and sell_sweeps:
            dual_sweeps.append(
                DualSweepGroup(
                    group_id=f"LIQ:DUAL_SWEEP:{candle.timestamp.isoformat()}",
                    timestamp=candle.timestamp,
                    confirmed_at=confirmed_at,
                    buy_side_event_ids=tuple(buy_sweeps),
                    sell_side_event_ids=tuple(sell_sweeps),
                )
            )

        while swing_index < len(usable_swings) and usable_swings[swing_index].confirmed_at <= confirmed_at:
            consume_swing(usable_swings[swing_index])
            swing_index += 1

    return LiquidityAnalysisResult(
        timeframe=timeframe,
        config=config,
        candle_count=len(candles),
        data_cutoff_at=cutoff,
        pools=[_to_schema(pool) for pool in pools],
        interactions=interactions,
        dual_sweeps=dual_sweeps,
    )
