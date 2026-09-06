from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.backtesting.identity import (
    build_backtest_run_identity,
)
from app.backtesting.runner import BacktestInputError, run_backtest
from app.core.algorithm_identity import (
    AlgorithmSourceManifestRules,
    build_algorithm_identity,
)
from app.core.config import REPOSITORY_ROOT
from app.core.strategy_identity import build_strategy_identity
from app.market_data.resampling import resample_canonical_candles
from app.schemas.backtest import (
    BacktestConfig,
    HistoricalCandleSeries,
    HistoricalOHLCInput,
)
from app.schemas.backtest_identity import CanonicalDatasetIdentity
from app.schemas.candle import Candle
from app.schemas.signal_lifecycle import SameCandlePolicy
from app.schemas.strategy import StrategyConfig, StrategyEvaluationContext, StrategyEvaluationResult
from app.schemas.types import MarketSymbol, Timeframe
from tests.factories import TEST_STRATEGY_CONFIG
from tests.unit.test_backtest_runner import (
    ScheduledEngine,
    backtest_config as scheduled_config,
    bar as scheduled_bar,
    historical as scheduled_historical,
)


START = datetime(2026, 6, 1, tzinfo=UTC)


def candles(
    count: int,
    *,
    start: datetime = START,
    price_text: str = "100",
) -> tuple[Candle, ...]:
    price = Decimal(price_text)
    return tuple(
        Candle(
            timestamp=start + timedelta(minutes=index),
            open=price,
            high=price + Decimal("100"),
            low=price - Decimal("10"),
            close=price + Decimal(index),
            volume=Decimal("1.000"),
        )
        for index in range(count)
    )


def historical(
    source: tuple[Candle, ...],
    *,
    symbol: MarketSymbol = MarketSymbol.BTCUSDT,
    source_label: str | None = None,
    extra: tuple[HistoricalCandleSeries, ...] = (),
) -> HistoricalOHLCInput:
    return HistoricalOHLCInput(
        series=(
            HistoricalCandleSeries(
                symbol=symbol,
                timeframe=Timeframe.ONE_MINUTE,
                candles=source,
                source_label=source_label,
            ),
            *extra,
        )
    )


def config(
    *,
    evaluation: Timeframe = Timeframe.ONE_MINUTE,
    required: tuple[Timeframe, ...] = (Timeframe.ONE_MINUTE,),
    same_bar: SameCandlePolicy = SameCandlePolicy.AMBIGUOUS,
) -> BacktestConfig:
    return BacktestConfig(
        evaluation_timeframe=evaluation,
        required_timeframes=required,
        same_candle_policy=same_bar,
    )


class NoTradeEngine:
    def __init__(self, strategy_config: StrategyConfig = TEST_STRATEGY_CONFIG) -> None:
        self.strategy_config = strategy_config
        self.strategy_identity = build_strategy_identity(strategy_config)
        self.contexts: list[StrategyEvaluationContext] = []

    def evaluate(self, context: StrategyEvaluationContext) -> StrategyEvaluationResult:
        self.contexts.append(context)
        return StrategyEvaluationResult(evaluated_at=context.as_of)


def run(source: tuple[Candle, ...], **kwargs):
    return run_backtest(
        historical(source, source_label=kwargs.pop("source_label", None)),
        kwargs.pop("engine", NoTradeEngine()),
        kwargs.pop("backtest_config", config()),
    )


def test_golden_identical_run_reproduces_identity_trades_and_metrics() -> None:
    source = [
        scheduled_bar(0, "104", "105", "103", "104"),
        scheduled_bar(1, "103", "104", "100", "102"),
        scheduled_bar(2, "103", "114", "103", "113"),
    ]
    first = run_backtest(
        scheduled_historical(source), ScheduledEngine(), scheduled_config()
    )
    second = run_backtest(
        scheduled_historical(source), ScheduledEngine(), scheduled_config()
    )

    assert first.strategy_identity == second.strategy_identity
    assert first.run_identity == second.run_identity
    assert first.run_spec == second.run_spec
    assert first.trades == second.trades
    assert first.metrics == second.metrics
    assert first.run_identity.run_identity_hash == second.run_identity.run_identity_hash


