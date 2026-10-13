"""Execution-state tests use explicit fakes; never live strategy evidence."""
import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.errors import AppError, ResearchCutoffForbiddenError
from app.schemas.analysis import ProductionAnalysisRequest
from app.schemas.market import MarketDataProvenance
from app.schemas.strategy_identity import StrategyIdentity
from app.schemas.types import Timeframe
from app.services.evaluation_jobs import EvaluationJobs

NOW = datetime(2025, 1, 1, 0, 15, tzinfo=UTC)
IDENTITY = StrategyIdentity(strategy_version='explicit_unit_fixture', config_hash='1'*64, algorithm_build_hash='2'*64)


class FakeEvaluation:
    def __init__(self, gate=None, failure=None):
        self.gate = gate or asyncio.Event()
        self.failure = failure
        self.calls = 0
        self.cleaned = 0
        self._now = lambda: NOW

    def _authorize_cutoff(self, cutoff, token):
        if cutoff is not None and token != 'explicit-unit-token':
            raise ResearchCutoffForbiddenError()

    def _resolve_binding(self, request, token):
        self._authorize_cutoff(request.cutoff, token)
        binding = SimpleNamespace(source_timeframe=Timeframe.FIFTEEN_MINUTES,
            engine=SimpleNamespace(strategy_identity=IDENTITY))
        return Timeframe.FIFTEEN_MINUTES, binding

    async def complete_response(self, request, *, cutoff, prepared, evaluated, research_token):
        self.calls += 1
        provenance = MarketDataProvenance(provider='explicit_unit_fixture', data_mode='SERVER_PROVIDER',
            symbol=request.symbol, timeframe='15m', first_candle_at=NOW-timedelta(minutes=15),
            last_candle_at=NOW-timedelta(minutes=15), data_cutoff_at=cutoff, expected_latest_closed_candle_at=cutoff,
            retrieved_at=NOW, requested_candles=1, received_candles=1, lag_seconds=0)
        prepared(SimpleNamespace(provenance=provenance,
            historical_provenance=SimpleNamespace(content_hash='3'*64)))
        try:
            await self.gate.wait()
            if self.failure is not None:
                raise self.failure
            evaluated(IDENTITY.model_dump(mode='json'))
            return b'{"explicit_fixture":"signal"}', b'{"explicit_fixture":"analysis"}'
        finally:
            self.cleaned += 1


def test_lifecycle_reads_do_not_recompute_and_completed_bytes_are_exact():
    async def exercise():
        fake = FakeEvaluation()
        jobs = EvaluationJobs(fake)
        accepted = jobs.create(ProductionAnalysisRequest(symbol='BTCUSDT'))
        assert accepted.status == 'PENDING' and not accepted.result_available
        await asyncio.sleep(0)
        running = jobs.status(accepted.evaluation_id)
        assert running.status == 'RUNNING' and running.started_at
        for _ in range(100):
            assert jobs.status(accepted.evaluation_id).status == 'RUNNING'
        assert fake.calls == 1
        with pytest.raises(AppError) as missing:
            jobs.result(accepted.evaluation_id, 'signal')
        assert missing.value.code == 'EVALUATION_NOT_COMPLETED'
        fake.gate.set()
        await jobs._jobs[accepted.evaluation_id].task
        complete = jobs.status(accepted.evaluation_id)
        assert complete.status == 'COMPLETED' and complete.result_available and complete.completed_at
        assert complete.market_data_identity.history_content_hash == '3'*64
        assert jobs.result(accepted.evaluation_id, 'signal') == b'{"explicit_fixture":"signal"}'
        assert jobs.result(accepted.evaluation_id, 'analysis') == b'{"explicit_fixture":"analysis"}'
        assert fake.calls == 1 and fake.cleaned == 1
        await jobs.aclose()
    asyncio.run(exercise())


def test_duplicate_requests_are_independent_bounded_and_cancelled_work_is_owned():
    async def exercise():
        fake = FakeEvaluation()
        jobs = EvaluationJobs(fake)
        request = ProductionAnalysisRequest(symbol='BTCUSDT')
        first, second = jobs.create(request), jobs.create(request)
        assert first.evaluation_id != second.evaluation_id  # No unproved reuse.
        with pytest.raises(AppError) as busy:
            jobs.create(request)
        assert busy.value.code == 'STRATEGY_EVALUATION_BUSY'
        await asyncio.sleep(0)
        cancelled = await jobs.cancel(first.evaluation_id)
        assert cancelled.status == 'CANCELLED' and not cancelled.result_available
        assert fake.cleaned == 1
        await jobs.cancel(second.evaluation_id)
        third = jobs.create(request)
        # Cancellation before the first instruction is terminal too.
        assert (await jobs.cancel(third.evaluation_id)).status == 'CANCELLED'
        assert jobs.status(first.evaluation_id).status == 'CANCELLED'
        await jobs.aclose()
        assert not jobs._jobs
    asyncio.run(exercise())


