"""One-use readiness, source guards and complete process ownership."""
import asyncio
from functools import partial
import json
import multiprocessing
from pathlib import Path

import pytest

from app.core.errors import AppError
from app.core.strategy_config import load_strategy_config
from app.services.evaluation_execution import (
    IsolatedEvaluationRunner, _runtime_source_checkpoint, evaluate_response, prepare_response_engine,
)
from tests.integration.test_deterministic_api import LEGACY_CONFIG_PATH


def checkpoint_file(path):
    return Path(path).read_text(encoding='utf-8')


def failing_checkpoint():
    raise ValueError('private initialization detail')


def config_payload():
    return load_strategy_config(LEGACY_CONFIG_PATH).model_dump(mode='json')


async def ready_again(runner):
    async with asyncio.timeout(10):
        while not runner.ready_pids:
            await asyncio.sleep(.02)


def test_one_use_worker_produces_exact_public_projection_and_is_replaced():
    from datetime import timedelta
    from app.engines.strategy_engine import ConcreteDeterministicStrategyEngine
    from app.schemas.market import MarketDataProvenance
    from app.schemas.strategy import StrategyEvaluationContext
    from app.schemas.types import Timeframe
    from app.services.evaluation_response import signal_response
    from tests.integration.test_deterministic_api import BULLISH_PRICES, candles_from

    async def exercise():
        engine = ConcreteDeterministicStrategyEngine(load_strategy_config(LEGACY_CONFIG_PATH))
        candles = candles_from(BULLISH_PRICES[:2])
        cutoff = candles[-1].timestamp+timedelta(minutes=1)
        context = StrategyEvaluationContext(symbol='BTCUSDT', as_of=cutoff,
            candles_by_timeframe={Timeframe.ONE_MINUTE: candles})
        provenance = MarketDataProvenance(provider='explicit_legacy_test_fixture', data_mode='SERVER_PROVIDER',
            symbol='BTCUSDT', timeframe='1m', first_candle_at=candles[0].timestamp,
            last_candle_at=candles[-1].timestamp, data_cutoff_at=cutoff,
            expected_latest_closed_candle_at=cutoff, retrieved_at=cutoff,
            requested_candles=len(candles), received_candles=len(candles), lag_seconds=0)
        expected = signal_response(provenance, engine.evaluate(context)).model_dump(mode='json')
        runner = IsolatedEvaluationRunner(max_workers=1)
        try:
            await runner.warm(engine.strategy_config.model_dump(mode='json'))
            initial_pid, = runner.ready_pids
            assert not runner.active_pids and len(runner._active) == 1
            body = await runner.response(engine, context, provenance, Timeframe.ONE_MINUTE, 'signal')
            assert json.loads(body) == expected
            assert initial_pid not in {child.pid for child in multiprocessing.active_children()}
            await ready_again(runner)
            assert runner.ready_pids != (initial_pid,) and not runner.active_pids
            assert len(runner._active) == 1
        finally:
            pids = set(runner.ready_pids)
            await runner.aclose()
        assert not runner._active and not runner.ready_pids
        assert not pids.intersection(child.pid for child in multiprocessing.active_children())
    asyncio.run(exercise())


@pytest.mark.parametrize('shutdown', [False, True])
def test_cancelled_preparation_reaps_claimed_worker_and_shutdown_reaps_idle_worker(shutdown):
    async def exercise():
        runner = IsolatedEvaluationRunner(max_workers=2)
        config = config_payload()
        entered, cancelled, gate = asyncio.Event(), asyncio.Event(), asyncio.Event()
        async def prepare():
            entered.set()
            try:
                await gate.wait()
                return {}
            finally:
                cancelled.set()
        task = None
        try:
            await runner.warm(config)
            initial_pids = set(runner.ready_pids)
            assert len(initial_pids) == 2
            task = asyncio.create_task(runner.run_prepared(evaluate_response, prepare,
                initializer=prepare_response_engine, initial_payload=config))
            await entered.wait()
            claimed_pid, = runner.active_pids
            assert claimed_pid in initial_pids and len(runner._active) == 2
            if shutdown:
                await runner.aclose()
            else:
                task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert cancelled.is_set() and not runner.active_pids
            assert claimed_pid not in {child.pid for child in multiprocessing.active_children()}
            if not shutdown:
                async with asyncio.timeout(10):
                    while len(runner.ready_pids) != 2:
                        await asyncio.sleep(.02)
                assert len(runner._active) == 2 and claimed_pid not in runner.ready_pids
        finally:
            await runner.aclose()
        assert not runner._active and not runner._warm_slots
    asyncio.run(exercise())


