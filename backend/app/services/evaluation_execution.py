"""Bounded, cancellable process isolation for deterministic CPU work."""
from __future__ import annotations

import asyncio
import gc
from collections.abc import Awaitable, Callable
from functools import partial
from dataclasses import dataclass
from hashlib import sha256
import json
import multiprocessing
import sys
from multiprocessing.connection import Connection
from typing import Any, Literal

import anyio
from pydantic import TypeAdapter

if sys.platform == 'win32':
    from multiprocessing.connection import PipeConnection as NativeConnection
else:
    from multiprocessing.connection import Connection as NativeConnection

from app.core.errors import AppError
from app.core.algorithm_identity import (
    DEFAULT_ALGORITHM_SOURCE_RULES, SourceManifestEntry, canonical_source_manifest,
    _resolved_repository_root, _contained_path, _add_source_path, _read_normalized_source,
)
from app.core.config import REPOSITORY_ROOT
from app.core.time import evaluation_temporal_scope
from app.engines.strategy_engine import ConcreteDeterministicStrategyEngine
from app.schemas.strategy import StrategyConfig, StrategyEvaluationContext, StrategyEvaluationResult
from app.schemas.market import MarketDataProvenance
from app.schemas.analysis import AnalysisResult
from app.schemas.signal import SignalEvaluationResponse
from app.schemas.types import Timeframe
from app.services.evaluation_response import analysis_response, signal_response, validate_engine_result


_signal_json = TypeAdapter(SignalEvaluationResponse)
_analysis_json = TypeAdapter(AnalysisResult)


def serialize_response(response: SignalEvaluationResponse | AnalysisResult) -> bytes:
    # Both public DTOs have already run their original validators. Use their
    # original complete serializers directly, without a full UTF-8 roundtrip.
    if isinstance(response, SignalEvaluationResponse):
        return _signal_json.dump_json(response)
    return _analysis_json.dump_json(response)


def _run_callable(connection: Connection, function: Callable[[Any], Any], payload: Any) -> None:
    # This entrypoint owns one request in a fresh, bounded-lifetime process.
    # Keep reference counting; defer costly repeated whole-graph cycle scans
    # until after publication. The web process's collector is never changed.
    collection_enabled = gc.isenabled()
    gc.disable()
    try:
        connection.send((True, function(payload)))
    except AppError as exc:
        connection.send((False, {"status_code": exc.status_code, "code": exc.code,
            "message": exc.message, "details": exc.details}))
    except Exception:
        # Arbitrary worker exception text must not escape through the public API.
        connection.send((False, None))
    finally:
        try:
            connection.close()
        finally:
            if collection_enabled:
                gc.enable()


def evaluate_strategy(payload: dict[str, Any]) -> dict[str, Any]:
    with evaluation_temporal_scope():
        return _evaluate_strategy(payload)


def _evaluate_strategy(payload: dict[str, Any]) -> dict[str, Any]:
    config = StrategyConfig.model_validate(payload["config"])
    context = StrategyEvaluationContext.model_validate(payload["context"])
    engine = ConcreteDeterministicStrategyEngine(config)
    return engine.evaluate(context).model_dump(mode="json")


def prepare_response_engine(config_payload: dict[str, Any]) -> Callable[..., bytes | None]:
    engine = ConcreteDeterministicStrategyEngine(StrategyConfig.model_validate(config_payload))
    return partial(evaluate_response, engine=engine)


def _run_waiting(connection: Connection, function: Callable[[Any], Any],
    initializer: Callable[[Any], Callable[[Any], Any]] | None, initial_payload: Any) -> None:
    def prepared_request(_: Any) -> Any:
        prepared_function: Callable[..., Any] = initializer(initial_payload) if initializer is not None else function
        payload = connection.recv()
        if isinstance(payload, dict) and payload.get('_response_group'):
            return prepared_function(payload, connection=connection)
        return prepared_function(payload)
    _run_callable(connection, prepared_request, None)


def _runtime_source_checkpoint() -> str:
    """Guard loaded initialization with all possible local dependency sources.

    The existing identity builder still owns the actual strategy build hash.
    Unchanged complete source bytes/module paths prove its dependency closure
    cannot have changed while this one-use worker waited for its request.
    """
    root = _resolved_repository_root(REPOSITORY_ROOT)
    rules = DEFAULT_ALGORITHM_SOURCE_RULES
    paths: dict[str, Any] = {}
    for relative in (*rules.source_roots, *rules.dependency_package_roots):
        directory = _contained_path(root, relative)
        if not directory.is_dir() or directory.is_symlink():
            raise ValueError('runtime source root is unavailable')
        for path in directory.rglob('*.py'):
            _add_source_path(root, path, paths)
    for relative in rules.source_files:
        path = _contained_path(root, relative)
        if not path.is_file():
            raise ValueError('runtime source file is unavailable')
        _add_source_path(root, path, paths)
    entries = tuple(SourceManifestEntry(relative, sha256(_read_normalized_source(path, relative)).hexdigest())
        for relative, path in sorted(paths.items()))
    return sha256(canonical_source_manifest(entries)).hexdigest()


