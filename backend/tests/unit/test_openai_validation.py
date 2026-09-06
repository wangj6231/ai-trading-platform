from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.schemas.openai_validation import (
    OpenAIValidationContext,
    OpenAIValidationEvidenceV1,
    OpenAIValidationOutput,
    OpenAIValidationStatus,
    canonical_openai_evidence_hash,
    canonical_openai_input_hash,
)
from app.schemas.signal import EntryZone, SignalDecision
from app.schemas.types import MarketSymbol
from app.services.openai_validation import (
    OpenAIValidationService,
    SYSTEM_INSTRUCTIONS,
    build_openai_validation_service,
)


NOW = datetime(2025, 11, 1, 12, 0, tzinfo=UTC)


class MockResponses:
    def __init__(self, *, output=None, error: Exception | None = None) -> None:
        self.output = output
        self.error = error
        self.calls: list[dict] = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return SimpleNamespace(output_parsed=self.output)


class MockClient:
    def __init__(self, responses: MockResponses) -> None:
        self.responses = responses


def settings(*, enabled: bool = True, min_confidence: int = 50) -> Settings:
    return Settings(
        _env_file=None,
        openai_validation_enabled=enabled,
        openai_model="mock-model",
        openai_validation_timeout_seconds=3,
        openai_validation_min_confidence=min_confidence,
    )


def context(direction: SignalDecision = SignalDecision.LONG) -> OpenAIValidationContext:
    if direction is SignalDecision.NO_TRADE:
        entry = tp = sl = rr = None
    elif direction is SignalDecision.LONG:
        entry = EntryZone(low=Decimal("100"), high=Decimal("102"))
        tp, sl, rr = Decimal("108"), Decimal("98"), Decimal("2")
    else:
        entry = EntryZone(low=Decimal("100"), high=Decimal("102"))
        tp, sl, rr = Decimal("94"), Decimal("104"), Decimal("2")
    return OpenAIValidationContext(
        symbol=MarketSymbol.BTCUSDT,
        current_price=Decimal("101"),
        multi_timeframe_context={"alignment": "ALIGNED"},
        macd={"bullish_crossover": direction is SignalDecision.LONG},
        market_structure={"event": "MSS"},
        smc={"fvg": "ACTIVE"},
        ict={"setup": "READY"},
        snr={"support": "100-102"},
        candidate_direction=direction,
        algorithm_score=7 if direction is SignalDecision.LONG else -7,
        entry_zone=entry,
        candidate_tp=tp,
        candidate_sl=sl,
        risk_reward=rr,
        data_cutoff_at=NOW,
    )


def ai_output(
    decision: SignalDecision = SignalDecision.LONG,
    *,
    confidence: int = 80,
    entry_min: str | None = "100",
    entry_max: str | None = "102",
    tp: str | None = "108",
    sl: str | None = "98",
    rr: str | None = "2",
) -> OpenAIValidationOutput:
    return OpenAIValidationOutput(
        decision=decision,
        confidence=confidence,
        entry_min=Decimal(entry_min) if entry_min is not None else None,
        entry_max=Decimal(entry_max) if entry_max is not None else None,
        take_profit=Decimal(tp) if tp is not None else None,
        stop_loss=Decimal(sl) if sl is not None else None,
        risk_reward=Decimal(rr) if rr is not None else None,
        reason=["The supplied deterministic evidence is internally consistent."],
    )


def test_confirmed_candidate_preserves_all_deterministic_levels() -> None:
    responses = MockResponses(output=ai_output())
    service = OpenAIValidationService(settings(), client=MockClient(responses))

    result = service.validate(context())

    assert result.algorithm_decision is SignalDecision.LONG
    assert result.ai_decision is SignalDecision.LONG
    assert result.final_decision is SignalDecision.LONG
    assert result.validation_status is OpenAIValidationStatus.CONFIRMED
    assert result.entry_zone == EntryZone(low=Decimal("100"), high=Decimal("102"))
    assert result.take_profit == Decimal("108")
    assert result.stop_loss == Decimal("98")
    assert result.risk_reward == Decimal("2")
    assert result.evidence.status is OpenAIValidationStatus.CONFIRMED
    assert result.evidence.provider == "OPENAI"
    assert result.evidence.model_id == "mock-model"
    assert result.evidence.deterministic_input_hash == canonical_openai_input_hash(
        context()
    )
    assert result.evidence.structured_response == ai_output()
    assert responses.calls[0]["text_format"] is OpenAIValidationOutput
    assert responses.calls[0]["timeout"] == 3


