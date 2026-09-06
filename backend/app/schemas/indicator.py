from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.time import UtcDateTime


class ATRSmoothing(str, Enum):
    WILDER = "WILDER"
    SMA = "SMA"


class MACDConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    fast_period: int = Field(ge=1)
    slow_period: int = Field(ge=2)
    signal_period: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_period_order(self) -> "MACDConfig":
        if self.fast_period >= self.slow_period:
            raise ValueError("fast_period must be less than slow_period")
        return self


class ATRConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    period: int = Field(ge=1)
    smoothing: ATRSmoothing


class MACDPoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    timestamp: UtcDateTime
    fast_ema: Decimal | None
    slow_ema: Decimal | None
    macd_line: Decimal | None
    signal_line: Decimal | None
    histogram: Decimal | None
    bullish_crossover: bool
    bearish_crossover: bool
    histogram_increasing: bool
    histogram_decreasing: bool


class MACDResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    config: MACDConfig
    source: str = "close"
    points: list[MACDPoint]


class ATRPoint(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    timestamp: UtcDateTime
    true_range: Decimal
    atr: Decimal | None


class ATRResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    config: ATRConfig
    points: list[ATRPoint]


class IndicatorAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candle_count: int = Field(ge=0)
    data_cutoff_at: UtcDateTime | None
    macd: MACDResult
    atr: ATRResult
