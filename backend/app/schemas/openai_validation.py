import hashlib
import json
from decimal import Decimal
from enum import Enum
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    WithJsonSchema,
    field_validator,
    model_validator,
)

from app.core.time import UtcDateTime
from app.schemas.signal import EntryZone, SignalDecision
from app.schemas.types import MarketSymbol


StructuredNumber = Annotated[Decimal, WithJsonSchema({"type": "number"})]


class OpenAIValidationStatus(str, Enum):
    NOT_REQUESTED = "NOT_REQUESTED"
    SKIPPED_ALGORITHM_NO_TRADE = "SKIPPED_ALGORITHM_NO_TRADE"
    DISABLED = "DISABLED"
    UNAVAILABLE = "UNAVAILABLE"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"
    REDUCED_CONFIDENCE = "REDUCED_CONFIDENCE"
    CONSTRAINT_REJECTED = "CONSTRAINT_REJECTED"
    TIMEOUT = "TIMEOUT"
    INVALID_RESPONSE = "INVALID_RESPONSE"
    API_ERROR = "API_ERROR"


class OpenAIValidationContext(BaseModel):
    """Structured deterministic analysis sent only after backend evaluation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: MarketSymbol
    current_price: Decimal = Field(gt=0, allow_inf_nan=False)
    multi_timeframe_context: dict[str, JsonValue]
    macd: dict[str, JsonValue]
    market_structure: dict[str, JsonValue]
    smc: dict[str, JsonValue]
    ict: dict[str, JsonValue]
    snr: dict[str, JsonValue]
    candidate_direction: SignalDecision
    algorithm_score: int
    entry_zone: EntryZone | None = None
    candidate_tp: Decimal | None = Field(default=None, gt=0, allow_inf_nan=False)
    candidate_sl: Decimal | None = Field(default=None, gt=0, allow_inf_nan=False)
    risk_reward: Decimal | None = Field(default=None, gt=0, allow_inf_nan=False)
    data_cutoff_at: UtcDateTime

    @model_validator(mode="after")
    def validate_deterministic_candidate(self) -> "OpenAIValidationContext":
        levels = (self.entry_zone, self.candidate_tp, self.candidate_sl, self.risk_reward)
        if self.candidate_direction is SignalDecision.NO_TRADE:
            if any(value is not None for value in levels):
                raise ValueError("deterministic NO_TRADE must not contain trade levels")
            return self
        if any(value is None for value in levels):
            raise ValueError("deterministic trade candidate requires entry, TP, SL, and RR")

        assert self.entry_zone is not None
        assert self.candidate_tp is not None
        assert self.candidate_sl is not None
        if self.candidate_direction is SignalDecision.LONG:
            if not self.candidate_sl < self.entry_zone.low <= self.entry_zone.high < self.candidate_tp:
                raise ValueError("LONG candidate levels are directionally invalid")
        elif not self.candidate_tp < self.entry_zone.low <= self.entry_zone.high < self.candidate_sl:
            raise ValueError("SHORT candidate levels are directionally invalid")
        return self

    def prompt_payload(self) -> dict[str, JsonValue]:
        """Return only the approved structured fields for the API request."""

        return self.model_dump(mode="json")


class OpenAIValidationOutput(BaseModel):
    """Strict Structured Outputs schema returned by the secondary validator."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: SignalDecision
    confidence: int = Field(ge=0, le=100)
    entry_min: StructuredNumber | None = Field(gt=0, allow_inf_nan=False)
    entry_max: StructuredNumber | None = Field(gt=0, allow_inf_nan=False)
    take_profit: StructuredNumber | None = Field(gt=0, allow_inf_nan=False)
    stop_loss: StructuredNumber | None = Field(gt=0, allow_inf_nan=False)
    risk_reward: StructuredNumber | None = Field(gt=0, allow_inf_nan=False)
    reason: list[str] = Field(min_length=1, max_length=16)

    @field_validator("reason")
    @classmethod
    def require_nonblank_reasons(cls, value: list[str]) -> list[str]:
        if any(not item.strip() or len(item) > 1024 for item in value):
            raise ValueError("reason must not contain blank items")
        return value

    @model_validator(mode="after")
    def validate_output_levels(self) -> "OpenAIValidationOutput":
        levels = (
            self.entry_min,
            self.entry_max,
            self.take_profit,
            self.stop_loss,
            self.risk_reward,
        )
        if self.decision is SignalDecision.NO_TRADE:
            if any(value is not None for value in levels):
                raise ValueError("AI NO_TRADE must return null trade levels")
            return self
        if any(value is None for value in levels):
            raise ValueError("AI LONG/SHORT requires entry, TP, SL, and RR")
        assert self.entry_min is not None
        assert self.entry_max is not None
        if self.entry_min > self.entry_max:
            raise ValueError("entry_min must not exceed entry_max")
        return self


AI_VALIDATION_EVIDENCE_SCHEMA_VERSION: Literal["1"] = "1"
_AI_OUTPUT_STATUSES = frozenset(
    {
        OpenAIValidationStatus.CONFIRMED,
        OpenAIValidationStatus.REJECTED,
        OpenAIValidationStatus.REDUCED_CONFIDENCE,
        OpenAIValidationStatus.CONSTRAINT_REJECTED,
    }
)
_AI_REQUEST_FAILURE_STATUSES = frozenset(
    {
        OpenAIValidationStatus.TIMEOUT,
        OpenAIValidationStatus.INVALID_RESPONSE,
        OpenAIValidationStatus.API_ERROR,
    }
)
_AI_NO_REQUEST_STATUSES = frozenset(
    {
        OpenAIValidationStatus.SKIPPED_ALGORITHM_NO_TRADE,
        OpenAIValidationStatus.DISABLED,
        OpenAIValidationStatus.UNAVAILABLE,
    }
)


