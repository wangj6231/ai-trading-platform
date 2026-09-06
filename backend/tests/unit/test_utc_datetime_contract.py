import ast
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
import os
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from pydantic import TypeAdapter, ValidationError

from app.backtesting.identity import (
    backtest_run_spec_hash,
    build_canonical_dataset_identity,
)
from app.core.strategy_identity import build_strategy_identity
from app.core.time import UtcDateTime, canonical_utc_iso, normalize_utc_datetime
from app.database.snapshot_integrity import canonical_sha256
from app.schemas.analysis import ProductionAnalysisRequest
from app.schemas.analysis_snapshot import AnalysisSnapshot
from app.schemas.backtest_identity import BacktestRunSpec
from app.schemas.candle import Candle
from app.schemas.execution import (
    EntryExecutionReason,
    EntryExecutionRequest,
    EntryExecutionResult,
    ExecutionPolicyName,
)
from app.schemas.indicator import (
    ATRConfig,
    ATRResult,
    ATRSmoothing,
    IndicatorAnalysis,
    MACDConfig,
    MACDPoint,
    MACDResult,
)
from app.schemas.multi_timeframe import MTFResampleResult
from app.schemas.signal import SignalDecision
from app.schemas.signal_lifecycle import (
    SignalLifecycleEvent,
    SignalLifecycleEventType,
    SignalLifecycleReasonCode,
    SignalLifecycleResult,
    SignalLifecycleStatus,
    SameCandlePolicy,
)
from app.schemas.structure import (
    StructureBreakBasis,
    StructureBreakEvent,
    StructureDirection,
    StructureEventType,
    TrendState,
)
from app.schemas.types import MarketSymbol, Timeframe
from tests.factories import TEST_STRATEGY_CONFIG, make_analysis_snapshot


UTC_INSTANT = datetime(2026, 8, 31, 4, 0, tzinfo=UTC)
TAIPEI_INSTANT = datetime(
    2026,
    8,
    31,
    12,
    0,
    tzinfo=timezone(timedelta(hours=8)),
)
NEGATIVE_OFFSET_INSTANT = datetime(
    2026,
    8,
    31,
    0,
    0,
    tzinfo=timezone(timedelta(hours=-4)),
)
UTC_ADAPTER = TypeAdapter(UtcDateTime)


def candle(timestamp: object = UTC_INSTANT) -> Candle:
    return Candle.model_validate(
        {
            "timestamp": timestamp,
            "open": "100",
            "high": "102",
            "low": "99",
            "close": "101",
            "volume": "1",
        }
    )


def macd_point(timestamp: object) -> MACDPoint:
    return MACDPoint.model_validate(
        {
            "timestamp": timestamp,
            "fast_ema": None,
            "slow_ema": None,
            "macd_line": None,
            "signal_line": None,
            "histogram": None,
            "bullish_crossover": False,
            "bearish_crossover": False,
            "histogram_increasing": False,
            "histogram_decreasing": False,
        }
    )


def test_api_cutoff_normalizes_explicit_offset_to_utc() -> None:
    request = ProductionAnalysisRequest(
        symbol="BTCUSDT",
        timeframe="1m",
        cutoff=TAIPEI_INSTANT,
    )

    assert request.cutoff == UTC_INSTANT
    assert request.cutoff is not None and request.cutoff.tzinfo is UTC


def test_api_cutoff_rejects_naive_iso_and_serializes_canonical_z() -> None:
    with pytest.raises(ValidationError, match="UTC offset"):
        ProductionAnalysisRequest(
            symbol="BTCUSDT",
            timeframe="1m",
            cutoff="2026-08-31T04:00:00",
        )

    request = ProductionAnalysisRequest(
        symbol="BTCUSDT",
        timeframe="1m",
        cutoff="2026-08-31T12:00:00.123456+08:00",
    )
    assert '"cutoff":"2026-08-31T04:00:00.123456Z"' in request.model_dump_json()


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (UTC_INSTANT, UTC_INSTANT),
        (TAIPEI_INSTANT, UTC_INSTANT),
        (NEGATIVE_OFFSET_INSTANT, UTC_INSTANT),
        ("2026-08-31T04:00:00Z", UTC_INSTANT),
        ("2026-08-31T12:00:00+08:00", UTC_INSTANT),
    ],
)
def test_shared_utc_type_accepts_explicit_instants_and_normalizes(
    value: object,
    expected: datetime,
) -> None:
    parsed = UTC_ADAPTER.validate_python(value)

    assert parsed == expected
    assert parsed.tzinfo is UTC