def test_structured_output_schema_requires_every_field_and_numeric_levels() -> None:
    schema = OpenAIValidationOutput.model_json_schema()

    assert set(schema["required"]) == {
        "decision",
        "confidence",
        "entry_min",
        "entry_max",
        "take_profit",
        "stop_loss",
        "risk_reward",
        "reason",
    }
    for field_name in (
        "entry_min",
        "entry_max",
        "take_profit",
        "stop_loss",
        "risk_reward",
    ):
        alternatives = schema["properties"][field_name]["anyOf"]
        assert {item["type"] for item in alternatives} == {"number", "null"}


def test_prompt_is_structured_and_never_asks_for_a_primary_trade_decision() -> None:
    responses = MockResponses(output=ai_output())
    service = OpenAIValidationService(settings(), client=MockClient(responses))

    service.validate(context())

    call = responses.calls[0]
    prompt = call["input"][1]["content"]
    assert '"symbol":"BTCUSDT"' in prompt
    assert '"candidate_direction":"LONG"' in prompt
    assert '"algorithm_score":7' in prompt
    assert '"candidate_tp":"108"' in prompt
    assert "should i buy or sell" not in (SYSTEM_INSTRUCTIONS + prompt).lower()


def test_deterministic_no_trade_skips_api_and_cannot_be_upgraded() -> None:
    responses = MockResponses(output=ai_output())
    service = OpenAIValidationService(settings(), client=MockClient(responses))

    result = service.validate(context(SignalDecision.NO_TRADE))

    assert responses.calls == []
    assert result.algorithm_decision is SignalDecision.NO_TRADE
    assert result.ai_decision is None
    assert result.final_decision is SignalDecision.NO_TRADE
    assert result.validation_status is OpenAIValidationStatus.SKIPPED_ALGORITHM_NO_TRADE
    assert result.evidence.provider is None
    assert result.evidence.model_id is None
    assert result.evidence.structured_response is None


def test_ai_can_reject_candidate() -> None:
    rejection = ai_output(
        SignalDecision.NO_TRADE,
        entry_min=None,
        entry_max=None,
        tp=None,
        sl=None,
        rr=None,
    )
    service = OpenAIValidationService(
        settings(), client=MockClient(MockResponses(output=rejection))
    )

    result = service.validate(context())

    assert result.algorithm_decision is SignalDecision.LONG
    assert result.ai_decision is SignalDecision.NO_TRADE
    assert result.final_decision is SignalDecision.NO_TRADE
    assert result.validation_status is OpenAIValidationStatus.REJECTED
    assert result.entry_zone is None
    assert result.evidence.structured_response == rejection


@pytest.mark.parametrize(
    "output",
    [
        ai_output(SignalDecision.SHORT, tp="94", sl="104"),
        ai_output(entry_min="99"),
        ai_output(entry_max="103"),
        ai_output(tp="109"),
        ai_output(sl="97"),
        ai_output(rr="2.1"),
    ],
)
def test_direction_or_level_changes_are_constraint_rejected(output) -> None:
    service = OpenAIValidationService(
        settings(), client=MockClient(MockResponses(output=output))
    )

    result = service.validate(context())

    assert result.final_decision is SignalDecision.NO_TRADE
    assert result.validation_status is OpenAIValidationStatus.CONSTRAINT_REJECTED
    assert result.take_profit is None
    assert result.stop_loss is None


