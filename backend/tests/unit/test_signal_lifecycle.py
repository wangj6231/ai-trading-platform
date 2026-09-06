from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.engines.signal.lifecycle import (
    SignalLifecycleInputError,
    replay_signal_lifecycle as _replay_signal_lifecycle,
)
from app.backtesting.execution import build_entry_execution_resolver
from app.schemas.candle import Candle
from app.schemas.execution import (
    ExecutionConfig,
    ExecutionPolicyName,
    TradingCostConfig,
)
from app.schemas.signal import EntryZone, SignalDecision
from app.schemas.signal_lifecycle import (
    SameCandlePolicy,
    SignalLifecycleCandidate,
    SignalLifecycleConfig,
    SignalLifecycleReasonCode,
    SignalLifecycleStatus,
    StructuralInvalidation,
)
from app.schemas.types import Timeframe


START = datetime(2026, 8, 1, tzinfo=UTC)
ZERO_EXECUTION = ExecutionConfig(
    policy=ExecutionPolicyName.CONSERVATIVE_MARKET_FILL,
    costs=TradingCostConfig(
        commission_bps_per_side=Decimal(0),
        spread_bps=Decimal(0),
        slippage_bps_per_side=Decimal(0),
    ),
)


def replay_signal_lifecycle(*args, **kwargs):
    kwargs.setdefault(
        "entry_execution_resolver",
        build_entry_execution_resolver(ZERO_EXECUTION),
    )
    return _replay_signal_lifecycle(*args, **kwargs)


def candle(index: int, open_: str, high: str, low: str, close: str) -> Candle:
    return Candle(
        timestamp=START + timedelta(minutes=index),
        open=Decimal(open_),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal("1"),
    )


def candidate(
    direction: SignalDecision = SignalDecision.LONG,
    *,
    created_at: datetime = START,
) -> SignalLifecycleCandidate:
    return SignalLifecycleCandidate(
        signal_id=f"signal-{direction.value.lower()}",
        direction=direction,
        entry_zone=EntryZone(low=Decimal("100"), high=Decimal("102")),
        entry_reference=Decimal("101"),
        take_profit=Decimal("110" if direction is SignalDecision.LONG else "94"),
        stop_loss=Decimal("95" if direction is SignalDecision.LONG else "108"),
        created_at=created_at,
    )


def config(
    policy: SameCandlePolicy = SameCandlePolicy.AMBIGUOUS,
) -> SignalLifecycleConfig:
    return SignalLifecycleConfig(same_candle_policy=policy)


def invalidation(at: datetime) -> StructuralInvalidation:
    return StructuralInvalidation(
        confirmed_at=at,
        source_structure="setup-structure-1",
        reason="opposite close-confirmed MSS",
    )


def test_signal_remains_waiting_until_entry_zone_is_touched() -> None:
    result = replay_signal_lifecycle(
        candidate(),
        [candle(0, "105", "106", "103", "104")],
        Timeframe.ONE_MINUTE,
        config(),
    )

    assert result.status is SignalLifecycleStatus.WAITING
    assert result.activated_at is None
    assert result.terminal_at is None
    assert len(result.events) == 1
    assert result.last_evaluated_at == START + timedelta(minutes=1)


@pytest.mark.parametrize("direction", [SignalDecision.LONG, SignalDecision.SHORT])
def test_entry_zone_touch_activates_long_and_short(direction: SignalDecision) -> None:
    result = replay_signal_lifecycle(
        candidate(direction),
        [candle(0, "103", "104", "99", "102")],
        Timeframe.ONE_MINUTE,
        config(),
    )

    assert result.status is SignalLifecycleStatus.ACTIVE
    assert result.activated_at == START + timedelta(minutes=1)
    assert (
        result.events[-1].reason_code
        is SignalLifecycleReasonCode.ENTRY_EXECUTION_CONFIRMED
    )


@pytest.mark.parametrize(
    ("direction", "exit_bar", "expected"),
    [
        (
            SignalDecision.LONG,
            candle(1, "103", "111", "103", "109"),
            SignalLifecycleStatus.TP_HIT,
        ),
        (
            SignalDecision.LONG,
            candle(1, "101", "103", "94", "96"),
            SignalLifecycleStatus.SL_HIT,
        ),
        (
            SignalDecision.SHORT,
            candle(1, "99", "99", "93", "95"),
            SignalLifecycleStatus.TP_HIT,
        ),
        (
            SignalDecision.SHORT,
            candle(1, "103", "109", "103", "107"),
            SignalLifecycleStatus.SL_HIT,
        ),
    ],
)
def test_active_signal_resolves_at_exactly_one_exit(
    direction: SignalDecision,
    exit_bar: Candle,
    expected: SignalLifecycleStatus,
) -> None:
    result = replay_signal_lifecycle(
        candidate(direction),
        [candle(0, "103", "104", "99", "102"), exit_bar],
        Timeframe.ONE_MINUTE,
        config(),
    )

    assert result.status is expected
    assert result.activated_at == START + timedelta(minutes=1)
    assert result.terminal_at == START + timedelta(minutes=2)