@pytest.mark.parametrize('failure', [AppError(status_code=502, code='EXPLICIT_PROVIDER_ERROR', message='Fixture provider error.'), RuntimeError('private exception')])
def test_failure_never_exposes_a_strategy_result(failure):
    async def exercise():
        fake = FakeEvaluation(failure=failure)
        jobs = EvaluationJobs(fake)
        first = jobs.create(ProductionAnalysisRequest(symbol='BTCUSDT'))
        fake.gate.set()
        await jobs._jobs[first.evaluation_id].task
        state = jobs.status(first.evaluation_id)
        assert state.status == 'FAILED' and state.failure and not state.result_available
        assert 'private exception' not in state.model_dump_json()
        with pytest.raises(AppError):
            jobs.result(first.evaluation_id, 'signal')
        await jobs.aclose()
    asyncio.run(exercise())


def test_timeout_is_failed_and_shutdown_cancels_all_owners():
    async def exercise():
        fake = FakeEvaluation()
        jobs = EvaluationJobs(fake, timeout_seconds=.02)
        first = jobs.create(ProductionAnalysisRequest(symbol='BTCUSDT'))
        await jobs._jobs[first.evaluation_id].task
        assert jobs.status(first.evaluation_id).status == 'FAILED'
        assert jobs.status(first.evaluation_id).failure.code == 'STRATEGY_EVALUATION_TIMEOUT'
        assert fake.cleaned == 1
        second = jobs.create(ProductionAnalysisRequest(symbol='ETHUSDT'))
        await asyncio.sleep(0)
        assert jobs.status(second.evaluation_id).status == 'RUNNING'
        await jobs.aclose()
        assert fake.cleaned == 2 and jobs._jobs == {}
        assert jobs._closed
    asyncio.run(exercise())


def test_research_authorization_is_required_on_status_results_and_cancellation():
    async def exercise():
        fake = FakeEvaluation()
        jobs = EvaluationJobs(fake)
        request = ProductionAnalysisRequest(symbol='BTCUSDT', cutoff=NOW)
        with pytest.raises(ResearchCutoffForbiddenError):
            jobs.create(request)
        first = jobs.create(request, 'explicit-unit-token')
        for operation in (lambda: jobs.status(first.evaluation_id), lambda: jobs.result(first.evaluation_id, 'analysis')):
            with pytest.raises(ResearchCutoffForbiddenError):
                operation()
        with pytest.raises(ResearchCutoffForbiddenError):
            await jobs.cancel(first.evaluation_id)
        assert (await jobs.cancel(first.evaluation_id, 'explicit-unit-token')).status == 'CANCELLED'
        with pytest.raises(AppError) as missing:
            jobs.status(uuid4())
        assert missing.value.status_code == 404
        await jobs.aclose()
    asyncio.run(exercise())


def test_terminal_retention_and_complete_bytes_are_bounded_without_truncation(monkeypatch):
    async def exercise():
        fake = FakeEvaluation()
        fake.gate.set()
        size = len(b'{"explicit_fixture":"signal"}')+len(b'{"explicit_fixture":"analysis"}')
        jobs = EvaluationJobs(fake, max_retained_bytes=size, retention_seconds=10)
        first = jobs.create(ProductionAnalysisRequest(symbol='BTCUSDT'))
        await jobs._jobs[first.evaluation_id].task
        second = jobs.create(ProductionAnalysisRequest(symbol='ETHUSDT'))
        await jobs._jobs[second.evaluation_id].task
        with pytest.raises(AppError):
            jobs.status(first.evaluation_id)
        assert jobs.result(second.evaluation_id, 'analysis') == b'{"explicit_fixture":"analysis"}'
        value = jobs._jobs[second.evaluation_id].terminal_monotonic
        monkeypatch.setattr('app.services.evaluation_jobs.monotonic', lambda: value+11)
        with pytest.raises(AppError):
            jobs.status(second.evaluation_id)
        assert not jobs._jobs
        await jobs.aclose()
    asyncio.run(exercise())
