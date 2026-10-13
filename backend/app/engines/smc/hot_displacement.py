"""P5 displacement append-only TR index and unresolved structure-event queue."""
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from app.engines.incremental_strategy_engine import _DisplacementState
from app.engines.structure.references import structure_event_reference
from app.market_data.timeframes import timeframe_duration
from app.schemas.displacement import DisplacementAnalysisResult, DisplacementCandidateStatus, DisplacementLeg
from app.schemas.order_block import OrderBlockDisplacementLink
from app.schemas.structure import StructureBreakEvent


@dataclass
class HotDisplacementState(_DisplacementState):
    true_ranges: list[Decimal] = field(default_factory=list)
    timestamp_index: dict[datetime, int] = field(default_factory=dict)
    event_frontier: int = 0
    pending: dict[str, StructureBreakEvent] = field(default_factory=dict)
    order_index: dict[str, int] = field(default_factory=dict)
    leg_order: list[int] = field(default_factory=list)
    evaluation_order: list[int] = field(default_factory=list)
    ict_leg_keys: list[tuple[datetime, str]] = field(default_factory=list)
    ict_leg_values: list[DisplacementLeg] = field(default_factory=list)
    ict_leg_ids: set[str] = field(default_factory=set)
    link_by_version: dict[tuple[str, str, datetime, str], OrderBlockDisplacementLink] = field(default_factory=dict)
    link_versions: list[tuple[str, str, datetime, str]] = field(default_factory=list)
    order_block_links: tuple[OrderBlockDisplacementLink, ...] = ()
    empty_projection: DisplacementAnalysisResult = field(init=False)

    def __post_init__(self):
        self.empty_projection = DisplacementAnalysisResult(timeframe=self.timeframe,
            config=self.config, candle_count=0, data_cutoff_at=None, legs=[], evaluations=[])

    def reset(self):
        super().reset()
        self.true_ranges.clear()
        self.timestamp_index.clear()
        self.event_frontier = 0
        self.pending.clear()
        self.order_index.clear()
        self.leg_order.clear()
        self.evaluation_order.clear()
        self.ict_leg_keys.clear()
        self.ict_leg_values.clear()
        self.ict_leg_ids.clear()
        self.link_by_version.clear()
        self.link_versions.clear()
        self.order_block_links = ()

    def ict_legs_after(self, cutoff: datetime | None) -> list[DisplacementLeg]:
        """Private ICT support: immutable legs ordered by their earliest known time.

        Qualification needs both the structure confirmation and leg close. This
        derived availability key is identical for bulk and sequential rebuilds;
        it is not a process-local insertion counter or a future data prepass.
        """
        position = 0 if cutoff is None else bisect_right(self.ict_leg_keys, cutoff, key=lambda item: item[0])
        return self.ict_leg_values[position:]

    def append(self, candles, structure_events, fvg_zones):
        events = tuple(structure_events)
        if events[:len(self.structure_events)] != self.structure_events:
            self.reset()
        super().append(candles, events, fvg_zones)

    def _indices(self):
        for index in range(len(self.true_ranges), len(self.candles)):
            candle = self.candles[index]
            # Identical operations/context to P3; no changed ATR recurrence.
            value = candle.high - candle.low
            if index:
                previous = self.candles[index - 1].close
                value = max(value, abs(candle.high - previous), abs(candle.low - previous))
            self.true_ranges.append(value)
            self.timestamp_index[candle.timestamp] = index
        return self.true_ranges, self.timestamp_index

    def _pending_events(self):
        for index in range(self.event_frontier, len(self.structure_events)):
            event = self.structure_events[index]
            ref = structure_event_reference(event)
            self.order_index[ref] = index
            self.pending[ref] = event
        self.event_frontier = len(self.structure_events)
        return self.pending.values()

    def _after_evaluation(self):
        resolved = []
        links_changed = False
        for ref in self.pending:
            order = self.order_index[ref]
            position = bisect_left(self.evaluation_order, order)
            if ref in self.legs_by_event:
                leg = self.legs_by_event[ref]
                if leg.leg_id not in self.ict_leg_ids:
                    event = self.structure_events[order]
                    key = (max(event.confirmed_at, leg.confirmed_at), leg.leg_id)
                    slot = bisect_right(self.ict_leg_keys, key)
                    self.ict_leg_keys.insert(slot, key)
                    self.ict_leg_values.insert(slot, leg)
                    self.ict_leg_ids.add(leg.leg_id)
                leg_position = bisect_left(self.leg_order, order)
                if leg_position == len(self.leg_order) or self.leg_order[leg_position] != order:
                    # Qualified legs are immutable within an append epoch. Full
                    # event content versions the stable reference (which alone
                    # omits price/confirmation details). Replacements reset the
                    # owner before reaching this transition; never mutate a link.
                    version = (leg.leg_id, leg.associated_structure_break,
                               leg.confirmed_at, self.structure_events[order].model_dump_json())
                    link = self.link_by_version.get(version)
                    if link is None:
                        link = OrderBlockDisplacementLink(
                            displacement_id=leg.leg_id,
                            structure_event=leg.associated_structure_break,
                            confirmed_at=leg.confirmed_at,
                        )
                        self.link_by_version[version] = link
                    self.link_versions.insert(leg_position, version)
                    self.leg_order.insert(leg_position, order)
                    links_changed = True
                if position < len(self.evaluation_order) and self.evaluation_order[position] == order:
                    self.evaluation_order.pop(position)
                resolved.append(ref)
            else:
                evaluation = self.evaluations_by_event.get(ref)
                if evaluation is None:
                    continue
                if position == len(self.evaluation_order) or self.evaluation_order[position] != order:
                    self.evaluation_order.insert(position, order)
                if evaluation.status in {DisplacementCandidateStatus.REJECTED, DisplacementCandidateStatus.EXPIRED}:
                    resolved.append(ref)
        for ref in resolved:
            del self.pending[ref]
        if links_changed:
            # Canonical structure-input order, not qualification/cache insertion
            # order. Unchanged cutoffs do not even rebuild this immutable tuple.
            self.order_block_links = tuple(self.link_by_version[key] for key in self.link_versions)

    def result(self):
        # Canonical structure-input order is maintained on transitions, never
        # re-sorted over the archive at every cutoff. Models were validated on creation.
        return self.empty_projection.model_copy(update={
            'candle_count': len(self.candles),
            'data_cutoff_at': self.candles[-1].timestamp + timeframe_duration(self.timeframe) if self.candles else None,
            'legs': [self.legs_by_event[structure_event_reference(self.structure_events[index])] for index in self.leg_order],
            'evaluations': [self.evaluations_by_event[structure_event_reference(self.structure_events[index])] for index in self.evaluation_order],
        })
