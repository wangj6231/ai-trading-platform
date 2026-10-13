"""Indexed, event-driven scheduling of the unchanged per-sweep ICT rules.

Only the scheduler and candidate lookup change. The shared reference helper owns
all predicates, retest precedence, invalidation and levels. No external validator
is disabled. Historical outputs remain immutable; expiry is not assumed terminal.
"""
from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
import json
from typing import Any

from app.engines.ict import high_probability_entry as reference
from app.engines.structure.references import structure_event_reference
from app.market_data.timeframes import timeframe_duration
from app.schemas.candle import Candle
from app.schemas.displacement import DisplacementLeg
from app.schemas.entry_setup import (
    CompositeEntrySetup, EntrySetupAnalysisResult, EntrySetupConfig,
    EntrySetupReasonCode, EntrySetupStatus, SetupEntryZoneSource,
    SetupInvalidationSource,
)
from app.schemas.fvg import GapZone
from app.schemas.indicator import ATRResult
from app.schemas.liquidity import DualSweepGroup, LiquidityInteraction, LiquidityInteractionType
from app.schemas.order_block import OrderBlockZone
from app.schemas.structure import StructureBreakEvent, StructureDirection, StructureEventType
from app.schemas.types import Timeframe


@dataclass
class _TimeIndex:
    keys: list[tuple[datetime, str]] = field(default_factory=list)
    values: list[Any] = field(default_factory=list)

    def insert(self, value: Any, stable_id: str) -> None:
        key = (value.confirmed_at, stable_id)
        position = bisect_right(self.keys, key)
        self.keys.insert(position, key)
        self.values.insert(position, value)

    def after(self, timestamp: datetime) -> Any | None:
        # Bisect on timestamp alone excludes ALL same-time IDs, including Unicode.
        position = bisect_right(self.keys, timestamp, key=lambda item: item[0])
        return self.values[position] if position < len(self.values) else None


_CLOCK_REASONS = {
    EntrySetupReasonCode.SETUP_TOTAL_EXPIRED,
    EntrySetupReasonCode.MSS_STAGE_EXPIRED,
    EntrySetupReasonCode.DISPLACEMENT_STAGE_EXPIRED,
}