@pytest.mark.parametrize(
    "mutation",
    [
        lambda values: values[:-1]
        + (values[-1].model_copy(update={"close": Decimal("109")}),),
        lambda values: values[:-1]
        + (values[-1].model_copy(update={"high": Decimal("111")}),),
        lambda values: values[:-1]
        + (values[-1].model_copy(update={"low": Decimal("89")}),),
        lambda values: values[:-1],
        lambda values: values
        + (
            Candle(
                timestamp=values[-1].timestamp + timedelta(minutes=1),
                open=Decimal("100"),
                high=Decimal("110"),
                low=Decimal("90"),
                close=Decimal("100"),
                volume=Decimal("1"),
            ),
        ),
    ],
)
def test_effective_candle_content_addition_or_removal_changes_dataset_identity(
    mutation,
) -> None:
    source = candles(3)
    original = run(source)
    changed = run(mutation(source))

    assert changed.run_identity.dataset_hash != original.run_identity.dataset_hash
    assert changed.run_identity.run_identity_hash != original.run_identity.run_identity_hash


def test_one_timestamp_change_changes_dataset_identity() -> None:
    original = run(candles(1, start=START))
    shifted = run(candles(1, start=START + timedelta(minutes=1)))

    assert original.run_identity.dataset_hash != shifted.run_identity.dataset_hash
    assert original.run_identity.run_identity_hash != shifted.run_identity.run_identity_hash


def test_decimal_and_timezone_equivalence_have_same_dataset_hash() -> None:
    utc_source = candles(2, price_text="100")
    taipei = timezone(timedelta(hours=8))
    equivalent = tuple(
        Candle(
            timestamp=item.timestamp.astimezone(taipei),
            open=Decimal("100.000"),
            high=Decimal("200.0"),
            low=Decimal("90.0000"),
            close=Decimal(f"{item.close}.000"),
            volume=Decimal("1"),
        )
        for item in utc_source
    )

    assert run(utc_source).run_identity.dataset_hash == run(equivalent).run_identity.dataset_hash


def test_multi_symbol_series_order_is_canonical_but_candle_order_is_not_hidden() -> None:
    btc = HistoricalCandleSeries(
        symbol=MarketSymbol.BTCUSDT,
        timeframe=Timeframe.ONE_MINUTE,
        candles=candles(2),
    )
    eth = HistoricalCandleSeries(
        symbol=MarketSymbol.ETHUSDT,
        timeframe=Timeframe.ONE_MINUTE,
        candles=candles(2, price_text="200"),
    )
    first = run_backtest(
        HistoricalOHLCInput(series=(btc, eth)), NoTradeEngine(), config()
    )
    second = run_backtest(
        HistoricalOHLCInput(series=(eth, btc)), NoTradeEngine(), config()
    )

    assert first.run_identity.dataset_hash == second.run_identity.dataset_hash
    assert first.run_identity.run_identity_hash == second.run_identity.run_identity_hash

    malformed = historical(tuple(reversed(candles(2))))
    with pytest.raises(BacktestInputError, match="ascending"):
        run_backtest(malformed, NoTradeEngine(), config())


def test_external_derived_htf_is_validation_only_not_a_second_dataset() -> None:
    source = candles(5)
    derived = resample_canonical_candles(
        source,
        source_timeframe=Timeframe.ONE_MINUTE,
        target_timeframe=Timeframe.FIVE_MINUTES,
        cutoff=START + timedelta(minutes=5),
    )
    required = (Timeframe.ONE_MINUTE, Timeframe.FIVE_MINUTES)
    without_external = run_backtest(
        historical(source), NoTradeEngine(), config(required=required)
    )
    with_external = run_backtest(
        historical(
            source,
            extra=(
                HistoricalCandleSeries(
                    symbol=MarketSymbol.BTCUSDT,
                    timeframe=Timeframe.FIVE_MINUTES,
                    candles=derived,
                    source_label="validated-5m.csv",
                ),
            ),
        ),
        NoTradeEngine(),
        config(required=required),
    )

    assert without_external.run_identity == with_external.run_identity
    assert without_external.dataset_provenance != with_external.dataset_provenance


