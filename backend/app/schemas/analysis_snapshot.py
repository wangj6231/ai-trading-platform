from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
import json
import math
import re
from typing import Annotated, Any, Literal
import unicodedata

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

from app.core.time import UtcDateTime, normalize_utc_datetime
from app.market_data.timeframes import timeframe_duration
from app.schemas.displacement import DisplacementAnalysisResult
from app.schemas.entry_setup import EntrySetupAnalysisResult
from app.schemas.fvg import (
    FVGAnalysisResult,
    GapLifecycleEventType,
    GapLifecycleState,
    GapZoneStatus,
)
from app.schemas.indicator import IndicatorAnalysis
from app.schemas.liquidity import (
    LiquidityAnalysisResult,
    LiquidityPoolState,
)
from app.schemas.multi_timeframe import MTFAnalysisResult
from app.schemas.order_block import (
    BreakerBlockStatus,
    OrderBlockAnalysisResult,
    OrderBlockEventType,
    OrderBlockStatus,
)
from app.schemas.risk import RiskDecision, RiskPlan
from app.schemas.signal import EntryZone, SignalDecision
from app.schemas.signal_score import (
    SignalScoreComponent,
    SignalScoreEvidence,
    SignalScoreResult,
)
from app.schemas.strategy_identity import StrategyIdentity
from app.schemas.structure import (
    CandidateResolution,
    MarketStructureResult,
)
from app.schemas.types import MarketSymbol, Timeframe, freeze_mapping


LEGACY_SNAPSHOT_SCHEMA_VERSION: Literal["1"] = "1"
SNAPSHOT_SCHEMA_VERSION: Literal["2"] = "2"

NON_DECISION_METADATA_MAX_KEY_LENGTH = 64
NON_DECISION_METADATA_MAX_STRING_LENGTH = 1_024
NON_DECISION_METADATA_MAX_CONTAINER_ITEMS = 64
NON_DECISION_METADATA_MAX_DEPTH = 8
NON_DECISION_METADATA_MAX_NODES = 256
NON_DECISION_METADATA_MAX_CANONICAL_BYTES = 16_384
NON_DECISION_METADATA_MAX_ABS_NUMBER = 10**18

_TEMPORAL_METADATA_TOKENS = frozenset(
    {
        "time",
        "timestamp",
        "datetime",
        "date",
        "timezone",
        "created",
        "creation",
        "updated",
        "update",
        "confirmed",
        "confirmation",
        "validated",
        "validation",
        "activated",
        "activation",
        "closed",
        "closure",
        "executed",
        "execution",
        "mitigated",
        "mitigation",
        "invalidated",
        "invalidation",
        "swept",
        "converted",
        "conversion",
    }
)
_TEMPORAL_METADATA_COLLAPSED_KEYS = frozenset(
    {
        "eventtime",
        "eventtimestamp",
        "pivottime",
        "pivottimestamp",
        "candleclosetime",
        "sourcebarclosetime",
        "createdat",
        "updatedat",
        "confirmedat",
        "validatedat",
        "activatedat",
        "closedat",
        "executedat",
        "mitigatedat",
        "invalidatedat",
        "sweptat",
        "convertedat",
    }
)

# These names map directly to typed Snapshot V2 evidence sections or their
# standard trading aliases. Generic metadata cannot be an alternate channel.
_DECISION_METADATA_TOKENS = frozenset(
    {
        "entry",
        "tp",
        "sl",
        "score",
        "weight",
        "weights",
        "direction",
        "decision",
        "signal",
        "bos",
        "mss",
        "choch",
        "liquidity",
        "sweep",
        "fvg",
        "ifvg",
        "displacement",
        "risk",
        "reward",
        "macd",
        "atr",
        "indicator",
        "indicators",
        "structure",
        "swing",
        "pivot",
        "support",
        "resistance",
        "candle",
        "ohlc",
        "ohlcv",
        "price",
        "volume",
        "target",
        "setup",
        "status",
        "result",
        "outcome",
        "confidence",
        "reason",
    }
)
_DECISION_METADATA_COMPOUND_KEYS = frozenset(
    {
        "entry_price",
        "entry_zone",
        "take_profit",
        "stop_loss",
        "order_block",
        "risk_reward",
        "market_data",
        "market_structure",
        "multi_timeframe",
        "support_resistance",
        "buy_side_liquidity",
        "sell_side_liquidity",
    }
)
_DECISION_METADATA_COLLAPSED_KEYS = frozenset(
    key.replace("_", "") for key in _DECISION_METADATA_COMPOUND_KEYS
)