@dataclass
class HotICTState:
    timeframe: Timeframe
    config: EntrySetupConfig
    candles: tuple[Candle, ...] = ()
    timestamp_to_index: dict[datetime, int] = field(default_factory=dict)
    close_to_index: dict[datetime, int] = field(default_factory=dict)
    interactions: dict[str, LiquidityInteraction] = field(default_factory=dict)
    structures: dict[str, StructureBreakEvent] = field(default_factory=dict)
    displacement: dict[str, DisplacementLeg] = field(default_factory=dict)
    zones: dict[str, GapZone] = field(default_factory=dict)
    mss: dict[StructureDirection, _TimeIndex] = field(default_factory=dict)
    taken: dict[str, _TimeIndex] = field(default_factory=dict)
    legs: dict[tuple[str, Any], _TimeIndex] = field(default_factory=dict)
    sweeps: _TimeIndex = field(default_factory=_TimeIndex)
    dual_ids: set[str] = field(default_factory=set)
    results: dict[str, CompositeEntrySetup] = field(default_factory=dict)
    pending: set[str] = field(default_factory=set)
    clock_only: set[str] = field(default_factory=set)
    zone_dependents: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    # Deterministic content versions, not trusted StrategyIdentity hashes. XOR
    # of keyed SHA-256 leaves is insertion-order independent and supports deltas.
    versions: dict[str, int] = field(default_factory=dict)
    zone_hot: set[str] = field(default_factory=set)
    deadlines: dict[int, set[str]] = field(default_factory=dict)
    deadline_keys: list[int] = field(default_factory=list)
    scheduled: dict[str, int] = field(default_factory=dict)
    empty_projection: EntrySetupAnalysisResult = field(init=False)

    def __post_init__(self):
        self.empty_projection = EntrySetupAnalysisResult(timeframe=self.timeframe,
            config=self.config, candle_count=0, data_cutoff_at=None, setups=[])

    def _version(self, family, identity, old, new):
        value = self.versions.get(family, 0)
        for item in (old, new):
            if item is not None:
                encoded = json.dumps([identity, item.model_dump(mode='json')], sort_keys=True, separators=(',', ':'), allow_nan=False)
                value ^= int.from_bytes(sha256(encoded.encode()).digest(), 'big')
        if value:
            self.versions[family] = value
        else:
            self.versions.pop(family, None)

    def _schedule(self, identity, deadline):
        previous = self.scheduled.pop(identity, None)
        if previous is not None:
            self.deadlines[previous].discard(identity)
            if not self.deadlines[previous]:
                del self.deadlines[previous]
                self.deadline_keys.remove(previous)
        if deadline is not None:
            if deadline not in self.deadlines:
                self.deadline_keys.insert(bisect_right(self.deadline_keys, deadline), deadline)
                self.deadlines[deadline] = set()
            self.deadlines[deadline].add(identity)
            self.scheduled[identity] = deadline

    def _evaluate_owned(self, liquidity, structure, displacement, fvg, *, atr_result):
        """Private engine-owned source adapter; never accepts a trusted=True flag.

        The coordinator owns these states after its unchanged input/PIT boundary.
        Arbitrary sequence clients use evaluate(), which ALWAYS fully validates.
        New/rewritten candle prefixes also go through that full boundary here.
        """
        candles = liquidity.candles
        if (not self.candles or len(candles) < len(self.candles)
                or candles[:len(self.candles)] != self.candles):
            return self.evaluate(candles, liquidity.interactions, structure.events,
                displacement.ict_leg_values, fvg.projections,
                dual_sweeps=liquidity.dual_sweeps, atr_result=atr_result)
        interval = timeframe_duration(self.timeframe)
        previous_cutoff = self.candles[-1].timestamp + interval
        new_events = liquidity.interactions[len(self.interactions):]
        new_structures = structure.events[len(self.structures):]
        new_legs = displacement.ict_legs_after(previous_cutoff)
        # Active IDs include just-terminal transitions retained from the prior
        # cutoff. The immutable terminal archive is not repeatedly scanned.
        changed_ids = self.zone_hot | fvg.active.keys()
        changed_ids.update(zone.zone_id for zone in fvg.projections[len(self.zones):])
        changed_zones = [fvg.projections[fvg.positions[key]] for key in sorted(changed_ids)
            if self.zones.get(key) != fvg.projections[fvg.positions[key]]]
        added_timestamps = set()
        added_closes = set()
        for index in range(len(self.candles), len(candles)):
            candle = candles[index]
            if candle.timestamp - candles[index-1].timestamp != interval:
                raise reference.EntrySetupInputError('candle sequence contains a timeframe gap')
            for name in ('open','high','low','close'):
                if getattr(candle, name) % self.config.tick_size:
                    raise reference.EntrySetupInputError(f'candle {name} price is not aligned to tick_size')
            added_timestamps.add(candle.timestamp)
            added_closes.add(candle.timestamp+interval)
        for item in (*new_events, *new_structures, *new_legs):
            if ((item.timestamp not in self.timestamp_to_index and item.timestamp not in added_timestamps)
                    or (item.confirmed_at not in self.close_to_index and item.confirmed_at not in added_closes)):
                raise reference.EntrySetupInputError('new event must align with an available candle')
        for zone in changed_zones:
            if zone.confirmed_at not in self.close_to_index and zone.confirmed_at not in added_closes:
                raise reference.EntrySetupInputError('FVG confirmation must align with an available candle')
        if atr_result is not None:
            if len(atr_result.points) != len(candles):
                raise reference.EntrySetupInputError('ATR points must align one-to-one with candles')
            for index in range(len(self.candles), len(candles)):
                if candles[index].timestamp != atr_result.points[index].timestamp:
                    raise reference.EntrySetupInputError('ATR timestamps must align with candle timestamps')
        return self._advance(candles, new_events, new_structures, new_legs, changed_zones,
            dual_sweeps=liquidity.dual_sweeps, order_blocks=(), atr_result=atr_result)

    def reset(self) -> None:
        fresh = type(self)(self.timeframe, self.config)
        self.__dict__.update(fresh.__dict__)

    def _requires_rebuild(self, candles, interactions, structures, legs) -> bool:
        if len(candles) < len(self.candles) or tuple(candles[:len(self.candles)]) != self.candles:
            return True
        previous_cutoff = self.candles[-1].timestamp + timeframe_duration(self.timeframe) if self.candles else None
        for items, retained, key in (
            (interactions, self.interactions, lambda item: item.event_id),
            (structures, self.structures, structure_event_reference),
            (legs, self.displacement, lambda item: item.leg_id),
        ):
            present = {key(item): item for item in items}
            if not retained.keys() <= present.keys():
                return True
            for identity, item in present.items():
                old = retained.get(identity)
                if old is not None and old != item:
                    return True
                if old is None and previous_cutoff is not None and item.confirmed_at <= previous_cutoff:
                    return True
        return False

    def evaluate(
        self,
        candles: Sequence[Candle],
        liquidity_events: Sequence[LiquidityInteraction],
        structure_events: Sequence[StructureBreakEvent],
        displacement_events: Sequence[DisplacementLeg],
        fvg_zones: Sequence[GapZone],
        *,
        dual_sweeps: Sequence[DualSweepGroup] = (),
        order_blocks: Sequence[OrderBlockZone] = (),
        atr_result: ATRResult | None = None,
    ) -> EntrySetupAnalysisResult:
        reference._validate_inputs(candles, self.timeframe, liquidity_events, structure_events,
                                   displacement_events, fvg_zones, self.config, atr_result)
        # OB-dependent selection retains the oracle until its point-in-time query
        # frontier is independently proven. Duplicate IDs retain reference behavior.
        needs_ob = self.config.signal_entry_zone_source is not SetupEntryZoneSource.FVG or self.config.setup_invalidation_source is SetupInvalidationSource.ORDER_BLOCK_EXTREME
        duplicate_ids = (
            len({item.event_id for item in liquidity_events}) != len(liquidity_events)
            or len({structure_event_reference(item) for item in structure_events}) != len(structure_events)
            or len({item.leg_id for item in displacement_events}) != len(displacement_events)
            or len({item.zone_id for item in fvg_zones}) != len(fvg_zones)
        )
        if not candles or needs_ob or duplicate_ids:
            self.reset()
            return reference.detect_high_probability_entry_setups(candles, self.timeframe, liquidity_events,
                structure_events, displacement_events, fvg_zones, self.config,
                dual_sweeps=dual_sweeps, order_blocks=order_blocks, atr_result=atr_result)
        if self._requires_rebuild(candles, liquidity_events, structure_events, displacement_events):
            self.reset()
        changed_zones = [zone for zone in fvg_zones if self.zones.get(zone.zone_id) != zone]
        removed_zones = self.zones.keys() - {zone.zone_id for zone in fvg_zones}
        return self._advance(candles,
            [event for event in liquidity_events if event.event_id not in self.interactions],
            [event for event in structure_events if structure_event_reference(event) not in self.structures],
            [leg for leg in displacement_events if leg.leg_id not in self.displacement],
            changed_zones, dual_sweeps=dual_sweeps, order_blocks=order_blocks,
            atr_result=atr_result, removed_zones=removed_zones)

    def _advance(self, candles, liquidity_events, structure_events, displacement_events,
                 fvg_zones, *, dual_sweeps, order_blocks, atr_result, removed_zones=()):
        """Consume validated deltas; no second strategy implementation."""
        interval = timeframe_duration(self.timeframe)
        cutoff = candles[-1].timestamp + interval
        for index in range(len(self.candles), len(candles)):
            self.timestamp_to_index[candles[index].timestamp] = index
            self.close_to_index[candles[index].timestamp + interval] = index
        self.candles = tuple(candles)
        dirty = set(self.pending)
        # Expiry is itself an event: a stage-expired explanation can later become
        # total-expired without new market evidence. Wake the shared rule exactly
        # when its total deadline is exceeded; do not synthesize a new reason.
        while self.deadline_keys and self.deadline_keys[0] <= len(candles)-1:
            deadline = self.deadline_keys.pop(0)
            for identity in self.deadlines.pop(deadline):
                self.scheduled.pop(identity)
                dirty.add(identity)
        for event in liquidity_events:
            if event.event_id in self.interactions:
                continue
            self.interactions[event.event_id] = event
            self._version('sweep' if event.type is LiquidityInteractionType.SWEEP else 'taken', event.event_id, None, event)
            if event.type is LiquidityInteractionType.SWEEP:
                self.sweeps.insert(event, event.event_id)
                dirty.add(event.event_id)
            elif event.type is LiquidityInteractionType.TAKEN:
                self.taken.setdefault(event.pool_id, _TimeIndex()).insert(event, event.event_id)
                dirty.update(identity for identity in self.clock_only
                    if self.interactions[identity].pool_id == event.pool_id
                    and ((matched := self.results[identity].structure_event) is None
                         or event.confirmed_at <= matched.confirmed_at))
        for structure_event in structure_events:
            ref = structure_event_reference(structure_event)
            if ref not in self.structures:
                self.structures[ref] = structure_event
                self._version('structure', ref, None, structure_event)
                if structure_event.type is StructureEventType.MSS:
                    self._version('mss', ref, None, structure_event)
                    self.mss.setdefault(structure_event.direction, _TimeIndex()).insert(structure_event, ref)
                    for identity in self.clock_only:
                        sweep = self.interactions[identity]
                        result = self.results[identity]
                        desired = reference._desired_structure_direction(result.direction)
                        if structure_event.confirmed_at <= sweep.confirmed_at:
                            continue
                        if structure_event.direction is not desired:
                            dirty.add(identity)
                        elif result.structure_event is None and (
                            self.close_to_index[structure_event.confirmed_at] - self.close_to_index[sweep.confirmed_at]
                            <= min(self.config.signal_max_bars_sweep_to_mss, self.config.signal_setup_max_total_bars)
                        ):
                            dirty.add(identity)
        for leg in displacement_events:
            if leg.leg_id not in self.displacement:
                self.displacement[leg.leg_id] = leg
                self._version('displacement', leg.leg_id, None, leg)
                self.legs.setdefault((leg.associated_structure_break, leg.direction), _TimeIndex()).insert(leg, leg.leg_id)
                dirty.update(identity for identity in self.clock_only
                    if (matched := self.results[identity].structure_event) is not None
                    and structure_event_reference(matched) == leg.associated_structure_break)
        dual_ids = {identity for group in dual_sweeps for identity in (*group.buy_side_event_ids, *group.sell_side_event_ids)}
        dirty.update((dual_ids ^ self.dual_ids) & self.interactions.keys())
        self.dual_ids = dual_ids
        for identity in removed_zones:
            self._version('fvg', identity, self.zones.pop(identity), None)
            self.zone_hot.discard(identity)
            dirty.update(self.zone_dependents.get(identity, ()))
        for zone in fvg_zones:
            identity = zone.zone_id
            self._version('fvg', identity, self.zones.get(identity), zone)
            self.zones[identity] = zone
            if zone.lifecycle_state in reference.TERMINAL_FVG_STATES:
                self.zone_hot.discard(identity)
            else:
                self.zone_hot.add(identity)
            dirty.update(self.zone_dependents.get(identity, ()))
        for identity in sorted(dirty, key=lambda key: (self.interactions[key].confirmed_at, key)):
            sweep = self.interactions[identity]
            direction = reference._direction_from_sweep(sweep)
            desired = reference._desired_structure_direction(direction)
            opposite = StructureDirection.BEARISH if desired is StructureDirection.BULLISH else StructureDirection.BULLISH
            selected_mss = self.mss.get(desired, _TimeIndex()).after(sweep.confirmed_at)
            first_opposite = self.mss.get(opposite, _TimeIndex()).after(sweep.confirmed_at)
            sweep_index = self.close_to_index[sweep.confirmed_at]
            if selected_mss is not None and self.close_to_index[selected_mss.confirmed_at] - sweep_index > min(self.config.signal_max_bars_sweep_to_mss, self.config.signal_setup_max_total_bars):
                selected_mss = None
            selected_leg = None
            if selected_mss is not None:
                key = (structure_event_reference(selected_mss), reference._desired_displacement_direction(direction))
                selected_leg = self.legs.get(key, _TimeIndex()).after(selected_mss.confirmed_at)
                if selected_leg is not None and (
                    self.close_to_index[selected_leg.confirmed_at] - self.close_to_index[selected_mss.confirmed_at] > self.config.signal_max_bars_mss_to_displacement
                    or self.close_to_index[selected_leg.confirmed_at] - sweep_index > self.config.signal_setup_max_total_bars
                ):
                    selected_leg = None
            linked = []
            if selected_leg is not None:
                for zone_id in selected_leg.associated_fvg:
                    if zone_id in self.zones:
                        linked.append(self.zones[zone_id])
            taken = self.taken.get(sweep.pool_id, _TimeIndex()).after(sweep.confirmed_at)
            result = reference._evaluate_sweep(sweep, candles=candles, interval=interval, cutoff=cutoff,
                timestamp_to_index=self.timestamp_to_index, close_to_index=self.close_to_index,
                current_index=len(candles)-1, dual_event_ids=dual_ids,
                taken_events=[taken] if taken is not None else [],
                mss_events=sorted([item for item in (selected_mss, first_opposite) if item is not None], key=lambda item: (item.confirmed_at, structure_event_reference(item))),
                legs=[selected_leg] if selected_leg is not None else [], fvg_zones=linked,
                config=self.config, order_blocks=order_blocks, atr_result=atr_result)
            # Subscribe only when the authoritative helper actually reached the
            # displacement/FVG stage. Early rejection can make a syntactically
            # matching leg irrelevant; visiting it only during bulk rebuild must
            # not create path-dependent subscriptions. Keep ALL associated IDs,
            # including missing FVGs, so later visible versions still wake setups.
            previous = self.results.get(identity)
            previous_links = set(previous.displacement_event.associated_fvg) if previous is not None and previous.displacement_event is not None else set()
            current_links = set(result.displacement_event.associated_fvg) if result.displacement_event is not None else set()
            for zone_id in previous_links - current_links:
                subscribers = self.zone_dependents[zone_id]
                subscribers.discard(identity)
                if not subscribers:
                    del self.zone_dependents[zone_id]
            for zone_id in current_links:
                self.zone_dependents[zone_id].add(identity)
            self.results[identity] = result
            self.pending.discard(identity)
            self.clock_only.discard(identity)
            next_deadline: int | None = None
            if result.setup_status is EntrySetupStatus.WAITING_RETRACE:
                self.pending.add(identity)
            elif result.fvg is None and (result.setup_status is EntrySetupStatus.FORMING or any(reason in _CLOCK_REASONS for reason in result.reason_codes)):
                self.clock_only.add(identity)
                total_deadline = sweep_index + self.config.signal_setup_max_total_bars + 1
                if len(candles)-1 < total_deadline:
                    next_deadline = total_deadline
                if result.setup_status is EntrySetupStatus.FORMING:
                    stage_deadline = (
                        sweep_index + self.config.signal_max_bars_sweep_to_mss + 1
                        if result.structure_event is None else
                        self.close_to_index[result.structure_event.confirmed_at] + self.config.signal_max_bars_mss_to_displacement + 1
                    )
                    next_deadline = min(total_deadline, stage_deadline)
            self._schedule(identity, next_deadline)
        # Reference intentionally timestamps unresolved expired stages at each
        # cutoff. Preserve that metadata without repeating historical matching.
        for identity in self.clock_only - dirty:
            self.results[identity] = self.results[identity].model_copy(update={'confirmed_at': cutoff})
        # Child projections are validated on transition; never revalidate the
        # unchanged immutable archive just to give the caller a fresh container.
        return self.empty_projection.model_copy(update={
            'candle_count':len(candles), 'data_cutoff_at':cutoff,
            'setups':[self.results[event.event_id] for event in self.sweeps.values]})