def test_schedule_and_same_bar_policy_participate_in_run_spec_identity() -> None:
    source = candles(10)
    required = (Timeframe.ONE_MINUTE, Timeframe.FIVE_MINUTES)
    every_minute = run_backtest(
        historical(source),
        NoTradeEngine(),
        config(evaluation=Timeframe.ONE_MINUTE, required=required),
    )
    every_five = run_backtest(
        historical(source),
        NoTradeEngine(),
        config(evaluation=Timeframe.FIVE_MINUTES, required=required),
    )
    stop_first = run_backtest(
        historical(source),
        NoTradeEngine(),
        config(
            evaluation=Timeframe.ONE_MINUTE,
            required=required,
            same_bar=SameCandlePolicy.CONSERVATIVE_STOP_FIRST,
        ),
    )

    assert every_minute.run_identity.dataset_hash == every_five.run_identity.dataset_hash
    assert every_minute.run_identity.run_spec_hash != every_five.run_identity.run_spec_hash
    assert every_minute.run_identity.run_identity_hash != every_five.run_identity.run_identity_hash
    assert every_minute.run_spec.schedule_policy == "EVALUATION_TIMEFRAME_CLOSED_CANDLES_V1"
    assert every_minute.run_spec.same_candle_policy is SameCandlePolicy.AMBIGUOUS
    assert every_minute.run_spec.entry_exit_same_bar_policy == "OPEN_KNOWN_ELSE_AMBIGUOUS_V1"
    assert every_minute.run_spec.opening_gap_precedence_policy == "OPEN_BEFORE_INTRABAR_EXTREMES_V1"
    assert "spread" not in every_minute.run_spec.model_dump(mode="json")
    assert stop_first.run_identity.run_spec_hash != every_minute.run_identity.run_spec_hash


def test_warmup_prefix_is_hashed_and_reported_before_metrics_start() -> None:
    source = candles(9, start=START + timedelta(minutes=1))
    run_config = config(
        evaluation=Timeframe.FIVE_MINUTES,
        required=(Timeframe.ONE_MINUTE, Timeframe.FIVE_MINUTES),
    )
    engine = NoTradeEngine()
    original = run_backtest(historical(source), engine, run_config)
    changed_warmup = source[:1] + (
        source[1].model_copy(update={"close": Decimal("109")}),
    ) + source[2:]
    changed = run_backtest(historical(changed_warmup), NoTradeEngine(), run_config)

    assert original.run_identity.analysis_input_start == START + timedelta(minutes=1)
    assert original.run_identity.metrics_start == START + timedelta(minutes=10)
    assert original.run_identity.candle_count == 9
    assert [context.as_of for context in engine.contexts] == [
        START + timedelta(minutes=10)
    ]
    assert changed.run_identity.dataset_hash != original.run_identity.dataset_hash
    assert changed.run_identity.run_identity_hash != original.run_identity.run_identity_hash


def test_trailing_incomplete_bucket_is_excluded_but_next_complete_bucket_changes_identity() -> None:
    run_config = config(
        evaluation=Timeframe.FIVE_MINUTES,
        required=(Timeframe.ONE_MINUTE, Timeframe.FIVE_MINUTES),
    )
    exact = run_backtest(historical(candles(10)), NoTradeEngine(), run_config)
    unused_tail = run_backtest(historical(candles(11)), NoTradeEngine(), run_config)
    next_complete = run_backtest(historical(candles(15)), NoTradeEngine(), run_config)

    assert exact.run_identity == unused_tail.run_identity
    assert exact.run_identity.candle_count == 10
    assert exact.run_identity.end_at == START + timedelta(minutes=10)
    assert next_complete.run_identity.dataset_hash != exact.run_identity.dataset_hash
    assert next_complete.run_identity.end_at == START + timedelta(minutes=15)


