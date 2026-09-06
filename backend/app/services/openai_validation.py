import json
from datetime import datetime
from typing import Any, Protocol, cast

from pydantic import ValidationError

from app.core.config import Settings
from app.core.time import utc_now
from app.schemas.openai_validation import (
    AI_VALIDATION_EVIDENCE_SCHEMA_VERSION,
    FinalValidationResult,
    OpenAIValidationContext,
    OpenAIValidationEvidenceV1,
    OpenAIValidationOutput,
    OpenAIValidationStatus,
    canonical_openai_input_hash,
)
from app.schemas.signal import SignalDecision


SYSTEM_INSTRUCTIONS = """You are a secondary validator for an already completed deterministic technical-analysis candidate.
The backend algorithm is authoritative. You may confirm the candidate, reject it, or lower confidence.
You must never create a trade from NO_TRADE, reverse direction, invent market structures, or change entry, take-profit, stop-loss, or risk/reward values.
If evidence is insufficient or conflicting, return NO_TRADE with null levels and concise reasons.
When confirming, echo the supplied deterministic direction and levels exactly."""


class ResponsesAPI(Protocol):
    def parse(self, **kwargs: Any) -> Any: ...


class OpenAIClient(Protocol):
    responses: ResponsesAPI


class OpenAIValidationService:
    def __init__(
        self,
        settings: Settings,
        *,
        client: OpenAIClient | None = None,
    ) -> None:
        self._enabled = settings.openai_validation_enabled
        self._model = settings.openai_model
        self._timeout = settings.openai_validation_timeout_seconds
        self._minimum_confidence = settings.openai_validation_min_confidence
        self._client = client

    def validate(self, context: OpenAIValidationContext) -> FinalValidationResult:
        """Run only after deterministic analysis, with fail-closed merge rules."""

        completed_at = utc_now()
        deterministic_input_hash = canonical_openai_input_hash(context)
        algorithm_decision = context.candidate_direction
        if algorithm_decision is SignalDecision.NO_TRADE:
            return _no_trade(
                context,
                status=OpenAIValidationStatus.SKIPPED_ALGORITHM_NO_TRADE,
                reason=("Deterministic engine returned NO_TRADE; AI validation was skipped.",),
                validated_at=completed_at,
                deterministic_input_hash=deterministic_input_hash,
            )
        if not self._enabled:
            return _no_trade(
                context,
                status=OpenAIValidationStatus.DISABLED,
                reason=("OpenAI validation is disabled; candidate was not promoted.",),
                validated_at=completed_at,
                deterministic_input_hash=deterministic_input_hash,
            )
        if self._client is None or not self._model:
            return _no_trade(
                context,
                status=OpenAIValidationStatus.UNAVAILABLE,
                reason=("OpenAI validation client or model is unavailable.",),
                validated_at=completed_at,
                deterministic_input_hash=deterministic_input_hash,
            )

        request_started_at = utc_now()
        try:
            response = self._client.responses.parse(
                model=self._model,
                input=[
                    {"role": "system", "content": SYSTEM_INSTRUCTIONS},
                    {
                        "role": "user",
                        "content": json.dumps(
                            context.prompt_payload(),
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                    },
                ],
                text_format=OpenAIValidationOutput,
                timeout=self._timeout,
            )
            parsed = getattr(response, "output_parsed", None)
            ai_output = (
                parsed
                if isinstance(parsed, OpenAIValidationOutput)
                else OpenAIValidationOutput.model_validate(parsed)
            )
        except Exception as exc:  # SDK exceptions intentionally fail closed.
            completed_at = utc_now()
            if _is_timeout(exc):
                status = OpenAIValidationStatus.TIMEOUT
                message = "OpenAI validation timed out; candidate was rejected safely."
            elif isinstance(exc, (ValidationError, ValueError, TypeError, json.JSONDecodeError)):
                status = OpenAIValidationStatus.INVALID_RESPONSE
                message = "OpenAI returned an invalid structured response."
            else:
                status = OpenAIValidationStatus.API_ERROR
                message = "OpenAI validation failed; candidate was rejected safely."
            return _no_trade(
                context,
                status=status,
                reason=(message,),
                validated_at=completed_at,
                deterministic_input_hash=deterministic_input_hash,
                model_id=self._model,
                request_started_at=request_started_at,
            )

        completed_at = utc_now()
        if ai_output.decision is SignalDecision.NO_TRADE:
            return _no_trade(
                context,
                ai_output=ai_output,
                status=OpenAIValidationStatus.REJECTED,
                reason=tuple(ai_output.reason),
                validated_at=completed_at,
                deterministic_input_hash=deterministic_input_hash,
                model_id=self._model,
                request_started_at=request_started_at,
            )
        if not _matches_deterministic_candidate(context, ai_output):
            return _no_trade(
                context,
                ai_output=ai_output,
                status=OpenAIValidationStatus.CONSTRAINT_REJECTED,
                reason=(
                    "AI direction or levels differed from the immutable deterministic candidate.",
                    *ai_output.reason,
                ),
                validated_at=completed_at,
                deterministic_input_hash=deterministic_input_hash,
                model_id=self._model,
                request_started_at=request_started_at,
            )
        if ai_output.confidence < self._minimum_confidence:
            return _no_trade(
                context,
                ai_output=ai_output,
                status=OpenAIValidationStatus.REDUCED_CONFIDENCE,
                reason=(
                    f"AI confidence {ai_output.confidence} is below configured minimum "
                    f"{self._minimum_confidence}.",
                    *ai_output.reason,
                ),
                validated_at=completed_at,
                deterministic_input_hash=deterministic_input_hash,
                model_id=self._model,
                request_started_at=request_started_at,
            )

        evidence = _validation_evidence(
            status=OpenAIValidationStatus.CONFIRMED,
            completed_at=completed_at,
            deterministic_input_hash=deterministic_input_hash,
            model_id=self._model,
            request_started_at=request_started_at,
            ai_output=ai_output,
        )
        return FinalValidationResult(
            algorithm_decision=algorithm_decision,
            ai_decision=ai_output.decision,
            final_decision=algorithm_decision,
            validation_status=OpenAIValidationStatus.CONFIRMED,
            confidence=ai_output.confidence,
            entry_zone=context.entry_zone,
            take_profit=context.candidate_tp,
            stop_loss=context.candidate_sl,
            risk_reward=context.risk_reward,
            reason=tuple(ai_output.reason),
            validated_at=completed_at,
            evidence=evidence,
        )


def build_openai_validation_service(
    settings: Settings,
    *,
    client: OpenAIClient | None = None,
) -> OpenAIValidationService:
    """Build the optional client without placing credentials in source code."""

    if client is not None:
        return OpenAIValidationService(settings, client=client)
    api_key = (
        settings.openai_api_key.get_secret_value().strip()
        if settings.openai_api_key is not None
        else ""
    )
    if not settings.openai_validation_enabled or not api_key:
        return OpenAIValidationService(settings)

    try:
        from openai import OpenAI

        sdk_client = OpenAI(api_key=api_key)
    except Exception:
        return OpenAIValidationService(settings)
    return OpenAIValidationService(settings, client=cast(OpenAIClient, sdk_client))


def _matches_deterministic_candidate(
    context: OpenAIValidationContext,
    output: OpenAIValidationOutput,
) -> bool:
    assert context.entry_zone is not None
    return (
        output.decision is context.candidate_direction
        and output.entry_min == context.entry_zone.low
        and output.entry_max == context.entry_zone.high
        and output.take_profit == context.candidate_tp
        and output.stop_loss == context.candidate_sl
        and output.risk_reward == context.risk_reward
    )


def _no_trade(
    context: OpenAIValidationContext,
    *,
    status: OpenAIValidationStatus,
    reason: tuple[str, ...],
    validated_at: datetime,
    deterministic_input_hash: str,
    model_id: str | None = None,
    request_started_at: datetime | None = None,
    ai_output: OpenAIValidationOutput | None = None,
) -> FinalValidationResult:
    evidence = _validation_evidence(
        status=status,
        completed_at=validated_at,
        deterministic_input_hash=deterministic_input_hash,
        model_id=model_id,
        request_started_at=request_started_at,
        ai_output=ai_output,
    )
    return FinalValidationResult(
        algorithm_decision=context.candidate_direction,
        ai_decision=ai_output.decision if ai_output is not None else None,
        final_decision=SignalDecision.NO_TRADE,
        validation_status=status,
        confidence=ai_output.confidence if ai_output is not None else None,
        reason=reason,
        validated_at=validated_at,
        evidence=evidence,
    )


def _validation_evidence(
    *,
    status: OpenAIValidationStatus,
    completed_at: datetime,
    deterministic_input_hash: str,
    model_id: str | None,
    request_started_at: datetime | None,
    ai_output: OpenAIValidationOutput | None,
) -> OpenAIValidationEvidenceV1:
    requested = request_started_at is not None
    return OpenAIValidationEvidenceV1(
        schema_version=AI_VALIDATION_EVIDENCE_SCHEMA_VERSION,
        status=status,
        provider="OPENAI" if requested else None,
        model_id=model_id if requested else None,
        deterministic_input_hash=deterministic_input_hash,
        request_started_at=request_started_at,
        completed_at=completed_at,
        structured_response=ai_output,
    )


def _is_timeout(exc: Exception) -> bool:
    return isinstance(exc, TimeoutError) or exc.__class__.__name__ in {
        "APITimeoutError",
        "ConnectTimeout",
        "ReadTimeout",
        "TimeoutException",
    }