def _run_warmed(connection: Connection, config_payload: dict[str, Any], checkpoint: Callable[[], Any]) -> None:
    def prepared_request(_: Any) -> bytes | None:
        initializing_source = checkpoint()
        function = prepare_response_engine(config_payload)
        initialized_source = checkpoint()
        if initialized_source != initializing_source:
            raise AppError(status_code=503, code='STRATEGY_WORKER_SOURCE_CHANGED',
                message='Evaluation source changed during worker initialization. Retry with a fresh worker.')
        connection.send(('PREPARED', None))
        payload = connection.recv()
        if checkpoint() != initialized_source:
            raise AppError(status_code=503, code='STRATEGY_WORKER_SOURCE_CHANGED',
                message='Evaluation source changed while the worker was waiting. Retry with a fresh worker.')
        if payload.get('_response_group'):
            return function(payload, connection=connection)
        return function(payload)
    _run_callable(connection, prepared_request, None)


@dataclass(eq=False)
class _WarmSlot:
    process: Any
    parent: NativeConnection
    child: NativeConnection
    start: asyncio.Task
    ready: asyncio.Task

    @property
    def reservation(self) -> int:
        return id(self.process)


def evaluate_response(payload: dict[str, Any], *, engine=None, connection: Connection | None = None) -> bytes | None:
    with evaluation_temporal_scope():
        return _evaluate_response(payload, engine=engine, connection=connection)


def _evaluate_response(payload: dict[str, Any], *, engine=None, connection: Connection | None = None) -> bytes | None:
    config = StrategyConfig.model_validate(payload["config"])
    context = StrategyEvaluationContext.model_validate(payload["context"])
    provenance = MarketDataProvenance.model_validate(payload["provenance"])
    if engine is None:
        engine = ConcreteDeterministicStrategyEngine(config)
    elif engine.strategy_config != config:
        raise ValueError('prepared configuration does not match validated request')
    result = engine.evaluate(context)
    # Engine construction validates the complete evidence. Preserve the existing
    # service checks and public DTO validators before serializing in this worker.
    validate_engine_result(provenance, Timeframe(payload["signal_timeframe"]), result)
    if payload.get('_response_group'):
        if connection is None:
            raise ValueError('group publication requires an owned connection')
        assert result.evaluation is not None
        connection.send(('EVALUATED', result.evaluation.strategy_identity.model_dump(mode='json')))
        projections = connection.recv()
        # Publish the small signal first without delaying it behind the full
        # analysis serialization. Every caller retains its own validated data.
        for index, member in sorted(enumerate(projections), key=lambda item: item[1]['response_kind'] != 'signal'):
            member_config = StrategyConfig.model_validate(member['config'])
            member_context = StrategyEvaluationContext.model_validate(member['context'])
            member_provenance = MarketDataProvenance.model_validate(member['provenance'])
            if member_config != config or member_context != context:
                raise ValueError('group evidence differs from evaluated evidence')
            validate_engine_result(member_provenance, Timeframe(member['signal_timeframe']), result)
            body = _project_response(member['response_kind'], member_provenance, result)
            connection.send(('PROJECTED', (index, body)))
        return None
    return _project_response(payload['response_kind'], provenance, result)


def _project_response(response_kind, provenance, result) -> bytes:
    response: SignalEvaluationResponse | AnalysisResult
    if response_kind == "signal":
        response = signal_response(provenance, result)
    elif response_kind == "analysis":
        response = analysis_response(provenance, result)
    else:
        raise ValueError("unknown response projection")
    return serialize_response(response)


