from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.core.strategy_config import (
    DEFAULT_STRATEGY_CONFIG_PATH,
    StrategyConfigError,
    load_strategy_config,
)
from app.core.strategy_identity import STRATEGY_VERSION
from app.engines.signal import calculate_signal_score as _calculate_signal_score
from app.schemas.crt import CRTConfig
from app.schemas.signal_score import (
    SignalComponentEvidence,
    SignalEvidenceDirection,
    SignalScoreComponent,
    SignalScoreDecision,
    SignalScoreEvidence,
    SignalScoreMetadata,
    SignalScoreReasonCode,
    SignalScoreThresholds,
    SignalScoreWeights,
    StrategyScoreConfig,
)


DECISION_TIME = datetime(2025, 9, 1, 12, 0, tzinfo=UTC)


def load_strategy_score_config():
    return load_strategy_config().pipelines["BTCUSDT"].signal_score


def calculate_signal_score(evidence, config):
    return _calculate_signal_score(
        evidence,
        config,
        strategy_version=STRATEGY_VERSION,
    )


def component(
    direction: SignalEvidenceDirection,
    *,
    source: str,
    confirmed_at: datetime = DECISION_TIME,
) -> SignalComponentEvidence:
    return SignalComponentEvidence(
        direction=direction,
        confirmed_at=confirmed_at,
        source_ids=(source,),
    )


def evidence(
    directions: dict[SignalScoreComponent, SignalEvidenceDirection],
    *,
    htf_conflict: bool = False,
) -> SignalScoreEvidence:
    return SignalScoreEvidence(
        decision_time=DECISION_TIME,
        components={
            name: component(direction, source=f"source-{name.value}")
            for name, direction in directions.items()
        },
        higher_timeframe_conflict=htf_conflict,
    )


def test_repository_strategy_configuration_loads_and_is_unvalidated() -> None:
    config = load_strategy_score_config()

    assert DEFAULT_STRATEGY_CONFIG_PATH.name == "strategy.yaml"
    assert config.signal.long_threshold == 5
    assert config.signal.short_threshold == -5
    assert config.metadata.empirical_validation_status == "UNVALIDATED"
    assert set(config.weights.as_component_map()) == set(SignalScoreComponent)


def test_bullish_confirmations_produce_long_candidate_and_exact_breakdown() -> None:
    config = load_strategy_score_config()
    result = calculate_signal_score(
        evidence(
            {
                SignalScoreComponent.MACD: SignalEvidenceDirection.BULLISH,
                SignalScoreComponent.BOS: SignalEvidenceDirection.BULLISH,
                SignalScoreComponent.LIQUIDITY_SWEEP: SignalEvidenceDirection.BULLISH,
                SignalScoreComponent.FVG: SignalEvidenceDirection.BULLISH,
                SignalScoreComponent.ORDER_BLOCK: SignalEvidenceDirection.BULLISH,
            }
        ),
        config,
    )

    assert result.decision is SignalScoreDecision.LONG_CANDIDATE
    assert result.score == 7
    assert result.score_breakdown == {
        SignalScoreComponent.MACD: 1,
        SignalScoreComponent.BOS: 2,
        SignalScoreComponent.MSS: 0,
        SignalScoreComponent.LIQUIDITY_SWEEP: 2,
        SignalScoreComponent.FVG: 1,
        SignalScoreComponent.ORDER_BLOCK: 1,
        SignalScoreComponent.DISPLACEMENT: 0,
        SignalScoreComponent.SUPPORT_RESISTANCE: 0,
        SignalScoreComponent.HTF_ALIGNMENT: 0,
    }
    assert result.reason_codes == (
        SignalScoreReasonCode.SCORE_LONG_THRESHOLD_MET,
    )


def test_bearish_confirmations_use_negative_weights_and_produce_short() -> None:
    config = load_strategy_score_config()
    result = calculate_signal_score(
        evidence(
            {
                SignalScoreComponent.MACD: SignalEvidenceDirection.BEARISH,
                SignalScoreComponent.MSS: SignalEvidenceDirection.BEARISH,
                SignalScoreComponent.DISPLACEMENT: SignalEvidenceDirection.BEARISH,
            }
        ),
        config,
    )

    assert result.score == -5
    assert result.decision is SignalScoreDecision.SHORT_CANDIDATE
    assert result.score_breakdown[SignalScoreComponent.MACD] == -1
    assert result.score_breakdown[SignalScoreComponent.MSS] == -2
    assert result.score_breakdown[SignalScoreComponent.DISPLACEMENT] == -2


