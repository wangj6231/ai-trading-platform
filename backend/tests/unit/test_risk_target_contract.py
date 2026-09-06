from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from app.core.strategy_config import StrategyConfigError, load_strategy_config
from app.core.strategy_identity import canonical_strategy_config
from app.schemas.risk import RiskEngineConfig, RiskPlan, RiskTargetSource
from app.schemas.signal import SignalDecision
from app.schemas.signal_lifecycle import SignalLifecycleStatus
from app.schemas.signal_persistence import (
    SignalDirection,
    SignalPersistenceCreate,
)
from app.schemas.strategy import DeterministicSignalCandidate
from tests.factories import make_engine_candidate, make_not_requested_ai_validation


NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
UNSUPPORTED_TARGET_FIELDS = ("tp1", "tp2", "tp3", "targets")


def _write_strategy_config(
    tmp_path: Path,
    *,
    risk_updates: dict[str, object],
) -> Path:
    raw = load_strategy_config().model_dump(mode="json")
    raw["pipelines"]["BTCUSDT"]["risk"].update(risk_updates)
    path = tmp_path / "strategy.yaml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def accepted_risk_plan() -> RiskPlan:
    candidate = make_engine_candidate(NOW)
    risk = candidate.analysis_snapshot.payload.risk
    assert risk is not None
    return risk


def test_canonical_risk_config_has_only_one_supported_target_contract() -> None:
    config = load_strategy_config().pipelines["BTCUSDT"].risk

    assert config.target_source is RiskTargetSource.NEAREST_OPPOSING_LIQUIDITY
    assert set(RiskEngineConfig.model_fields) == {
        "entry_reference",
        "stop_buffer_ticks",
        "atr_buffer",
        "min_distance_ticks",
        "max_distance_atr_ratio",
        "target_source",
        "target_min_distance_ticks",
        "min_rr",
    }
    assert b"same_bar_resolution" not in canonical_strategy_config(
        load_strategy_config()
    )
    assert set(RiskTargetSource) == {RiskTargetSource.NEAREST_OPPOSING_LIQUIDITY}


def test_target_first_is_rejected_by_strict_strategy_loader(tmp_path: Path) -> None:
    path = _write_strategy_config(
        tmp_path,
        risk_updates={"same_bar_resolution": "TARGET_FIRST"},
    )

    with pytest.raises(StrategyConfigError, match="invalid strategy configuration"):
        load_strategy_config(path)


def test_dead_same_bar_resolution_is_rejected_even_when_unresolved(
    tmp_path: Path,
) -> None:
    path = _write_strategy_config(
        tmp_path,
        risk_updates={"same_bar_resolution": "UNRESOLVED"},
    )

    with pytest.raises(StrategyConfigError, match="invalid strategy configuration"):
        load_strategy_config(path)


def test_unsupported_fixed_rr_target_mode_is_rejected(tmp_path: Path) -> None:
    path = _write_strategy_config(
        tmp_path,
        risk_updates={
            "target_source": "FIXED_RR",
            "fixed_rr_ratio": "3",
        },
    )

    with pytest.raises(StrategyConfigError, match="invalid strategy configuration"):
        load_strategy_config(path)


@pytest.mark.parametrize("field", UNSUPPORTED_TARGET_FIELDS)
def test_risk_plan_rejects_multi_target_fields(
    accepted_risk_plan: RiskPlan,
    field: str,
) -> None:
    payload = accepted_risk_plan.model_dump(mode="python")
    payload[field] = [accepted_risk_plan.take_profit]

    with pytest.raises(ValidationError, match=field):
        RiskPlan.model_validate(payload)


def test_risk_plan_serializes_exactly_one_take_profit(
    accepted_risk_plan: RiskPlan,
) -> None:
    payload = accepted_risk_plan.model_dump(mode="python")

    assert payload["take_profit"] == accepted_risk_plan.take_profit
    assert not (set(payload) & set(UNSUPPORTED_TARGET_FIELDS))


@pytest.mark.parametrize("field", UNSUPPORTED_TARGET_FIELDS)
def test_deterministic_candidate_rejects_multi_target_fields(field: str) -> None:
    payload = make_engine_candidate(NOW).model_dump(mode="python")
    payload[field] = [payload["take_profit"]]

    with pytest.raises(ValidationError, match=field):
        DeterministicSignalCandidate.model_validate(payload)


def test_snapshot_decision_and_risk_plan_share_one_target(
    accepted_risk_plan: RiskPlan,
) -> None:
    candidate = make_engine_candidate(NOW)
    snapshot = candidate.analysis_snapshot.payload

    assert snapshot.risk == accepted_risk_plan
    assert snapshot.decision.take_profit == accepted_risk_plan.take_profit
    assert snapshot.decision.risk_reward == accepted_risk_plan.risk_reward
    assert candidate.take_profit == accepted_risk_plan.take_profit
    assert candidate.risk_reward == accepted_risk_plan.risk_reward


def test_persistence_payload_preserves_snapshot_risk_target() -> None:
    candidate = make_engine_candidate(NOW)
    decision = candidate.analysis_snapshot.payload.decision
    risk = candidate.analysis_snapshot.payload.risk
    assert risk is not None
    assert decision.entry_zone is not None
    assert decision.take_profit is not None
    assert decision.stop_loss is not None
    assert decision.risk_reward is not None

    persisted = SignalPersistenceCreate(
        symbol=candidate.symbol,
        timeframe=candidate.timeframe,
        direction=SignalDirection(candidate.direction.value),
        entry_min=decision.entry_zone.low,
        entry_max=decision.entry_zone.high,
        take_profit=decision.take_profit,
        stop_loss=decision.stop_loss,
        risk_reward=decision.risk_reward,
        algorithm_score=candidate.algorithm_score,
        algorithm_decision=candidate.direction,
        final_decision=candidate.direction,
        ai_validation=make_not_requested_ai_validation(
            candidate.analysis_snapshot.captured_at
        ),
        status=SignalLifecycleStatus.WAITING,
        analysis_snapshot=candidate.analysis_snapshot,
    )

    assert persisted.final_decision is SignalDecision.LONG
    assert persisted.take_profit == risk.take_profit
    assert persisted.stop_loss == risk.stop_loss
    assert persisted.risk_reward == risk.risk_reward