def test_low_confidence_reduces_candidate_to_no_trade() -> None:
    service = OpenAIValidationService(
        settings(min_confidence=70),
        client=MockClient(MockResponses(output=ai_output(confidence=69))),
    )

    result = service.validate(context())

    assert result.ai_decision is SignalDecision.LONG
    assert result.final_decision is SignalDecision.NO_TRADE
    assert result.validation_status is OpenAIValidationStatus.REDUCED_CONFIDENCE
    assert result.confidence == 69


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (TimeoutError("late"), OpenAIValidationStatus.TIMEOUT),
        (RuntimeError("network unavailable"), OpenAIValidationStatus.API_ERROR),
    ],
)
def test_api_failures_fail_closed(error, expected_status) -> None:
    service = OpenAIValidationService(
        settings(), client=MockClient(MockResponses(error=error))
    )

    result = service.validate(context())

    assert result.final_decision is SignalDecision.NO_TRADE
    assert result.ai_decision is None
    assert result.validation_status is expected_status
    assert result.entry_zone is None
    assert result.evidence.provider == "OPENAI"
    assert result.evidence.model_id == "mock-model"
    assert result.evidence.structured_response is None


@pytest.mark.parametrize("invalid", [None, "not-json", {"decision": "LONG"}])
def test_invalid_structured_output_fails_closed(invalid) -> None:
    service = OpenAIValidationService(
        settings(), client=MockClient(MockResponses(output=invalid))
    )

    result = service.validate(context())

    assert result.final_decision is SignalDecision.NO_TRADE
    assert result.validation_status is OpenAIValidationStatus.INVALID_RESPONSE


def test_disabled_and_unavailable_validation_never_promote_candidate() -> None:
    disabled_responses = MockResponses(output=ai_output())
    disabled = OpenAIValidationService(
        settings(enabled=False), client=MockClient(disabled_responses)
    ).validate(context())
    unavailable = OpenAIValidationService(settings(), client=None).validate(context())

    assert disabled.final_decision is SignalDecision.NO_TRADE
    assert disabled.validation_status is OpenAIValidationStatus.DISABLED
    assert disabled_responses.calls == []
    assert unavailable.final_decision is SignalDecision.NO_TRADE
    assert unavailable.validation_status is OpenAIValidationStatus.UNAVAILABLE


def test_enabled_service_with_missing_api_key_is_unavailable_not_crashed() -> None:
    service = build_openai_validation_service(settings())

    result = service.validate(context())

    assert result.final_decision is SignalDecision.NO_TRADE
    assert result.validation_status is OpenAIValidationStatus.UNAVAILABLE


def test_validation_input_and_evidence_hashes_are_canonical_and_sensitive() -> None:
    original = context()
    equivalent = OpenAIValidationContext.model_validate(
        original.model_dump(mode="python")
    )
    changed = original.model_copy(update={"algorithm_score": 8})
    result = OpenAIValidationService(
        settings(), client=MockClient(MockResponses(output=ai_output()))
    ).validate(original)

    assert canonical_openai_input_hash(original) == canonical_openai_input_hash(
        equivalent
    )
    assert canonical_openai_input_hash(original) != canonical_openai_input_hash(changed)
    assert canonical_openai_evidence_hash(result.evidence) == (
        canonical_openai_evidence_hash(
            OpenAIValidationEvidenceV1.model_validate(
                result.evidence.model_dump(mode="python")
            )
        )
    )


def test_validation_evidence_rejects_contradictory_or_forged_provenance() -> None:
    with pytest.raises(ValidationError, match="NOT_REQUESTED"):
        OpenAIValidationEvidenceV1(
            status=OpenAIValidationStatus.NOT_REQUESTED,
            provider="OPENAI",
            model_id="client-claimed-model",
            completed_at=NOW,
        )
    with pytest.raises(ValidationError, match="requires model"):
        OpenAIValidationEvidenceV1(
            status=OpenAIValidationStatus.CONFIRMED,
            completed_at=NOW,
            structured_response=ai_output(),
        )


def test_structured_response_is_bounded_and_rejects_unknown_fields() -> None:
    raw = ai_output().model_dump(mode="python")
    raw["unknown"] = "untrusted"
    with pytest.raises(ValidationError, match="Extra inputs"):
        OpenAIValidationOutput.model_validate(raw)
    with pytest.raises(ValidationError, match="reason"):
        OpenAIValidationOutput.model_validate(
            {**ai_output().model_dump(mode="python"), "reason": ["x" * 1025]}
        )
