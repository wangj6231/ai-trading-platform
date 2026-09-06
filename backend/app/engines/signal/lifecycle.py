from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Protocol

from app.market_data.timeframes import timeframe_duration
from app.schemas.candle import Candle
from app.schemas.signal import SignalDecision
from app.schemas.signal_lifecycle import (
    SameCandlePolicy,
    SignalLifecycleCandidate,
    SignalLifecycleConfig,
    SignalLifecycleEvent,
    SignalLifecycleEventType,
    SignalLifecycleReasonCode,
    SignalLifecycleResult,
    SignalLifecycleStatus,
    StructuralInvalidation,
)
from app.schemas.types import Timeframe


class EntryExecutionEvidence(Protocol):
    """Structural type documented for entry resolvers used by the lifecycle."""

    executed: bool
    executed_at: datetime | None
    executed_entry_price: Decimal | None
    source_bar_timestamp: datetime
    execution_reason: object


EntryExecutionResolver = Callable[
    [SignalLifecycleCandidate, Candle, Candle | None, datetime],
    EntryExecutionEvidence,
]


class SignalLifecycleInputError(ValueError):
    pass


TERMINAL_STATUSES = {
    SignalLifecycleStatus.TP_HIT,
    SignalLifecycleStatus.SL_HIT,
    SignalLifecycleStatus.CANCELLED,
    SignalLifecycleStatus.AMBIGUOUS,
}