@pytest.mark.parametrize(
    "value",
    [
        datetime(2026, 8, 31, 4, 0),
        "2026-08-31T04:00:00",
        "2026-08-31T04:00:00+25:00",
        "2026-08-31T04:00:00 America/New_York",
        "not-a-datetime",
        1_777_000_000,
        1_777_000_000.5,
        date(2026, 8, 31),
    ],
)
def test_shared_utc_type_rejects_non_instant_inputs(value: object) -> None:
    with pytest.raises(ValidationError):
        UTC_ADAPTER.validate_python(value)


def test_shared_utc_serializer_preserves_microseconds_and_uses_z() -> None:
    value = datetime(2026, 8, 31, 4, 0, 0, 123456, tzinfo=UTC)

    assert canonical_utc_iso(value) == "2026-08-31T04:00:00.123456Z"
    assert UTC_ADAPTER.dump_json(value) == b'"2026-08-31T04:00:00.123456Z"'


def test_explicit_dst_offsets_normalize_without_wall_clock_inference() -> None:
    zone = ZoneInfo("America/New_York")
    first = datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=0)
    second = datetime(2026, 11, 1, 1, 30, tzinfo=zone, fold=1)

    assert normalize_utc_datetime(first) == datetime(2026, 11, 1, 5, 30, tzinfo=UTC)
    assert normalize_utc_datetime(second) == datetime(2026, 11, 1, 6, 30, tzinfo=UTC)
    with pytest.raises(ValidationError, match="UTC offset"):
        UTC_ADAPTER.validate_python("2026-11-01T01:30:00")


def test_indicator_rejects_naive_timestamp() -> None:
    with pytest.raises(ValidationError, match="UTC offset"):
        macd_point(datetime(2026, 8, 31, 4, 0))


def test_indicator_cutoff_and_points_normalize_to_utc() -> None:
    result = IndicatorAnalysis(
        candle_count=1,
        data_cutoff_at=TAIPEI_INSTANT,
        macd=MACDResult(
            config=MACDConfig(fast_period=12, slow_period=26, signal_period=9),
            points=[macd_point(TAIPEI_INSTANT)],
        ),
        atr=ATRResult(
            config=ATRConfig(period=14, smoothing=ATRSmoothing.WILDER),
            points=[],
        ),
    )

    assert result.data_cutoff_at == UTC_INSTANT
    assert result.macd.points[0].timestamp == UTC_INSTANT


def test_lifecycle_event_rejects_naive_timestamps() -> None:
    with pytest.raises(ValidationError, match="UTC offset"):
        SignalLifecycleEvent(
            event_type=SignalLifecycleEventType.CREATED,
            from_status=None,
            to_status=SignalLifecycleStatus.WAITING,
            occurred_at=datetime(2026, 8, 31, 4, 0),
            bar_timestamp=None,
            price=None,
            reason_code=SignalLifecycleReasonCode.SIGNAL_CREATED,
            detail="created",
        )


def test_lifecycle_offsets_normalize_before_ordering_comparison() -> None:
    created = "2026-08-31T04:00:00Z"
    activated = "2026-08-31T12:01:00+08:00"
    closed = "2026-08-31T00:02:00-04:00"
    result = SignalLifecycleResult(
        signal_id="signal",
        status=SignalLifecycleStatus.TP_HIT,
        created_at=created,
        activated_at=activated,
        terminal_at=closed,
        last_evaluated_at=closed,
        events=(
            SignalLifecycleEvent(
                event_type=SignalLifecycleEventType.CREATED,
                from_status=None,
                to_status=SignalLifecycleStatus.WAITING,
                occurred_at=created,
                bar_timestamp=None,
                price=None,
                reason_code=SignalLifecycleReasonCode.SIGNAL_CREATED,
                detail="created",
            ),
        ),
    )

    assert result.created_at.tzinfo is UTC
    assert result.activated_at is not None and result.activated_at.tzinfo is UTC
    assert result.terminal_at is not None and result.terminal_at.tzinfo is UTC
    assert result.created_at <= result.activated_at <= result.terminal_at


