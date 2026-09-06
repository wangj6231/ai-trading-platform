from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.engines.crt import analyze_crt
from app.schemas.candle import Candle
from app.schemas.crt import (
    CRTConfig,
    CRTDirection,
    CRTEntryRelation,
    CRTRejectionCode,
    CRTSweepEvidence,
    CRTSweptSide,
)
from app.schemas.types import Timeframe


START = datetime(2026, 3, 1, tzinfo=UTC)


def bar(index: int, open_: str, high: str, low: str, close: str) -> Candle:
    return Candle(
        timestamp=START + timedelta(minutes=index),
        open=Decimal(open_),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal("1"),
    )


def candles() -> list[Candle]:
    return [
        bar(0, "104", "110", "100", "106"),
        bar(1, "106", "108", "99", "103"),
        bar(2, "103", "109", "102", "108"),
    ]


def sweep(
    side: CRTSweptSide = CRTSweptSide.LOW,
    *,
    evidence_id: str = "crt-sweep-1",
    level: str | None = None,
    confirmed_at: datetime = START + timedelta(minutes=2),
) -> CRTSweepEvidence:
    expected = "100" if side is CRTSweptSide.LOW else "110"
    return CRTSweepEvidence(
        evidence_id=evidence_id,
        source_event_id=f"liquidity-{evidence_id}",
        range_candle_timestamp=START,
        manipulation_candle_timestamp=START + timedelta(minutes=1),
        swept_side=side,
        level=Decimal(level or expected),
        confirmed_at=confirmed_at,
    )


def test_disabled_crt_returns_no_confirmation() -> None:
    result = analyze_crt(
        candles(),
        Timeframe.ONE_MINUTE,
        CRTConfig(enabled=False, signal_uses=(), weight=None),
        confirmed_sweeps=[sweep()],
    )

    assert result.enabled is False
    assert result.confirmations == ()
    assert result.rejections == ()


def test_closed_low_sweep_produces_reference_defined_bullish_confirmation() -> None:
    result = analyze_crt(
        candles(),
        Timeframe.ONE_MINUTE,
        CRTConfig(enabled=True, signal_uses=(), weight=None),
        confirmed_sweeps=[sweep()],
    )

    confirmation = result.confirmations[0]
    assert confirmation.direction is CRTDirection.BULLISH
    assert confirmation.range_high == Decimal("110")
    assert confirmation.range_low == Decimal("100")
    assert confirmation.manipulation_closed_at == START + timedelta(minutes=2)
    assert confirmation.third_candle_timestamp == START + timedelta(minutes=2)
    assert confirmation.third_candle_open == Decimal("103")
    assert (
        confirmation.entry_relation
        is CRTEntryRelation.BUY_BELOW_THIRD_CANDLE_OPEN
    )
    assert confirmation.opposite_wick_reference == Decimal("110")
    dumped = confirmation.model_dump()
    assert "entry_zone" not in dumped
    assert "take_profit" not in dumped
    assert "stop_loss" not in dumped


def test_closed_high_sweep_produces_bearish_mirror_confirmation() -> None:
    result = analyze_crt(
        candles(),
        Timeframe.ONE_MINUTE,
        CRTConfig(enabled=True, signal_uses=(), weight=None),
        confirmed_sweeps=[sweep(CRTSweptSide.HIGH)],
    )

    confirmation = result.confirmations[0]
    assert confirmation.direction is CRTDirection.BEARISH
    assert (
        confirmation.entry_relation
        is CRTEntryRelation.SELL_ABOVE_THIRD_CANDLE_OPEN
    )
    assert confirmation.opposite_wick_reference == Decimal("100")


def test_raw_ohlc_never_invents_a_sweep_without_formal_evidence() -> None:
    result = analyze_crt(
        candles(),
        Timeframe.ONE_MINUTE,
        CRTConfig(enabled=True, signal_uses=(), weight=None),
    )

    assert result.confirmations == ()
    assert result.rejections == ()


def test_sweep_is_unavailable_until_confirmation_time() -> None:
    result = analyze_crt(
        candles()[:2],
        Timeframe.ONE_MINUTE,
        CRTConfig(enabled=True, signal_uses=(), weight=None),
        confirmed_sweeps=[
            sweep(confirmed_at=START + timedelta(minutes=3))
        ],
    )

    assert result.confirmations == ()
    assert result.rejections[0].code is CRTRejectionCode.EVIDENCE_NOT_YET_CONFIRMED


def test_sweep_confirmation_before_manipulation_close_is_rejected() -> None:
    result = analyze_crt(
        candles(),
        Timeframe.ONE_MINUTE,
        CRTConfig(enabled=True, signal_uses=(), weight=None),
        confirmed_sweeps=[
            sweep(confirmed_at=START + timedelta(minutes=1, seconds=59))
        ],
    )

    assert result.confirmations == ()
    assert (
        result.rejections[0].code
        is CRTRejectionCode.SWEEP_CONFIRMED_BEFORE_CANDLE_CLOSE
    )


def test_evidence_level_must_match_the_referenced_range_boundary() -> None:
    result = analyze_crt(
        candles(),
        Timeframe.ONE_MINUTE,
        CRTConfig(enabled=True, signal_uses=(), weight=None),
        confirmed_sweeps=[sweep(level="99")],
    )

    assert result.confirmations == ()
    assert (
        result.rejections[0].code
        is CRTRejectionCode.LEVEL_DOES_NOT_MATCH_RANGE_BOUNDARY
    )


def test_dual_side_sweep_is_not_silently_directionalized() -> None:
    result = analyze_crt(
        candles(),
        Timeframe.ONE_MINUTE,
        CRTConfig(enabled=True, signal_uses=(), weight=None),
        confirmed_sweeps=[
            sweep(CRTSweptSide.LOW, evidence_id="low"),
            sweep(CRTSweptSide.HIGH, evidence_id="high"),
        ],
    )

    assert result.confirmations == ()
    assert (
        result.rejections[0].code
        is CRTRejectionCode.DUAL_SIDE_SWEEP_NEEDS_FORMALIZATION
    )