def test_selected_effective_range_change_changes_dataset_and_run_identity() -> None:
    full = run(candles(4))
    selected = run(candles(4)[1:])

    assert selected.run_identity.analysis_input_start == START + timedelta(minutes=1)
    assert selected.run_identity.dataset_hash != full.run_identity.dataset_hash
    assert selected.run_identity.run_identity_hash != full.run_identity.run_identity_hash


def test_provenance_name_wall_clock_and_secrets_do_not_affect_identity(monkeypatch) -> None:
    source = candles(2)
    first = run(source, source_label="original.csv")
    monkeypatch.setenv("USERNAME", "another-machine-user")
    monkeypatch.setenv("DATABASE_URL", "postgresql://secret@different-host/db")
    monkeypatch.setenv("OPENAI_API_KEY", "not-used-by-backtest")
    second = run(source, source_label="renamed.csv")

    assert first.run_identity == second.run_identity
    assert first.dataset_provenance != second.dataset_provenance
    with pytest.raises(ValidationError, match="machine path"):
        historical(source, source_label=r"C:\\Users\\name\\dataset.csv")


def _changed_strategy_config(*path: object, value: object) -> StrategyConfig:
    raw = TEST_STRATEGY_CONFIG.model_dump(mode="python")
    cursor = raw
    for part in path[:-1]:
        cursor = cursor[part]
    cursor[path[-1]] = value
    return StrategyConfig.model_validate(raw)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("execution", "costs", "spread_bps"), "1"),
        (("execution", "costs", "slippage_bps_per_side"), "1"),
        (
            (
                "pipelines",
                MarketSymbol.BTCUSDT,
                "signal_score",
                "weights",
                "macd",
            ),
            2,
        ),
    ],
)
def test_strategy_or_execution_config_change_changes_strategy_and_run_identity(
    path, value
) -> None:
    source = candles(2)
    original = run(source)
    changed = run(source, engine=NoTradeEngine(_changed_strategy_config(*path, value=value)))

    assert original.run_identity.dataset_hash == changed.run_identity.dataset_hash
    assert original.run_identity.strategy_identity.config_hash != changed.run_identity.strategy_identity.config_hash
    assert original.run_identity.run_identity_hash != changed.run_identity.run_identity_hash


def test_algorithm_build_hash_participates_in_overall_identity() -> None:
    report = run(candles(2))
    dataset = CanonicalDatasetIdentity(
        dataset_hash=report.run_identity.dataset_hash,
        symbols=report.run_identity.symbols,
        canonical_timeframe=report.run_identity.canonical_timeframe,
        candle_count=report.run_identity.candle_count,
        first_candle_at=report.run_identity.first_candle_at,
        last_candle_at=report.run_identity.last_candle_at,
    )
    changed_strategy = report.strategy_identity.model_copy(
        update={"algorithm_build_hash": "a" * 64}
    )
    changed = build_backtest_run_identity(changed_strategy, dataset, report.run_spec)

    assert changed.dataset_hash == report.run_identity.dataset_hash
    assert changed.run_spec_hash == report.run_identity.run_spec_hash
    assert changed.run_identity_hash != report.run_identity.run_identity_hash


