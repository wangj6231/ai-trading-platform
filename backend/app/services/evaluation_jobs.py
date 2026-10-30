"""Bounded ephemeral jobs own work independently of status HTTP connections."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from time import monotonic
from typing import Literal
from uuid import UUID, uuid4

import anyio

from app.core.errors import AppError
from app.core.time import normalize_utc_datetime, utc_now
from app.market_data.timeframes import timeframe_bucket_start
from app.schemas.analysis import ProductionAnalysisRequest
from app.schemas.evaluation_job import (
    EvaluationDataIdentity, EvaluationFailure, EvaluationJobResponse, EvaluationStatus,
    TERMINAL_EVALUATION_STATUSES,
)
from app.schemas.strategy_identity import StrategyIdentity
from app.schemas.types import Timeframe
from app.services.strategy_evaluation import DeterministicStrategyEvaluationService, PreparedStrategyEvaluation


@dataclass
class _Job:
    evaluation_id: UUID
    request: ProductionAnalysisRequest
    timeframe: Timeframe
    cutoff: datetime
    strategy_identity: StrategyIdentity
    created_at: datetime
    status: EvaluationStatus = EvaluationStatus.PENDING
    started_at: datetime | None = None
    completed_at: datetime | None = None
    data: EvaluationDataIdentity | None = None
    failure: EvaluationFailure | None = None
    bodies: tuple[bytes, bytes] | None = None
    task: asyncio.Task | None = None
    terminal_monotonic: float | None = None


class EvaluationJobs:
    def __init__(self, evaluation: DeterministicStrategyEvaluationService, *,
        max_active: int = 2, max_jobs: int = 4, max_retained_bytes: int = 384*1024*1024,
        timeout_seconds: float = 120, retention_seconds: float = 300) -> None:
        if min(max_active, max_jobs, max_retained_bytes, timeout_seconds, retention_seconds) <= 0:
            raise ValueError('job limits must be positive')
        self._evaluation = evaluation
        self._max_active = max_active
        self._max_jobs = max_jobs
        self._max_retained_bytes = max_retained_bytes
        self._timeout_seconds = timeout_seconds
        self._retention_seconds = retention_seconds
        self._jobs: dict[UUID, _Job] = {}
        self._closed = False

    def _terminal_jobs(self):
        return sorted((job for job in self._jobs.values() if job.status in TERMINAL_EVALUATION_STATUSES),
            key=lambda job: job.terminal_monotonic or 0)

    def _expire(self) -> None:
        for job in self._terminal_jobs():
            assert job.terminal_monotonic is not None
            if monotonic()-job.terminal_monotonic >= self._retention_seconds:
                self._jobs.pop(job.evaluation_id)

    def create(self, request: ProductionAnalysisRequest, research_token: str | None = None) -> EvaluationJobResponse:
        # No provider I/O, history acquisition or strategy computation in POST.
        _, binding = self._evaluation._resolve_binding(request, research_token)
        self._expire()
        active = sum(job.status not in TERMINAL_EVALUATION_STATUSES for job in self._jobs.values())
        if self._closed or active >= self._max_active:
            raise AppError(status_code=503, code='STRATEGY_EVALUATION_BUSY', message='Evaluation capacity is busy. Retry later.')
        while len(self._jobs) >= self._max_jobs and self._terminal_jobs():
            self._jobs.pop(self._terminal_jobs()[0].evaluation_id)
        if len(self._jobs) >= self._max_jobs:
            raise AppError(status_code=503, code='STRATEGY_EVALUATION_BUSY', message='Evaluation capacity is busy. Retry later.')
        now = normalize_utc_datetime(self._evaluation._now())
        cutoff = request.cutoff or timeframe_bucket_start(now, binding.source_timeframe)
        job = _Job(uuid4(), request.model_copy(), binding.source_timeframe, cutoff,
            binding.engine.strategy_identity, utc_now())
        self._jobs[job.evaluation_id] = job
        job.task = asyncio.create_task(self._run(job, research_token))
        return self._status(job)

    async def _run(self, job: _Job, research_token: str | None) -> None:
        job.status = EvaluationStatus.RUNNING
        job.started_at = utc_now()
        def prepared(value: PreparedStrategyEvaluation):
            history = value.historical_provenance
            job.data = EvaluationDataIdentity(provenance=value.provenance,
                history_content_hash=history.content_hash if history is not None else None)
        def evaluated(identity):
            # Actual evaluated worker identity, rather than a guessed version.
            job.strategy_identity = StrategyIdentity.model_validate(identity)
        try:
            async with asyncio.timeout(self._timeout_seconds):
                bodies = await self._evaluation.complete_response(job.request, cutoff=job.cutoff,
                    prepared=prepared, evaluated=evaluated, research_token=research_token)
                size = sum(map(len, bodies))
                if size > self._max_retained_bytes:
                    raise AppError(status_code=503, code='EVALUATION_RESULT_TOO_LARGE',
                        message='The complete result exceeds available retention capacity.')
                def retained_size():
                    return sum(sum(map(len, value.bodies)) for value in self._jobs.values() if value.bodies is not None)
                while retained_size()+size > self._max_retained_bytes:
                    self._jobs.pop(self._terminal_jobs()[0].evaluation_id)
                job.bodies = bodies
                job.status = EvaluationStatus.COMPLETED
        except asyncio.CancelledError:
            job.status = EvaluationStatus.CANCELLED
        except (AppError, TimeoutError) as exc:
            job.status = EvaluationStatus.FAILED
            job.failure = EvaluationFailure(
                code=exc.code if isinstance(exc, AppError) else 'STRATEGY_EVALUATION_TIMEOUT',
                message=exc.message if isinstance(exc, AppError) else 'Evaluation exceeded its execution lifetime.')
        except Exception:
            job.status = EvaluationStatus.FAILED
            job.failure = EvaluationFailure(code='STRATEGY_EVALUATION_FAILED', message='Evaluation could not complete.')
        finally:
            # The evaluation service has already awaited owned process/cache
            # cleanup before returning or propagating cancellation.
            job.completed_at = utc_now()
            job.terminal_monotonic = monotonic()

    def _get(self, evaluation_id: UUID, research_token: str | None) -> _Job:
        self._expire()
        job = self._jobs.get(evaluation_id)
        if job is None:
            raise AppError(status_code=404, code='EVALUATION_NOT_FOUND', message='Evaluation does not exist or has expired.')
        # Research jobs retain the existing authorization on every read/cancel.
        self._evaluation._authorize_cutoff(job.request.cutoff, research_token)
        return job

    @staticmethod
    def _status(job: _Job) -> EvaluationJobResponse:
        return EvaluationJobResponse(evaluation_id=job.evaluation_id, symbol=job.request.symbol,
            canonical_timeframe=job.timeframe, cutoff=job.cutoff, strategy_identity=job.strategy_identity,
            market_data_identity=job.data, created_at=job.created_at, started_at=job.started_at,
            completed_at=job.completed_at, status=job.status,
            result_available=job.status is EvaluationStatus.COMPLETED, failure=job.failure)

    def status(self, evaluation_id: UUID, research_token: str | None = None) -> EvaluationJobResponse:
        return self._status(self._get(evaluation_id, research_token))

    def result(self, evaluation_id: UUID, kind: Literal['signal', 'analysis'], research_token: str | None = None) -> bytes:
        job = self._get(evaluation_id, research_token)
        if job.status is not EvaluationStatus.COMPLETED or job.bodies is None:
            raise AppError(status_code=409, code='EVALUATION_NOT_COMPLETED', message='A complete validated result is not available.')
        return job.bodies[0 if kind == 'signal' else 1]

    async def cancel(self, evaluation_id: UUID, research_token: str | None = None) -> EvaluationJobResponse:
        job = self._get(evaluation_id, research_token)
        if job.status not in TERMINAL_EVALUATION_STATUSES and job.task is not None:
            with anyio.CancelScope(shield=True):
                job.task.cancel()
                await asyncio.gather(job.task, return_exceptions=True)
                # A task cancelled before its first instruction has no finally.
                if job.status is EvaluationStatus.PENDING:
                    job.status = EvaluationStatus.CANCELLED
                    job.completed_at = utc_now()
                    job.terminal_monotonic = monotonic()
        return self._status(job)

    async def aclose(self) -> None:
        self._closed = True
        with anyio.CancelScope(shield=True):
            tasks = [job.task for job in self._jobs.values() if job.task is not None and not job.task.done()]
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            self._jobs.clear()
