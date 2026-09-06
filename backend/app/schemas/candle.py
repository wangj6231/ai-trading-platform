from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.time import UtcDateTime

class Candle(BaseModel):
    """Provider-neutral OHLCV candle whose timestamp is its UTC open time."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    timestamp: UtcDateTime
    open: Decimal = Field(gt=0, allow_inf_nan=False)
    high: Decimal = Field(gt=0, allow_inf_nan=False)
    low: Decimal = Field(gt=0, allow_inf_nan=False)
    close: Decimal = Field(gt=0, allow_inf_nan=False)
    volume: Decimal = Field(ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_ohlc(self) -> "Candle":
        if self.high < max(self.open, self.close):
            raise ValueError("high must be greater than or equal to open and close")
        if self.low > min(self.open, self.close):
            raise ValueError("low must be less than or equal to open and close")
        if self.low > self.high:
            raise ValueError("low must be less than or equal to high")
        return self
