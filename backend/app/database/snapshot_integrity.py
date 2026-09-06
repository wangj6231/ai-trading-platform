from __future__ import annotations

from hashlib import sha256
import json
from typing import Any

from pydantic import BaseModel

from app.core.strategy_identity import (
    build_strategy_identity,
)
from app.schemas.signal_persistence import SignalPersistenceCreate
from app.schemas.strategy import StrategyConfig
from app.schemas.execution import ExecutionConfig
from app.schemas.strategy_identity import StrategyIdentity


def canonical_json_bytes(value: Any) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return sha256(canonical_json_bytes(value)).hexdigest()


class SignalPersistenceAuthority:
    """Validate snapshots against one server-owned canonical strategy manifest."""

    def __init__(self, config: StrategyConfig) -> None:
        self._config = config
        self._identity = build_strategy_identity(config)

    def resolve(self, data: SignalPersistenceCreate) -> StrategyIdentity:
        pipeline = self._config.pipelines.get(data.symbol)
        if pipeline is None or pipeline.signal_timeframe is not data.timeframe:
            raise ValueError("no trusted persistence identity for symbol/timeframe")
        snapshot = data.analysis_snapshot
        if snapshot.payload.strategy_identity != self._identity:
            raise ValueError("snapshot strategy identity does not match server configuration")
        if snapshot.payload.symbol != data.symbol:
            raise ValueError("snapshot symbol does not match signal")
        if snapshot.payload.timeframe != data.timeframe:
            raise ValueError("snapshot timeframe does not match signal")
        if snapshot.payload.market_data.source_timeframe is not pipeline.multi_timeframe.mtf_source_timeframe:
            raise ValueError("snapshot market-data source does not match server configuration")
        indicator = snapshot.payload.indicators
        if indicator is not None and (
            indicator.macd.config != pipeline.macd
            or indicator.atr.config != pipeline.atr
        ):
            raise ValueError("snapshot indicator configuration does not match server configuration")
        for result in snapshot.payload.market_structure.values():
            expected_structure = pipeline.market_structure.get(result.timeframe)
            if expected_structure is None or result.config != expected_structure:
                raise ValueError("snapshot structure configuration does not match server configuration")
        smc_ict = snapshot.payload.smc_ict
        if smc_ict is not None:
            actual_configs = (
                smc_ict.liquidity.config,
                smc_ict.fvg.config,
                smc_ict.displacement.config,
                smc_ict.order_blocks.config,
                smc_ict.entry_setups.config,
            )
            expected_configs = (
                pipeline.liquidity,
                pipeline.fvg,
                pipeline.displacement,
                pipeline.order_block,
                pipeline.entry_setup,
            )
            if actual_configs != expected_configs:
                raise ValueError("snapshot SMC/ICT configuration does not match server configuration")
        score = snapshot.payload.signal_score
        if score is not None and score.result.strategy_version != self._identity.strategy_version:
            raise ValueError("snapshot score strategy version does not match server identity")
        decision = snapshot.payload.decision
        if decision.deterministic_decision is not data.algorithm_decision:
            raise ValueError("snapshot deterministic decision does not match signal")
        if decision.score != data.algorithm_score:
            raise ValueError("snapshot algorithm score does not match signal")
        if data.direction is not None:
            expected_levels = (
                data.entry_min,
                data.entry_max,
                data.take_profit,
                data.stop_loss,
                data.risk_reward,
            )
            snapshot_levels = (
                decision.entry_zone.low if decision.entry_zone is not None else None,
                decision.entry_zone.high if decision.entry_zone is not None else None,
                decision.take_profit,
                decision.stop_loss,
                decision.risk_reward,
            )
            if snapshot_levels != expected_levels:
                raise ValueError("snapshot trade levels do not match signal")
        return self._identity

    @property
    def strategy_identity(self) -> StrategyIdentity:
        return self._identity

    @property
    def algorithm_build_hash(self) -> str:
        return self._identity.algorithm_build_hash

    @property
    def execution_config(self) -> ExecutionConfig:
        return self._config.execution