def test_mixed_evidence_below_threshold_returns_no_trade() -> None:
    config = load_strategy_score_config()
    result = calculate_signal_score(
        evidence(
            {
                SignalScoreComponent.BOS: SignalEvidenceDirection.BULLISH,
                SignalScoreComponent.MSS: SignalEvidenceDirection.BEARISH,
                SignalScoreComponent.FVG: SignalEvidenceDirection.BULLISH,
            }
        ),
        config,
    )

    assert result.score == 1
    assert result.decision is SignalScoreDecision.NO_TRADE
    assert result.reason_codes == (SignalScoreReasonCode.SCORE_BELOW_THRESHOLDS,)


@pytest.mark.parametrize("component_name", list(SignalScoreComponent))
def test_every_configured_component_contributes_its_configured_weight(
    component_name: SignalScoreComponent,
) -> None:
    config = load_strategy_score_config()
    result = calculate_signal_score(
        evidence({component_name: SignalEvidenceDirection.BULLISH}),
        config,
    )

    assert result.score_breakdown[component_name] == getattr(
        config.weights, component_name.value
    )
    assert sum(result.score_breakdown.values()) == result.score


def test_neutral_and_missing_components_contribute_zero() -> None:
    config = load_strategy_score_config()
    result = calculate_signal_score(
        evidence({SignalScoreComponent.BOS: SignalEvidenceDirection.NEUTRAL}),
        config,
    )

    assert result.score == 0
    assert all(value == 0 for value in result.score_breakdown.values())
    assert result.decision is SignalScoreDecision.NO_TRADE


def test_htf_conflict_vetoes_an_otherwise_long_candidate() -> None:
    config = load_strategy_score_config()
    result = calculate_signal_score(
        evidence(
            {
                SignalScoreComponent.BOS: SignalEvidenceDirection.BULLISH,
                SignalScoreComponent.MSS: SignalEvidenceDirection.BULLISH,
                SignalScoreComponent.DISPLACEMENT: SignalEvidenceDirection.BULLISH,
            },
            htf_conflict=True,
        ),
        config,
    )

    assert result.score == 6
    assert result.decision is SignalScoreDecision.NO_TRADE
    assert result.reason_codes == (SignalScoreReasonCode.HTF_CONFLICT_VETO,)


def test_thresholds_and_weights_are_taken_from_config_not_engine_constants() -> None:
    custom = StrategyScoreConfig(
        metadata=SignalScoreMetadata(
            empirical_validation_status="UNVALIDATED",
        ),
        signal=SignalScoreThresholds(
            long_threshold=3,
            short_threshold=-3,
            veto_on_htf_conflict=False,
        ),
        weights=SignalScoreWeights(
            macd=3,
            bos=0,
            mss=0,
            liquidity_sweep=0,
            fvg=0,
            order_block=0,
            displacement=0,
            support_resistance=0,
            htf_alignment=0,
        ),
        crt=CRTConfig(enabled=False, signal_uses=(), weight=None),
    )
    result = calculate_signal_score(
        evidence(
            {SignalScoreComponent.MACD: SignalEvidenceDirection.BULLISH},
            htf_conflict=True,
        ),
        custom,
    )

    assert result.score == 3
    assert result.decision is SignalScoreDecision.LONG_CANDIDATE
    assert result.strategy_version == STRATEGY_VERSION


def test_future_confirmation_is_rejected_to_prevent_lookahead() -> None:
    with pytest.raises(ValidationError, match="confirms after decision_time"):
        SignalScoreEvidence(
            decision_time=DECISION_TIME,
            components={
                SignalScoreComponent.BOS: component(
                    SignalEvidenceDirection.BULLISH,
                    source="future-bos",
                    confirmed_at=DECISION_TIME + timedelta(seconds=1),
                )
            },
        )


def test_negative_weights_are_rejected() -> None:
    base = load_strategy_score_config().model_dump()
    base["weights"]["bos"] = -1
    with pytest.raises(ValidationError):
        StrategyScoreConfig.model_validate(base)


def test_invalid_strategy_yaml_is_reported_as_configuration_error(tmp_path) -> None:
    path = tmp_path / "strategy.yaml"
    path.write_text("weights: [not, a, mapping]", encoding="utf-8")

    with pytest.raises(StrategyConfigError, match="invalid strategy configuration"):
        load_strategy_config(path)
