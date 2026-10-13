"""Additive execution metadata; original signal/analysis schemas remain intact."""
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.time import UtcDateTime
from app.schemas.market import MarketDataProvenance
from app.schemas.strategy_identity import StrategyIdentity
from app.schemas.types import MarketSymbol, Timeframe


class EvaluationStatus(str, Enum):
    PENDING = 'PENDING'
    RUNNING = 'RUNNING'
    COMPLETED = 'COMPLETED'
    FAILED = 'FAILED'
    CANCELLED = 'CANCELLED'


TERMINAL_EVALUATION_STATUSES = {
    EvaluationStatus.COMPLETED, EvaluationStatus.FAILED, EvaluationStatus.CANCELLED,
}


class EvaluationDataIdentity(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    provenance: MarketDataProvenance
    history_content_hash: str | None = Field(default=None, pattern=r'^[0-9a-f]{64}$')


class EvaluationFailure(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)


class EvaluationJobResponse(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    evaluation_id: UUID
    symbol: MarketSymbol
    canonical_timeframe: Timeframe
    cutoff: UtcDateTime
    strategy_identity: StrategyIdentity
    market_data_identity: EvaluationDataIdentity | None = None
    created_at: UtcDateTime
    started_at: UtcDateTime | None = None
    completed_at: UtcDateTime | None = None
    status: EvaluationStatus
    result_available: bool
    failure: EvaluationFailure | None = None

    @model_validator(mode='after')
    def validate_lifecycle(self) -> 'EvaluationJobResponse':
        terminal = self.status in TERMINAL_EVALUATION_STATUSES
        if terminal != (self.completed_at is not None):
            raise ValueError('terminal state requires its completion timestamp')
        if self.result_available != (self.status is EvaluationStatus.COMPLETED):
            raise ValueError('only fully completed evaluations expose results')
        if (self.failure is not None) != (self.status is EvaluationStatus.FAILED):
            raise ValueError('technical failure is distinct from a strategy result')
        if self.status is EvaluationStatus.COMPLETED and self.market_data_identity is None:
            raise ValueError('completed evaluation requires validated data identity')
        if self.status is EvaluationStatus.RUNNING and self.started_at is None:
            raise ValueError('running evaluation requires its start time')
        return self