class IsolatedEvaluationRunner:
    def __init__(self, *, max_workers: int = 2, timeout_seconds: float = 120) -> None:
        if max_workers < 1 or timeout_seconds <= 0:
            raise ValueError("execution capacity and timeout must be positive")
        self._max_workers = max_workers
        self._timeout_seconds = timeout_seconds
        self._active: dict[int, Any] = {}
        self._context = multiprocessing.get_context("spawn")
        self._warm_slots: list[_WarmSlot] = []
        self._warm_config: dict[str, Any] | None = None
        self._checkpoint: Callable[[], Any] = _runtime_source_checkpoint
        self._warm_tasks: set[asyncio.Task] = set()
        self._operations: set[asyncio.Task] = set()
        self._closed = False

    @property
    def active_pids(self) -> tuple[int, ...]:
        idle = {slot.reservation for slot in self._warm_slots}
        return tuple(process.pid for key, process in self._active.items()
            if key not in idle and process.pid is not None)

    @property
    def ready_pids(self) -> tuple[int, ...]:
        return tuple(slot.process.pid for slot in self._warm_slots
            if slot.process.pid is not None and slot.ready.done() and not slot.ready.cancelled()
            and slot.ready.exception() is None and slot.ready.result()[0] == 'PREPARED')

    async def warm(self, config: dict[str, Any], *, checkpoint: Callable[[], Any] = _runtime_source_checkpoint) -> None:
        if self._closed or self._warm_config is not None:
            raise RuntimeError('worker initialization can only start once')
        self._warm_config = json.loads(json.dumps(config))
        self._checkpoint = checkpoint
        for _ in range(self._max_workers):
            self._queue_warm_slot()
        messages = await asyncio.gather(*(asyncio.shield(slot.ready) for slot in self._warm_slots))
        for tag, details in messages:
            if tag != 'PREPARED':
                if details is not None:
                    raise AppError(**details)
                raise AppError(status_code=500, code='STRATEGY_EVALUATION_FAILED', message='Worker initialization failed.')

    def _queue_warm_slot(self) -> None:
        if self._closed or self._warm_config is None or len(self._active) >= self._max_workers:
            return
        parent, child = self._context.Pipe(duplex=True)
        process = self._context.Process(target=_run_warmed,
            args=(child, self._warm_config, self._checkpoint), daemon=True)
        self._active[id(process)] = process
        start = asyncio.create_task(asyncio.to_thread(process.start))
        async def ready():
            await asyncio.shield(start)
            child.close()
            return await asyncio.to_thread(parent.recv)
        slot = _WarmSlot(process, parent, child, start, asyncio.create_task(ready()))
        self._warm_slots.append(slot)
        task = asyncio.create_task(self._watch_warm_slot(slot))
        self._warm_tasks.add(task)
        def completed(done):
            self._warm_tasks.discard(done)
            if not done.cancelled():
                done.exception()
        task.add_done_callback(completed)

    async def _watch_warm_slot(self, slot: _WarmSlot) -> None:
        try:
            message = await asyncio.shield(slot.ready)
            if message[0] == 'PREPARED':
                return
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        if slot in self._warm_slots:
            self._warm_slots.remove(slot)
            await self._dispose_warm_slot(slot)
        # Failed initialization is not retried in a CPU-consuming loop. A new
        # request can use the original cold path; startup failures stay visible.

    async def _dispose_warm_slot(self, slot: _WarmSlot) -> None:
        try:
            await slot.start
            if slot.process.is_alive():
                slot.process.terminate()
            await asyncio.to_thread(slot.process.join, 2)
            if slot.process.is_alive():
                slot.process.kill()
                await asyncio.to_thread(slot.process.join, 2)
        finally:
            slot.child.close()
            slot.parent.close()
            self._active.pop(slot.reservation, None)
            slot.process.close()
            try:
                await slot.ready
            except (EOFError, OSError, asyncio.CancelledError):
                pass

    async def aclose(self) -> None:
        self._closed = True
        with anyio.CancelScope(shield=True):
            operations = [task for task in self._operations if task is not asyncio.current_task()]
            for task in operations:
                task.cancel()
            await asyncio.gather(*operations, return_exceptions=True)
            watchers = tuple(self._warm_tasks)
            slots, self._warm_slots = self._warm_slots, []
            await asyncio.gather(*(self._dispose_warm_slot(slot) for slot in slots))
            # Closing each owned pipe resolves its ready reader. Do not cancel
            # a watcher while it is already reaping a failed initialization.
            await asyncio.gather(*watchers, return_exceptions=True)

    async def run(self, function: Callable[[Any], Any], payload: Any) -> Any:
        async def prepared_payload():
            return payload
        return await self.run_prepared(function, prepared_payload)

    async def run_prepared(self, function: Callable[[Any], Any],
        prepare: Callable[[], Awaitable[Any]], *,
        initializer: Callable[[Any], Callable[[Any], Any]] | None = None,
        initial_payload: Any = None,
        projections: Callable[[], Awaitable[Any]] | None = None,
        published: Callable[[Any], None] | None = None,
        evaluated: Callable[[Any], None] | None = None) -> Any:
        if self._closed:
            raise AppError(status_code=503, code='STRATEGY_EVALUATION_BUSY', message='Evaluation service is closing.')
        slot = None
        if initializer is prepare_response_engine and initial_payload == self._warm_config and self._warm_slots:
            slot = self._warm_slots.pop(0)
        if slot is None and len(self._active) >= self._max_workers:
            raise AppError(status_code=503, code="STRATEGY_EVALUATION_BUSY", message="Strategy evaluation capacity is busy. Retry later.")
        if slot is None:
            parent, child = self._context.Pipe(duplex=True)
            process = self._context.Process(target=_run_waiting,
                args=(child, function, initializer, initial_payload), daemon=True)
            start = asyncio.create_task(asyncio.to_thread(process.start))
        else:
            parent, child, process, start = slot.parent, slot.child, slot.process, slot.start
        reservation = id(process)
        self._active[reservation] = process
        operation = asyncio.current_task()
        assert operation is not None
        self._operations.add(operation)
        receive = None
        send = None
        try:
            # Imports/configuration can finish while the original async market
            # boundary prepares the complete validated history and cutoff.
            payload = await prepare()
            await asyncio.shield(start)
            child.close()
            if slot is not None:
                tag, details = await asyncio.shield(slot.ready)
                if tag != 'PREPARED':
                    if details is not None:
                        raise AppError(**details)
                    raise AppError(status_code=500, code='STRATEGY_EVALUATION_FAILED', message='Worker initialization failed.')
            send = asyncio.create_task(asyncio.to_thread(parent.send, payload))
            await asyncio.shield(send)
            receive = asyncio.create_task(asyncio.to_thread(parent.recv))
            deadline = asyncio.get_running_loop().time() + self._timeout_seconds
            while True:
                success, result = await asyncio.wait_for(asyncio.shield(receive),
                    max(0, deadline-asyncio.get_running_loop().time()))
                if success == 'EVALUATED' and projections is not None:
                    if evaluated is not None:
                        evaluated(result)
                    members = await projections()
                    send = asyncio.create_task(asyncio.to_thread(parent.send, members))
                    await asyncio.shield(send)
                elif success == 'PROJECTED' and published is not None:
                    published(result)
                else:
                    break
                receive = asyncio.create_task(asyncio.to_thread(parent.recv))
            if not success:
                if result is not None:
                    raise AppError(**result)
                raise AppError(status_code=500, code="STRATEGY_EVALUATION_FAILED", message="Strategy evaluation failed.")
            return result
        except TimeoutError as exc:
            raise AppError(status_code=504, code="STRATEGY_EVALUATION_TIMEOUT", message="Strategy evaluation timed out.") from exc
        except (EOFError, OSError) as exc:
            raise AppError(status_code=500, code="STRATEGY_EVALUATION_FAILED", message="Strategy evaluation worker stopped.") from exc
        finally:
            # ASGI task groups may repeatedly cancel during shutdown. Reaping is
            # owned by this request and must finish even under that cancellation.
            with anyio.CancelScope(shield=True):
                try:
                    await start
                    if process.is_alive():
                        process.terminate()
                    await asyncio.to_thread(process.join, 2)
                    if process.is_alive():
                        process.kill()
                        await asyncio.to_thread(process.join, 2)
                finally:
                    child.close()
                    parent.close()
                    self._active.pop(reservation, None)
                    process.close()
                for pending_io in (send, receive, slot.ready if slot is not None else None):
                    if pending_io is None:
                        continue
                    try:
                        await pending_io
                    except (EOFError, OSError, asyncio.CancelledError):
                        pass
                self._operations.discard(operation)
                self._queue_warm_slot()

    async def evaluate(self, engine, context: StrategyEvaluationContext) -> StrategyEvaluationResult:
        payload = {"config": engine.strategy_config.model_dump(mode="json"), "context": context.model_dump(mode="json")}
        result = await self.run(evaluate_strategy, payload)
        return await asyncio.to_thread(StrategyEvaluationResult.model_validate, result)

    async def response(self, engine, context: StrategyEvaluationContext,
        provenance: MarketDataProvenance, signal_timeframe: Timeframe,
        response_kind: Literal["signal", "analysis"]) -> bytes:
        async def prepare():
            return await self.response_payload(engine, context, provenance, signal_timeframe, response_kind)
        return await self.run_prepared(evaluate_response, prepare,
            initializer=prepare_response_engine,
            initial_payload=engine.strategy_config.model_dump(mode='json'))

    async def response_payload(self, engine, context: StrategyEvaluationContext,
        provenance: MarketDataProvenance, signal_timeframe: Timeframe,
        response_kind: Literal["signal", "analysis"]) -> dict[str, Any]:
        return await asyncio.to_thread(lambda: {
            "config": engine.strategy_config.model_dump(mode="json"),
            "context": context.model_dump(mode="json"),
            "provenance": provenance.model_dump(mode="json"),
            "signal_timeframe": signal_timeframe.value, "response_kind": response_kind})
