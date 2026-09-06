from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.time import UtcDateTime
from app.schemas.signal_lifecycle import SameCandlePolicy
from app.schemas.strategy_identity import StrategyIdentity
from app.schemas.types import MarketSymbol, Timeframe


DATASET_SCHEMA_VERSION: Literal["1"] = "1"
RUN_SPEC_SCHEMA_VERSION: Literal["1"] = "1"
RUN_IDENTITY_SCHEMA_VERSION: Literal["1"] = "1"


class DatasetSeriesRole(str, Enum):
    CANONICAL_SOURCE = "CANONICAL_SOURCE"
    EXTERNAL_DERIVED_VALIDATION = "EXTERNAL_DERIVED_VALIDATION"


class DatasetSeriesProvenance(BaseModel):
    """Auditing metadata that never participates in reproducibility hashes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: MarketSymbol
    timeframe: Timeframe
    role: DatasetSeriesRole
    source_label: str | None = Field(default=None, min_length=1, max_length=128)

    @field_validator("source_label")
    @classmethod
    def reject_machine_paths(cls, value: str | None) -> str | None:
        if value is not None and ("/" in value or "\\" in value or ":" in value):
            raise ValueError("source_label must not contain a machine path")
        return value


class CanonicalDatasetIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_schema_version: Literal["1"] = DATASET_SCHEMA_VERSION
    dataset_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    symbols: tuple[MarketSymbol, ...] = Field(min_length=1)
    canonical_timeframe: Timeframe
    candle_count: int = Field(gt=0)
    first_candle_at: UtcDateTime
    last_candle_at: UtcDateTime

    @model_validator(mode="after")
    def validate_metadata(self) -> "CanonicalDatasetIdentity":
        if self.symbols != tuple(sorted(set(self.symbols), key=lambda item: item.value)):
            raise ValueError("dataset symbols must be unique and canonically sorted")
        if self.last_candle_at < self.first_candle_at:
            raise ValueError("last_candle_at cannot predate first_candle_at")
        return self


class BacktestRunSpec(BaseModel):
    """Strict non-dataset inputs and semantic policies for one backtest."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_spec_schema_version: Literal["1"] = RUN_SPEC_SCHEMA_VERSION
    symbols: tuple[MarketSymbol, ...] = Field(min_length=1)
    canonical_timeframe: Timeframe
    required_timeframes: tuple[Timeframe, ...] = Field(min_length=1)
    evaluation_timeframe: Timeframe
    analysis_input_start: UtcDateTime
    metrics_start: UtcDateTime
    end_at: UtcDateTime
    schedule_policy: Literal["EVALUATION_TIMEFRAME_CLOSED_CANDLES_V1"] = (
        "EVALUATION_TIMEFRAME_CLOSED_CANDLES_V1"
    )
    warmup_policy: Literal["EFFECTIVE_PREFIX_BEFORE_FIRST_EVALUATION_V1"] = (
        "EFFECTIVE_PREFIX_BEFORE_FIRST_EVALUATION_V1"
    )
    cutoff_policy: Literal["CLOSED_CANDLES_AT_OR_BEFORE_AS_OF_V1"] = (
        "CLOSED_CANDLES_AT_OR_BEFORE_AS_OF_V1"
    )
    data_gap_policy: Literal["REJECT_NONCONTIGUOUS_CANONICAL_SOURCE_V1"] = (
        "REJECT_NONCONTIGUOUS_CANONICAL_SOURCE_V1"
    )
    resampling_policy: Literal["UTC_COMPLETE_BUCKET_OHLCV_V1"] = (
        "UTC_COMPLETE_BUCKET_OHLCV_V1"
    )
    activation_policy: Literal["TYPED_ENTRY_EXECUTION_EVIDENCE_V1"] = (
        "TYPED_ENTRY_EXECUTION_EVIDENCE_V1"
    )
    same_candle_policy: SameCandlePolicy
    entry_exit_same_bar_policy: Literal["OPEN_KNOWN_ELSE_AMBIGUOUS_V1"] = (
        "OPEN_KNOWN_ELSE_AMBIGUOUS_V1"
    )
    opening_gap_precedence_policy: Literal["OPEN_BEFORE_INTRABAR_EXTREMES_V1"] = (
        "OPEN_BEFORE_INTRABAR_EXTREMES_V1"
    )
    execution_config_source: Literal["CANONICAL_STRATEGY_CONFIG_V1"] = (
        "CANONICAL_STRATEGY_CONFIG_V1"
    )
    ai_policy: Literal["DISABLED_V1"] = "DISABLED_V1"
    randomness_policy: Literal["NONE_V1"] = "NONE_V1"

    @model_validator(mode="after")
    def validate_run_spec(self) -> "BacktestRunSpec":
        if self.symbols != tuple(sorted(set(self.symbols), key=lambda item: item.value)):
            raise ValueError("run symbols must be unique and canonically sorted")
        if len(self.required_timeframes) != len(set(self.required_timeframes)):
            raise ValueError("required_timeframes must be unique")
        if self.canonical_timeframe not in self.required_timeframes:
            raise ValueError("canonical_timeframe must be required")
        if self.evaluation_timeframe not in self.required_timeframes:
            raise ValueError("evaluation_timeframe must be required")
        if not self.analysis_input_start <= self.metrics_start <= self.end_at:
            raise ValueError("analysis, metrics and end boundaries are out of order")
        return self


class BacktestRunIdentity(BaseModel):
    """Server-generated identity of exact reproducible experiment inputs."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_identity_schema_version: Literal["1"] = RUN_IDENTITY_SCHEMA_VERSION
    strategy_identity: StrategyIdentity
    dataset_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_schema_version: Literal["1"] = DATASET_SCHEMA_VERSION
    run_spec_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    run_identity_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    symbols: tuple[MarketSymbol, ...] = Field(min_length=1)
    canonical_timeframe: Timeframe
    analysis_input_start: UtcDateTime
    metrics_start: UtcDateTime
    end_at: UtcDateTime
    candle_count: int = Field(gt=0)
    first_candle_at: UtcDateTime
    last_candle_at: UtcDateTime

    @model_validator(mode="after")
    def validate_metadata(self) -> "BacktestRunIdentity":
        if self.symbols != tuple(sorted(set(self.symbols), key=lambda item: item.value)):
            raise ValueError("run identity symbols must be canonically sorted")
        if self.analysis_input_start != self.first_candle_at:
            raise ValueError("analysis_input_start must equal first effective candle")
        if not self.first_candle_at <= self.last_candle_at < self.end_at:
            raise ValueError("effective dataset timestamps are inconsistent")
        if not self.analysis_input_start <= self.metrics_start <= self.end_at:
            raise ValueError("run identity boundaries are out of order")
        return self