class _FrozenList(list[Any]):
    @staticmethod
    def _immutable(*_args: Any, **_kwargs: Any) -> None:
        raise TypeError("validated snapshot sequences are immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    __iadd__ = _immutable  # type: ignore[assignment]
    __imul__ = _immutable  # type: ignore[assignment]
    append = _immutable
    clear = _immutable
    extend = _immutable
    insert = _immutable
    pop = _immutable
    remove = _immutable
    reverse = _immutable
    sort = _immutable


class LegacyAnalysisSnapshotPayloadV1(BaseModel):
    """Read-only legacy payload.

    V1 accepted arbitrary nested JSON. It remains parseable so historical rows
    are not rewritten, but it is not accepted by the new-write contract.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: MarketSymbol
    timeframe: Timeframe
    as_of: UtcDateTime
    indicator: dict[str, JsonValue] = Field(min_length=1)
    market_structure: dict[str, JsonValue] = Field(min_length=1)
    smc_ict: dict[str, JsonValue] = Field(min_length=1)
    multi_timeframe: dict[str, JsonValue] = Field(min_length=1)
    score: int
    score_result: dict[str, JsonValue] = Field(min_length=1)
    risk: dict[str, JsonValue] = Field(min_length=1)
    pipeline_config: dict[str, JsonValue] = Field(min_length=1)

class LegacyAnalysisSnapshotV1(BaseModel):
    """Historical V1 reader without a claim of deep point-in-time proof."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1"] = LEGACY_SNAPSHOT_SCHEMA_VERSION
    captured_at: UtcDateTime
    data_cutoff_at: UtcDateTime
    payload: LegacyAnalysisSnapshotPayloadV1

    @model_validator(mode="after")
    def validate_legacy_envelope(self) -> "LegacyAnalysisSnapshotV1":
        if self.data_cutoff_at > self.captured_at:
            raise ValueError("data_cutoff_at cannot be after captured_at")
        if self.payload.as_of != self.captured_at:
            raise ValueError("snapshot payload as_of must equal captured_at")
        return self


class SnapshotSeriesSource(str, Enum):
    CANONICAL = "CANONICAL"
    DERIVED = "DERIVED"


class SnapshotCandleSeriesEvidence(BaseModel):
    """Closed-candle watermark for one series consumed by the strategy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    timeframe: Timeframe
    source: SnapshotSeriesSource
    candle_count: int = Field(ge=1)
    first_candle_at: UtcDateTime
    last_candle_at: UtcDateTime
    last_candle_close_at: UtcDateTime

    @model_validator(mode="after")
    def validate_series_bounds(self) -> "SnapshotCandleSeriesEvidence":
        if self.first_candle_at > self.last_candle_at:
            raise ValueError("first_candle_at cannot be after last_candle_at")
        expected_close = self.last_candle_at + timeframe_duration(self.timeframe)
        if self.last_candle_close_at != expected_close:
            raise ValueError("last_candle_close_at must be the exact timeframe close")
        return self


class SnapshotMarketDataEvidence(BaseModel):
    """Market-data event time, intentionally separate from retrieval time."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_timeframe: Timeframe
    data_cutoff_at: UtcDateTime
    series: dict[str, SnapshotCandleSeriesEvidence] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_series_identity(self) -> "SnapshotMarketDataEvidence":
        for key, value in self.series.items():
            if key != value.timeframe.value:
                raise ValueError("market-data series key must match its timeframe")
            if value.last_candle_close_at > self.data_cutoff_at:
                raise ValueError("snapshot market data contains an unclosed candle")
        object.__setattr__(self, "series", freeze_mapping(self.series))
        return self


class SnapshotSMCICTEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    liquidity: LiquidityAnalysisResult
    fvg: FVGAnalysisResult
    displacement: DisplacementAnalysisResult
    order_blocks: OrderBlockAnalysisResult
    entry_setups: EntrySetupAnalysisResult


class SnapshotSignalScoreEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence: SignalScoreEvidence
    result: SignalScoreResult

    @model_validator(mode="after")
    def validate_score_times(self) -> "SnapshotSignalScoreEvidence":
        if self.evidence.decision_time != self.result.decision_time:
            raise ValueError("score evidence and result must share decision_time")
        return self


class SnapshotDecisionEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    deterministic_decision: SignalDecision
    candidate_direction: SignalDecision
    decision_at: UtcDateTime
    evidence_cutoff_at: UtcDateTime
    score: int | None = None
    score_breakdown: dict[SignalScoreComponent, int] = Field(default_factory=dict)
    entry_zone: EntryZone | None = None
    entry_reference: Decimal | None = Field(default=None, gt=0, allow_inf_nan=False)
    take_profit: Decimal | None = Field(default=None, gt=0, allow_inf_nan=False)
    stop_loss: Decimal | None = Field(default=None, gt=0, allow_inf_nan=False)
    risk_reward: Decimal | None = Field(default=None, gt=0, allow_inf_nan=False)
    reason_codes: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_decision(self) -> "SnapshotDecisionEvidence":
        levels = (
            self.entry_zone,
            self.entry_reference,
            self.take_profit,
            self.stop_loss,
            self.risk_reward,
        )
        if self.decision_at < self.evidence_cutoff_at:
            raise ValueError("decision_at cannot precede evidence_cutoff_at")
        if self.deterministic_decision is SignalDecision.NO_TRADE:
            if any(value is not None for value in levels):
                raise ValueError("NO_TRADE snapshot decision cannot expose trade levels")
        else:
            if self.candidate_direction is not self.deterministic_decision:
                raise ValueError("trade decision must match candidate direction")
            if self.score is None or any(value is None for value in levels):
                raise ValueError("trade decision requires score, entry, TP, SL, and RR")
            assert self.entry_zone is not None
            assert self.entry_reference is not None
            assert self.take_profit is not None
            assert self.stop_loss is not None
            if not self.entry_zone.low <= self.entry_reference <= self.entry_zone.high:
                raise ValueError("decision entry_reference must be inside entry_zone")
            if self.deterministic_decision is SignalDecision.LONG:
                ordered = (
                    self.stop_loss
                    < self.entry_zone.low
                    <= self.entry_zone.high
                    < self.take_profit
                )
            else:
                ordered = (
                    self.take_profit
                    < self.entry_zone.low
                    <= self.entry_zone.high
                    < self.stop_loss
                )
            if not ordered:
                raise ValueError("snapshot decision levels are directionally invalid")
        object.__setattr__(
            self,
            "score_breakdown",
            freeze_mapping(self.score_breakdown),
        )
        return self


class AnalysisSnapshotPayloadV2(BaseModel):
    """Fully typed deterministic evidence known at one historical cutoff."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: MarketSymbol
    timeframe: Timeframe
    as_of: UtcDateTime
    strategy_identity: StrategyIdentity
    market_data: SnapshotMarketDataEvidence
    indicators: IndicatorAnalysis | None = None
    market_structure: dict[str, MarketStructureResult] = Field(default_factory=dict)
    smc_ict: SnapshotSMCICTEvidence | None = None
    multi_timeframe: MTFAnalysisResult | None = None
    signal_score: SnapshotSignalScoreEvidence | None = None
    risk: RiskPlan | None = None
    decision: SnapshotDecisionEvidence
    non_decision_metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("non_decision_metadata", mode="before")
    @classmethod
    def validate_non_decision_metadata(cls, value: Any) -> Any:
        _validate_non_decision_metadata(value)
        return value

    @model_validator(mode="after")
    def freeze_typed_mappings(self) -> "AnalysisSnapshotPayloadV2":
        for key, result in self.market_structure.items():
            if key != result.timeframe.value:
                raise ValueError("market-structure key must match its timeframe")
        object.__setattr__(
            self,
            "market_structure",
            freeze_mapping(self.market_structure),
        )
        object.__setattr__(
            self,
            "non_decision_metadata",
            freeze_mapping(self.non_decision_metadata),
        )
        return self


class AnalysisSnapshot(BaseModel):
    """V2 new-write snapshot: typed, UTC-normalized, and point-in-time safe."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["2"] = SNAPSHOT_SCHEMA_VERSION
    captured_at: UtcDateTime
    data_cutoff_at: UtcDateTime
    payload: AnalysisSnapshotPayloadV2

    @model_validator(mode="after")
    def normalize_and_validate_point_in_time(self) -> "AnalysisSnapshot":
        # Nested runtime models predate Snapshot V2. Re-parse their typed Python
        # representation after normalizing every datetime so the persisted JSON
        # has one deterministic UTC representation.
        normalized_payload = AnalysisSnapshotPayloadV2.model_validate(
            _normalize_datetime_tree(self.payload)
        )
        _deep_freeze_tree(normalized_payload)
        object.__setattr__(self, "payload", normalized_payload)
        if self.data_cutoff_at > self.captured_at:
            raise ValueError("data_cutoff_at cannot be after captured_at")
        if self.payload.as_of != self.captured_at:
            raise ValueError("snapshot payload as_of must equal captured_at")
        if self.payload.market_data.data_cutoff_at != self.data_cutoff_at:
            raise ValueError("market-data cutoff must equal snapshot data_cutoff_at")
        if self.payload.decision.evidence_cutoff_at != self.data_cutoff_at:
            raise ValueError("decision evidence cutoff must equal snapshot cutoff")
        if self.payload.decision.decision_at != self.captured_at:
            raise ValueError("snapshot decision_at must equal captured_at")
        _validate_point_in_time_evidence(self.payload, self.data_cutoff_at)
        return self


PersistedAnalysisSnapshot = Annotated[
    LegacyAnalysisSnapshotV1 | AnalysisSnapshot,
    Field(discriminator="schema_version"),
]


