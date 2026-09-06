from datetime import datetime, timedelta
from decimal import Decimal

from app.core.strategy_config import load_strategy_config
from app.core.strategy_identity import build_strategy_identity
from app.engines.strategy_engine import ConcreteDeterministicStrategyEngine
from app.schemas.analysis_snapshot import (
    AnalysisSnapshot,
    AnalysisSnapshotPayloadV2,
    SnapshotCandleSeriesEvidence,
    SnapshotDecisionEvidence,
    SnapshotMarketDataEvidence,
    SnapshotSeriesSource,
)
from app.schemas.candle import Candle
from app.schemas.openai_validation import (
    OpenAIValidationEvidenceV1,
    OpenAIValidationOutput,
    OpenAIValidationStatus,
)
from app.schemas.signal import SignalDecision
from app.schemas.strategy import DeterministicSignalCandidate, StrategyEvaluationContext
from app.schemas.types import MarketSymbol, Timeframe


TEST_STRATEGY_CONFIG = load_strategy_config()
TEST_STRATEGY_IDENTITY = build_strategy_identity(TEST_STRATEGY_CONFIG)
TEST_PIPELINE_CONFIG = TEST_STRATEGY_CONFIG.model_dump(mode="json")

_BULLISH_PRICES = (
    (100, 110, 90, 100), (100, 108, 94, 105), (105, 109, 96, 108),
    (108, 120, 100, 118), (118, 125, 105, 120), (120, 121, 100, 110),
    (110, 114, 100, 112), (112, 115, 101, 113), (113, 114, 97, 105),
    (105, 300, 103, 120), (120, 126, 108, 115), (115, 128, 109, 120),
    (120, 124, 104, 110), (110, 126, 106, 120), (120, 122, 102, 105),
    (105, 132, 105, 131), (131, 172, 130, 170), (174, 190, 174, 188),
    (188, 190, 150, 180), (180, 190, 150, 180),
)


def make_analysis_snapshot(
    captured_at: datetime,
    *,
    symbol: MarketSymbol = MarketSymbol.BTCUSDT,
    timeframe: Timeframe = Timeframe.ONE_MINUTE,
    data_cutoff_at: datetime | None = None,
    marker: str = "deterministic-test-fixture",
    strategy_identity=TEST_STRATEGY_IDENTITY,
) -> AnalysisSnapshot:
    """Minimal typed NO_TRADE snapshot for isolated test doubles only."""

    cutoff = data_cutoff_at or captured_at
    source_timeframe = Timeframe.ONE_MINUTE
    last_candle_at = cutoff - timedelta(minutes=1)
    return AnalysisSnapshot(
        captured_at=captured_at,
        data_cutoff_at=cutoff,
        payload=AnalysisSnapshotPayloadV2(
            symbol=symbol,
            timeframe=timeframe,
            as_of=captured_at,
            strategy_identity=strategy_identity,
            market_data=SnapshotMarketDataEvidence(
                source_timeframe=source_timeframe,
                data_cutoff_at=cutoff,
                series={
                    source_timeframe.value: SnapshotCandleSeriesEvidence(
                        timeframe=source_timeframe,
                        source=SnapshotSeriesSource.CANONICAL,
                        candle_count=1,
                        first_candle_at=last_candle_at,
                        last_candle_at=last_candle_at,
                        last_candle_close_at=cutoff,
                    )
                },
            ),
            decision=SnapshotDecisionEvidence(
                deterministic_decision=SignalDecision.NO_TRADE,
                candidate_direction=SignalDecision.NO_TRADE,
                decision_at=captured_at,
                evidence_cutoff_at=cutoff,
                reason_codes=("TEST_FIXTURE_NO_TRADE",),
            ),
            non_decision_metadata={
                "fixture": marker,
                "openai_used": False,
            },
        ),
    )


