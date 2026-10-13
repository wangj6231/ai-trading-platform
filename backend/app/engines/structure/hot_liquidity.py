"""P5 liquidity hot interaction index plus validated immutable pool versions."""
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from app.engines.incremental_strategy_engine import _LiquidityState
from app.engines.structure.liquidity import TERMINAL_POOL_STATES, _PoolState, _to_schema
from app.market_data.timeframes import timeframe_duration
from app.schemas.liquidity import LiquidityAnalysisResult, LiquidityPool


@dataclass
class HotLiquidityState(_LiquidityState):
    active: dict[str, _PoolState] = field(default_factory=dict)
    positions: dict[str, int] = field(default_factory=dict)
    projections: list[LiquidityPool] = field(default_factory=list)
    versions: dict[str, int] = field(default_factory=dict)
    close_index: dict[datetime, int] = field(default_factory=dict)
    atr_index: dict[datetime, Decimal | None] = field(default_factory=dict)
    atr_present: bool = False
    empty_projection: LiquidityAnalysisResult = field(init=False)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.empty_projection = LiquidityAnalysisResult(timeframe=self.timeframe, config=self.config,
            candle_count=0, data_cutoff_at=None, pools=[], interactions=[], dual_sweeps=[])

    def reset(self) -> None:
        super().reset()
        self.active.clear()
        self.positions.clear()
        self.projections.clear()
        self.versions.clear()
        self.close_index.clear()
        self.atr_index.clear()
        self.atr_present = False

    def _indices(self, incoming, atr_result, interval):
        if atr_result is not None and len(atr_result.points) != len(incoming):
            raise ValueError('ATR points must align with candles')
        for index in range(len(self.close_index), len(incoming)):
            self.close_index[incoming[index].timestamp+interval] = index
        if (atr_result is not None) != self.atr_present:
            self.atr_index.clear()
        self.atr_present = atr_result is not None
        if atr_result is not None:
            for index in range(len(self.atr_index), len(incoming)):
                self.atr_index[incoming[index].timestamp+interval] = atr_result.points[index].atr
        return self.close_index, self.atr_index

    def _add_pool(self, pool):
        # Derived pool IDs are unique. Existing cluster membership is consumed by
        # the unchanged parent algorithm before entering this creation seam.
        super()._add_pool(pool)
        self.active[pool.pool_id] = pool

    def _interaction_pools(self):
        return self.active.values()

    def _after_bar(self) -> None:
        completed = []
        for identity, pool in self.active.items():
            version = len(pool.history)
            if self.versions.get(identity) != version:
                projection = _to_schema(pool)  # full existing pool/history validators
                position = self.positions.get(identity)
                if position is None:
                    self.positions[identity] = len(self.projections)
                    self.projections.append(projection)
                else:
                    self.projections[position] = projection
                self.versions[identity] = version
            if pool.state in TERMINAL_POOL_STATES:
                completed.append(identity)
        for identity in completed:
            del self.active[identity]

    def result(self) -> LiquidityAnalysisResult:
        # Internal projection of already validated immutable versions. New list
        # containers prevent mutation of prior results. Never accept caller-owned
        # raw models here; API/snapshot/repository serialization revalidation stays
        # unchanged. Do not globally disable nested schema validators.
        return self.empty_projection.model_copy(update={
            'candle_count': len(self.candles),
            'data_cutoff_at': self.candles[-1].timestamp+timeframe_duration(self.timeframe) if self.candles else None,
            'pools': list(self.projections),
            'interactions': list(self.interactions),
            'dual_sweeps': list(self.dual_sweeps),
        })