def _normalize_datetime_tree(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _normalize_datetime_tree(value.model_dump(mode="python"))
    if isinstance(value, datetime):
        return normalize_utc_datetime(value)
    if isinstance(value, dict):
        return {key: _normalize_datetime_tree(child) for key, child in value.items()}
    if isinstance(value, tuple):
        return tuple(_normalize_datetime_tree(child) for child in value)
    if isinstance(value, list):
        return [_normalize_datetime_tree(child) for child in value]
    return value


def _deep_freeze_tree(value: Any) -> Any:
    """Freeze containers inside reused runtime models after snapshot validation."""

    if isinstance(value, BaseModel):
        for field_name in type(value).model_fields:
            object.__setattr__(
                value,
                field_name,
                _deep_freeze_tree(getattr(value, field_name)),
            )
        return value
    if isinstance(value, dict):
        return freeze_mapping(
            {key: _deep_freeze_tree(child) for key, child in value.items()}
        )
    if isinstance(value, tuple):
        return tuple(_deep_freeze_tree(child) for child in value)
    if isinstance(value, list):
        return _FrozenList(_deep_freeze_tree(child) for child in value)
    return value


def _validate_point_in_time_evidence(
    payload: AnalysisSnapshotPayloadV2,
    cutoff: datetime,
) -> None:
    trusted_sections = (
        payload.market_data,
        payload.indicators,
        payload.market_structure,
        payload.smc_ict,
        payload.multi_timeframe,
        payload.signal_score,
        payload.risk,
    )
    for section in trusted_sections:
        _reject_datetime_after_cutoff(section, cutoff=cutoff)

    _validate_result_cutoffs(payload, cutoff)
    _validate_structure_semantics(payload)
    _validate_liquidity_semantics(payload)
    _validate_fvg_semantics(payload)
    _validate_order_block_semantics(payload)
    _validate_mtf_semantics(payload, cutoff)
    _validate_score_references(payload)
    _validate_risk_references(payload)
    _validate_decision_consistency(payload)


def _reject_datetime_after_cutoff(value: Any, *, cutoff: datetime) -> None:
    if value is None:
        return
    if isinstance(value, BaseModel):
        for field_name in type(value).model_fields:
            _reject_datetime_after_cutoff(getattr(value, field_name), cutoff=cutoff)
        return
    if isinstance(value, datetime):
        offset = value.utcoffset()
        if offset is None:
            raise ValueError("snapshot evidence datetime must include a UTC offset")
        if offset.total_seconds() != 0:
            raise ValueError("snapshot evidence datetime must be normalized to UTC")
        if value > cutoff:
            raise ValueError("snapshot evidence datetime is after data_cutoff_at")
        return
    if isinstance(value, dict):
        for child in value.values():
            _reject_datetime_after_cutoff(child, cutoff=cutoff)
        return
    if isinstance(value, (tuple, list)):
        for child in value:
            _reject_datetime_after_cutoff(child, cutoff=cutoff)


def _validate_result_cutoffs(
    payload: AnalysisSnapshotPayloadV2,
    cutoff: datetime,
) -> None:
    results: list[tuple[str, Timeframe, datetime | None]] = []
    if payload.indicators is not None:
        results.append(("indicators", payload.timeframe, payload.indicators.data_cutoff_at))
        for macd_point in payload.indicators.macd.points:
            if macd_point.timestamp + timeframe_duration(payload.timeframe) > cutoff:
                raise ValueError("indicator point uses a candle not closed by cutoff")
        for atr_point in payload.indicators.atr.points:
            if atr_point.timestamp + timeframe_duration(payload.timeframe) > cutoff:
                raise ValueError("indicator point uses a candle not closed by cutoff")
    results.extend(
        (f"market_structure[{key}]", result.timeframe, result.data_cutoff_at)
        for key, result in payload.market_structure.items()
    )
    if payload.smc_ict is not None:
        smc_results = (
            ("liquidity", payload.smc_ict.liquidity),
            ("fvg", payload.smc_ict.fvg),
            ("displacement", payload.smc_ict.displacement),
            ("order_blocks", payload.smc_ict.order_blocks),
            ("entry_setups", payload.smc_ict.entry_setups),
        )
        results.extend(
            (name, result.timeframe, result.data_cutoff_at)
            for name, result in smc_results
        )
    for name, timeframe, result_cutoff in results:
        if result_cutoff is None:
            raise ValueError(f"{name} must expose a point-in-time data_cutoff_at")
        if result_cutoff > cutoff:
            raise ValueError(f"{name} data_cutoff_at is after snapshot cutoff")
        if name in {"indicators", "liquidity", "fvg", "displacement", "order_blocks", "entry_setups"}:
            if timeframe is not payload.timeframe:
                raise ValueError(f"{name} timeframe must equal snapshot timeframe")


def _validate_structure_semantics(payload: AnalysisSnapshotPayloadV2) -> None:
    for result in payload.market_structure.values():
        swing_ids = {swing.swing_id for swing in result.confirmed_swings}
        for candidate in result.candidate_swings:
            if candidate.resolution is CandidateResolution.PENDING:
                if candidate.resolved_at is not None:
                    raise ValueError("pending swing candidate cannot have resolved_at")
            elif candidate.resolved_at is None:
                raise ValueError("resolved swing candidate requires resolved_at")
        for swing in result.confirmed_swings:
            if swing.pivot_timestamp >= swing.confirmed_at:
                raise ValueError("swing pivot must precede confirmation availability")
            if any(item > swing.confirmed_at for item in swing.left_evidence_timestamps):
                raise ValueError("left swing evidence cannot occur after confirmation")
            if any(item >= swing.confirmed_at for item in swing.right_evidence_timestamps):
                raise ValueError("right swing evidence must precede confirmed_at")
        for event in result.structure_events:
            if event.broken_structure_id not in swing_ids:
                raise ValueError("structure break references an unavailable confirmed swing")


def _validate_liquidity_semantics(payload: AnalysisSnapshotPayloadV2) -> None:
    if payload.smc_ict is None:
        return
    liquidity = payload.smc_ict.liquidity
    interaction_ids = {event.event_id for event in liquidity.interactions}
    for pool in liquidity.pools:
        if pool.updated_at != pool.history[-1].available_at:
            raise ValueError("liquidity pool must expose its latest point-in-time history")
        if pool.state is LiquidityPoolState.SWEPT and pool.swept_at is None:
            raise ValueError("swept liquidity state requires swept_at")
        if pool.swept_at is not None and pool.swept_at < pool.created_at:
            raise ValueError("liquidity sweep cannot precede pool creation")
        if any(event.event_id not in interaction_ids for event in pool.interactions):
            raise ValueError("liquidity pool interaction must exist in typed analysis")


def _validate_fvg_semantics(payload: AnalysisSnapshotPayloadV2) -> None:
    if payload.smc_ict is None:
        return
    zones = payload.smc_ict.fvg.zones
    zone_ids = {zone.zone_id for zone in zones}
    status_by_state = {
        GapLifecycleState.ACTIVE: GapZoneStatus.OPEN,
        GapLifecycleState.PARTIALLY_FILLED: GapZoneStatus.PARTIAL,
        GapLifecycleState.FILLED: GapZoneStatus.FILLED,
        GapLifecycleState.INVERTED: GapZoneStatus.INVALIDATED,
        GapLifecycleState.INVALIDATED: GapZoneStatus.INVALIDATED,
        GapLifecycleState.EXPIRED: GapZoneStatus.INVALIDATED,
    }
    for zone in zones:
        if not zone.lifecycle:
            raise ValueError("FVG/IFVG zone requires lifecycle evidence")
        first, latest = zone.lifecycle[0], zone.lifecycle[-1]
        if first.occurred_at != zone.created_at or zone.confirmed_at != zone.created_at:
            raise ValueError("FVG/IFVG creation timestamps are inconsistent")
        if latest.occurred_at > zone.last_updated_at:
            raise ValueError("FVG/IFVG lifecycle cannot be newer than last_updated_at")
        if latest.to_state is not zone.lifecycle_state:
            raise ValueError("FVG/IFVG status must match latest lifecycle state")
        if status_by_state[zone.lifecycle_state] is not zone.status:
            raise ValueError("FVG/IFVG public status is inconsistent with lifecycle")
        if any(
            current.occurred_at < previous.occurred_at
            for previous, current in zip(zone.lifecycle, zone.lifecycle[1:], strict=False)
        ):
            raise ValueError("FVG/IFVG lifecycle must be chronological")
        if zone.origin_fvg_id is not None and zone.origin_fvg_id not in zone_ids:
            raise ValueError("IFVG origin must exist in typed point-in-time evidence")
        if zone.type.value == "IFVG" and first.event_type is not GapLifecycleEventType.IFVG_CREATED:
            raise ValueError("IFVG lifecycle must begin with IFVG_CREATED")
        if zone.type.value == "FVG" and first.event_type is not GapLifecycleEventType.FVG_CREATED:
            raise ValueError("FVG lifecycle must begin with FVG_CREATED")


def _validate_order_block_semantics(payload: AnalysisSnapshotPayloadV2) -> None:
    if payload.smc_ict is None:
        return
    analysis = payload.smc_ict.order_blocks
    breaker_ids = {breaker.zone_id for breaker in analysis.breaker_blocks}
    for zone in analysis.order_blocks:
        if not zone.lifecycle:
            raise ValueError("order block requires lifecycle evidence")
        first, latest = zone.lifecycle[0], zone.lifecycle[-1]
        if first.type is not OrderBlockEventType.OB_CREATED:
            raise ValueError("order-block lifecycle must begin with OB_CREATED")
        if first.confirmed_at != zone.created_at:
            raise ValueError("order-block created_at must match creation event")
        if latest.to_status is not zone.status:
            raise ValueError("order-block status must match latest lifecycle event")
        event_times = {event.type: event.confirmed_at for event in zone.lifecycle}
        expected_fields = (
            (OrderBlockEventType.OB_VALIDATED, zone.validated_at),
            (OrderBlockEventType.OB_MITIGATED, zone.mitigated_at),
            (OrderBlockEventType.OB_INVALIDATED, zone.invalidated_at),
        )
        for event_type, timestamp in expected_fields:
            if (event_type in event_times) != (timestamp is not None):
                raise ValueError("order-block lifecycle timestamp and event disagree")
            if timestamp is not None and event_times[event_type] != timestamp:
                raise ValueError("order-block lifecycle timestamp is inconsistent")
        if zone.breaker_zone_id is not None and zone.breaker_zone_id not in breaker_ids:
            raise ValueError("order block cannot expose a future/missing breaker")
        if zone.status is OrderBlockStatus.CANDIDATE and zone.validated_at is not None:
            raise ValueError("candidate order block cannot already be validated")
    order_block_ids = {zone.zone_id for zone in analysis.order_blocks}
    for breaker in analysis.breaker_blocks:
        if breaker.origin_order_block_id not in order_block_ids:
            raise ValueError("breaker origin must exist in typed evidence")
        if not breaker.lifecycle:
            raise ValueError("breaker requires lifecycle evidence")
        first, latest = breaker.lifecycle[0], breaker.lifecycle[-1]
        if first.type is not OrderBlockEventType.BREAKER_CREATED:
            raise ValueError("breaker lifecycle must begin with BREAKER_CREATED")
        if first.confirmed_at != breaker.created_at:
            raise ValueError("breaker created_at must match creation event")
        if latest.to_status is not breaker.status:
            raise ValueError("breaker status must match latest lifecycle event")
        activation_events = [
            event for event in breaker.lifecycle
            if event.type is OrderBlockEventType.BREAKER_ACTIVATED
        ]
        invalidation_events = [
            event for event in breaker.lifecycle
            if event.type is OrderBlockEventType.BREAKER_INVALIDATED
        ]
        if bool(activation_events) != (breaker.activated_at is not None):
            raise ValueError("breaker activation status and timestamp disagree")
        if activation_events and activation_events[-1].confirmed_at != breaker.activated_at:
            raise ValueError("breaker activated_at is inconsistent")
        if bool(invalidation_events) != (breaker.invalidated_at is not None):
            raise ValueError("breaker invalidation status and timestamp disagree")
        if invalidation_events and invalidation_events[-1].confirmed_at != breaker.invalidated_at:
            raise ValueError("breaker invalidated_at is inconsistent")
        if breaker.status is BreakerBlockStatus.CANDIDATE and breaker.activated_at is not None:
            raise ValueError("candidate breaker cannot already be active")


def _validate_mtf_semantics(
    payload: AnalysisSnapshotPayloadV2,
    cutoff: datetime,
) -> None:
    result = payload.multi_timeframe
    if result is None:
        return
    if result.decision_time > cutoff:
        raise ValueError("MTF decision_time is after snapshot cutoff")
    for key, snapshot in result.timeframes.items():
        if key != snapshot.timeframe.value:
            raise ValueError("MTF timeframe key must match nested snapshot")
        closed_fields = (
            snapshot.source_bar_close_time,
            snapshot.latest_closed_bar_at,
            snapshot.state_confirmed_at,
        )
        if any(value is not None and value > cutoff for value in closed_fields):
            raise ValueError("MTF nested timeframe evidence exceeds snapshot cutoff")
        required = (
            snapshot.state_event_id,
            snapshot.state_confirmed_at,
            snapshot.source_bar_timestamp,
            snapshot.source_bar_close_time,
            snapshot.latest_closed_bar_at,
        )
        if snapshot.available and any(value is None for value in required):
            raise ValueError("available MTF state requires complete close-watermark evidence")


def _available_source_times(
    payload: AnalysisSnapshotPayloadV2,
) -> dict[str, datetime]:
    sources: dict[str, datetime] = {}
    for result in payload.market_structure.values():
        for event in result.structure_events:
            reference = (
                f"{event.type.value}:{event.direction.value}:{event.timestamp.isoformat()}:"
                f"{event.broken_structure_id}"
            )
            sources[reference] = event.confirmed_at
        for zone in (*result.support_candidates, *result.resistance_candidates):
            sources[zone.zone_id] = zone.created_at
    if payload.indicators is not None:
        for point in payload.indicators.macd.points:
            sources[f"MACD:{point.timestamp.isoformat()}"] = (
                point.timestamp + timeframe_duration(payload.timeframe)
            )
    if payload.smc_ict is not None:
        for liquidity_event in payload.smc_ict.liquidity.interactions:
            sources[liquidity_event.event_id] = liquidity_event.confirmed_at
        for fvg_zone in payload.smc_ict.fvg.zones:
            sources[fvg_zone.zone_id] = fvg_zone.confirmed_at
        for leg in payload.smc_ict.displacement.legs:
            sources[leg.leg_id] = leg.confirmed_at
        for order_block in payload.smc_ict.order_blocks.order_blocks:
            sources[order_block.zone_id] = (
                order_block.validated_at or order_block.created_at
            )
    if payload.multi_timeframe is not None:
        sources[payload.multi_timeframe.snapshot_id] = payload.multi_timeframe.decision_time
    return sources


def _validate_score_references(payload: AnalysisSnapshotPayloadV2) -> None:
    score = payload.signal_score
    if score is None:
        return
    sources = _available_source_times(payload)
    for component, contribution in score.result.score_breakdown.items():
        if contribution != 0 and component not in score.evidence.components:
            raise ValueError("non-zero score contribution requires typed source evidence")
    for component, evidence in score.evidence.components.items():
        for source_id in evidence.source_ids:
            if source_id not in sources:
                raise ValueError(
                    f"score component {component.value} references unavailable evidence"
                )
            if evidence.confirmed_at < sources[source_id]:
                raise ValueError("score evidence predates its typed source availability")


def _validate_risk_references(payload: AnalysisSnapshotPayloadV2) -> None:
    risk = payload.risk
    if risk is None or risk.decision is RiskDecision.NO_TRADE:
        return
    if payload.smc_ict is None or risk.selection_metadata is None:
        raise ValueError("accepted risk plan requires typed SMC/ICT source evidence")
    setups = {
        setup.setup_id: setup for setup in payload.smc_ict.entry_setups.setups
    }
    setup = setups.get(risk.candidate_id)
    if setup is None:
        raise ValueError("risk candidate must reference a typed entry setup")
    if setup.confirmed_at > risk.decision_time:
        raise ValueError("risk plan predates its entry-setup availability")
    expected_stop_source = f"setup:{risk.candidate_id}:invalidation"
    if risk.selection_metadata.stop_source_id != expected_stop_source:
        raise ValueError("risk stop source does not reference the typed setup")
    pools = {
        pool.pool_id: pool for pool in payload.smc_ict.liquidity.pools
    }
    target = pools.get(risk.selection_metadata.target_source_id)
    if target is None:
        raise ValueError("risk target must reference typed liquidity evidence")
    if target.updated_at > risk.decision_time:
        raise ValueError("risk target state was unavailable at decision_time")
    if target.state is not LiquidityPoolState.ACTIVE:
        raise ValueError("risk target must be active at decision_time")
    if risk.selection_metadata.target_source_structure != target.source_structure:
        raise ValueError("risk target source structure does not match typed liquidity")
    if risk.selection_metadata.stop_structural_level != setup.invalidation_level:
        raise ValueError("risk stop level does not match typed setup invalidation")
    expected_target = (
        target.lower_bound
        if risk.decision is RiskDecision.LONG
        else target.upper_bound
    )
    if risk.selection_metadata.target_raw_level != expected_target:
        raise ValueError("risk target raw level does not match typed liquidity bounds")


def _validate_decision_consistency(payload: AnalysisSnapshotPayloadV2) -> None:
    decision = payload.decision
    score = payload.signal_score
    risk = payload.risk
    if score is not None:
        if decision.score != score.result.score:
            raise ValueError("decision score must match typed score result")
        if decision.score_breakdown != score.result.score_breakdown:
            raise ValueError("decision breakdown must match typed score result")
    elif decision.score is not None or decision.score_breakdown:
        raise ValueError("decision cannot expose score without typed score evidence")

    if decision.deterministic_decision is SignalDecision.NO_TRADE:
        return
    if risk is None or risk.decision.value != decision.deterministic_decision.value:
        raise ValueError("trade decision requires matching accepted risk plan")
    if (
        decision.entry_zone,
        decision.entry_reference,
        decision.take_profit,
        decision.stop_loss,
        decision.risk_reward,
    ) != (
        risk.entry_zone,
        risk.entry_reference,
        risk.take_profit,
        risk.stop_loss,
        risk.risk_reward,
    ):
        raise ValueError("decision levels must equal the typed risk plan")


def _validate_non_decision_metadata(value: Any) -> None:
    """Validate the sole generic V2 section before Pydantic JSON coercion."""

    node_count = [0]
    _validate_metadata_node(
        value,
        depth=0,
        node_count=node_count,
        active_containers=set(),
    )
    try:
        canonical = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("non-decision metadata is not canonical JSON") from exc
    if len(canonical) > NON_DECISION_METADATA_MAX_CANONICAL_BYTES:
        raise ValueError("non-decision metadata exceeds maximum canonical size")


def _validate_metadata_node(
    value: Any,
    *,
    depth: int,
    node_count: list[int],
    active_containers: set[int],
) -> None:
    if depth > NON_DECISION_METADATA_MAX_DEPTH:
        raise ValueError("non-decision metadata exceeds maximum nesting depth")
    node_count[0] += 1
    if node_count[0] > NON_DECISION_METADATA_MAX_NODES:
        raise ValueError("non-decision metadata exceeds maximum node count")

    value_type = type(value)
    if value is None or value_type is bool:
        return
    if value_type is str:
        if len(value) > NON_DECISION_METADATA_MAX_STRING_LENGTH:
            raise ValueError("non-decision metadata exceeds maximum string length")
        return
    if value_type is int:
        if abs(value) > NON_DECISION_METADATA_MAX_ABS_NUMBER:
            raise ValueError("non-decision metadata number exceeds maximum magnitude")
        return
    if value_type is float:
        if not math.isfinite(value):
            raise ValueError("non-decision metadata numbers must be finite")
        if abs(value) > NON_DECISION_METADATA_MAX_ABS_NUMBER:
            raise ValueError("non-decision metadata number exceeds maximum magnitude")
        return
    if value_type not in {dict, list}:
        raise ValueError(
            "non-decision metadata accepts only JSON null, bool, bounded number, "
            "bounded string, list, and object values"
        )

    container_id = id(value)
    if container_id in active_containers:
        raise ValueError("non-decision metadata cannot contain cyclic containers")
    active_containers.add(container_id)
    try:
        if value_type is dict:
            if len(value) > NON_DECISION_METADATA_MAX_CONTAINER_ITEMS:
                raise ValueError("non-decision metadata exceeds maximum object size")
            normalized_keys: set[str] = set()
            for key, child in value.items():
                normalized = _normalize_metadata_key(key)
                if normalized in normalized_keys:
                    raise ValueError(
                        "non-decision metadata contains ambiguous normalized keys"
                    )
                normalized_keys.add(normalized)
                _reject_reserved_metadata_key(normalized)
                _validate_metadata_node(
                    child,
                    depth=depth + 1,
                    node_count=node_count,
                    active_containers=active_containers,
                )
        else:
            if len(value) > NON_DECISION_METADATA_MAX_CONTAINER_ITEMS:
                raise ValueError("non-decision metadata exceeds maximum list size")
            for child in value:
                _validate_metadata_node(
                    child,
                    depth=depth + 1,
                    node_count=node_count,
                    active_containers=active_containers,
                )
    finally:
        active_containers.remove(container_id)


def _normalize_metadata_key(key: Any) -> str:
    if type(key) is not str:
        raise ValueError("non-decision metadata keys must be strings")
    if not key.strip():
        raise ValueError("non-decision metadata keys cannot be empty or whitespace")
    if len(key) > NON_DECISION_METADATA_MAX_KEY_LENGTH:
        raise ValueError("non-decision metadata exceeds maximum key length")
    if any(unicodedata.category(character) in {"Cc", "Cf", "Cs"} for character in key):
        raise ValueError("non-decision metadata keys cannot contain control characters")

    normalized = unicodedata.normalize("NFKC", key)
    normalized = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", "_", normalized)
    normalized = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", normalized)
    normalized = re.sub(r"[^\w]+", "_", normalized, flags=re.UNICODE)
    normalized = normalized.strip("_").casefold()
    if not normalized:
        raise ValueError("non-decision metadata key has no semantic characters")
    if len(normalized) > NON_DECISION_METADATA_MAX_KEY_LENGTH:
        raise ValueError("normalized non-decision metadata key is too long")
    return normalized


def _reject_reserved_metadata_key(normalized: str) -> None:
    tokens = frozenset(token for token in normalized.split("_") if token)
    collapsed = normalized.replace("_", "")
    if (
        tokens & _TEMPORAL_METADATA_TOKENS
        or collapsed in _TEMPORAL_METADATA_COLLAPSED_KEYS
    ):
        raise ValueError("temporal fields are forbidden in non-decision metadata")
    if (
        tokens & _DECISION_METADATA_TOKENS
        or normalized in _DECISION_METADATA_COMPOUND_KEYS
        or collapsed in _DECISION_METADATA_COLLAPSED_KEYS
    ):
        raise ValueError(
            "decision evidence fields are forbidden in non-decision metadata"
        )
