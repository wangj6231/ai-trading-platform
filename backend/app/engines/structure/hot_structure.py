"""P5 latest-relevant swing indices; inherited detector and S/R merge unchanged."""
from dataclasses import dataclass, field

from app.engines.incremental_strategy_engine import _StructureState
from app.engines.structure.primitives import _classify_trend
from app.schemas.structure import ConfirmedSwing, MarketStructureResult, SwingKind


def _sides():
    return {SwingKind.HIGH: [], SwingKind.LOW: []}


@dataclass
class HotStructureState(_StructureState):
    closed_tail: dict[SwingKind, list[ConfirmedSwing]] = field(default_factory=_sides)
    eligible_tail: dict[SwingKind, list[ConfirmedSwing]] = field(default_factory=_sides)
    unbroken: dict[SwingKind, list[ConfirmedSwing]] = field(default_factory=_sides)
    eligible_frontier: int = 0
    projection: MarketStructureResult | None = None

    def reset(self):
        super().reset()
        self.closed_tail = _sides()
        self.eligible_tail = _sides()
        self.unbroken = _sides()
        self.eligible_frontier = 0
        self.projection = None

    def append(self, candles):
        old = self.candles
        super().append(candles)
        if self.candles != old:
            self.projection = None

    def _append_zone(self, swing):
        super()._append_zone(swing)
        self._tail_append(self.closed_tail, swing)

    def _tail_append(self, sides, swing):
        values = sides[swing.kind]
        values.append(swing)
        if len(values) > self.config.trend_points_per_side:
            del values[0]

    def _break_context(self, candle):
        # P3 confirms pivots in ascending index with fixed N-right candles.
        # Close-confirmed pivots are deliberately not eligible at this bar OPEN.
        while self.eligible_frontier < len(self.confirmed):
            swing = self.confirmed[self.eligible_frontier]
            if swing.confirmed_at > candle.timestamp:
                break
            self.eligible_frontier += 1
            self._tail_append(self.eligible_tail, swing)
            values = self.unbroken[swing.kind]
            if values:
                assert (values[-1].confirmed_at, values[-1].pivot_index) <= (swing.confirmed_at, swing.pivot_index)
            values.append(swing)
        latest = {}
        for kind in SwingKind:
            values = self.unbroken[kind]
            while values and values[-1].swing_id in self.broken_ids:
                values.pop()
            latest[kind] = values[-1] if values else None
        trend = _classify_trend(self.eligible_tail[SwingKind.HIGH] + self.eligible_tail[SwingKind.LOW], self.config)
        return trend, latest[SwingKind.HIGH], latest[SwingKind.LOW]

    def _result_trend(self):
        return _classify_trend(self.closed_tail[SwingKind.HIGH] + self.closed_tail[SwingKind.LOW], self.config)

    def result(self):
        if self.projection is None:
            self.projection = super().result()  # full schema validation on new-bar version
        # Cache never escapes directly: downstream callers get their own lists.
        return self.projection.model_copy(update={
            name: list(getattr(self.projection, name)) for name in (
                'candidate_swings', 'confirmed_swings', 'support_candidates',
                'resistance_candidates', 'structure_events', 'structure_rejections')
        })
