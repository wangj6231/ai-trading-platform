from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.core.strategy_config import load_strategy_config
from app.core.strategy_identity import STRATEGY_VERSION
from app.engines.signal import calculate_signal_score as _calculate_signal_score
from app.schemas.crt import (
    CRTConfig,
    CRTConfirmation,
    CRTConfirmationStatus,
    CRTDirection,
    CRTEntryRelation,
    CRTSignalMatchStatus,
    CRTSignalUse,
    CRTSweptSide,
)
from app.schemas.signal_score import (
    SignalComponentEvidence,
    SignalEvidenceDirection,
    SignalScoreComponent,
    SignalScoreDecision,
    SignalScoreEvidence,
    SignalScoreReasonCode,
)
from app.schemas.types import Timeframe


NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


def load_strategy_score_config():
    return load_strategy_config().pipelines["BTCUSDT"].signal_score


def calculate_signal_score(evidence, config):
    return _calculate_signal_score(
        evidence,
        config,
        strategy_version=STRATEGY_VERSION,
    )


def crt_confirmation(
    direction: CRTDirection,
    *,
    confirmed_at: datetime = NOW,
) -> CRTConfirmation:
    bullish = direction is CRTDirection.BULLISH
    return CRTConfirmation(
        confirmation_id=f"crt-{direction.value}",
        status=CRTConfirmationStatus.SWEEP_CANDLE_CLOSED,
        direction=direction,
        timeframe=Timeframe.FIVE_MINUTES,
        range_candle_timestamp=NOW - timedelta(minutes=10),
        range_high=110,
        range_low=100,
        manipulation_candle_timestamp=NOW - timedelta(minutes=5),
        manipulation_closed_at=NOW,
        swept_side=CRTSweptSide.LOW if bullish else CRTSweptSide.HIGH,
        sweep_level=100 if bullish else 110,
        source_event_id="formal-sweep-source",
        confirmed_at=confirmed_at,
        third_candle_timestamp=None,
        third_candle_open=None,
        entry_relation=(
            CRTEntryRelation.BUY_BELOW_THIRD_CANDLE_OPEN
            if bullish
            else CRTEntryRelation.SELL_ABOVE_THIRD_CANDLE_OPEN
        ),
        opposite_wick_reference=110 if bullish else 100,
    )


def evidence(
    confirmation: CRTConfirmation | None,
    *,
    only_bos: bool = False,
) -> SignalScoreEvidence:
    components = {
        SignalScoreComponent.BOS: SignalComponentEvidence(
            direction=SignalEvidenceDirection.BULLISH,
            confirmed_at=NOW,
            source_ids=("bos-1",),
        )
    }
    if not only_bos:
        components.update(
            {
                SignalScoreComponent.MSS: SignalComponentEvidence(
                    direction=SignalEvidenceDirection.BULLISH,
                    confirmed_at=NOW,
                    source_ids=("mss-1",),
                ),
                SignalScoreComponent.DISPLACEMENT: SignalComponentEvidence(
                    direction=SignalEvidenceDirection.BULLISH,
                    confirmed_at=NOW,
                    source_ids=("displacement-1",),
                ),
            }
        )
    return SignalScoreEvidence(
        decision_time=NOW,
        components=components,
        crt_confirmation=confirmation,
    )


def configured_crt(
    *,
    uses: tuple[CRTSignalUse, ...],
    weight: int | None = None,
    enabled: bool = True,
):
    base = load_strategy_score_config()
    return base.model_copy(
        update={
            "crt": CRTConfig(
                enabled=enabled,
                signal_uses=uses,
                weight=weight,
            )
        }
    )


def test_default_repository_config_has_no_crt_weight_or_signal_effect() -> None:
    config = load_strategy_score_config()
    result = calculate_signal_score(
        evidence(crt_confirmation(CRTDirection.BULLISH)),
        config,
    )

    assert config.crt.enabled is False
    assert config.crt.weight is None
    assert result.score == 6
    assert result.crt_score_contribution == 0
    assert result.crt_confirmation_status is CRTSignalMatchStatus.DISABLED


def test_confirmation_mode_records_match_without_changing_score() -> None:
    result = calculate_signal_score(
        evidence(crt_confirmation(CRTDirection.BULLISH)),
        configured_crt(uses=(CRTSignalUse.CONFIRMATION,)),
    )

    assert result.decision is SignalScoreDecision.LONG_CANDIDATE
    assert result.score == 6
    assert result.crt_score_contribution == 0
    assert result.crt_confirmation_status is CRTSignalMatchStatus.MATCH
    assert SignalScoreReasonCode.CRT_CONFIRMATION_MATCH in result.reason_codes


def test_filter_mode_keeps_match_and_rejects_missing_or_conflicting_crt() -> None:
    config = configured_crt(uses=(CRTSignalUse.FILTER,))
    matching = calculate_signal_score(
        evidence(crt_confirmation(CRTDirection.BULLISH)), config
    )
    missing = calculate_signal_score(evidence(None), config)
    conflict = calculate_signal_score(
        evidence(crt_confirmation(CRTDirection.BEARISH)), config
    )

    assert matching.decision is SignalScoreDecision.LONG_CANDIDATE
    assert missing.decision is SignalScoreDecision.NO_TRADE
    assert SignalScoreReasonCode.CRT_FILTER_MISSING in missing.reason_codes
    assert conflict.decision is SignalScoreDecision.NO_TRADE
    assert (
        SignalScoreReasonCode.CRT_FILTER_DIRECTION_CONFLICT
        in conflict.reason_codes
    )


def test_crt_contributes_only_when_weight_is_explicitly_configured() -> None:
    without_weight = calculate_signal_score(
        evidence(crt_confirmation(CRTDirection.BULLISH), only_bos=True),
        configured_crt(uses=(CRTSignalUse.CONFIRMATION,)),
    )
    with_weight = calculate_signal_score(
        evidence(crt_confirmation(CRTDirection.BULLISH), only_bos=True),
        configured_crt(uses=(CRTSignalUse.CONFIRMATION,), weight=3),
    )

    assert without_weight.score == 2
    assert without_weight.decision is SignalScoreDecision.NO_TRADE
    assert with_weight.score == 5
    assert with_weight.crt_score_contribution == 3
    assert with_weight.decision is SignalScoreDecision.LONG_CANDIDATE


def test_disabled_crt_ignores_even_an_explicit_latent_weight() -> None:
    result = calculate_signal_score(
        evidence(crt_confirmation(CRTDirection.BULLISH), only_bos=True),
        configured_crt(
            uses=(CRTSignalUse.CONFIRMATION,),
            weight=10,
            enabled=False,
        ),
    )

    assert result.score == 2
    assert result.crt_score_contribution == 0
    assert result.decision is SignalScoreDecision.NO_TRADE


def test_future_crt_confirmation_is_rejected() -> None:
    with pytest.raises(ValidationError, match="CRT confirmation"):
        evidence(
            crt_confirmation(
                CRTDirection.BULLISH,
                confirmed_at=NOW + timedelta(seconds=1),
            )
        )