def test_source_drift_is_technical_error_before_any_evaluation(tmp_path):
    async def exercise():
        marker = tmp_path/'source-checkpoint'
        marker.write_text('original', encoding='utf-8')
        config = config_payload()
        runner = IsolatedEvaluationRunner(max_workers=1)
        try:
            await runner.warm(config, checkpoint=partial(checkpoint_file, str(marker)))
            initial_pid, = runner.ready_pids
            marker.write_text('changed', encoding='utf-8')
            async def payload():
                # The source guard must fail before this deliberately invalid
                # test payload could enter the evaluator or produce NO_TRADE.
                return {}
            with pytest.raises(AppError) as caught:
                await runner.run_prepared(evaluate_response, payload,
                    initializer=prepare_response_engine, initial_payload=config)
            assert caught.value.code == 'STRATEGY_WORKER_SOURCE_CHANGED'
            assert caught.value.status_code == 503
            assert initial_pid not in {child.pid for child in multiprocessing.active_children()}
        finally:
            await runner.aclose()
        assert not runner._active
    asyncio.run(exercise())


def test_failed_initialization_is_redacted_and_is_not_retried():
    async def exercise():
        runner = IsolatedEvaluationRunner(max_workers=1)
        try:
            with pytest.raises(AppError) as caught:
                await runner.warm(config_payload(), checkpoint=failing_checkpoint)
            assert caught.value.code == 'STRATEGY_EVALUATION_FAILED'
            assert 'private' not in str(caught.value)
            async with asyncio.timeout(10):
                while runner._active:
                    await asyncio.sleep(.02)
            await asyncio.sleep(.1)
            assert not runner._active and not runner._warm_slots
        finally:
            await runner.aclose()
    asyncio.run(exercise())


@pytest.mark.parametrize('change', ['unreferenced_dependency', 'new_module', 'missing_required'])
def test_source_checkpoint_covers_dependency_universe_and_missing_sources(tmp_path, monkeypatch, change):
    from app.core.algorithm_identity import AlgorithmSourceManifestRules
    from app.services import evaluation_execution as execution
    package = tmp_path/'backend'/'app'
    engines = package/'engines'
    engines.mkdir(parents=True)
    (engines/'strategy.py').write_text('VALUE = 1\n', encoding='utf-8')
    required = package/'identity.py'
    required.write_text('VERSION = 1\n', encoding='utf-8')
    dependency = package/'unreferenced.py'
    dependency.write_text('VALUE = 1\n', encoding='utf-8')
    monkeypatch.setattr(execution, 'REPOSITORY_ROOT', tmp_path)
    monkeypatch.setattr(execution, 'DEFAULT_ALGORITHM_SOURCE_RULES', AlgorithmSourceManifestRules(
        source_roots=('backend/app/engines',), source_files=('backend/app/identity.py',),
        dependency_package_roots=('backend/app',)))
    before = _runtime_source_checkpoint()
    if change == 'unreferenced_dependency':
        dependency.write_text('VALUE = 2\n', encoding='utf-8')
    elif change == 'new_module':
        (package/'new_dependency.py').write_text('VALUE = 1\n', encoding='utf-8')
    else:
        required.unlink()
        with pytest.raises(ValueError, match='source file is unavailable'):
            _runtime_source_checkpoint()
        return
    assert _runtime_source_checkpoint() != before
