from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.time import UtcDateTime
from app.schemas.candle import Candle
from app.schemas.types import MarketSymbol, Timeframe
from app.schemas.market_schedule import MarketScheduleMode


class MarketDataQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: MarketSymbol
    timeframe: Timeframe
    limit: int = Field(ge=1)


class MarketDataMode(str, Enum):
    SERVER_PROVIDER = "SERVER_PROVIDER"
    RESEARCH_UPLOAD = "RESEARCH_UPLOAD"


class MarketDataProvenance(BaseModel):
    """Server-owned evidence for one validated point-in-time candle set."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str = Field(min_length=1)
    data_mode: MarketDataMode
    symbol: MarketSymbol
    timeframe: Timeframe
    first_candle_at: UtcDateTime
    last_candle_at: UtcDateTime
    data_cutoff_at: UtcDateTime
    expected_latest_closed_candle_at: UtcDateTime
    retrieved_at: UtcDateTime
    requested_candles: int = Field(ge=1)
    received_candles: int = Field(ge=1)
    lag_seconds: int = Field(ge=0)
    market_schedule_mode: MarketScheduleMode = MarketScheduleMode.CONTINUOUS_24_7
    session_calendar_id: str | None = None
    session_calendar_version: str | None = None
    session_calendar_hash: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    validated: Literal[True] = True

    @model_validator(mode="after")
    def validate_provenance(self) -> "MarketDataProvenance":
        if self.first_candle_at > self.last_candle_at:
            raise ValueError("first_candle_at must not follow last_candle_at")
        if self.last_candle_at >= self.data_cutoff_at:
            raise ValueError("data_cutoff_at must be after the last candle open")
        if self.data_cutoff_at > self.expected_latest_closed_candle_at:
            raise ValueError("data cutoff cannot exceed the expected closed-candle cutoff")
        if self.expected_latest_closed_candle_at > self.retrieved_at:
            raise ValueError("expected closed-candle cutoff cannot exceed retrieval time")
        if self.received_candles > self.requested_candles:
            raise ValueError("provider returned more candles than requested")
        expected_lag = int(
            (self.expected_latest_closed_candle_at - self.data_cutoff_at).total_seconds()
        )
        if self.lag_seconds != expected_lag:
            raise ValueError("lag_seconds must match the closed-candle cutoff difference")
        calendar_fields = (
            self.session_calendar_id,
            self.session_calendar_version,
            self.session_calendar_hash,
        )
        if self.market_schedule_mode is MarketScheduleMode.SESSION_CALENDAR:
            if any(value is None for value in calendar_fields):
                raise ValueError(
                    "session-calendar provenance requires complete calendar identity"
                )
        elif any(value is not None for value in calendar_fields):
            raise ValueError(
                "continuous provenance cannot contain session-calendar identity"
            )
        return self


class ValidatedMarketData(BaseModel):
    """Only this server-produced type may cross into live strategy evaluation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: MarketSymbol
    timeframe: Timeframe
    source: str
    retrieved_at: UtcDateTime
    candles: tuple[Candle, ...] = Field(min_length=1)
    provenance: MarketDataProvenance

    @model_validator(mode="after")
    def validate_identity_and_evidence(self) -> "ValidatedMarketData":
        evidence = self.provenance
        if evidence.data_mode is not MarketDataMode.SERVER_PROVIDER:
            raise ValueError("live market data must have SERVER_PROVIDER provenance")
        if (
            self.symbol is not evidence.symbol
            or self.timeframe is not evidence.timeframe
            or self.source != evidence.provider
            or self.retrieved_at != evidence.retrieved_at
        ):
            raise ValueError("market-data identity does not match provenance")
        if len(self.candles) != evidence.received_candles:
            raise ValueError("candle count does not match provenance")
        if self.candles[0].timestamp != evidence.first_candle_at:
            raise ValueError("first candle does not match provenance")
        if self.candles[-1].timestamp != evidence.last_candle_at:
            raise ValueError("last candle does not match provenance")
        return self


class MarketDataResponse(ValidatedMarketData):
    """Public serialization of server-validated market data."""