def test_structure_invalidation_before_entry_cancels_waiting_signal() -> None:
    result = replay_signal_lifecycle(
        candidate(),
        [candle(0, "105", "106", "103", "104")],
        Timeframe.ONE_MINUTE,
        config(),
        structural_invalidation=invalidation(START + timedelta(minutes=1)),
    )

    assert result.status is SignalLifecycleStatus.CANCELLED
    assert result.activated_at is None
    assert result.terminal_at == START + timedelta(minutes=1)
    assert (
        result.events[-1].reason_code
        is SignalLifecycleReasonCode.STRUCTURAL_INVALIDATION_BEFORE_ENTRY
    )


def test_structure_invalidation_after_activation_does_not_reclassify_as_cancelled() -> None:
    result = replay_signal_lifecycle(
        candidate(),
        [
            candle(0, "103", "104", "99", "102"),
            candle(1, "103", "111", "103", "109"),
        ],
        Timeframe.ONE_MINUTE,
        config(),
        structural_invalidation=invalidation(START + timedelta(minutes=2)),
    )

    assert result.status is SignalLifecycleStatus.TP_HIT


def test_active_signal_touching_tp_and_sl_in_same_candle_is_ambiguous() -> None:
    result = replay_signal_lifecycle(
        candidate(),
        [
            candle(0, "103", "104", "99", "102"),
            candle(1, "102", "111", "94", "100"),
        ],
        Timeframe.ONE_MINUTE,
        config(),
    )

    assert result.status is SignalLifecycleStatus.AMBIGUOUS
    assert (
        result.events[-1].reason_code
        is SignalLifecycleReasonCode.TP_AND_SL_TOUCHED_SAME_CANDLE
    )


def test_conservative_policy_records_stop_when_both_exits_touch() -> None:
    result = replay_signal_lifecycle(
        candidate(),
        [
            candle(0, "103", "104", "99", "102"),
            candle(1, "102", "111", "94", "100"),
        ],
        Timeframe.ONE_MINUTE,
        config(SameCandlePolicy.CONSERVATIVE_STOP_FIRST),
    )

    assert result.status is SignalLifecycleStatus.SL_HIT
    assert (
        result.events[-1].reason_code
        is SignalLifecycleReasonCode.CONSERVATIVE_STOP_FIRST
    )
    assert "TARGET_FIRST" not in SameCandlePolicy.__members__


def test_entry_and_exit_in_same_candle_is_ambiguous_even_when_only_tp_touches() -> None:
    result = replay_signal_lifecycle(
        candidate(),
        [candle(0, "103", "111", "101", "109")],
        Timeframe.ONE_MINUTE,
        config(),
    )

    assert result.status is SignalLifecycleStatus.AMBIGUOUS
    assert result.activated_at == START + timedelta(minutes=1)
    assert (
        result.events[-1].reason_code
        is SignalLifecycleReasonCode.ENTRY_AND_EXIT_ORDER_UNKNOWN
    )


def test_entry_and_invalidation_in_same_interval_is_ambiguous() -> None:
    result = replay_signal_lifecycle(
        candidate(),
        [candle(0, "103", "104", "99", "102")],
        Timeframe.ONE_MINUTE,
        config(),
        structural_invalidation=invalidation(START + timedelta(seconds=30)),
    )

    assert result.status is SignalLifecycleStatus.AMBIGUOUS
    assert (
        result.events[-1].reason_code
        is SignalLifecycleReasonCode.ENTRY_AND_INVALIDATION_ORDER_UNKNOWN
    )


def test_partial_pre_creation_candle_is_not_used_for_activation() -> None:
    created_at = START + timedelta(seconds=30)
    result = replay_signal_lifecycle(
        candidate(created_at=created_at),
        [
            candle(0, "103", "104", "99", "103"),
            candle(1, "105", "106", "103", "104"),
        ],
        Timeframe.ONE_MINUTE,
        config(),
    )

    assert result.status is SignalLifecycleStatus.WAITING
    assert result.activated_at is None
    assert result.last_evaluated_at == START + timedelta(minutes=2)


def test_no_trade_and_directionally_invalid_candidates_are_rejected() -> None:
    with pytest.raises(ValidationError, match="NO_TRADE"):
        candidate(SignalDecision.NO_TRADE)

    with pytest.raises(ValidationError, match="directionally invalid"):
        SignalLifecycleCandidate(
            signal_id="bad-long",
            direction=SignalDecision.LONG,
            entry_zone=EntryZone(low=Decimal("100"), high=Decimal("102")),
            entry_reference=Decimal("101"),
            take_profit=Decimal("94"),
            stop_loss=Decimal("110"),
            created_at=START,
        )


@pytest.mark.parametrize(
    "candles",
    [
        [
            candle(0, "105", "106", "103", "104"),
            candle(0, "105", "106", "103", "104"),
        ],
        [
            candle(0, "105", "106", "103", "104"),
            candle(2, "105", "106", "103", "104"),
        ],
    ],
)
def test_duplicate_or_missing_candles_are_rejected(candles: list[Candle]) -> None:
    with pytest.raises(SignalLifecycleInputError):
        replay_signal_lifecycle(
            candidate(),
            candles,
            Timeframe.ONE_MINUTE,
            config(),
        )
