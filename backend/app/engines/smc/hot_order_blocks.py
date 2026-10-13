"""P5 OB creation frontier and active lifecycle set; reference rules unchanged."""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.engines.incremental_strategy_engine import _OrderBlockIncrementalState
from app.engines.smc.order_blocks import _OrderBlockState, _to_order_block_schema
from app.market_data.timeframes import timeframe_duration
from app.schemas.order_block import OrderBlockAnalysisResult, OrderBlockStatus, OrderBlockZone
from app.schemas.structure import StructureBreakEvent


@dataclass
class HotOrderBlockState(_OrderBlockIncrementalState):
    active: dict[str, _OrderBlockState] = field(default_factory=dict)
    projections: list[OrderBlockZone] = field(default_factory=list)
    positions: dict[str, int] = field(default_factory=dict)
    versions: dict[str, tuple[Any, ...]] = field(default_factory=dict)
    timestamp_index: dict[datetime, int] = field(default_factory=dict)
    close_index: dict[datetime, int] = field(default_factory=dict)
    event_frontier: int = 0
    future_events: dict[int, StructureBreakEvent] = field(default_factory=dict)
    empty_projection: OrderBlockAnalysisResult = field(init=False)

    def __post_init__(self):
        if self.config.breaker_enabled or self.config.ob_require_displacement:
            raise ValueError('Delayed displacement and breaker modes use the reference fallback')
        self.empty_projection = OrderBlockAnalysisResult(timeframe=self.timeframe,
            config=self.config, candle_count=0, data_cutoff_at=None,
            order_blocks=[], breaker_blocks=[], rejections=[])

    def reset(self):
        super().reset()
        self.active.clear()
        self.projections.clear()
        self.positions.clear()
        self.versions.clear()
        self.timestamp_index.clear()
        self.close_index.clear()
        self.event_frontier = 0
        self.future_events.clear()

    def append(self, candles, structure_events, **kwargs):
        incoming_events = tuple(structure_events)
        if incoming_events[:len(self.structure_events)] != self.structure_events:
            self.reset()
        super().append(candles, incoming_events, **kwargs)

    def _indices(self, interval):
        for index in range(len(self.timestamp_index), len(self.candles)):
            timestamp = self.candles[index].timestamp
            self.timestamp_index[timestamp] = index
            self.close_index[timestamp + interval] = index
        return self.timestamp_index, self.close_index

    def _events_for_creation(self, cutoff):
        for index in range(self.event_frontier, len(self.structure_events)):
            self.future_events[index] = self.structure_events[index]
        self.event_frontier = len(self.structure_events)
        available = []
        # Only not-yet-visible events need revisiting; preserve original input
        # sequence even when confirmations are not supplied in chronological order.
        for index, event in list(self.future_events.items()):
            if cutoff is not None and event.confirmed_at <= cutoff:
                available.append(event)
                del self.future_events[index]
        return available

    def _add_order_block(self, zone):
        super()._add_order_block(zone)
        self.active[zone.zone_id] = zone

    def _interaction_zones(self):
        return self.active.values()

    def _after_bar(self):
        terminal = []
        for identity, zone in self.active.items():
            version = (zone.status, zone.validated_at, zone.validation_bar_index,
                       zone.mitigated_at, zone.invalidated_at, zone.breaker_zone_id,
                       len(zone.lifecycle))
            if self.versions.get(identity) != version:
                projection = _to_order_block_schema(zone, self.config)
                position = self.positions.get(identity)
                if position is None:
                    self.positions[identity] = len(self.projections)
                    self.projections.append(projection)
                else:
                    self.projections[position] = projection
                self.versions[identity] = version
            if zone.status in {OrderBlockStatus.INVALIDATED, OrderBlockStatus.EXPIRED}:
                terminal.append(identity)
        for identity in terminal:
            del self.active[identity]

    def result(self):
        return self.empty_projection.model_copy(update={
            'candle_count': len(self.candles),
            'data_cutoff_at': self.candles[-1].timestamp + timeframe_duration(self.timeframe) if self.candles else None,
            'order_blocks': list(self.projections), 'breaker_blocks': [],
            'rejections': list(self.rejections),
        })
