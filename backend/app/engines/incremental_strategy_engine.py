"""Append-only deterministic feature state for P3 historical replay.

The reference strategy orchestration is still the authority.  This module
only supplies append-safe feature calculators through the narrow seams on the
reference engine.  Each state accepts an exact candle prefix and is reset on
any non-prefix input.  The P3 tests compare the complete structured result to
the reference result; a faster but different result is never accepted.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import datetime
from decimal import Decimal, localcontext
from enum import Enum
from hashlib import sha256
import json
from typing import Any

from pydantic import BaseModel

from app.engines.optimized_strategy_engine import OptimizedDeterministicStrategyEngine
from app.engines.indicators.calculations import INDICATOR_DECIMAL_CONTEXT
from app.engines.smc.displacement import (
    _failure_reasons,
    _matching_fvgs,
    _metrics,
)
from app.engines.smc.fvg import (
    _ZoneState,
    _new_fvg,
    _to_schema as _fvg_to_schema,
    _update_zone,
)
from app.engines.smc.order_blocks import (
    _BreakerState,
    _OrderBlockState,
    _append_breaker_event,
    _append_ob_event,
    _direction as _ob_direction,
    _hard_invalidation,
    _midpoint_holds,
    _new_breaker,
    _new_order_block,
    _select_candidate,
    _validation_passes,
    _to_breaker_schema,
    _to_order_block_schema,
)
from app.engines.structure.liquidity import (
    TERMINAL_POOL_STATES,
    _ClusterState,
    _PoolState,
    _membership,
    _new_single_pool,
    _process_interaction,
    _record_history,
    _side_for,
    _to_schema as _pool_to_schema,
    _update_cluster_pool,
)
from app.engines.structure.primitives import (
    _validate_candles,
    _classify_trend,
    _fully_qualifies,
    _left_qualifies,
    _latest_unbroken_swing,
    _event_type_for,
)
from app.engines.structure.references import structure_event_reference
from app.market_data.timeframes import timeframe_duration
from app.schemas.candle import Candle
from app.schemas.displacement import (
    DisplacementAnalysisResult,
    DisplacementCandidateStatus,
    DisplacementDirection,
    DisplacementEvaluation,
    DisplacementLeg,
    DisplacementRejectionCode,
)
from app.schemas.fvg import FVGAnalysisResult, FVGRejection, GapDirection
from app.schemas.indicator import (
    MACDConfig,
    ATRConfig,
    ATRPoint,
    ATRResult,
    IndicatorAnalysis,
    MACDPoint,
    MACDResult,
)
from app.schemas.liquidity import (
    LiquidityConfig,
    DualSweepGroup,
    LiquidityDirection,
    LiquidityAnalysisResult,
    LiquidityInteractionType,
    LiquidityPoolHistoryEventType,
    LiquidityPoolState,
    LiquidityTerminationReason,
)
from app.schemas.order_block import (
    OrderBlockConfig,
    BreakerBlockStatus,
    OrderBlockAnalysisResult,
    OrderBlockDisplacementLink,
    OrderBlockEventType,
    OrderBlockRejection,
    OrderBlockRejectionCode,
    OrderBlockStatus,
)
from app.schemas.structure import (
    MarketStructureConfig,
    CandidateResolution,
    ConfirmedSwing,
    MarketStructureResult,
    PriceZoneCandidate,
    StructureBreakEvent,
    StructureDirection,
    StructureDisplayAlias,
    StructureEventType,
    StructureRejection,
    SwingCandidate,
    SwingKind,
    ZoneKind,
)
from app.schemas.types import MarketSymbol, Timeframe
from app.schemas.fvg import FVGConfig
from app.schemas.displacement import DisplacementConfig


def _prefix_ok(previous: tuple[Candle, ...], current: Sequence[Candle]) -> bool:
    return len(current) >= len(previous) and tuple(current[: len(previous)]) == previous


@dataclass
class _IndicatorState:
    timeframe: Timeframe
    macd_config: MACDConfig
    atr_config: ATRConfig
    candles: tuple[Candle, ...] = ()
    fast: list[Decimal | None] = field(default_factory=list)
    slow: list[Decimal | None] = field(default_factory=list)
    macd: list[Decimal | None] = field(default_factory=list)
    signal: list[Decimal | None] = field(default_factory=list)
    histogram: list[Decimal | None] = field(default_factory=list)
    true_ranges: list[Decimal] = field(default_factory=list)
    atr: list[Decimal | None] = field(default_factory=list)
    macd_points: list[MACDPoint] = field(default_factory=list)
    atr_points: list[ATRPoint] = field(default_factory=list)

    def reset(self) -> None:
        self.candles = ()
        for values in (
            self.fast,
            self.slow,
            self.macd,
            self.signal,
            self.histogram,
            self.true_ranges,
            self.atr,
        ):
            values.clear()
        self.macd_points.clear()
        self.atr_points.clear()

    def append(self, candles: Sequence[Candle]) -> None:
        incoming = tuple(candles)
        if not _prefix_ok(self.candles, incoming):
            self.reset()
        for candle in incoming[len(self.candles) :]:
            index = len(self.candles)
            self.candles = self.candles + (candle,)
            self.fast.append(
                self._ema(self.candles, index, self.macd_config.fast_period, self.fast)
            )
            self.slow.append(
                self._ema(self.candles, index, self.macd_config.slow_period, self.slow)
            )
            slow_value = self.slow[-1]
            macd_value = (
                None
                if slow_value is None or self.fast[-1] is None
                else self._calc(lambda: self.fast[-1] - slow_value)
            )
            self.macd.append(macd_value)
            compact_index = index - self.macd_config.slow_period + 1
            if macd_value is None:
                signal_value = None
            else:
                signal_values = self.signal
                if compact_index == self.macd_config.signal_period - 1:
                    start = index - self.macd_config.signal_period + 1
                    seed_values = [
                        value
                        for value in self.macd[start : index + 1]
                        if value is not None
                    ]
                    signal_value = self._calc(
                        lambda: (
                            sum(seed_values, start=Decimal(0))
                            / Decimal(self.macd_config.signal_period)
                        )
                    )
                elif compact_index >= self.macd_config.signal_period:
                    previous = signal_values[-1]
                    assert previous is not None
                    signal_value = self._calc(
                        lambda: (
                            previous
                            + (Decimal(2) / Decimal(self.macd_config.signal_period + 1))
                            * (macd_value - previous)
                        )
                    )
                else:
                    signal_value = None
            self.signal.append(signal_value)
            histogram_value = (
                None
                if macd_value is None or signal_value is None
                else self._calc(lambda: macd_value - signal_value)
            )
            self.histogram.append(histogram_value)
            high_low = candle.high - candle.low
            if index == 0:
                tr = high_low
            else:
                previous_close = self.candles[-2].close
                tr = max(
                    high_low,
                    abs(candle.high - previous_close),
                    abs(candle.low - previous_close),
                )
            self.true_ranges.append(tr)
            period = self.atr_config.period
            if index < period - 1:
                atr_value = None
            elif index == period - 1:
                atr_value = self._calc(
                    lambda: (
                        sum(self.true_ranges[:period], start=Decimal(0))
                        / Decimal(period)
                    )
                )
            elif self.atr_config.smoothing.value == "SMA":
                atr_value = self._calc(
                    lambda: (
                        sum(
                            self.true_ranges[index - period + 1 : index + 1],
                            start=Decimal(0),
                        )
                        / Decimal(period)
                    )
                )
            else:
                previous_atr = self.atr[-1]
                assert previous_atr is not None
                atr_value = self._calc(
                    lambda: (previous_atr * Decimal(period - 1) + tr) / Decimal(period)
                )
            self.atr.append(atr_value)

    @staticmethod
    def _ema(
        values_in: Sequence[Candle],
        index: int,
        period: int,
        values: list[Decimal | None],
    ) -> Decimal | None:
        if index < period - 1:
            return None
        with localcontext(INDICATOR_DECIMAL_CONTEXT):
            if index == period - 1:
                return +(
                    sum((bar.close for bar in values_in[:period]), start=Decimal(0))
                    / Decimal(period)
                )
            previous = values[-1]
            assert previous is not None
            alpha = Decimal(2) / Decimal(period + 1)
            return _IndicatorState._calc(
                lambda: previous + alpha * (values_in[index].close - previous)
            )

    @staticmethod
    def _calc(fn) -> Decimal:
        with localcontext(INDICATOR_DECIMAL_CONTEXT):
            return +fn()

    def result(self) -> IndicatorAnalysis:
        for index in range(len(self.macd_points), len(self.candles)):
            candle = self.candles[index]
            previous = index - 1
            pm = self.macd[previous] if previous >= 0 else None
            ps = self.signal[previous] if previous >= 0 else None
            cm = self.macd[index]
            cs = self.signal[index]
            ph = self.histogram[previous] if previous >= 0 else None
            ch = self.histogram[index]
            self.macd_points.append(
                MACDPoint(
                    timestamp=candle.timestamp,
                    fast_ema=self.fast[index],
                    slow_ema=self.slow[index],
                    macd_line=cm,
                    signal_line=cs,
                    histogram=ch,
                    bullish_crossover=pm is not None
                    and ps is not None
                    and cm is not None
                    and cs is not None
                    and pm <= ps
                    and cm > cs,
                    bearish_crossover=pm is not None
                    and ps is not None
                    and cm is not None
                    and cs is not None
                    and pm >= ps
                    and cm < cs,
                    histogram_increasing=ph is not None and ch is not None and ch > ph,
                    histogram_decreasing=ph is not None and ch is not None and ch < ph,
                )
            )
            self.atr_points.append(
                ATRPoint(
                    timestamp=candle.timestamp,
                    true_range=self.true_ranges[index],
                    atr=self.atr[index],
                )
            )
        return IndicatorAnalysis(
            candle_count=len(self.candles),
            data_cutoff_at=(
                self.candles[-1].timestamp + timeframe_duration(self.timeframe)
                if self.candles
                else None
            ),
            macd=MACDResult(config=self.macd_config, points=list(self.macd_points)),
            atr=ATRResult(
                config=self.atr_config,
                points=list(self.atr_points),
            ),
        )


@dataclass
class _StructureState:
    timeframe: Timeframe
    config: MarketStructureConfig
    candles: tuple[Candle, ...] = ()
    candidates: list[SwingCandidate] = field(default_factory=list)
    confirmed: list[ConfirmedSwing] = field(default_factory=list)
    events: list[StructureBreakEvent] = field(default_factory=list)
    rejections: list[StructureRejection] = field(default_factory=list)
    broken_ids: set[str] = field(default_factory=set)
    pending_indices: list[int] = field(default_factory=list)
    zones: dict[ZoneKind, list[PriceZoneCandidate]] = field(
        default_factory=lambda: {ZoneKind.SUPPORT: [], ZoneKind.RESISTANCE: []}
    )

    def reset(self) -> None:
        self.candles = ()
        self.candidates.clear()
        self.confirmed.clear()
        self.events.clear()
        self.rejections.clear()
        self.broken_ids.clear()
        self.pending_indices.clear()
        self.zones = {ZoneKind.SUPPORT: [], ZoneKind.RESISTANCE: []}

    def append(self, candles: Sequence[Candle]) -> None:
        incoming = tuple(candles)
        if not _prefix_ok(self.candles, incoming):
            self.reset()
        _validate_candles(
            incoming[max(0, len(self.candles) - 1) :],
            self.timeframe,
            self.config.tick_size,
        )
        for candle in incoming[len(self.candles) :]:
            self.candles = self.candles + (candle,)
            index = len(self.candles) - 1
            duration = timeframe_duration(self.timeframe)
            # A pending candidate can resolve when its final right candle is
            # appended.  Recreate the immutable model in-place, preserving the
            # candidate ordering of the reference detector.
            still_pending = []
            for candidate_index in self.pending_indices:
                candidate = self.candidates[candidate_index]
                pivot_index = candidate.pivot_index
                available = min(
                    self.config.swing_right_bars, len(self.candles) - pivot_index - 1
                )
                if available == candidate.observed_right_bars:
                    still_pending.append(candidate_index)
                    continue
                pivot = self.candles[pivot_index]
                left = self.candles[
                    pivot_index - self.config.swing_left_bars : pivot_index
                ]
                right = self.candles[pivot_index + 1 : pivot_index + 1 + available]
                left_prices = [
                    bar.high if candidate.kind is SwingKind.HIGH else bar.low
                    for bar in left
                ]
                right_prices = [
                    bar.high if candidate.kind is SwingKind.HIGH else bar.low
                    for bar in right
                ]
                full = available == self.config.swing_right_bars
                resolution = CandidateResolution.PENDING
                resolved_at = None
                if full:
                    resolution = (
                        CandidateResolution.CONFIRMED
                        if _fully_qualifies(
                            candidate.kind,
                            candidate.price,
                            left_prices,
                            right_prices,
                            self.config.swing_tie_policy,
                        )
                        else CandidateResolution.REJECTED
                    )
                    resolved_at = right[-1].timestamp + duration
                updated = candidate.model_copy(
                    update={
                        "observed_right_bars": available,
                        "resolution": resolution,
                        "resolved_at": resolved_at,
                    }
                )
                self.candidates[candidate_index] = updated
                if resolution is CandidateResolution.PENDING:
                    still_pending.append(candidate_index)
                if resolution is CandidateResolution.CONFIRMED:
                    assert resolved_at is not None
                    self.confirmed.append(
                        ConfirmedSwing(
                            swing_id=candidate.candidate_id,
                            source_candidate_id=candidate.candidate_id,
                            kind=candidate.kind,
                            pivot_index=pivot_index,
                            pivot_timestamp=candidate.pivot_timestamp,
                            price=candidate.price,
                            candidate_at=candidate.candidate_at,
                            confirmed_at=resolved_at,
                            left_evidence_timestamps=tuple(
                                bar.timestamp for bar in left
                            ),
                            right_evidence_timestamps=tuple(
                                bar.timestamp for bar in right
                            ),
                        )
                    )
                    self._append_zone(self.confirmed[-1])

            self.pending_indices = still_pending

            # A new pivot can become a candidate as soon as its left window is
            # available.  The reference checks HIGH before LOW.
            if index >= self.config.swing_left_bars:
                pivot = self.candles[index]
                left = self.candles[index - self.config.swing_left_bars : index]
                for kind in (SwingKind.HIGH, SwingKind.LOW):
                    price = pivot.high if kind is SwingKind.HIGH else pivot.low
                    left_prices = [
                        bar.high if kind is SwingKind.HIGH else bar.low for bar in left
                    ]
                    if not _left_qualifies(
                        kind, price, left_prices, self.config.swing_tie_policy
                    ):
                        continue
                    self.candidates.append(
                        SwingCandidate(
                            candidate_id=f"{kind.value}:{pivot.timestamp.isoformat()}",
                            kind=kind,
                            pivot_index=index,
                            pivot_timestamp=pivot.timestamp,
                            price=price,
                            candidate_at=pivot.timestamp + duration,
                            required_right_bars=self.config.swing_right_bars,
                            observed_right_bars=0,
                            resolution=CandidateResolution.PENDING,
                            resolved_at=None,
                        )
                    )
                    self.pending_indices.append(len(self.candidates) - 1)

            # The current candle can break only swings confirmed before its
            # open.  Confirmation at this candle's close is not visible yet.
            self._append_structure_event(candle, index)

    def _append_zone(self, swing: ConfirmedSwing) -> None:
        kind = ZoneKind.SUPPORT if swing.kind is SwingKind.LOW else ZoneKind.RESISTANCE
        zones = self.zones[kind]
        tolerance = self.config.tick_size * Decimal(
            self.config.zone_merge_tolerance_ticks
        )
        padding = self.config.tick_size * Decimal(self.config.zone_padding_ticks)
        matches = [
            (abs(swing.price - zone.anchor_price), index)
            for index, zone in enumerate(zones)
            if abs(swing.price - zone.anchor_price) <= tolerance
        ]
        if matches:
            _, index = min(matches)
            zone = zones[index]
            zones[index] = PriceZoneCandidate(
                zone_id=zone.zone_id,
                kind=kind,
                anchor_price=zone.anchor_price,
                lower_bound=min(zone.lower_bound + padding, swing.price) - padding,
                upper_bound=max(zone.upper_bound - padding, swing.price) + padding,
                touch_count=zone.touch_count + 1,
                source_swing_ids=(*zone.source_swing_ids, swing.swing_id),
                source_pivot_timestamps=(
                    *zone.source_pivot_timestamps,
                    swing.pivot_timestamp,
                ),
                created_at=zone.created_at,
                updated_at=swing.confirmed_at,
            )
        else:
            zones.append(
                PriceZoneCandidate(
                    zone_id=f"{kind.value}:{len(zones)}",
                    kind=kind,
                    anchor_price=swing.price,
                    lower_bound=swing.price - padding,
                    upper_bound=swing.price + padding,
                    touch_count=1,
                    source_swing_ids=(swing.swing_id,),
                    source_pivot_timestamps=(swing.pivot_timestamp,),
                    created_at=swing.confirmed_at,
                    updated_at=swing.confirmed_at,
                )
            )

    def _append_structure_event(self, candle: Candle, bar_index: int) -> None:
        duration = timeframe_duration(self.timeframe)
        eligible = [
            item for item in self.confirmed if item.confirmed_at <= candle.timestamp
        ]
        trend = _classify_trend(eligible, self.config)
        up = _latest_unbroken_swing(
            eligible, SwingKind.HIGH, candle.timestamp, self.broken_ids
        )
        down = _latest_unbroken_swing(
            eligible, SwingKind.LOW, candle.timestamp, self.broken_ids
        )
        if self.config.structure_break_basis.value == "CLOSE":
            up_value, down_value = candle.close, candle.close
        else:
            up_value, down_value = candle.high, candle.low
        buffer = self.config.tick_size * Decimal(
            self.config.structure_break_buffer_ticks
        )
        up_break = up is not None and up_value > up.price + buffer
        down_break = down is not None and down_value < down.price - buffer
        confirmed_at = candle.timestamp + duration
        if up_break and down_break:
            assert up is not None and down is not None
            self.rejections.append(
                StructureRejection(
                    code="AMBIGUOUS_DUAL_STRUCTURE_BREAK",
                    timestamp=candle.timestamp,
                    confirmed_at=confirmed_at,
                    up_structure_id=up.swing_id,
                    down_structure_id=down.swing_id,
                )
            )
            return
        if not up_break and not down_break:
            return
        direction = (
            StructureDirection.BULLISH if up_break else StructureDirection.BEARISH
        )
        broken = up if up_break else down
        assert broken is not None
        event_type = _event_type_for(direction, trend)
        self.events.append(
            StructureBreakEvent(
                type=event_type,
                direction=direction,
                price=up_value if up_break else down_value,
                timestamp=candle.timestamp,
                broken_structure_id=broken.swing_id,
                confirmation_type=self.config.structure_break_basis,
                confirmed_at=confirmed_at,
                display_alias=StructureDisplayAlias.CHOCH
                if event_type is StructureEventType.MSS
                else None,
                trend_before_break=trend,
            )
        )
        self.broken_ids.add(broken.swing_id)

    def result(self) -> MarketStructureResult:
        # Project fresh containers; callers cannot mutate the internal lists.
        return MarketStructureResult(
            timeframe=self.timeframe,
            config=self.config,
            candle_count=len(self.candles),
            data_cutoff_at=(
                self.candles[-1].timestamp + timeframe_duration(self.timeframe)
                if self.candles
                else None
            ),
            candidate_swings=list(self.candidates),
            confirmed_swings=list(self.confirmed),
            support_candidates=list(self.zones[ZoneKind.SUPPORT]),
            resistance_candidates=list(self.zones[ZoneKind.RESISTANCE]),
            trend_state=_classify_trend(self.confirmed, self.config),
            structure_events=list(self.events),
            structure_rejections=list(self.rejections),
        )


@dataclass
class _FVGState:
    timeframe: Timeframe
    config: FVGConfig
    candles: tuple[Candle, ...] = ()
    zones: list[_ZoneState] = field(default_factory=list)
    rejections: list[FVGRejection] = field(default_factory=list)

    def reset(self) -> None:
        self.candles = ()
        self.zones.clear()
        self.rejections.clear()

    def append(self, candles: Sequence[Candle], atr_result: ATRResult | None) -> None:
        incoming = tuple(candles)
        if not _prefix_ok(self.candles, incoming):
            self.reset()
        for bar in incoming[len(self.candles) :]:
            index = len(self.candles)
            self.candles = self.candles + (bar,)
            duration = timeframe_duration(self.timeframe)
            confirmed_at = bar.timestamp + duration
            if index >= 2:
                atr_at_open = (
                    atr_result.points[index - 1].atr if atr_result is not None else None
                )
                if self.config.fvg_min_gap_atr_ratio > 0 and (
                    atr_at_open is None or atr_at_open <= 0
                ):
                    self.rejections.append(
                        FVGRejection(
                            code="FVG_ATR_UNAVAILABLE",
                            third_candle_timestamp=bar.timestamp,
                            confirmed_at=confirmed_at,
                        )
                    )
                else:
                    threshold = (
                        self.config.fvg_min_gap_atr_ratio * atr_at_open
                        if atr_at_open is not None
                        else Decimal(0)
                    )
                    minimum = max(
                        self.config.tick_size * Decimal(self.config.fvg_min_gap_ticks),
                        threshold,
                    )
                    first, middle = self.candles[index - 2], self.candles[index - 1]
                    bullish = (
                        bar.low - first.high > 0 and bar.low - first.high >= minimum
                    )
                    bearish = (
                        first.low - bar.high > 0 and first.low - bar.high >= minimum
                    )
                    if self.config.fvg_require_middle_candle_direction:
                        bullish = bullish and middle.close > middle.open
                        bearish = bearish and middle.close < middle.open
                    if bullish and bearish:
                        self.rejections.append(
                            FVGRejection(
                                code="FVG_IMPOSSIBLE_DUAL_FORMATION",
                                third_candle_timestamp=bar.timestamp,
                                confirmed_at=confirmed_at,
                            )
                        )
                    elif bullish:
                        self.zones.append(
                            _new_fvg(
                                direction=GapDirection.BULLISH,
                                lower=first.high,
                                upper=bar.low,
                                candles=self.candles,
                                third_index=index,
                                confirmed_at=confirmed_at,
                            )
                        )
                    elif bearish:
                        self.zones.append(
                            _new_fvg(
                                direction=GapDirection.BEARISH,
                                lower=bar.high,
                                upper=first.low,
                                candles=self.candles,
                                third_index=index,
                                confirmed_at=confirmed_at,
                            )
                        )
            new_ifvgs: list[_ZoneState] = []
            for zone in list(self.zones):
                if bar.timestamp < zone.confirmed_at:
                    continue
                created = _update_zone(zone, bar, index, confirmed_at, self.config)
                if created is not None:
                    new_ifvgs.append(created)
            self.zones.extend(new_ifvgs)

    def result(self, atr_result: ATRResult | None) -> FVGAnalysisResult:
        return FVGAnalysisResult(
            timeframe=self.timeframe,
            config=self.config,
            candle_count=len(self.candles),
            data_cutoff_at=(
                self.candles[-1].timestamp + timeframe_duration(self.timeframe)
                if self.candles
                else None
            ),
            zones=[_fvg_to_schema(zone) for zone in self.zones],
            rejections=list(self.rejections),
        )


@dataclass
class _LiquidityState:
    timeframe: Timeframe
    config: LiquidityConfig
    candles: tuple[Candle, ...] = ()
    pools: list[_PoolState] = field(default_factory=list)
    clusters: dict[Any, list[_ClusterState]] = field(default_factory=dict)
    interactions: list[Any] = field(default_factory=list)
    dual_sweeps: list[DualSweepGroup] = field(default_factory=list)
    swing_index: int = 0
    swings: tuple[ConfirmedSwing, ...] = ()

    def __post_init__(self) -> None:
        self.clusters = {
            LiquidityDirection.BUY_SIDE: [],
            LiquidityDirection.SELL_SIDE: [],
        }

    def reset(self) -> None:
        self.candles = ()
        self.pools.clear()
        self.clusters = {item: [] for item in self.clusters}
        self.interactions.clear()
        self.dual_sweeps.clear()
        self.swing_index = 0
        self.swings = ()

    def append(
        self,
        candles: Sequence[Candle],
        swings: Sequence[ConfirmedSwing],
        atr_result: ATRResult | None,
    ) -> None:
        incoming = tuple(candles)
        if not _prefix_ok(self.candles, incoming):
            self.reset()
        self.swings = tuple(swings)
        interval = timeframe_duration(self.timeframe)
        close_index = {
            item.timestamp + interval: index for index, item in enumerate(incoming)
        }
        atr_by_confirmation = (
            {
                item.timestamp + interval: point.atr
                for item, point in zip(incoming, atr_result.points, strict=True)
            }
            if atr_result is not None
            else {}
        )

        def consume_swing(swing: ConfirmedSwing) -> None:
            confirmed_bar_index = close_index.get(swing.confirmed_at)
            if confirmed_bar_index is None:
                raise ValueError("swing confirmed_at must align with candle close")
            if self.config.liquidity_include_single_swing_pools:
                self.pools.append(
                    _new_single_pool(swing, self.config, confirmed_bar_index)
                )
            direction = _side_for(swing)
            matching = None
            classification = None
            atr = atr_by_confirmation.get(swing.confirmed_at)
            for cluster in self.clusters[direction]:
                if (
                    cluster.pool is not None
                    and cluster.pool.state in TERMINAL_POOL_STATES
                ):
                    continue
                item = _membership(cluster, swing, atr, self.config)
                if item is not None:
                    matching, classification = cluster, item
                    break
            if matching is None:
                self.clusters[direction].append(
                    _ClusterState(
                        direction=direction, anchor_price=swing.price, members=[swing]
                    )
                )
                return
            matching.members.append(swing)
            if classification is not None and classification.value == "RELATIVE_EQUAL":
                matching.contains_relative_member = True
            pool = _update_cluster_pool(matching, self.config, confirmed_bar_index)
            if pool is not None and pool not in self.pools:
                self.pools.append(pool)

        for bar_index, candle in enumerate(
            incoming[len(self.candles) :], start=len(self.candles)
        ):
            self.candles = self.candles + (candle,)
            while (
                self.swing_index < len(self.swings)
                and self.swings[self.swing_index].confirmed_at <= candle.timestamp
            ):
                consume_swing(self.swings[self.swing_index])
                self.swing_index += 1
            confirmed_at = candle.timestamp + interval
            bar_events = []
            for pool in self.pools:
                event = _process_interaction(pool, candle, confirmed_at, self.config)
                if event is not None:
                    self.interactions.append(event)
                    bar_events.append(event)
                if (
                    pool.state not in TERMINAL_POOL_STATES
                    and bar_index - pool.created_bar_index
                    > self.config.liquidity_pool_max_age_bars
                ):
                    pool.state = LiquidityPoolState.EXPIRED
                    pool.terminal_reason = LiquidityTerminationReason.MAX_AGE_EXCEEDED
                    pool.updated_at = confirmed_at
                    _record_history(
                        pool, LiquidityPoolHistoryEventType.EXPIRED, confirmed_at
                    )
            buy = tuple(
                item.event_id
                for item in bar_events
                if item.type is LiquidityInteractionType.SWEEP
                and item.direction.value == "BUY_SIDE"
            )
            sell = tuple(
                item.event_id
                for item in bar_events
                if item.type is LiquidityInteractionType.SWEEP
                and item.direction.value == "SELL_SIDE"
            )
            if buy and sell:
                self.dual_sweeps.append(
                    DualSweepGroup(
                        group_id=f"LIQ:DUAL_SWEEP:{candle.timestamp.isoformat()}",
                        timestamp=candle.timestamp,
                        confirmed_at=confirmed_at,
                        buy_side_event_ids=buy,
                        sell_side_event_ids=sell,
                    )
                )
            while (
                self.swing_index < len(self.swings)
                and self.swings[self.swing_index].confirmed_at <= confirmed_at
            ):
                consume_swing(self.swings[self.swing_index])
                self.swing_index += 1

    def result(self) -> LiquidityAnalysisResult:
        return LiquidityAnalysisResult(
            timeframe=self.timeframe,
            config=self.config,
            candle_count=len(self.candles),
            data_cutoff_at=(
                self.candles[-1].timestamp + timeframe_duration(self.timeframe)
                if self.candles
                else None
            ),
            pools=[_pool_to_schema(pool) for pool in self.pools],
            interactions=list(self.interactions),
            dual_sweeps=list(self.dual_sweeps),
        )


@dataclass
class _DisplacementState:
    timeframe: Timeframe
    config: DisplacementConfig
    candles: tuple[Candle, ...] = ()
    structure_events: tuple[StructureBreakEvent, ...] = ()
    legs_by_event: dict[str, DisplacementLeg] = field(default_factory=dict)
    evaluations_by_event: dict[str, DisplacementEvaluation] = field(
        default_factory=dict
    )

    def reset(self) -> None:
        self.candles = ()
        self.structure_events = ()
        self.legs_by_event.clear()
        self.evaluations_by_event.clear()

    def append(
        self,
        candles: Sequence[Candle],
        structure_events: Sequence[StructureBreakEvent],
        fvg_zones: Sequence[Any],
    ) -> None:
        incoming = tuple(candles)
        if not _prefix_ok(self.candles, incoming):
            self.reset()
        self.candles = incoming
        self.structure_events = tuple(structure_events)
        true_ranges: list[Decimal] = []
        for index, candle in enumerate(self.candles):
            if index == 0:
                true_ranges.append(candle.high - candle.low)
            else:
                previous = self.candles[index - 1].close
                true_ranges.append(
                    max(
                        candle.high - candle.low,
                        abs(candle.high - previous),
                        abs(candle.low - previous),
                    )
                )
        timestamp_to_index = {
            item.timestamp: index for index, item in enumerate(self.candles)
        }
        interval = timeframe_duration(self.timeframe)
        for event in self.structure_events:
            ref = structure_event_reference(event)
            if ref in self.legs_by_event:
                continue
            existing = self.evaluations_by_event.get(ref)
            if existing is not None and existing.status in {
                DisplacementCandidateStatus.REJECTED,
                DisplacementCandidateStatus.EXPIRED,
            }:
                continue
            start = timestamp_to_index[event.timestamp]
            candidate_id = f"DISPLACEMENT:{ref}"
            direction = (
                DisplacementDirection.BULLISH
                if event.direction is StructureDirection.BULLISH
                else DisplacementDirection.BEARISH
            )
            if event.type not in {StructureEventType.BOS, StructureEventType.MSS}:
                self.evaluations_by_event[ref] = DisplacementEvaluation(
                    candidate_id=candidate_id,
                    direction=direction,
                    status=DisplacementCandidateStatus.REJECTED,
                    start_bar_index=start,
                    start_timestamp=event.timestamp,
                    last_evaluated_bar_index=None,
                    last_evaluated_at=None,
                    strength_metrics=None,
                    associated_fvg=(),
                    associated_structure_break=ref,
                    reason_codes=(
                        DisplacementRejectionCode.UNSUPPORTED_STRUCTURE_EVENT,
                    ),
                )
                continue
            baseline_start = start - self.config.displacement_atr_period
            if baseline_start < 0:
                self.evaluations_by_event[ref] = DisplacementEvaluation(
                    candidate_id=candidate_id,
                    direction=direction,
                    status=DisplacementCandidateStatus.REJECTED,
                    start_bar_index=start,
                    start_timestamp=event.timestamp,
                    last_evaluated_bar_index=None,
                    last_evaluated_at=None,
                    strength_metrics=None,
                    associated_fvg=(),
                    associated_structure_break=ref,
                    reason_codes=(DisplacementRejectionCode.ATR_UNAVAILABLE,),
                )
                continue
            with localcontext(INDICATOR_DECIMAL_CONTEXT):
                baseline = sum(
                    true_ranges[baseline_start:start], start=Decimal(0)
                ) / Decimal(self.config.displacement_atr_period)
            if baseline <= 0:
                self.evaluations_by_event[ref] = DisplacementEvaluation(
                    candidate_id=candidate_id,
                    direction=direction,
                    status=DisplacementCandidateStatus.REJECTED,
                    start_bar_index=start,
                    start_timestamp=event.timestamp,
                    last_evaluated_bar_index=None,
                    last_evaluated_at=None,
                    strength_metrics=None,
                    associated_fvg=(),
                    associated_structure_break=ref,
                    reason_codes=(DisplacementRejectionCode.ATR_UNAVAILABLE,),
                )
                continue
            last_permitted = start + self.config.displacement_max_bars - 1
            available_end = min(last_permitted, len(self.candles) - 1)
            latest_metrics = None
            latest_fvg: tuple[str, ...] = ()
            latest_reasons: tuple[DisplacementRejectionCode, ...] = ()
            qualified = None
            for end in range(start, available_end + 1):
                end_close = self.candles[end].timestamp + interval
                latest_metrics = _metrics(self.candles, start, end, direction, baseline)
                latest_fvg = _matching_fvgs(
                    fvg_zones, timestamp_to_index, direction, start, end, end_close
                )
                latest_reasons = _failure_reasons(
                    latest_metrics, latest_fvg, self.config
                )
                if not latest_reasons:
                    qualified = end
                    break
            if qualified is not None:
                assert latest_metrics is not None
                end_bar = self.candles[qualified]
                self.legs_by_event[ref] = DisplacementLeg(
                    leg_id=f"LEG:{ref}:{end_bar.timestamp.isoformat()}",
                    direction=direction,
                    start_bar_index=start,
                    end_bar_index=qualified,
                    start_timestamp=self.candles[start].timestamp,
                    end_timestamp=end_bar.timestamp,
                    timestamp=end_bar.timestamp,
                    confirmed_at=end_bar.timestamp + interval,
                    strength_metrics=latest_metrics,
                    associated_fvg=latest_fvg,
                    associated_structure_break=ref,
                )
                self.evaluations_by_event.pop(ref, None)
            else:
                assert latest_metrics is not None
                self.evaluations_by_event[ref] = DisplacementEvaluation(
                    candidate_id=candidate_id,
                    direction=direction,
                    status=DisplacementCandidateStatus.EXPIRED
                    if available_end == last_permitted
                    else DisplacementCandidateStatus.CANDIDATE,
                    start_bar_index=start,
                    start_timestamp=event.timestamp,
                    last_evaluated_bar_index=available_end,
                    last_evaluated_at=self.candles[available_end].timestamp + interval,
                    strength_metrics=latest_metrics,
                    associated_fvg=latest_fvg,
                    associated_structure_break=ref,
                    reason_codes=latest_reasons,
                )

    def result(self) -> DisplacementAnalysisResult:
        order = {
            structure_event_reference(event): index
            for index, event in enumerate(self.structure_events)
        }
        return DisplacementAnalysisResult(
            timeframe=self.timeframe,
            config=self.config,
            candle_count=len(self.candles),
            data_cutoff_at=(
                self.candles[-1].timestamp + timeframe_duration(self.timeframe)
                if self.candles
                else None
            ),
            legs=[
                self.legs_by_event[key]
                for key in sorted(self.legs_by_event, key=lambda item: order[item])
            ],
            evaluations=[
                self.evaluations_by_event[key]
                for key in sorted(
                    self.evaluations_by_event, key=lambda item: order[item]
                )
            ],
        )


@dataclass
class _OrderBlockIncrementalState:
    timeframe: Timeframe
    config: OrderBlockConfig
    candles: tuple[Candle, ...] = ()
    structure_events: tuple[StructureBreakEvent, ...] = ()
    order_blocks: list[_OrderBlockState] = field(default_factory=list)
    breakers: list[_BreakerState] = field(default_factory=list)
    rejections: list[OrderBlockRejection] = field(default_factory=list)
    processed_events: set[str] = field(default_factory=set)

    def reset(self) -> None:
        self.candles = ()
        self.structure_events = ()
        self.order_blocks.clear()
        self.breakers.clear()
        self.rejections.clear()
        self.processed_events.clear()

    def append(
        self,
        candles: Sequence[Candle],
        structure_events: Sequence[StructureBreakEvent],
        *,
        qualified_displacements: Sequence[OrderBlockDisplacementLink],
        confirmed_swings: Sequence[ConfirmedSwing],
        liquidity_pools: Sequence[Any],
        atr_result: ATRResult | None,
    ) -> None:
        incoming = tuple(candles)
        if not _prefix_ok(self.candles, incoming):
            self.reset()
        old_count = len(self.candles)
        self.candles = incoming
        self.structure_events = tuple(structure_events)
        interval = timeframe_duration(self.timeframe)
        timestamp_to_index = {
            item.timestamp: index for index, item in enumerate(self.candles)
        }
        close_to_index = {
            item.timestamp + interval: index for index, item in enumerate(self.candles)
        }
        cutoff = self.candles[-1].timestamp + interval if self.candles else None

        # A structure event first becomes available at its own confirmation;
        # creation is therefore append-only and can never be rewritten by a
        # later liquidity member.
        for event in self.structure_events:
            event_ref = structure_event_reference(event)
            if (
                event_ref in self.processed_events
                or cutoff is None
                or event.confirmed_at > cutoff
            ):
                continue
            self.processed_events.add(event_ref)
            available = sorted(
                (
                    item
                    for item in qualified_displacements
                    if item.structure_event == event_ref and item.confirmed_at <= cutoff
                ),
                key=lambda item: (item.confirmed_at, item.displacement_id),
            )
            if self.config.ob_require_displacement and not available:
                self.rejections.append(
                    OrderBlockRejection(
                        code=OrderBlockRejectionCode.DISPLACEMENT_REQUIRED,
                        structure_event=event_ref,
                        rejected_at=event.confirmed_at,
                    )
                )
                continue
            creation_time = (
                max(event.confirmed_at, available[0].confirmed_at)
                if self.config.ob_require_displacement
                else event.confirmed_at
            )
            creation_index = close_to_index[creation_time]
            candidate = _select_candidate(
                direction=_ob_direction(event),
                break_index=timestamp_to_index[event.timestamp],
                candles=self.candles,
                confirmed_swings=confirmed_swings,
                liquidity_pools=liquidity_pools,
                atr_result=atr_result,
                config=self.config,
            )
            if candidate is None:
                self.rejections.append(
                    OrderBlockRejection(
                        code=OrderBlockRejectionCode.OB_NO_CANDIDATE,
                        structure_event=event_ref,
                        rejected_at=event.confirmed_at,
                    )
                )
                continue
            self.order_blocks.append(
                _new_order_block(
                    event=event,
                    event_ref=event_ref,
                    direction=_ob_direction(event),
                    candidate=candidate,
                    created_at=creation_time,
                    created_bar_index=creation_index,
                    creation_candle=self.candles[creation_index],
                    displacement_confirmed=bool(
                        available and available[0].confirmed_at <= creation_time
                    ),
                    config=self.config,
                )
            )

        for bar_index in range(old_count, len(self.candles)):
            candle = self.candles[bar_index]
            confirmed_at = candle.timestamp + interval
            for zone in self.order_blocks:
                if bar_index < zone.created_bar_index or zone.status in {
                    OrderBlockStatus.INVALIDATED,
                    OrderBlockStatus.EXPIRED,
                }:
                    continue
                if zone.status is OrderBlockStatus.CANDIDATE:
                    if _validation_passes(zone, candle, self.config):
                        _append_ob_event(
                            zone,
                            OrderBlockEventType.OB_VALIDATED,
                            candle,
                            confirmed_at,
                            OrderBlockStatus.VALIDATED,
                        )
                        zone.validated_at = confirmed_at
                        zone.validation_bar_index = bar_index
                    elif (
                        bar_index - zone.created_bar_index + 1
                        >= self.config.ob_validation_max_bars
                    ):
                        _append_ob_event(
                            zone,
                            OrderBlockEventType.OB_EXPIRED,
                            candle,
                            confirmed_at,
                            OrderBlockStatus.EXPIRED,
                        )
                    continue
                assert zone.validated_at is not None
                if candle.timestamp <= zone.validated_at:
                    continue
                if _hard_invalidation(
                    zone.direction, zone.zone_low, zone.zone_high, candle, self.config
                ):
                    _append_ob_event(
                        zone,
                        OrderBlockEventType.OB_INVALIDATED,
                        candle,
                        confirmed_at,
                        OrderBlockStatus.INVALIDATED,
                    )
                    zone.invalidated_at = confirmed_at
                    if self.config.breaker_enabled:
                        self.breakers.append(
                            _new_breaker(zone, candle, confirmed_at, bar_index)
                        )
                    continue
                overlap = candle.low <= zone.zone_high and candle.high >= zone.zone_low
                if (
                    zone.status is OrderBlockStatus.VALIDATED
                    and overlap
                    and _midpoint_holds(zone, candle, self.config)
                ):
                    _append_ob_event(
                        zone,
                        OrderBlockEventType.OB_MITIGATED,
                        candle,
                        confirmed_at,
                        OrderBlockStatus.MITIGATED,
                        mean_threshold_held=True,
                    )
                    zone.mitigated_at = confirmed_at
                assert zone.validation_bar_index is not None
                if (
                    zone.status
                    in {OrderBlockStatus.VALIDATED, OrderBlockStatus.MITIGATED}
                    and bar_index - zone.validation_bar_index
                    > self.config.ob_max_age_bars
                ):
                    _append_ob_event(
                        zone,
                        OrderBlockEventType.OB_EXPIRED,
                        candle,
                        confirmed_at,
                        OrderBlockStatus.EXPIRED,
                    )
            for breaker in self.breakers:
                if (
                    breaker.status
                    in {BreakerBlockStatus.INVALIDATED, BreakerBlockStatus.EXPIRED}
                    or bar_index <= breaker.created_bar_index
                ):
                    continue
                if breaker.status is BreakerBlockStatus.CANDIDATE:
                    overlap = (
                        candle.low <= breaker.zone_high
                        and candle.high >= breaker.zone_low
                    )
                    activation = overlap and (
                        candle.close > breaker.zone_high
                        if breaker.direction.value == "BULLISH"
                        else candle.close < breaker.zone_low
                    )
                    if activation:
                        _append_breaker_event(
                            breaker,
                            OrderBlockEventType.BREAKER_ACTIVATED,
                            candle,
                            confirmed_at,
                            BreakerBlockStatus.ACTIVE,
                        )
                        breaker.activated_at = confirmed_at
                        breaker.activation_bar_index = bar_index
                    elif (
                        bar_index - breaker.created_bar_index
                        > self.config.breaker_retest_max_bars
                    ):
                        _append_breaker_event(
                            breaker,
                            OrderBlockEventType.BREAKER_EXPIRED,
                            candle,
                            confirmed_at,
                            BreakerBlockStatus.EXPIRED,
                        )
                    continue
                assert breaker.activation_bar_index is not None
                if bar_index > breaker.activation_bar_index and _hard_invalidation(
                    breaker.direction,
                    breaker.zone_low,
                    breaker.zone_high,
                    candle,
                    self.config,
                ):
                    _append_breaker_event(
                        breaker,
                        OrderBlockEventType.BREAKER_INVALIDATED,
                        candle,
                        confirmed_at,
                        BreakerBlockStatus.INVALIDATED,
                    )
                    breaker.invalidated_at = confirmed_at

    def result(self) -> OrderBlockAnalysisResult:
        return OrderBlockAnalysisResult(
            timeframe=self.timeframe,
            config=self.config,
            candle_count=len(self.candles),
            data_cutoff_at=(
                self.candles[-1].timestamp + timeframe_duration(self.timeframe)
                if self.candles
                else None
            ),
            order_blocks=[
                _to_order_block_schema(zone, self.config) for zone in self.order_blocks
            ],
            breaker_blocks=[_to_breaker_schema(item) for item in self.breakers],
            rejections=list(self.rejections),
        )


class IncrementalDeterministicStrategyEngine(OptimizedDeterministicStrategyEngine):
    """P3 append-state engine with the reference orchestration call graph.

    This class is intentionally distinct from the P1 implementation.  It
    reuses the same inherited ``evaluate`` method and only replaces feature
    seams with append-only state.  The runner/lifecycle/execution layers are
    unchanged and can call this class wherever a
    ``DeterministicStrategyEngine`` is accepted.
    """

    def __init__(self, config) -> None:
        super().__init__(config)
        self._active_symbol: MarketSymbol | None = None
        self._p3_structures: dict[tuple[MarketSymbol, Timeframe], _StructureState] = {}
        self._p3_indicators: dict[tuple[MarketSymbol, Timeframe], _IndicatorState] = {}
        self._p3_fvgs: dict[tuple[MarketSymbol, Timeframe], _FVGState] = {}
        self._p3_liquidity: dict[tuple[MarketSymbol, Timeframe], _LiquidityState] = {}
        self._p3_displacement: dict[
            tuple[MarketSymbol, Timeframe], _DisplacementState
        ] = {}
        self._p3_order_blocks: dict[
            tuple[MarketSymbol, Timeframe], _OrderBlockIncrementalState
        ] = {}

    def reset_state(self) -> None:
        self._active_symbol = None
        self._incremental_states.clear()
        self._p3_structures.clear()
        self._p3_indicators.clear()
        self._p3_fvgs.clear()
        self._p3_liquidity.clear()
        self._p3_displacement.clear()
        self._p3_order_blocks.clear()

    def state_hash(self) -> str:
        """Diagnostic hash of retained state, not a Strategy/Backtest identity.

        Includes pending candidates, recursive seeds and lifecycle histories.
        No object addresses, wall clock or final-decision-only proxy is used.
        Callers must not treat this diagnostic format as persisted state.
        """

        def canonical(value: Any) -> Any:
            if isinstance(value, BaseModel):
                return canonical(value.model_dump(mode="python"))
            if is_dataclass(value) and not isinstance(value, type):
                return {
                    item.name: canonical(getattr(value, item.name))
                    for item in fields(value)
                }
            if isinstance(value, Enum):
                return canonical(value.value)
            if isinstance(value, (Decimal, datetime)):
                return str(value)
            if isinstance(value, dict):
                pairs = [
                    [canonical(key), canonical(item)] for key, item in value.items()
                ]
                return sorted(
                    pairs, key=lambda pair: json.dumps(pair[0], sort_keys=True)
                )
            if isinstance(value, (set, frozenset)):
                return sorted(
                    (canonical(item) for item in value),
                    key=lambda item: json.dumps(item, sort_keys=True),
                )
            if isinstance(value, (tuple, list)):
                return [canonical(item) for item in value]
            if value is None or isinstance(value, (str, int, bool)):
                return value
            raise TypeError(
                f"unsupported diagnostic state type: {type(value).__name__}"
            )

        state = {
            name: value
            for name, value in vars(self).items()
            if name.startswith("_p3_") or name == "_incremental_states"
        }
        encoded = json.dumps(
            canonical(state), sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
        return sha256(encoded).hexdigest()

    def _structure_state(self, symbol, timeframe, config):
        key = (symbol, timeframe)
        state = self._p3_structures.get(key)
        if state is None:
            state = _StructureState(timeframe, config)
            self._p3_structures[key] = state
        return state

    def _analyze_market_structure(self, candles, timeframe, config):
        # Symbol is supplied by the current evaluation through a transient
        # key set in _build_candles_by_target; this avoids changing the shared
        # reference method signature.
        symbol = self._active_symbol
        state = self._structure_state(symbol, timeframe, config)
        state.append(candles)
        return state.result()

    def _calculate_indicators(self, candles, *, timeframe, macd_config, atr_config):
        assert self._active_symbol is not None
        key = (self._active_symbol, timeframe)
        state = self._p3_indicators.get(key)
        if state is None:
            state = _IndicatorState(timeframe, macd_config, atr_config)
            self._p3_indicators[key] = state
        state.append(candles)
        return state.result()

    def _analyze_fvg(self, candles, timeframe, config, *, atr_result):
        assert self._active_symbol is not None
        key = (self._active_symbol, timeframe)
        state = self._p3_fvgs.get(key)
        if state is None:
            state = _FVGState(timeframe, config)
            self._p3_fvgs[key] = state
        state.append(candles, atr_result)
        return state.result(atr_result)

    def _analyze_liquidity(
        self, candles, timeframe, confirmed_swings, config, atr_result
    ):
        assert self._active_symbol is not None
        key = (self._active_symbol, timeframe)
        state = self._p3_liquidity.get(key)
        if state is None:
            state = _LiquidityState(timeframe, config)
            self._p3_liquidity[key] = state
        state.append(candles, confirmed_swings, atr_result)
        return state.result()

    def _analyze_displacement(
        self, candles, timeframe, structure_events, config, *, fvg_zones
    ):
        assert self._active_symbol is not None
        key = (self._active_symbol, timeframe)
        state = self._p3_displacement.get(key)
        if state is None:
            state = _DisplacementState(timeframe, config)
            self._p3_displacement[key] = state
        state.append(candles, structure_events, fvg_zones)
        return state.result()

    def _analyze_order_blocks(
        self,
        candles,
        timeframe,
        structure_events,
        config,
        *,
        qualified_displacements,
        confirmed_swings,
        liquidity_pools,
        atr_result,
    ):
        assert self._active_symbol is not None
        # Delayed displacement can create a previously rejected OB and affect
        # chronological breaker ordering. Keep the reference for these modes.
        if config.ob_require_displacement or config.breaker_enabled:
            return super()._analyze_order_blocks(
                candles,
                timeframe,
                structure_events,
                config,
                qualified_displacements=qualified_displacements,
                confirmed_swings=confirmed_swings,
                liquidity_pools=liquidity_pools,
                atr_result=atr_result,
            )
        key = (self._active_symbol, timeframe)
        state = self._p3_order_blocks.get(key)
        if state is None:
            state = _OrderBlockIncrementalState(timeframe, config)
            self._p3_order_blocks[key] = state
        state.append(
            candles,
            structure_events,
            qualified_displacements=qualified_displacements,
            confirmed_swings=confirmed_swings,
            liquidity_pools=liquidity_pools,
            atr_result=atr_result,
        )
        return state.result()

    def _build_candles_by_target(self, source_candles, as_of, config, *, symbol):
        self._active_symbol = symbol
        return super()._build_candles_by_target(
            source_candles, as_of, config, symbol=symbol
        )
