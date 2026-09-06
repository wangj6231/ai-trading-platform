from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.time import UtcDateTime
from app.schemas.backtest_identity import (
    BacktestRunIdentity,
    BacktestRunSpec,
    DatasetSeriesProvenance,
)

from app.schemas.candle import Candle
from app.schemas.execution import (
    EntryExecutionResult,
    ExecutionResult,
    FinancialOutcome,
)
from app.schemas.signal import EntryZone, SignalDecision
from app.schemas.signal_lifecycle import SameCandlePolicy, SignalLifecycleStatus
from app.schemas.signal_persistence import AnalysisSnapshot, SignalResult
from app.schemas.strategy_identity import StrategyIdentity
from app.schemas.types import MarketSymbol, Timeframe


class HistoricalCandleSeries(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: MarketSymbol
    timeframe: Timeframe
    candles: tuple[Candle, ...] = Field(min_length=1)
    source_label: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def reject_machine_path_label(self) -> "HistoricalCandleSeries":
        if self.source_label is not None and any(
            marker in self.source_label for marker in ("/", "\\", ":")
        ):
            raise ValueError("source_label must not contain a machine path")
        return self


class HistoricalOHLCInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    series: tuple[HistoricalCandleSeries, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def require_unique_series(self) -> "HistoricalOHLCInput":
        keys = [(item.symbol, item.timeframe) for item in self.series]
        if len(keys) != len(set(keys)):
            raise ValueError("historical symbol/timeframe series must be unique")
        return self


class BacktestConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    evaluation_timeframe: Timeframe
    required_timeframes: tuple[Timeframe, ...] = Field(min_length=1)
    same_candle_policy: SameCandlePolicy = SameCandlePolicy.AMBIGUOUS
    strict_candle_continuity: Literal[True] = True
    openai_enabled: Literal[False] = False

    @model_validator(mode="after")
    def validate_timeframes(self) -> "BacktestConfig":
        if len(self.required_timeframes) != len(set(self.required_timeframes)):
            raise ValueError("required_timeframes must be unique")
        if self.evaluation_timeframe not in self.required_timeframes:
            raise ValueError("evaluation_timeframe must be required")
        return self


class BacktestTrade(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: str
    symbol: MarketSymbol
    timeframe: Timeframe
    direction: SignalDecision
    entry_zone: EntryZone
    entry_reference: Decimal = Field(gt=0, allow_inf_nan=False)
    status: SignalLifecycleStatus
    created_at: UtcDateTime
    activated_at: UtcDateTime | None
    closed_at: UtcDateTime | None
    result: SignalResult | None
    financial_outcome: FinancialOutcome | None
    entry_execution: EntryExecutionResult | None
    execution: ExecutionResult | None
    gross_r: Decimal | None
    trading_cost_r: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    pnl_r: Decimal | None
    analysis_snapshot: AnalysisSnapshot

    @model_validator(mode="after")
    def validate_execution_evidence(self) -> "BacktestTrade":
        if not self.entry_zone.low <= self.entry_reference <= self.entry_zone.high:
            raise ValueError("entry_reference must be inside entry_zone")
        if (self.activated_at is not None) != (
            self.entry_execution is not None and self.entry_execution.executed
        ):
            raise ValueError("activation requires executed entry evidence")
        if self.entry_execution is not None:
            if self.entry_execution.candidate_id != self.candidate_id:
                raise ValueError("entry execution candidate must match trade")
            if self.entry_execution.requested_entry_price != self.entry_reference:
                raise ValueError("entry execution must preserve requested reference")
            if self.entry_execution.executed_at != self.activated_at:
                raise ValueError("activation timestamp must match entry execution")
        price_resolved = self.status in {
            SignalLifecycleStatus.TP_HIT,
            SignalLifecycleStatus.SL_HIT,
        }
        if price_resolved != (self.execution is not None):
            raise ValueError("resolved TP/SL trade requires execution evidence")
        if self.execution is not None:
            if self.execution.entry_execution != self.entry_execution:
                raise ValueError("terminal execution must preserve entry evidence")
            if self.financial_outcome is not self.execution.financial_outcome:
                raise ValueError("financial outcome must match execution")
            if self.gross_r != self.execution.gross_r:
                raise ValueError("trade gross_r must match execution")
            if self.pnl_r != self.execution.net_r:
                raise ValueError("trade pnl_r must match execution net_r")
            expected_cost_r = (
                self.execution.spread_cost + self.execution.commission_cost
            ) / self.execution.planned_risk
            if self.trading_cost_r != expected_cost_r:
                raise ValueError("trade cost R must match execution costs")
        elif any(
            value is not None
            for value in (
                self.financial_outcome,
                self.gross_r,
                self.trading_cost_r,
                self.pnl_r,
            )
        ):
            raise ValueError(
                "trade without terminal execution cannot carry financial results"
            )
        return self


class PerformanceMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    total_signals: int = Field(ge=0)
    activated_signals: int = Field(ge=0)
    executed_trades: int = Field(ge=0)
    resolved_financial_trades: int = Field(ge=0)
    price_resolved_trades: int = Field(ge=0)
    wins: int = Field(ge=0)
    losses: int = Field(ge=0)
    flats: int = Field(ge=0)
    win_rate: Decimal = Field(ge=0, le=1, allow_inf_nan=False)
    loss_rate: Decimal = Field(ge=0, le=1, allow_inf_nan=False)
    lifecycle_tp_hits: int = Field(ge=0)
    lifecycle_sl_hits: int = Field(ge=0)
    tp_hit_rate: Decimal = Field(ge=0, le=1, allow_inf_nan=False)
    sl_hit_rate: Decimal = Field(ge=0, le=1, allow_inf_nan=False)
    cancelled: int = Field(ge=0)
    ambiguous: int = Field(ge=0)
    average_r: Decimal | None
    median_r: Decimal | None
    average_net_r: Decimal | None
    median_net_r: Decimal | None
    total_gross_pnl: Decimal = Field(allow_inf_nan=False)
    total_net_pnl: Decimal = Field(allow_inf_nan=False)
    profit_factor: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    maximum_drawdown: Decimal = Field(ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_metric_semantics(self) -> "PerformanceMetrics":
        if self.activated_signals != self.executed_trades:
            raise ValueError("activated_signals must equal executed_trades")
        if self.executed_trades > self.total_signals:
            raise ValueError("executed_trades cannot exceed total_signals")
        if self.resolved_financial_trades != self.wins + self.losses + self.flats:
            raise ValueError("resolved financial count must equal wins + losses + flats")
        if self.resolved_financial_trades > self.executed_trades:
            raise ValueError("resolved financial trades must be executed")
        if self.price_resolved_trades != (
            self.lifecycle_tp_hits + self.lifecycle_sl_hits
        ):
            raise ValueError("price-resolved count must equal TP hits + SL hits")
        if self.price_resolved_trades != self.resolved_financial_trades:
            raise ValueError(
                "price-resolved and financially resolved counts must agree"
            )
        financial_rate_denominator = self.wins + self.losses
        expected_win_rate = (
            Decimal(self.wins) / Decimal(financial_rate_denominator)
            if financial_rate_denominator
            else Decimal(0)
        )
        expected_loss_rate = (
            Decimal(self.losses) / Decimal(financial_rate_denominator)
            if financial_rate_denominator
            else Decimal(0)
        )
        if self.win_rate != expected_win_rate or self.loss_rate != expected_loss_rate:
            raise ValueError("financial win/loss rates use wins + losses only")
        expected_tp_rate = (
            Decimal(self.lifecycle_tp_hits) / Decimal(self.price_resolved_trades)
            if self.price_resolved_trades
            else Decimal(0)
        )
        expected_sl_rate = (
            Decimal(self.lifecycle_sl_hits) / Decimal(self.price_resolved_trades)
            if self.price_resolved_trades
            else Decimal(0)
        )
        if self.tp_hit_rate != expected_tp_rate or self.sl_hit_rate != expected_sl_rate:
            raise ValueError("TP/SL rates use price_resolved_trades only")
        if self.average_r != self.average_net_r or self.median_r != self.median_net_r:
            raise ValueError("legacy R labels must remain exact net-R aliases")
        return self


class BacktestMetrics(PerformanceMetrics):
    long_performance: PerformanceMetrics
    short_performance: PerformanceMetrics
    performance_by_symbol: dict[str, PerformanceMetrics]
    performance_by_timeframe: dict[str, PerformanceMetrics]


class BacktestReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    started_at: UtcDateTime
    ended_at: UtcDateTime
    strategy_version: str = Field(min_length=1, max_length=64)
    config_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    algorithm_build_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    run_identity: BacktestRunIdentity
    run_spec: BacktestRunSpec
    dataset_provenance: tuple[DatasetSeriesProvenance, ...] = ()
    engine_evaluations: int = Field(ge=0)
    openai_used: Literal[False] = False
    trades: tuple[BacktestTrade, ...]
    metrics: BacktestMetrics

    @model_validator(mode="after")
    def validate_reproducibility_identity(self) -> "BacktestReport":
        from app.backtesting.identity import (
            backtest_run_identity_hash,
            backtest_run_spec_hash,
        )

        if self.strategy_identity != self.run_identity.strategy_identity:
            raise ValueError("report strategy and run identities must agree")
        if self.started_at != self.run_identity.metrics_start:
            raise ValueError("started_at must equal deterministic metrics_start")
        if self.ended_at != self.run_identity.end_at:
            raise ValueError("ended_at must equal deterministic run end")
        if self.run_spec.symbols != self.run_identity.symbols:
            raise ValueError("run spec and identity symbols must agree")
        if self.run_spec.canonical_timeframe is not self.run_identity.canonical_timeframe:
            raise ValueError("run spec and identity canonical timeframe must agree")
        if self.run_spec.analysis_input_start != self.run_identity.analysis_input_start:
            raise ValueError("run spec and identity analysis start must agree")
        if self.run_spec.metrics_start != self.run_identity.metrics_start:
            raise ValueError("run spec and identity metrics start must agree")
        if self.run_spec.end_at != self.run_identity.end_at:
            raise ValueError("run spec and identity end must agree")
        expected_spec_hash = backtest_run_spec_hash(self.run_spec)
        if self.run_identity.run_spec_hash != expected_spec_hash:
            raise ValueError("run_spec_hash must match canonical run spec")
        expected_identity_hash = backtest_run_identity_hash(
            self.strategy_identity,
            self.run_identity.dataset_hash,
            expected_spec_hash,
        )
        if self.run_identity.run_identity_hash != expected_identity_hash:
            raise ValueError("run_identity_hash must match canonical identity payload")
        return self

    @property
    def strategy_identity(self) -> StrategyIdentity:
        return StrategyIdentity(
            strategy_version=self.strategy_version,
            config_hash=self.config_hash,
            algorithm_build_hash=self.algorithm_build_hash,
        )
