"""Test-only profiling of the exact F1 workload; no payload/SQL parameter logs."""
import argparse
from collections import defaultdict
from contextlib import ExitStack
import cProfile
import io
import json
import os
from pathlib import Path
import pstats
from threading import Event, Thread
from time import perf_counter, process_time
import tracemalloc
from unittest.mock import patch

import psutil
from sqlalchemy import create_engine, event, text

from app.core.telemetry import query_measurement
from app.execution.gateway import ExecutionGateway
from app.execution.repository import ExecutionRepository
from app.execution.models import Account, Order, ExecutionEvent, InstrumentProfile
from app.observation.worker import ObservationWorker
from tests.fixtures.foundation_capacity import owned_database, run_workload, PROFILES

RSS_CAP = 768 * 1024 * 1024


def measure(profile, output):
    active = [False]
    stages = defaultdict(lambda: dict(calls=0, wall=0., cpu=0., self_wall=0., self_cpu=0., sql_count=0, sql_seconds=0.))
    frames = []
    sql = defaultdict(lambda: dict(calls=0, wall=0.))
    counts = defaultdict(int)
    sampled = {}
    profiles = []
    worker_started = [0.]
    process = psutil.Process()

    def enter(name):
        sample = query_measurement.get()
        frame = [name, perf_counter(), process_time(), 0., 0., sample.count if sample else 0, sample.seconds if sample else 0.]
        frames.append(frame)
        return frame

    def leave(frame):
        assert frames.pop() is frame
        wall, cpu = perf_counter() - frame[1], process_time() - frame[2]
        sample = query_measurement.get()
        stage = stages[frame[0]]
        stage['calls'] += 1
        stage['wall'] += wall
        stage['cpu'] += cpu
        stage['self_wall'] += wall - frame[3]
        stage['self_cpu'] += cpu - frame[4]
        stage['sql_count'] += sample.count - frame[5] if sample else 0
        stage['sql_seconds'] += sample.seconds - frame[6] if sample else 0
        if frames:
            frames[-1][3] += wall
            frames[-1][4] += cpu

    def wrapped(name, original):
        def call(*args, **kwargs):
            if not active[0]:
                return original(*args, **kwargs)
            if name == 'gateway.observe':
                if process.memory_info().rss > RSS_CAP:
                    raise TimeoutError('profile RSS cap')
                if perf_counter() - worker_started[0] > 1800:
                    raise TimeoutError('profile worker admission time cap')
            frame = enter(name)
            profiler = None
            allocation = False
            if name == 'gateway.observe':
                n = stages[name]['calls']
                if n in {0, PROFILES[profile][0] - 1}:
                    profiler = cProfile.Profile()
                    profiler.enable()
                if n == PROFILES[profile][0] // 2:
                    tracemalloc.start(1)
                    allocation = True
                counts['max_candles_per_observe'] = max(counts['max_candles_per_observe'], len(args[2].candles))
            try:
                result = original(*args, **kwargs)
                if isinstance(result, Account):
                    counts['peak_account_trades'] = max(counts['peak_account_trades'], len(result.trades))
                    counts['peak_account_positions'] = max(counts['peak_account_positions'], len(result.positions))
                return result
            finally:
                if profiler:
                    profiler.disable()
                    profiles.append(profiler)
                if allocation:
                    current, peak = tracemalloc.get_traced_memory()
                    sampled.update(retained_bytes=current, temporary_peak_bytes=peak, rss_bytes=process.memory_info().rss,
                        top_allocations=[dict(location=str(s.traceback[0]), bytes=s.size, count=s.count)
                                         for s in tracemalloc.take_snapshot().statistics('lineno')[:20]])
                    tracemalloc.stop()
                leave(frame)
        return call

    original_tick = ObservationWorker.tick

    async def tick(worker):
        active[0] = True
        worker_started[0] = perf_counter()
        frame = enter('worker.tick')
        try:
            await original_tick(worker)
        finally:
            leave(frame)
            active[0] = False

    with ExitStack() as stack:
        for cls, method in ((ExecutionGateway, 'observe'), (ExecutionGateway, 'get_account'),
                (ExecutionRepository, 'read_account'), (ExecutionRepository, 'lock_account'),
                (ExecutionRepository, 'parse_account'), (ExecutionRepository, 'parse_order'),
                (ExecutionRepository, 'save_account'), (ExecutionRepository, 'admit')):
            name = ('gateway.' if cls is ExecutionGateway else 'repository.') + method
            stack.enter_context(patch.object(cls, method, wrapped(name, getattr(cls, method))))
        for cls in (Account, Order, ExecutionEvent, InstrumentProfile):
            stack.enter_context(patch.object(cls, 'model_validate', staticmethod(wrapped('schema.' + cls.__name__, cls.model_validate))))
        import app.execution.repository as repository
        import app.execution.gateway as gateway
        import app.execution.adapters.paper as paper
        for module in (repository, gateway, paper):
            for name in ('document', 'content_hash', 'apply_fill'):
                if hasattr(module, name):
                    stack.enter_context(patch.object(module, name, wrapped(name, getattr(module, name))))
        stack.enter_context(patch.object(ObservationWorker, 'tick', tick))
        with owned_database(os.environ.get('TEST_POSTGRES_URL', '')) as (database, nonce):
            stack.enter_context(patch.object(database.engine.pool, 'connect', wrapped('connection.acquire', database.engine.pool.connect)))
            query_frames = {}

            @event.listens_for(database.engine, 'before_cursor_execute')
            def before(connection, cursor, statement, *_args):
                if active[0]:
                    family = next((n for n in ('execution_orders', 'execution_marks', 'execution_accounts',
                        'execution_positions', 'execution_trades', 'execution_fills', 'observation_deliveries') if n in statement), 'other')
                    operation = statement.split(None, 1)[0].upper()
                    name = f'{operation}:{family}'
                    if 'FOR UPDATE' in statement or 'FOR SHARE' in statement:
                        name += ':row_lock'
                    query_frames[id(cursor)] = (enter('db.execute'), name, perf_counter())

            @event.listens_for(database.engine, 'after_cursor_execute')
            def after(connection, cursor, *_args):
                item = query_frames.pop(id(cursor), None)
                if item:
                    frame, family, started = item
                    sql[family]['calls'] += 1
                    sql[family]['wall'] += perf_counter() - started
                    leave(frame)

            observer = create_engine(database.engine.url, pool_size=1, max_overflow=0, hide_parameters=True)
            stopped = Event()
            resources = dict(connection_peak=0, lock_wait_samples=0, active_lock_wait_peak=0,
                             rss_peak=0, samples=0, sampler_errors=0)

            def monitor():
                while not stopped.wait(.25):
                    resources['rss_peak'] = max(resources['rss_peak'], process.memory_info().rss)
                    try:
                        with observer.connect() as connection:
                            rows = connection.execute(text('SELECT wait_event_type FROM pg_stat_activity WHERE datname=:name'), {'name': nonce}).all()
                        resources['connection_peak'] = max(resources['connection_peak'], len(rows))
                        waiting = sum(r[0] == 'Lock' for r in rows)
                        resources['lock_wait_samples'] += waiting > 0
                        resources['active_lock_wait_peak'] = max(resources['active_lock_wait_peak'], waiting)
                        resources['samples'] += 1
                    except Exception:
                        resources['sampler_errors'] += 1

            thread = Thread(target=monitor, daemon=True)
            thread.start()
            try:
                report = run_workload(database, nonce, profile, wall_cap=600)
            finally:
                stopped.set()
                thread.join(timeout=5)
                observer.dispose()
        report.update(isolated_database_removed=True, gateway_stages=dict(stages), worker_sql_families=dict(sql),
                      gateway_cardinalities=dict(counts), allocation_sample=sampled, resources=resources)
    report['caps'] = dict(cooperative_workload_seconds=600, cooperative_worker_admission_seconds=1800,
                         rss_bytes=RSS_CAP, tracemalloc_sample_gateway_calls=1, cprofile_gateway_calls=2)
    report['limits'] += ' Extra sampler connection; allocation/cProfile samples perturb only declared calls; SQL/CPU overlap. Cursor timers exclude ORM hydration/commit. No pure server-CPU or allocator-time assertion.'
    output.mkdir(parents=True, exist_ok=True)
    (output / f'{profile}.json').write_text(json.dumps(report, sort_keys=True, indent=2), encoding='utf8')
    for index, profiler in enumerate(profiles):
        buffer = io.StringIO()
        stats = pstats.Stats(profiler, stream=buffer)
        stats.sort_stats('cumulative').print_stats(40)
        stats.sort_stats('tottime').print_stats(40)
        (output / f'{profile}_cprofile_{index}.txt').write_text(buffer.getvalue(), encoding='utf8')
    print(json.dumps(dict(profile=profile, wall=report['duration_seconds'], errors=report['errors'],
                         gateway=stages.get('gateway.observe'), artifact=str(output / f'{profile}.json'))))
    if report['errors'] or report['timed_out']:
        raise SystemExit(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--profile', choices=('small', 'intermediate'), required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    measure(args.profile, args.output)
