from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.time import UtcDateTime
from app.schemas.market import MarketDataProvenance
from app.schemas.strategy import DeterministicStrategyEvaluation
from app.schemas.types import MarketSymbol, Timeframe


class ProductionAnalysisRequest(BaseModel):
    """Live/research-cutoff request; market evidence is always server fetched."""

    model_config = ConfigDict(extra="forbid")

    symbol: MarketSymbol
    timeframe: Timeframe | None = Field(
        default=None, deprecated=True,
        description="Display-only compatibility hint; never selects a strategy pipeline.",
    )
    cutoff: UtcDateTime | None = None


class AnalysisResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: MarketSymbol
    timeframe: Timeframe
    source: str
    retrieved_at: UtcDateTime
    data_cutoff_at: UtcDateTime
    provenance: MarketDataProvenance
    evaluation: DeterministicStrategyEvaluation

    @model_validator(mode="after")
    def validate_server_identity(self) -> "AnalysisResult":
        if (
            self.symbol is not self.provenance.symbol
            or self.timeframe is not self.provenance.timeframe
            or self.source != self.provenance.provider
            or self.retrieved_at != self.provenance.retrieved_at
            or self.data_cutoff_at != self.provenance.data_cutoff_at
        ):
            raise ValueError("analysis response identity must come from provenance")
        return self
