"""Real subprocess cancellation and event-loop availability at the execution seam."""
import asyncio
import gc
import multiprocessing
from pathlib import Path
import time

import pytest

from app.services.evaluation_execution import IsolatedEvaluationRunner
from app.core.errors import AppError


def cpu_task(seconds):
    if isinstance(seconds, tuple):
        seconds, marker = seconds
        Path(marker).write_text("CPU started", encoding="utf-8")
    started = time.perf_counter()
    while time.perf_counter() - started < seconds:
        pass
    return {"complete": True}


def failing_task(_):
    raise RuntimeError("private implementation detail")


def public_error_task(_):
    raise AppError(status_code=422, code="EXPECTED_PUBLIC_ERROR", message="Validated public error.")


def marked_initializer(marker):
    Path(marker).write_text('ready for complete payload', encoding='utf-8')
    return cpu_task


@pytest.mark.parametrize('failure', [False, True])
@pytest.mark.parametrize('original_enabled', [False, True])
def test_exclusive_worker_defers_cycle_scans_and_restores_original_state(failure, original_enabled):
    from app.services.evaluation_execution import _run_callable
    previous_enabled, thresholds = gc.isenabled(), gc.get_threshold()
    observations = []
    class Connection:
        def send(self, message):
            observations.append(('send', gc.isenabled()))
        def close(self):
            observations.append(('close', gc.isenabled()))
    def task(payload):
        observations.append(('compute', gc.isenabled()))
        if failure:
            raise ValueError('private test exception')
        return payload
    try:
        (gc.enable if original_enabled else gc.disable)()
        _run_callable(Connection(), task, {'complete': True})
        assert gc.isenabled() is original_enabled
        assert gc.get_threshold() == thresholds
        assert observations[:2] == [('compute', False), ('send', False)]
    finally:
        (gc.enable if previous_enabled else gc.disable)()


def test_cpu_work_isolated_and_cancellation_reaps_child(tmp_path):
    async def exercise():
        runner = IsolatedEvaluationRunner(max_workers=1, timeout_seconds=10)
        marker = tmp_path / "worker-started"
        task = asyncio.create_task(runner.run(cpu_task, (5, str(marker))))
        async with asyncio.timeout(8):
            while not marker.exists():
                await asyncio.sleep(.02)
        started = time.perf_counter()
        await asyncio.sleep(.03)
        assert time.perf_counter() - started < .25
        assert len(runner.active_pids) == 1
        pid = runner.active_pids[0]
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert runner.active_pids == ()
        assert pid not in {child.pid for child in multiprocessing.active_children()}
        assert await runner.run(cpu_task, .01) == {"complete": True}
        assert runner.active_pids == ()
    asyncio.run(exercise())


def test_worker_start_overlaps_preparation_and_cancellation_reaps_waiting_child(tmp_path):
    async def exercise():
        runner = IsolatedEvaluationRunner(max_workers=1)
        preparation_entered = asyncio.Event()
        preparation_cancelled = asyncio.Event()
        gate = asyncio.Event()
        marker = tmp_path / 'waiting-worker-ready'
        async def prepare():
            preparation_entered.set()
            try:
                await gate.wait()
                return .01
            finally:
                preparation_cancelled.set()
        task = asyncio.create_task(runner.run_prepared(cpu_task, prepare,
            initializer=marked_initializer, initial_payload=str(marker)))
        await preparation_entered.wait()
        async with asyncio.timeout(8):
            while not marker.exists():
                await asyncio.sleep(.01)
        pid = runner.active_pids[0]
        assert not task.done() and not gate.is_set()
        with pytest.raises(AppError) as caught:
            await runner.run(cpu_task, .01)
        assert caught.value.code == 'STRATEGY_EVALUATION_BUSY'
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert preparation_cancelled.is_set() and not runner.active_pids
        assert pid not in {child.pid for child in multiprocessing.active_children()}
        assert await runner.run(cpu_task, .01) == {'complete': True}
    asyncio.run(exercise())


def test_preparation_failure_preserves_public_error_and_reaps_worker():
    async def exercise():
        runner = IsolatedEvaluationRunner()
        async def prepare():
            raise AppError(status_code=422, code='INVALID_PREPARATION', message='Invalid data.')
        with pytest.raises(AppError) as caught:
            await runner.run_prepared(cpu_task, prepare)
        assert caught.value.code == 'INVALID_PREPARATION' and not runner.active_pids
    asyncio.run(exercise())


def test_timeout_is_technical_error_and_reaps_child():
    async def exercise():
        runner = IsolatedEvaluationRunner(timeout_seconds=.15)
        with pytest.raises(AppError) as caught:
            await runner.run(cpu_task, 5)
        assert caught.value.code == "STRATEGY_EVALUATION_TIMEOUT"
        assert runner.active_pids == ()
    asyncio.run(exercise())


def test_worker_error_redacted_and_capacity_recovers():
    async def exercise():
        runner = IsolatedEvaluationRunner()
        with pytest.raises(AppError) as caught:
            await runner.run(failing_task, None)
        assert caught.value.code == "STRATEGY_EVALUATION_FAILED"
        assert "private" not in str(caught.value)
        assert runner.active_pids == ()
    asyncio.run(exercise())