def replay_signal_lifecycle(
    signal: SignalLifecycleCandidate,
    candles: Sequence[Candle],
    timeframe: Timeframe,
    config: SignalLifecycleConfig,
    *,
    entry_execution_resolver: EntryExecutionResolver,
    structural_invalidation: StructuralInvalidation | None = None,
) -> SignalLifecycleResult:
    """Replay a signal using closed OHLC candles only.

    Candle timestamps are interval-open times. Transitions caused by OHLC are
    recorded at interval close because the intrabar touch time is unknowable.
    A candle that began before the signal existed is ignored in full, avoiding
    use of its pre-signal high/low. An entry established at candle open precedes
    later bar extremes. Boundary entry plus an exit in one candle remains
    AMBIGUOUS because intrabar order is unknown. For an already-active trade
    touching both exits, configuration may retain AMBIGUOUS or choose the
    documented conservative stop-first result.
    """

    duration = timeframe_duration(timeframe)
    _validate_inputs(signal, candles, duration, structural_invalidation)

    status = SignalLifecycleStatus.WAITING
    activated_at: datetime | None = None
    terminal_at: datetime | None = None
    last_evaluated_at = signal.created_at
    events = [
        SignalLifecycleEvent(
            event_type=SignalLifecycleEventType.CREATED,
            from_status=None,
            to_status=SignalLifecycleStatus.WAITING,
            occurred_at=signal.created_at,
            bar_timestamp=None,
            reason_code=SignalLifecycleReasonCode.SIGNAL_CREATED,
            detail="Signal accepted with immutable entry, take-profit, and stop-loss levels.",
        )
    ]

    if (
        structural_invalidation is not None
        and structural_invalidation.confirmed_at == signal.created_at
    ):
        status = SignalLifecycleStatus.CANCELLED
        terminal_at = structural_invalidation.confirmed_at
        events.append(
            _invalidation_event(
                structural_invalidation,
                from_status=SignalLifecycleStatus.WAITING,
                bar_timestamp=None,
            )
        )

    for index, bar in enumerate(candles):
        if status in TERMINAL_STATUSES:
            break
        bar_close = bar.timestamp + duration

        # A partial candle contains prices observed before signal creation and
        # therefore cannot safely activate or resolve this signal.
        if bar.timestamp < signal.created_at:
            continue

        previous_bar = candles[index - 1] if index > 0 else None
        entry_execution = (
            entry_execution_resolver(signal, bar, previous_bar, bar_close)
            if status is SignalLifecycleStatus.WAITING
            else None
        )
        entry_executed = entry_execution is not None and entry_execution.executed
        tp_touched = _take_profit_touched(signal, bar)
        sl_touched = _stop_loss_touched(signal, bar)

        if status is SignalLifecycleStatus.WAITING and structural_invalidation:
            invalidated_at = structural_invalidation.confirmed_at
            if invalidated_at <= bar.timestamp:
                status = SignalLifecycleStatus.CANCELLED
                terminal_at = invalidated_at
                last_evaluated_at = max(last_evaluated_at, invalidated_at)
                events.append(
                    _invalidation_event(
                        structural_invalidation,
                        from_status=SignalLifecycleStatus.WAITING,
                        bar_timestamp=None,
                    )
                )
                break
            if invalidated_at <= bar_close:
                last_evaluated_at = bar_close
                terminal_at = bar_close
                if entry_executed:
                    status = SignalLifecycleStatus.AMBIGUOUS
                    events.append(
                        SignalLifecycleEvent(
                            event_type=SignalLifecycleEventType.AMBIGUOUS,
                            from_status=SignalLifecycleStatus.WAITING,
                            to_status=status,
                            occurred_at=bar_close,
                            bar_timestamp=bar.timestamp,
                            reason_code=(
                                SignalLifecycleReasonCode.ENTRY_AND_INVALIDATION_ORDER_UNKNOWN
                            ),
                            detail=(
                                "Entry and confirmed structural invalidation occurred in the "
                                "same OHLC interval; their order is unknown."
                            ),
                        )
                    )
                else:
                    status = SignalLifecycleStatus.CANCELLED
                    terminal_at = invalidated_at
                    events.append(
                        _invalidation_event(
                            structural_invalidation,
                            from_status=SignalLifecycleStatus.WAITING,
                            bar_timestamp=bar.timestamp,
                        )
                    )
                break

        if status is SignalLifecycleStatus.WAITING:
            if not entry_executed:
                last_evaluated_at = bar_close
                continue
            assert entry_execution is not None
            assert entry_execution.executed_at is not None
            assert entry_execution.executed_entry_price is not None
            status = SignalLifecycleStatus.ACTIVE
            activated_at = entry_execution.executed_at
            last_evaluated_at = bar_close
            events.append(
                SignalLifecycleEvent(
                    event_type=SignalLifecycleEventType.ACTIVATED,
                    from_status=SignalLifecycleStatus.WAITING,
                    to_status=status,
                    occurred_at=activated_at,
                    bar_timestamp=bar.timestamp,
                    price=entry_execution.executed_entry_price,
                    reason_code=SignalLifecycleReasonCode.ENTRY_EXECUTION_CONFIRMED,
                    detail=(
                        "Entry activated from conservative execution evidence: "
                        f"{entry_execution.execution_reason}."
                    ),
                )
            )

            # An open-inside-zone fill is known to precede the remainder of the
            # candle. A boundary touch has unknown intrabar ordering relative to
            # any exit touch, so it remains ambiguous.
            open_fill = entry_execution.executed_at == bar.timestamp
            if (tp_touched or sl_touched) and not open_fill:
                status = SignalLifecycleStatus.AMBIGUOUS
                terminal_at = bar_close
                events.append(
                    SignalLifecycleEvent(
                        event_type=SignalLifecycleEventType.AMBIGUOUS,
                        from_status=SignalLifecycleStatus.ACTIVE,
                        to_status=status,
                        occurred_at=bar_close,
                        bar_timestamp=bar.timestamp,
                        reason_code=SignalLifecycleReasonCode.ENTRY_AND_EXIT_ORDER_UNKNOWN,
                        detail=(
                            "Entry and at least one exit were touched in the same OHLC candle; "
                            "the exit cannot be proven to occur after activation."
                        ),
                    )
                )
                break
            if not (tp_touched or sl_touched):
                continue

        last_evaluated_at = bar_close
        if tp_touched and sl_touched:
            terminal_at = bar_close
            if config.same_candle_policy is SameCandlePolicy.CONSERVATIVE_STOP_FIRST:
                status = SignalLifecycleStatus.SL_HIT
                event_type = SignalLifecycleEventType.STOP_LOSS_HIT
                event_price = signal.stop_loss
                reason = SignalLifecycleReasonCode.CONSERVATIVE_STOP_FIRST
                detail = (
                    "TP and SL were both touched in one OHLC candle; the configured "
                    "conservative policy records SL first."
                )
            else:
                status = SignalLifecycleStatus.AMBIGUOUS
                event_type = SignalLifecycleEventType.AMBIGUOUS
                event_price = None
                reason = SignalLifecycleReasonCode.TP_AND_SL_TOUCHED_SAME_CANDLE
                detail = "TP and SL were both touched in one OHLC candle; tick order is unknown."
            events.append(
                SignalLifecycleEvent(
                    event_type=event_type,
                    from_status=SignalLifecycleStatus.ACTIVE,
                    to_status=status,
                    occurred_at=bar_close,
                    bar_timestamp=bar.timestamp,
                    price=event_price,
                    reason_code=reason,
                    detail=detail,
                )
            )
            break
        if tp_touched:
            status = SignalLifecycleStatus.TP_HIT
            terminal_at = bar_close
            events.append(
                _exit_event(
                    status=status,
                    bar=bar,
                    occurred_at=bar_close,
                    price=signal.take_profit,
                    reason=SignalLifecycleReasonCode.TAKE_PROFIT_TOUCHED,
                )
            )
            break
        if sl_touched:
            status = SignalLifecycleStatus.SL_HIT
            terminal_at = bar_close
            events.append(
                _exit_event(
                    status=status,
                    bar=bar,
                    occurred_at=bar_close,
                    price=signal.stop_loss,
                    reason=SignalLifecycleReasonCode.STOP_LOSS_TOUCHED,
                )
            )
            break

    return SignalLifecycleResult(
        signal_id=signal.signal_id,
        status=status,
        created_at=signal.created_at,
        activated_at=activated_at,
        terminal_at=terminal_at,
        last_evaluated_at=last_evaluated_at,
        events=tuple(events),
    )