def test_execution_request_normalizes_explicit_offset_to_utc() -> None:
    request = EntryExecutionRequest(
        candidate_id="candidate",
        direction=SignalDecision.LONG,
        entry_zone_low=Decimal("100"),
        entry_zone_high=Decimal("101"),
        entry_reference=Decimal("100.5"),
        stop_loss=Decimal("95"),
        candle=candle(),
        candle_close_at=TAIPEI_INSTANT,
    )

    assert request.candle_close_at == UTC_INSTANT
    assert request.candle_close_at.tzinfo is UTC


def test_entry_execution_result_normalizes_executed_and_source_timestamps() -> None:
    result = EntryExecutionResult(
        execution_policy=ExecutionPolicyName.CONSERVATIVE_MARKET_FILL,
        candidate_id="candidate",
        direction=SignalDecision.LONG,
        executed=True,
        execution_reason=EntryExecutionReason.OPEN_INSIDE_ZONE,
        requested_entry_price=Decimal("100"),
        stop_loss=Decimal("95"),
        base_entry_execution_price=Decimal("100"),
        executed_entry_price=Decimal("100"),
        entry_gap_detected=False,
        entry_spread_cost=Decimal("0"),
        entry_slippage=Decimal("0"),
        planned_risk=Decimal("5"),
        actual_entry_risk=Decimal("5"),
        executed_at=TAIPEI_INSTANT,
        source_bar_timestamp=TAIPEI_INSTANT,
    )

    assert result.executed_at == UTC_INSTANT
    assert result.source_bar_timestamp == UTC_INSTANT
    with pytest.raises(ValidationError, match="UTC offset"):
        result.model_copy(update={"executed_at": datetime(2026, 8, 31, 4, 0)})
        EntryExecutionResult.model_validate(
            result.model_copy(
                update={"executed_at": datetime(2026, 8, 31, 4, 0)}
            ).model_dump(mode="python")
        )


def test_structure_event_rejects_naive_timestamps() -> None:
    with pytest.raises(ValidationError, match="UTC offset"):
        StructureBreakEvent(
            type=StructureEventType.BOS,
            direction=StructureDirection.BULLISH,
            price=Decimal("101"),
            timestamp=datetime(2026, 8, 31, 4, 0),
            broken_structure_id="swing",
            confirmation_type=StructureBreakBasis.CLOSE,
            confirmed_at=datetime(2026, 8, 31, 4, 1),
            display_alias=None,
            trend_before_break=TrendState.BULLISH,
        )


def test_structure_event_offsets_normalize_and_order_by_instant() -> None:
    event = StructureBreakEvent(
        type=StructureEventType.BOS,
        direction=StructureDirection.BULLISH,
        price=Decimal("101"),
        timestamp="2026-08-31T12:00:00+08:00",
        broken_structure_id="swing",
        confirmation_type=StructureBreakBasis.CLOSE,
        confirmed_at="2026-08-31T00:01:00-04:00",
        display_alias=None,
        trend_before_break=TrendState.BULLISH,
    )

    assert event.timestamp == UTC_INSTANT
    assert event.confirmed_at == UTC_INSTANT + timedelta(minutes=1)


def test_mtf_cutoff_normalizes_and_naive_cutoff_is_rejected() -> None:
    result = MTFResampleResult(
        decision_time=TAIPEI_INSTANT,
        bars={},
        issues=[],
    )
    assert result.decision_time == UTC_INSTANT
    with pytest.raises(ValidationError, match="UTC offset"):
        MTFResampleResult(
            decision_time=datetime(2026, 8, 31, 4, 0),
            bars={},
            issues=[],
        )