def test_actual_source_change_changes_only_algorithm_and_overall_run_identity(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "backend" / "app" / "engines"
    source_root.mkdir(parents=True)
    source = source_root / "strategy.py"
    source.write_text("OUTCOME = 'a'\n", encoding="utf-8")
    rules = AlgorithmSourceManifestRules(
        source_roots=("backend/app/engines",),
    )
    first_build = build_algorithm_identity(tmp_path, rules)
    report = run(candles(2))
    dataset = CanonicalDatasetIdentity(
        dataset_hash=report.run_identity.dataset_hash,
        symbols=report.run_identity.symbols,
        canonical_timeframe=report.run_identity.canonical_timeframe,
        candle_count=report.run_identity.candle_count,
        first_candle_at=report.run_identity.first_candle_at,
        last_candle_at=report.run_identity.last_candle_at,
    )
    first_strategy = report.strategy_identity.model_copy(
        update={"algorithm_build_hash": first_build.algorithm_build_hash}
    )
    first = build_backtest_run_identity(first_strategy, dataset, report.run_spec)

    source.write_text("OUTCOME = 'b'\n", encoding="utf-8")
    second_build = build_algorithm_identity(tmp_path, rules)
    second_strategy = report.strategy_identity.model_copy(
        update={"algorithm_build_hash": second_build.algorithm_build_hash}
    )
    second = build_backtest_run_identity(second_strategy, dataset, report.run_spec)

    assert first.strategy_identity.config_hash == second.strategy_identity.config_hash
    assert first.dataset_hash == second.dataset_hash
    assert first.run_spec_hash == second.run_spec_hash
    assert first_build.source_content_hash != second_build.source_content_hash
    assert (
        first.strategy_identity.algorithm_build_hash
        != second.strategy_identity.algorithm_build_hash
    )
    assert first.run_identity_hash != second.run_identity_hash


def test_audit_v4_dependency_changes_propagate_only_through_algorithm_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = run(candles(2))
    dataset = CanonicalDatasetIdentity(
        dataset_hash=report.run_identity.dataset_hash,
        symbols=report.run_identity.symbols,
        canonical_timeframe=report.run_identity.canonical_timeframe,
        candle_count=report.run_identity.candle_count,
        first_candle_at=report.run_identity.first_candle_at,
        last_candle_at=report.run_identity.last_candle_at,
    )
    baseline_build = build_algorithm_identity(REPOSITORY_ROOT)
    baseline_strategy = report.strategy_identity.model_copy(
        update={"algorithm_build_hash": baseline_build.algorithm_build_hash}
    )
    baseline = build_backtest_run_identity(
        baseline_strategy,
        dataset,
        report.run_spec,
    )
    original_read_bytes = Path.read_bytes

    for relative_path in (
        "backend/app/core/time.py",
        "backend/app/core/financial.py",
        "backend/app/metrics/financial.py",
    ):
        target = (REPOSITORY_ROOT / relative_path).resolve()

        def read_with_simulated_change(path: Path) -> bytes:
            content = original_read_bytes(path)
            if path.resolve() == target:
                return content + b"\n# simulated-run-identity-change\n"
            return content

        with monkeypatch.context() as scoped:
            scoped.setattr(Path, "read_bytes", read_with_simulated_change)
            changed_build = build_algorithm_identity(REPOSITORY_ROOT)
        changed_strategy = report.strategy_identity.model_copy(
            update={"algorithm_build_hash": changed_build.algorithm_build_hash}
        )
        changed = build_backtest_run_identity(
            changed_strategy,
            dataset,
            report.run_spec,
        )

        assert changed_build.source_content_hash != baseline_build.source_content_hash
        assert changed.strategy_identity.config_hash == baseline.strategy_identity.config_hash
        assert changed.dataset_hash == baseline.dataset_hash
        assert changed.run_spec_hash == baseline.run_spec_hash
        assert changed.run_identity_hash != baseline.run_identity_hash


def test_report_exposes_complete_reproducibility_block_without_instance_uuid() -> None:
    report = run(candles(2))
    payload = report.model_dump(mode="json")

    assert payload["run_identity"]["dataset_hash"]
    assert payload["run_identity"]["run_spec_hash"]
    assert payload["run_identity"]["run_identity_hash"]
    assert payload["run_identity"]["strategy_identity"]["config_hash"]
    assert payload["run_identity"]["analysis_input_start"]
    assert payload["run_identity"]["metrics_start"]
    assert payload["run_identity"]["end_at"]
    assert "run_instance_id" not in payload

    payload["run_identity"]["run_spec_hash"] = "0" * 64
    with pytest.raises(ValidationError, match="run_spec_hash"):
        report.__class__.model_validate(payload)
