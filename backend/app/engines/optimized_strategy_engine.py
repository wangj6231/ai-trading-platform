"""Equivalence-preserving incremental orchestration for historical replay.

The reference engine remains :class:`ConcreteDeterministicStrategyEngine`.
This module only replaces the repeated point-in-time resampling step.  All
indicator, structure, SMC/ICT, scoring, and risk code is still executed by the
same inherited orchestration method.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Hashable

from app.engines.strategy_engine import ConcreteDeterministicStrategyEngine
from app.market_data.timeframes import timeframe_duration
from app.schemas.candle import Candle
from app.schemas.strategy import DeterministicStrategyPipelineConfig
from app.schemas.types import MarketSymbol, Timeframe


def _bucket_start(timestamp: datetime, duration: timedelta) -> datetime:
    seconds = int(duration.total_seconds())
    epoch_seconds = int(timestamp.timestamp())
    return datetime.fromtimestamp((epoch_seconds // seconds) * seconds, tz=UTC)


@dataclass
class _TargetState:
    buckets: dict[datetime, list[Candle]] = field(default_factory=dict)
    emitted: set[datetime] = field(default_factory=set)
    bars: list[Candle] = field(default_factory=list)


@dataclass
class IncrementalResamplingState:
    """Restartable point-in-time state for one symbol/configuration."""

    source_timeframe: Timeframe
    target_timeframes: tuple[Timeframe, ...]
    source_candles: tuple[Candle, ...] = ()
    targets: dict[Timeframe, _TargetState] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.targets:
            self.targets = {
                timeframe: _TargetState() for timeframe in self.target_timeframes
            }

    @property
    def signature(self) -> tuple[str, tuple[str, ...]]:
        return (
            self.source_timeframe.value,
            tuple(timeframe.value for timeframe in self.target_timeframes),
        )

    def reset(self) -> None:
        self.source_candles = ()
        self.targets = {
            timeframe: _TargetState() for timeframe in self.target_timeframes
        }

    def append(self, candles: tuple[Candle, ...]) -> None:
        """Append a strict source prefix and close only complete UTC buckets."""

        if len(candles) < len(self.source_candles) or candles[: len(self.source_candles)] != self.source_candles:
            self.reset()

        for candle in candles[len(self.source_candles) :]:
            for timeframe in self.target_timeframes:
                target = self.targets[timeframe]
                duration = timeframe_duration(timeframe)
                bucket = _bucket_start(candle.timestamp, duration)
                constituents = target.buckets.setdefault(bucket, [])
                constituents.append(candle)
                source_duration = timeframe_duration(self.source_timeframe)
                expected_count = int(duration / source_duration)
                if len(constituents) != expected_count:
                    continue
                expected = tuple(
                    bucket + index * source_duration
                    for index in range(expected_count)
                )
                observed = tuple(item.timestamp for item in constituents)
                if observed != expected or bucket in target.emitted:
                    continue
                target.bars.append(
                    Candle(
                        timestamp=bucket,
                        open=constituents[0].open,
                        high=max(item.high for item in constituents),
                        low=min(item.low for item in constituents),
                        close=constituents[-1].close,
                        volume=sum(
                            (item.volume for item in constituents),
                            start=Decimal(0),
                        ),
                    )
                )
                target.emitted.add(bucket)
        self.source_candles = candles

    def snapshot(self) -> dict[Timeframe, tuple[Candle, ...]]:
        return {
            timeframe: tuple(self.targets[timeframe].bars)
            for timeframe in self.target_timeframes
        }


class OptimizedDeterministicStrategyEngine(ConcreteDeterministicStrategyEngine):
    """Concrete strategy engine with incremental, restartable resampling.

    This is not a second strategy.  It inherits the complete reference
    orchestration and changes only how the already-closed target candle prefix
    is assembled.  A state is maintained per symbol and is reset whenever the
    supplied input is not an exact extension of the known prefix.
    """

    def __init__(self, config) -> None:
        super().__init__(config)
        self._incremental_states: dict[Hashable, IncrementalResamplingState] = {}

    def _build_candles_by_target(
        self,
        source_candles,
        as_of: datetime,
        config: DeterministicStrategyPipelineConfig,
        *,
        symbol: MarketSymbol,
    ) -> dict[Timeframe, tuple[Candle, ...]]:
        source_timeframe = config.multi_timeframe.mtf_source_timeframe
        targets = config.multi_timeframe.mtf_target_timeframes
        key = self._state_key(symbol, source_timeframe, targets)
        state = self._incremental_states.get(key)
        if state is None:
            state = IncrementalResamplingState(source_timeframe, targets)
            self._incremental_states[key] = state
        state.append(tuple(source_candles))
        return state.snapshot()

    @staticmethod
    def _state_key(
        symbol: MarketSymbol,
        source_timeframe: Timeframe,
        target_timeframes: tuple[Timeframe, ...],
    ) -> tuple[MarketSymbol, str, tuple[str, ...]]:
        return (
            symbol,
            source_timeframe.value,
            tuple(timeframe.value for timeframe in target_timeframes),
        )