def test_candle_rejects_numeric_timestamp_coercion() -> None:
    with pytest.raises(ValidationError, match="datetime"):
        candle(1_777_000_000)


def test_equivalent_snapshot_offsets_have_identical_hash() -> None:
    original = make_analysis_snapshot(UTC_INSTANT)
    shifted = _shift_datetimes(
        original.model_dump(mode="python"),
        timezone(timedelta(hours=8)),
    )
    normalized = AnalysisSnapshot.model_validate(shifted)

    assert normalized.captured_at == original.captured_at
    assert normalized.data_cutoff_at == original.data_cutoff_at
    assert canonical_sha256(normalized) == canonical_sha256(original)


def test_equivalent_backtest_boundaries_have_identical_run_spec_hash() -> None:
    utc = _run_spec(UTC_INSTANT)
    taipei = _run_spec(TAIPEI_INSTANT)

    assert utc == taipei
    assert backtest_run_spec_hash(utc) == backtest_run_spec_hash(taipei)


def test_equivalent_dataset_timestamps_have_identical_hash() -> None:
    utc = build_canonical_dataset_identity(
        {MarketSymbol.BTCUSDT: (candle(UTC_INSTANT),)},
        Timeframe.ONE_MINUTE,
    )
    taipei = build_canonical_dataset_identity(
        {MarketSymbol.BTCUSDT: (candle(TAIPEI_INSTANT),)},
        Timeframe.ONE_MINUTE,
    )

    assert utc.dataset_hash == taipei.dataset_hash
    assert utc.first_candle_at == taipei.first_candle_at == UTC_INSTANT


def test_strategy_identity_does_not_depend_on_deployment_timezone() -> None:
    with patch.dict(os.environ, {"TZ": "UTC"}):
        utc_identity = build_strategy_identity(TEST_STRATEGY_CONFIG)
    with patch.dict(os.environ, {"TZ": "Asia/Taipei"}):
        taipei_identity = build_strategy_identity(TEST_STRATEGY_CONFIG)

    assert utc_identity == taipei_identity


def test_trusted_pydantic_schema_fields_do_not_use_raw_datetime_annotations() -> None:
    schema_root = Path(__file__).resolve().parents[2] / "app" / "schemas"
    violations: list[str] = []
    for path in schema_root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            if not any(_annotation_name(base).endswith("BaseModel") for base in node.bases):
                continue
            for child in node.body:
                if not isinstance(child, ast.AnnAssign):
                    continue
                annotation_names = {
                    descendant.id
                    for descendant in ast.walk(child.annotation)
                    if isinstance(descendant, ast.Name)
                }
                if "datetime" in annotation_names:
                    field = child.target.id if isinstance(child.target, ast.Name) else "?"
                    violations.append(f"{path.name}:{node.name}.{field}")

    assert violations == []


def _annotation_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_annotation_name(node.value)}.{node.attr}"
    return ""


def _shift_datetimes(value: object, target_timezone: timezone) -> object:
    if isinstance(value, datetime):
        return value.astimezone(target_timezone).isoformat()
    if isinstance(value, dict):
        return {
            key: _shift_datetimes(child, target_timezone)
            for key, child in value.items()
        }
    if isinstance(value, tuple):
        return tuple(_shift_datetimes(child, target_timezone) for child in value)
    if isinstance(value, list):
        return [_shift_datetimes(child, target_timezone) for child in value]
    return value


def _run_spec(start: datetime) -> BacktestRunSpec:
    return BacktestRunSpec(
        symbols=(MarketSymbol.BTCUSDT,),
        canonical_timeframe=Timeframe.ONE_MINUTE,
        required_timeframes=(Timeframe.ONE_MINUTE,),
        evaluation_timeframe=Timeframe.ONE_MINUTE,
        analysis_input_start=start,
        metrics_start=start + timedelta(minutes=1),
        end_at=start + timedelta(minutes=2),
        same_candle_policy=SameCandlePolicy.AMBIGUOUS,
    )