class OpenAIValidationEvidenceV1(BaseModel):
    """Immutable, bounded provenance for one secondary-validation outcome."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1"] = AI_VALIDATION_EVIDENCE_SCHEMA_VERSION
    status: OpenAIValidationStatus
    provider: Literal["OPENAI"] | None = None
    model_id: str | None = Field(default=None, min_length=1, max_length=128)
    deterministic_input_hash: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    request_started_at: UtcDateTime | None = None
    completed_at: UtcDateTime
    structured_response: OpenAIValidationOutput | None = None

    @field_validator("model_id")
    @classmethod
    def reject_unsafe_model_id(cls, value: str | None) -> str | None:
        if value is not None and (
            not value.strip() or any(ord(char) < 32 for char in value)
        ):
            raise ValueError("model_id must be a safe nonblank server identifier")
        return value

    @model_validator(mode="after")
    def validate_provenance_shape(self) -> "OpenAIValidationEvidenceV1":
        requested = self.status in _AI_OUTPUT_STATUSES | _AI_REQUEST_FAILURE_STATUSES
        has_request_identity = (
            self.provider is not None
            and self.model_id is not None
            and self.request_started_at is not None
        )
        if self.status is OpenAIValidationStatus.NOT_REQUESTED:
            if any(
                value is not None
                for value in (
                    self.provider,
                    self.model_id,
                    self.deterministic_input_hash,
                    self.request_started_at,
                    self.structured_response,
                )
            ):
                raise ValueError("NOT_REQUESTED cannot contain AI request evidence")
        elif self.status in _AI_NO_REQUEST_STATUSES:
            if (
                self.deterministic_input_hash is None
                or any(
                    value is not None
                    for value in (
                        self.provider,
                        self.model_id,
                        self.request_started_at,
                        self.structured_response,
                    )
                )
            ):
                raise ValueError(
                    "non-requested validation requires only deterministic input hash"
                )
        elif requested:
            if self.deterministic_input_hash is None or not has_request_identity:
                raise ValueError("requested validation requires model, time, and input hash")
            if (
                self.request_started_at is not None
                and self.completed_at < self.request_started_at
            ):
                raise ValueError("AI validation completion precedes request")
            if (self.status in _AI_OUTPUT_STATUSES) != (
                self.structured_response is not None
            ):
                raise ValueError(
                    "structured response presence contradicts validation status"
                )
        else:
            raise ValueError("unsupported AI validation status")
        return self


def canonical_openai_input_hash(context: OpenAIValidationContext) -> str:
    payload = json.dumps(
        context.prompt_payload(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def canonical_openai_evidence_hash(evidence: OpenAIValidationEvidenceV1) -> str:
    payload = json.dumps(
        evidence.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class FinalValidationResult(BaseModel):
    """Auditable merge that keeps algorithm, AI, and final decisions separate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    algorithm_decision: SignalDecision
    ai_decision: SignalDecision | None
    final_decision: SignalDecision
    validation_status: OpenAIValidationStatus
    confidence: int | None = Field(default=None, ge=0, le=100)
    entry_zone: EntryZone | None = None
    take_profit: Decimal | None = Field(default=None, gt=0, allow_inf_nan=False)
    stop_loss: Decimal | None = Field(default=None, gt=0, allow_inf_nan=False)
    risk_reward: Decimal | None = Field(default=None, gt=0, allow_inf_nan=False)
    reason: tuple[str, ...] = Field(min_length=1)
    validated_at: UtcDateTime
    evidence: OpenAIValidationEvidenceV1

    @model_validator(mode="after")
    def enforce_final_decision_constraints(self) -> "FinalValidationResult":
        levels = (self.entry_zone, self.take_profit, self.stop_loss, self.risk_reward)
        if (
            self.evidence.status is not self.validation_status
            or self.evidence.completed_at != self.validated_at
        ):
            raise ValueError("AI validation result and evidence disagree")
        output = self.evidence.structured_response
        if self.ai_decision is not (output.decision if output is not None else None):
            raise ValueError("AI decision does not match structured evidence")
        if self.confidence != (output.confidence if output is not None else None):
            raise ValueError("AI confidence does not match structured evidence")
        if self.algorithm_decision is SignalDecision.NO_TRADE:
            if self.final_decision is not SignalDecision.NO_TRADE:
                raise ValueError("AI cannot upgrade deterministic NO_TRADE")
        if self.final_decision is SignalDecision.NO_TRADE:
            if any(value is not None for value in levels):
                raise ValueError("final NO_TRADE must not contain trade levels")
            return self
        if self.final_decision is not self.algorithm_decision:
            raise ValueError("final trade direction must equal algorithm direction")
        if self.ai_decision is not self.algorithm_decision:
            raise ValueError("final trade requires matching AI confirmation")
        if any(value is None for value in levels):
            raise ValueError("final trade requires exact deterministic levels")
        return self
