"""P5 FVG hot lifecycle set with immutable, validated historical projections."""
from dataclasses import dataclass, field
from typing import Any

from app.engines.incremental_strategy_engine import _FVGState
from app.engines.smc.fvg import TERMINAL_STATES, _ZoneState, _to_schema
from app.market_data.timeframes import timeframe_duration
from app.schemas.fvg import FVGAnalysisResult, GapZone


@dataclass
class HotFVGState(_FVGState):
    active: dict[str, _ZoneState] = field(default_factory=dict)
    positions: dict[str, int] = field(default_factory=dict)
    projections: list[GapZone] = field(default_factory=list)
    versions: dict[str, tuple[Any, ...]] = field(default_factory=dict)
    empty_projection: FVGAnalysisResult = field(init=False)

    def __post_init__(self) -> None:
        self.empty_projection = FVGAnalysisResult(timeframe=self.timeframe,
            config=self.config, candle_count=0, data_cutoff_at=None, zones=[], rejections=[])

    def reset(self) -> None:
        super().reset()
        self.active.clear()
        self.positions.clear()
        self.projections.clear()
        self.versions.clear()

    def _add_zone(self, zone: _ZoneState) -> None:
        super()._add_zone(zone)
        self.active[zone.zone_id] = zone

    def _zones_for_update(self):
        # IFVG children are appended only after this traversal, exactly as P3.
        return self.active.values()

    def _after_bar(self) -> None:
        completed = []
        for identity, zone in self.active.items():
            # Repeated partial touches may change fields WITHOUT a lifecycle
            # event. Include every mutable semantic field, not just event count.
            version = (zone.lifecycle_state, zone.fill_fraction, zone.retest_count,
                       zone.last_updated_at, len(zone.lifecycle))
            if self.versions.get(identity) != version:
                projection = _to_schema(zone)
                position = self.positions.get(identity)
                if position is None:
                    self.positions[identity] = len(self.projections)
                    self.projections.append(projection)
                else:
                    self.projections[position] = projection
                self.versions[identity] = version
            if zone.lifecycle_state in TERMINAL_STATES:
                completed.append(identity)
        for identity in completed:
            del self.active[identity]

    def result(self, atr_result) -> FVGAnalysisResult:
        # Internal, already validated derived versions only; public trust-boundary
        # validators are unchanged. Fresh containers preserve prior outputs.
        return self.empty_projection.model_copy(update={
            'candle_count': len(self.candles),
            'data_cutoff_at': self.candles[-1].timestamp + timeframe_duration(self.timeframe) if self.candles else None,
            'zones': list(self.projections), 'rejections': list(self.rejections),
        })
