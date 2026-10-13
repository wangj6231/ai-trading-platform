"""P5 engine: same reference coordinator, progressively verified hot-state seams."""
from __future__ import annotations

from dataclasses import fields, is_dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from hashlib import sha256
import json
from typing import Any

from pydantic import BaseModel

from app.engines.ict.hot_state import HotICTState
from app.engines.incremental_strategy_engine import IncrementalDeterministicStrategyEngine
from app.engines.structure.hot_liquidity import HotLiquidityState
from app.engines.smc.hot_fvg import HotFVGState
from app.engines.smc.hot_order_blocks import HotOrderBlockState
from app.engines.smc.hot_displacement import HotDisplacementState
from app.engines.structure.hot_structure import HotStructureState
from app.schemas.types import MarketSymbol, Timeframe
from app.schemas.entry_setup import SetupEntryZoneSource, SetupInvalidationSource


class HotStateDeterministicStrategyEngine(IncrementalDeterministicStrategyEngine):
    def __init__(self, config) -> None:
        super().__init__(config)
        self._p5_ict: dict[tuple[MarketSymbol, Timeframe], HotICTState] = {}

    def reset_state(self) -> None:
        super().reset_state()
        self._p5_ict.clear()

    def _detect_entry_setups(self, candles, timeframe, liquidity_interactions,
                             structure_events, displacement_legs, fvg_zones, config,
                             *, dual_sweeps, order_blocks, atr_result):
        assert self._active_symbol is not None
        key = (self._active_symbol, timeframe)
        state = self._p5_ict.get(key)
        if state is None or state.config != config:
            state = HotICTState(timeframe, config)
            self._p5_ict[key] = state
        if (config.signal_entry_zone_source is SetupEntryZoneSource.FVG
                and config.setup_invalidation_source is not SetupInvalidationSource.ORDER_BLOCK_EXTREME):
            # Sources are fetched from this coordinator's own feature states,
            # not from caller-supplied evidence/version/validation assertions.
            return state._evaluate_owned(self._p3_liquidity[key], self._p3_structures[key],
                self._p3_displacement[key], self._p3_fvgs[key], atr_result=atr_result)
        return state.evaluate(candles, liquidity_interactions, structure_events,
                              displacement_legs, fvg_zones, dual_sweeps=dual_sweeps,
                              order_blocks=order_blocks, atr_result=atr_result)

    def _analyze_liquidity(self, candles, timeframe, confirmed_swings, config, atr_result):
        assert self._active_symbol is not None
        key = (self._active_symbol, timeframe)
        state = self._p3_liquidity.get(key)
        if state is None:
            state = HotLiquidityState(timeframe, config)
            self._p3_liquidity[key] = state
        state.append(candles, confirmed_swings, atr_result)
        return state.result()

    def _analyze_fvg(self, candles, timeframe, config, *, atr_result):
        assert self._active_symbol is not None
        key = (self._active_symbol, timeframe)
        state = self._p3_fvgs.get(key)
        if state is None:
            state = HotFVGState(timeframe, config)
            self._p3_fvgs[key] = state
        state.append(candles, atr_result)
        return state.result(atr_result)

    def _analyze_order_blocks(self, candles, timeframe, structure_events, config, **kwargs):
        if config.ob_require_displacement or config.breaker_enabled:
            return super()._analyze_order_blocks(candles, timeframe, structure_events, config, **kwargs)
        assert self._active_symbol is not None
        key = (self._active_symbol, timeframe)
        state = self._p3_order_blocks.get(key)
        if state is None:
            state = HotOrderBlockState(timeframe, config)
            self._p3_order_blocks[key] = state
        state.append(candles, structure_events, **kwargs)
        return state.result()

    def _analyze_displacement(self, candles, timeframe, structure_events, config, *, fvg_zones):
        assert self._active_symbol is not None
        key = (self._active_symbol, timeframe)
        state = self._p3_displacement.get(key)
        if state is None:
            state = HotDisplacementState(timeframe, config)
            self._p3_displacement[key] = state
        state.append(candles, structure_events, fvg_zones)
        return state.result()

    def _structure_state(self, symbol, timeframe, config):
        key = (symbol, timeframe)
        state = self._p3_structures.get(key)
        if state is None:
            state = HotStructureState(timeframe, config)
            self._p3_structures[key] = state
        return state

    def _project_displacement_links(self, displacement):
        # Private coordinator seam: the preceding displacement stage owns and
        # validated these projections. No caller-supplied link cache is accepted.
        if self._active_symbol is None:
            return super()._project_displacement_links(displacement)
        key = (self._active_symbol, displacement.timeframe)
        state = self._p3_displacement.get(key)
        if isinstance(state, HotDisplacementState):
            return state.order_block_links
        return super()._project_displacement_links(displacement)

    def state_hash(self) -> str:
        def canonical(value: Any) -> Any:
            if isinstance(value, BaseModel):
                return canonical(value.model_dump(mode='python'))
            if is_dataclass(value) and not isinstance(value, type):
                return {item.name: canonical(getattr(value, item.name)) for item in fields(value)}
            if isinstance(value, Enum):
                return value.value
            if isinstance(value, (datetime, Decimal)):
                return str(value)
            if isinstance(value, dict):
                return sorted([[canonical(key), canonical(item)] for key, item in value.items()], key=lambda pair: json.dumps(pair[0], sort_keys=True))
            if isinstance(value, (set, frozenset)):
                return sorted([canonical(item) for item in value], key=lambda item: json.dumps(item, sort_keys=True))
            if isinstance(value, (list, tuple)):
                return [canonical(item) for item in value]
            if value is None or isinstance(value, (str, bool, int)):
                return value
            raise TypeError(f'unsupported diagnostic state: {type(value).__name__}')
        payload = {'p3': super().state_hash(), 'ict': canonical(self._p5_ict)}
        return sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