def _validate_inputs(
    signal: SignalLifecycleCandidate,
    candles: Sequence[Candle],
    duration: timedelta,
    invalidation: StructuralInvalidation | None,
) -> None:
    for previous, current in zip(candles, candles[1:], strict=False):
        delta = current.timestamp - previous.timestamp
        if delta <= timedelta(0):
            raise SignalLifecycleInputError(
                "candles must have unique timestamps in ascending order"
            )
        if delta != duration:
            raise SignalLifecycleInputError("candle sequence contains a timeframe gap")
    if invalidation is not None and invalidation.confirmed_at < signal.created_at:
        raise SignalLifecycleInputError(
            "structural invalidation cannot predate signal creation"
        )


def _take_profit_touched(signal: SignalLifecycleCandidate, bar: Candle) -> bool:
    if signal.direction is SignalDecision.LONG:
        return bar.high >= signal.take_profit
    return bar.low <= signal.take_profit


def _stop_loss_touched(signal: SignalLifecycleCandidate, bar: Candle) -> bool:
    if signal.direction is SignalDecision.LONG:
        return bar.low <= signal.stop_loss
    return bar.high >= signal.stop_loss


def _exit_event(
    *,
    status: SignalLifecycleStatus,
    bar: Candle,
    occurred_at: datetime,
    price: Decimal,
    reason: SignalLifecycleReasonCode,
) -> SignalLifecycleEvent:
    is_tp = status is SignalLifecycleStatus.TP_HIT
    return SignalLifecycleEvent(
        event_type=(
            SignalLifecycleEventType.TAKE_PROFIT_HIT
            if is_tp
            else SignalLifecycleEventType.STOP_LOSS_HIT
        ),
        from_status=SignalLifecycleStatus.ACTIVE,
        to_status=status,
        occurred_at=occurred_at,
        bar_timestamp=bar.timestamp,
        price=price,
        reason_code=reason,
        detail="Take profit was touched." if is_tp else "Stop loss was touched.",
    )


def _invalidation_event(
    invalidation: StructuralInvalidation,
    *,
    from_status: SignalLifecycleStatus,
    bar_timestamp: datetime | None,
) -> SignalLifecycleEvent:
    return SignalLifecycleEvent(
        event_type=SignalLifecycleEventType.CANCELLED,
        from_status=from_status,
        to_status=SignalLifecycleStatus.CANCELLED,
        occurred_at=invalidation.confirmed_at,
        bar_timestamp=bar_timestamp,
        reason_code=SignalLifecycleReasonCode.STRUCTURAL_INVALIDATION_BEFORE_ENTRY,
        detail=(
            f"Structure invalidated before activation: {invalidation.reason} "
            f"(source={invalidation.source_structure})."
        ),
    )