def make_engine_candidate(
    captured_at: datetime,
    *,
    symbol: MarketSymbol = MarketSymbol.BTCUSDT,
    direction: SignalDecision = SignalDecision.LONG,
) -> DeterministicSignalCandidate:
    """Real-engine candidate used where persistence needs trusted trade evidence."""

    prices = _BULLISH_PRICES
    if direction is SignalDecision.SHORT:
        prices = tuple(
            (400 - open_, 400 - low, 400 - high, 400 - close)
            for open_, high, low, close in _BULLISH_PRICES
        )
    for prefix_count in range(3):
        flat = prices[0][0]
        effective_prices = ((flat, flat, flat, flat),) * prefix_count + prices
        start = captured_at - timedelta(minutes=len(effective_prices))
        candles = tuple(
            Candle(
                timestamp=start + timedelta(minutes=index),
                open=Decimal(open_),
                high=Decimal(high),
                low=Decimal(low),
                close=Decimal(close),
                volume=Decimal("1"),
            )
            for index, (open_, high, low, close) in enumerate(effective_prices)
        )
        output = ConcreteDeterministicStrategyEngine(TEST_STRATEGY_CONFIG).evaluate(
            StrategyEvaluationContext(
                symbol=symbol,
                as_of=captured_at,
                candles_by_timeframe={Timeframe.ONE_MINUTE: candles},
            )
        )
        if len(output.candidates) == 1 and output.candidates[0].direction is direction:
            return output.candidates[0]
    raise AssertionError("synthetic typed snapshot fixture did not produce candidate")


def make_confirmed_ai_validation(
    snapshot: AnalysisSnapshot,
    *,
    confidence: int = 82,
) -> OpenAIValidationEvidenceV1:
    """Typed server-style AI confirmation for persistence tests only."""

    decision = snapshot.payload.decision
    assert decision.deterministic_decision in {
        SignalDecision.LONG,
        SignalDecision.SHORT,
    }
    assert decision.entry_zone is not None
    assert decision.take_profit is not None
    assert decision.stop_loss is not None
    assert decision.risk_reward is not None
    completed_at = snapshot.captured_at
    return OpenAIValidationEvidenceV1(
        status=OpenAIValidationStatus.CONFIRMED,
        provider="OPENAI",
        model_id="mock-openai-model",
        deterministic_input_hash="a" * 64,
        request_started_at=completed_at - timedelta(seconds=1),
        completed_at=completed_at,
        structured_response=OpenAIValidationOutput(
            decision=decision.deterministic_decision,
            confidence=confidence,
            entry_min=decision.entry_zone.low,
            entry_max=decision.entry_zone.high,
            take_profit=decision.take_profit,
            stop_loss=decision.stop_loss,
            risk_reward=decision.risk_reward,
            reason=["Mocked AI confirmation fixture."],
        ),
    )


def make_rejected_ai_validation(
    snapshot: AnalysisSnapshot,
    *,
    confidence: int = 35,
) -> OpenAIValidationEvidenceV1:
    """Typed server-style AI rejection for persistence tests only."""

    completed_at = snapshot.captured_at
    return OpenAIValidationEvidenceV1(
        status=OpenAIValidationStatus.REJECTED,
        provider="OPENAI",
        model_id="mock-openai-model",
        deterministic_input_hash="b" * 64,
        request_started_at=completed_at - timedelta(seconds=1),
        completed_at=completed_at,
        structured_response=OpenAIValidationOutput(
            decision=SignalDecision.NO_TRADE,
            confidence=confidence,
            entry_min=None,
            entry_max=None,
            take_profit=None,
            stop_loss=None,
            risk_reward=None,
            reason=["Mocked AI rejection fixture."],
        ),
    )


def make_not_requested_ai_validation(
    completed_at: datetime,
) -> OpenAIValidationEvidenceV1:
    """Explicit provenance for a deterministic-only evaluation."""

    return OpenAIValidationEvidenceV1(
        status=OpenAIValidationStatus.NOT_REQUESTED,
        completed_at=completed_at,
    )