def test_worker_preserves_expected_public_error():
    async def exercise():
        runner = IsolatedEvaluationRunner()
        with pytest.raises(AppError) as caught:
            await runner.run(public_error_task, None)
        assert caught.value.status_code == 422
        assert caught.value.code == 'EXPECTED_PUBLIC_ERROR'
        assert caught.value.message == 'Validated public error.'
        assert not runner.active_pids
    asyncio.run(exercise())


def test_capacity_is_bounded_before_spawn_and_during_execution():
    async def exercise():
        runner = IsolatedEvaluationRunner(max_workers=1)
        first = asyncio.create_task(runner.run(cpu_task, 5))
        await asyncio.sleep(.02)
        with pytest.raises(AppError, match="capacity") as caught:
            await runner.run(cpu_task, 5)
        assert caught.value.code == "STRATEGY_EVALUATION_BUSY"
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert not runner.active_pids
    asyncio.run(exercise())


@pytest.mark.parametrize("case", ["long", "short", "no_trade"])
def test_full_result_roundtrip_is_exact(case):
    from datetime import timedelta
    from app.core.strategy_config import load_strategy_config
    from app.engines.strategy_engine import ConcreteDeterministicStrategyEngine
    from app.schemas.strategy import StrategyEvaluationContext
    from app.schemas.types import Timeframe
    from tests.integration.test_deterministic_api import (
        BULLISH_PRICES, LEGACY_CONFIG_PATH, candles_from, mirrored_prices,
    )
    prices = mirrored_prices() if case == "short" else BULLISH_PRICES
    candles = candles_from(prices[:2] if case == "no_trade" else prices)
    context = StrategyEvaluationContext(symbol="BTCUSDT",
        as_of=candles[-1].timestamp + timedelta(minutes=1),
        candles_by_timeframe={Timeframe.ONE_MINUTE: candles})
    engine = ConcreteDeterministicStrategyEngine(load_strategy_config(LEGACY_CONFIG_PATH))
    expected = engine.evaluate(context)
    actual = asyncio.run(IsolatedEvaluationRunner().evaluate(engine, context))
    assert actual == expected
    assert actual.model_dump(mode="json") == expected.model_dump(mode="json")
    assert expected.evaluation.final_deterministic_decision.value == {"long": "LONG", "short": "SHORT", "no_trade": "NO_TRADE"}[case]


@pytest.mark.parametrize('case', ['long', 'short', 'no_trade'])
@pytest.mark.parametrize('response_kind', ['signal', 'analysis'])
def test_isolated_public_response_keeps_complete_validated_projection(case, response_kind):
    import json
    from datetime import timedelta
    from app.core.strategy_config import load_strategy_config
    from app.engines.strategy_engine import ConcreteDeterministicStrategyEngine
    from app.schemas.analysis import AnalysisResult
    from app.schemas.signal import SignalEvaluationResponse
    from app.schemas.market import MarketDataProvenance, MarketDataMode
    from app.schemas.strategy import StrategyEvaluationContext
    from app.schemas.types import Timeframe
    from app.services.evaluation_response import analysis_response, signal_response
    from tests.integration.test_deterministic_api import (
        BULLISH_PRICES, LEGACY_CONFIG_PATH, candles_from, mirrored_prices,
    )
    prices = mirrored_prices() if case == 'short' else BULLISH_PRICES
    candles = candles_from(prices[:2] if case == 'no_trade' else prices)
    cutoff = candles[-1].timestamp + timedelta(minutes=1)
    context = StrategyEvaluationContext(symbol='BTCUSDT', as_of=cutoff,
        candles_by_timeframe={Timeframe.ONE_MINUTE: candles})
    provenance = MarketDataProvenance(provider='explicit_legacy_test_fixture', data_mode=MarketDataMode.SERVER_PROVIDER,
        symbol='BTCUSDT', timeframe=Timeframe.ONE_MINUTE, first_candle_at=candles[0].timestamp,
        last_candle_at=candles[-1].timestamp, data_cutoff_at=cutoff,
        expected_latest_closed_candle_at=cutoff, retrieved_at=cutoff,
        requested_candles=len(candles), received_candles=len(candles), lag_seconds=0)
    engine = ConcreteDeterministicStrategyEngine(load_strategy_config(LEGACY_CONFIG_PATH))
    result = engine.evaluate(context)
    project = signal_response if response_kind == 'signal' else analysis_response
    expected = project(provenance, result)
    body = asyncio.run(IsolatedEvaluationRunner().response(engine, context, provenance, Timeframe.ONE_MINUTE, response_kind))
    schema = SignalEvaluationResponse if response_kind == 'signal' else AnalysisResult
    assert schema.model_validate_json(body).model_dump(mode='json') == expected.model_dump(mode='json')
    assert json.loads(body) == expected.model_dump(mode='json')
    assert body == expected.model_dump_json().encode('utf-8')
