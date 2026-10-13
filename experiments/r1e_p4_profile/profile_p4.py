"""P4 external diagnosis only. Never writes production or previous experiments.

One continuous, frozen Q1/P3/shared-runner stream. No strategy result is exported.
Overall execution cap 1200 s; replay soft stop 1080 s, worker kill at 1110 s.
At M-9..M-5 use light stage timers; M-4..M use cProfile plus detailed probes.
"""
from __future__ import annotations

import ast
import builtins
import cProfile
import csv
import ctypes
from datetime import UTC, datetime
from functools import wraps
from hashlib import sha256
import inspect
import io
import json
import os
from pathlib import Path
import platform
import pstats
import subprocess
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'backend'))
from app.backtesting.identity import build_canonical_dataset_identity
from app.backtesting import runner
from app.core.algorithm_identity import build_algorithm_identity
from app.core.strategy_config import load_strategy_config
from app.core.strategy_identity import build_strategy_identity
from app.engines import incremental_strategy_engine as inc
from app.engines import optimized_strategy_engine as opt
from app.engines import strategy_engine as base
from app.engines.ict import high_probability_entry as ict
from app.schemas.backtest import BacktestConfig, HistoricalCandleSeries, HistoricalOHLCInput
from app.schemas.candle import Candle
from app.schemas.types import MarketSymbol, Timeframe

Q1 = ROOT / 'experiments/baseline/43bcadf425c161d4de8a56db6b77876208469720163bcf75adf01a3825a54849/canonical_candles.json'
MILESTONES = (1000, 2000, 5000, 7500, 10000, 20000)
EXPECTED = dict(strategy_version='deterministic-smc-ict-v1',
    config_hash='2a4abfbfd2ec5c15754dd9d2f9a12a9874df263bc1f64db668d56db9783394ad',
    source_content_hash='8e948ad6a98e81d80caa68bbf01226edfec2af42044761618dd9785b41bbce41',
    algorithm_build_hash='b36638c2e9e911e39233c3db3ba026ad9fdf66287c7ac59d98157d2d41316523',
    dataset_hash='af067e69968aa78db843f0a489d35fa1fd7dccd70016782784402bb53d296618')
TEST_ARGS = ['-q', 'tests/integration/test_p3_incremental_equivalence.py', '-k',
    'matches_reference_at_every_transition_fixture_prefix or prefix_replay_is_invariant or runner_uses_shared_lifecycle or invalid_inputs_fail_closed']

def utc():
    return datetime.now(UTC).isoformat()

def dump(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n', encoding='utf-8')

def write_csv(name, rows):
    if not rows:
        (OUT / name).write_text('no_observations\n', encoding='utf-8')
        return
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with (OUT / name).open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

def memory():
    class Counters(ctypes.Structure):
        _fields_ = [('cb', ctypes.c_ulong), ('faults', ctypes.c_ulong)] + [(key, ctypes.c_size_t) for key in ('peak', 'working', 'a', 'b', 'c', 'd', 'e', 'f')]
    data = Counters()
    data.cb = ctypes.sizeof(data)
    ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.c_void_p(-1), ctypes.byref(data), data.cb)
    return dict(working_set_bytes=data.working, peak_working_set_bytes=data.peak)

def frozen(dataset_hash):
    identity = build_strategy_identity(load_strategy_config()).model_dump(mode='json')
    identity.update(source_content_hash=build_algorithm_identity().source_content_hash, dataset_hash=dataset_hash)
    assert all(identity.get(key) == value for key, value in EXPECTED.items()), identity
    excluded = {'.git', '.venv', 'node_modules', '__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache', '.next', 'coverage', 'htmlcov', 'test-results', 'playwright-report', 'r1e_p4_profile'}
    extensions = {'.py', '.md', '.json', '.yaml', '.yml', '.toml', '.ts', '.tsx', '.js', '.mjs', '.css', '.ini', '.sql', '.ps1', '.txt', '.csv', '.zip', '.pdf', '.lock'}
    hashes = {}
    for folder, dirs, files in os.walk(ROOT):
        dirs[:] = [name for name in dirs if name not in excluded]
        for name in files:
            path = Path(folder) / name
            if path.suffix.lower() in extensions or name in {'.env.example', 'Dockerfile', '.gitignore'}:
                hashes[path.relative_to(ROOT).as_posix()] = sha256(path.read_bytes()).hexdigest()
    return dict(recorded_at=utc(), identity=identity, q1_file_sha256=sha256(Q1.read_bytes()).hexdigest(), protected_files=hashes,
        protected_policy='Authored extensions + prior experiment/data artifacts; excludes generated caches, environments, build outputs and this P4 directory.')

def tests(label, timeout):
    start = time.perf_counter()
    result = subprocess.run([sys.executable, '-m', 'pytest', *TEST_ARGS], cwd=ROOT / 'backend', capture_output=True, text=True, encoding='utf-8', timeout=timeout)
    (OUT / f'{label}_regression.txt').write_text(result.stdout + result.stderr, encoding='utf-8')
    if result.returncode:
        raise RuntimeError(f'{label} regression failed')
    guard = subprocess.run([sys.executable, str(Path(__file__)), 'instrumented_guard'], cwd=ROOT, capture_output=True, text=True, encoding='utf-8', timeout=30)
    (OUT / f'{label}_instrumented_guard.txt').write_text(guard.stdout + guard.stderr, encoding='utf-8')
    if guard.returncode:
        raise RuntimeError(f'{label} instrumented guard failed')
    return dict(returncode=result.returncode, instrumented_guard_returncode=guard.returncode, wall_seconds=time.perf_counter()-start, command=[sys.executable, '-m', 'pytest', *TEST_ARGS])

class StopMeasurement(BaseException):
    pass

class Probes:
    def __init__(self, milestone, mode):
        self.milestone, self.mode = milestone, mode
        self.rows, self.sorts, self.patches, self.stack = {}, {}, [], []
        self.profile = cProfile.Profile() if mode == 'cprofile' else None
        self.evaluations = 0

    def wrap(self, owner, name, category, detail=False):
        if not hasattr(owner, name) or (detail and self.mode != 'cprofile'):
            return
        original = getattr(owner, name)
        label = f'{original.__module__}.{original.__qualname__}'
        signature = inspect.signature(original)
        @wraps(original)
        def measured(*args, **kwargs):
            key = (label, category)
            row = self.rows.setdefault(key, dict(milestone=self.milestone, mode=self.mode, function=label, category=category, calls=0, inclusive_seconds=0., exclusive_seconds=0., input_lengths={}, state_lengths={}, output_items=0))
            row['calls'] += 1
            if self.mode == 'cprofile':
                bound = signature.bind_partial(*args, **kwargs).arguments
                for key_arg, value in bound.items():
                    if isinstance(value, (tuple, list, dict, set)):
                        row['input_lengths'][key_arg] = row['input_lengths'].get(key_arg, 0) + len(value)
                obj = args[0] if args else None
                for attr in ('candles', 'confirmed', 'pending_indices', 'zones', 'pools', 'events', 'history', 'source_structure', 'order_blocks', 'structure_events'):
                    value = getattr(obj, attr, None)
                    if isinstance(value, (tuple, list, dict, set)):
                        row['state_lengths'][attr] = row['state_lengths'].get(attr, 0) + len(value)
            self.stack.append(0.)
            start = time.perf_counter()
            try:
                result = original(*args, **kwargs)
                if isinstance(result, (tuple, list, dict)):
                    row['output_items'] += len(result)
                return result
            finally:
                elapsed = time.perf_counter() - start
                nested = self.stack.pop()
                row['inclusive_seconds'] += elapsed
                row['exclusive_seconds'] += elapsed - nested
                if self.stack:
                    self.stack[-1] += elapsed
        item = patch.object(owner, name, measured)
        item.start()
        self.patches.append(item)

    def start(self):
        for name in ('_build_candles_by_target', '_analyze_market_structure', '_calculate_indicators', '_analyze_fvg', '_analyze_liquidity', '_analyze_displacement', '_analyze_order_blocks', '_detect_entry_setups'):
            self.wrap(inc.IncrementalDeterministicStrategyEngine, name, 'engine_stage')
        for name in ('analyze_multi_timeframe', 'calculate_signal_score', 'calculate_risk_plan', '_has_source_gap'):
            self.wrap(base, name, 'engine_stage')
        for name in ('_validate_strategy_output', 'replay_signal_lifecycle', '_evaluate_execution'):
            self.wrap(runner, name, 'runner_stage')
        self.wrap(runner._IndexedCandleSeries, 'closed', 'runner_stage')
        for cls in (inc._IndicatorState, inc._StructureState, inc._FVGState, inc._LiquidityState, inc._DisplacementState, inc._OrderBlockIncrementalState, opt.IncrementalResamplingState):
            for name in ('append', 'result', 'snapshot', '_append_structure_event', '_append_zone'):
                self.wrap(cls, name, 'state_substage')
        for name in ('_prefix_ok', '_pool_to_schema', '_fvg_to_schema', '_update_zone', '_process_interaction', '_classify_trend', '_latest_unbroken_swing', '_to_order_block_schema'):
            self.wrap(inc, name, 'detail', True)
        for name in ('_validate_inputs', '_direction_from_sweep', '_desired_structure_direction', '_desired_displacement_direction', '_select_fvg', '_select_order_block', '_fvg_state_at', '_fvg_terminal_at', '_order_block_state_at'):
            self.wrap(ict, name, 'detail', True)
        if self.profile:
            original_sorted = builtins.sorted
            def observed_sorted(*args, **kwargs):
                frame = sys._getframe(1)
                filename = frame.f_code.co_filename
                if str(ROOT / 'backend' / 'app') not in filename:
                    return original_sorted(*args, **kwargs)
                key = (str(Path(filename).relative_to(ROOT)), frame.f_lineno, frame.f_code.co_name)
                start = time.perf_counter()
                result = original_sorted(*args, **kwargs)
                elapsed = time.perf_counter()-start
                row = self.sorts.setdefault(key, dict(milestone=self.milestone, file=key[0], line=key[1], function=key[2], calls=0, total_items=0, max_items=0, seconds=0.))
                row['calls'] += 1
                row['total_items'] += len(result)
                row['max_items'] = max(row['max_items'], len(result))
                row['seconds'] += elapsed
                return result
            item = patch.object(builtins, 'sorted', observed_sorted)
            item.start()
            self.patches.append(item)
            self.profile.enable()

    def stop(self):
        if self.profile:
            self.profile.disable()
        for item in reversed(self.patches):
            item.stop()
        self.patches.clear()

    def save(self):
        rows = []
        for row in self.rows.values():
            row = dict(row, evaluations=self.evaluations)
            # Output setup counts/decisions are not diagnostic exports.
            if '_detect_entry_setups' in row['function']:
                row['output_items'] = None
            rows.append(row)
        dump(f'region_{self.milestone}_{self.mode}.json', dict(evaluations=self.evaluations, stages=rows, sorts=list(self.sorts.values())))
        if self.profile:
            stream = io.StringIO()
            stats = pstats.Stats(self.profile, stream=stream)
            # Omit direct decision/result constructor counters; no market result export.
            stats.stats = {key: value for key, value in stats.stats.items() if key[2] not in {'_no_trade', '_candidate', '_setup'}}
            records = [dict(file=key[0], line=key[1], function=key[2], primitive_calls=value[0], calls=value[1], self_seconds=value[2], cumulative_seconds=value[3]) for key, value in stats.stats.items()]
            dump(f'cprofile_{self.milestone}.json', records)
            for order in ('cumulative', 'tottime', 'calls'):
                stream.write(f'\nTOP 45: {order}; diagnostic regions only; decision constructors omitted\n')
                stats.sort_stats(order).print_stats(45)
            (OUT / f'cprofile_{self.milestone}.txt').write_text(stream.getvalue(), encoding='utf-8')

def cardinality(engine, count):
    rows = []
    for attr in ('_p3_structures', '_p3_indicators', '_p3_liquidity', '_p3_fvgs', '_p3_order_blocks', '_p3_displacement'):
        for (_, timeframe), state in getattr(engine, attr).items():
            row = dict(milestone=count, state=type(state).__name__, timeframe=timeframe.value, candles=len(state.candles))
            for name in ('confirmed', 'candidates', 'pending_indices', 'events', 'interactions', 'macd_points', 'atr_points', 'structure_events', 'legs_by_event', 'evaluations_by_event'):
                if hasattr(state, name):
                    row[name] = len(getattr(state, name))
            if hasattr(state, 'pools'):
                row.update(pools_total=len(state.pools), pools_terminal=sum(p.state.value in {'TAKEN', 'EXPIRED'} for p in state.pools), pool_history_entries=sum(len(p.history) for p in state.pools), pool_members=sum(len(p.source_structure) for p in state.pools))
                row['pools_active'] = row['pools_total'] - row['pools_terminal']
            if attr == '_p3_fvgs':
                row.update(zones_total=len(state.zones), zones_terminal=sum(z.lifecycle_state.value in {'FILLED', 'INVERTED', 'INVALIDATED', 'EXPIRED'} for z in state.zones))
                row['zones_active'] = row['zones_total'] - row['zones_terminal']
            if hasattr(state, 'order_blocks'):
                row['ob_total'] = len(state.order_blocks)
                for status in ('CANDIDATE', 'VALIDATED', 'MITIGATED', 'INVALIDATED', 'EXPIRED'):
                    row['ob_' + status.lower()] = sum(z.status.value == status for z in state.order_blocks)
            rows.append(row)
    return rows

class Observer:
    def __init__(self, engine, deadline):
        self.engine, self.deadline = engine, deadline
        self.strategy_config, self.strategy_identity = engine.strategy_config, engine.strategy_identity
        self.completed = 0
        self.start = time.perf_counter()
        self.cpu_start = time.process_time()
        self.engine_seconds = 0.
        self.regions, self.cards, self.samples, self.eval_rows = [], [], [], []
        self.probe = None

    def evaluate(self, context):
        if time.perf_counter() >= self.deadline:
            raise StopMeasurement()
        index = self.completed + 1
        for milestone in MILESTONES:
            if index in (milestone-9, milestone-4):
                self.probe = Probes(milestone, 'wall' if index == milestone-9 else 'cprofile')
                self.probe.start()
        started = time.perf_counter()
        result = self.engine.evaluate(context)
        duration = time.perf_counter()-started
        self.engine_seconds += duration
        self.completed = index
        if self.probe:
            self.probe.evaluations += 1
            self.eval_rows.append(dict(milestone=self.probe.milestone, mode=self.probe.mode, evaluation=index, engine_seconds=duration))
            if index in (self.probe.milestone-5, self.probe.milestone):
                self.probe.stop()
                self.regions.append(self.probe)
                self.probe = None
        if index in MILESTONES:
            self.cards.extend(cardinality(self.engine, index))
        if index % 100 == 0:
            sample = dict(completed=index, elapsed_seconds=time.perf_counter()-self.start, cpu_seconds=time.process_time()-self.cpu_start, **memory())
            self.samples.append(sample)
            dump('progress.json', sample)
        return result

    def finish(self, status):
        if self.probe:
            self.probe.stop()
            self.regions.append(self.probe)
            self.probe = None
        replay_end = time.perf_counter()
        replay_cpu = time.process_time()-self.cpu_start
        start_save = time.perf_counter()
        for probe in self.regions:
            probe.save()
        write_csv('evaluation_timings.csv', self.eval_rows)
        write_csv('state_cardinality.csv', self.cards)
        dump('worker_summary.json', dict(status=status, completed_evaluations=self.completed, total_expected_evaluations=129600, replay_wall_seconds=replay_end-self.start, replay_cpu_seconds=replay_cpu, engine_seconds=self.engine_seconds, runner_and_observer_residual_seconds=replay_end-self.start-self.engine_seconds, artifact_serialization_seconds=time.perf_counter()-start_save, resources=self.samples, final_memory=memory(), ended_at=utc()))

def worker(deadline):
    load_start = time.perf_counter()
    candles = tuple(Candle.model_validate(row) for row in json.loads(Q1.read_text(encoding='utf-8')))
    data = HistoricalOHLCInput(series=(HistoricalCandleSeries(symbol=MarketSymbol.BTCUSDT, timeframe=Timeframe.ONE_MINUTE, candles=candles),))
    load_elapsed = time.perf_counter()-load_start
    observed = Observer(inc.IncrementalDeterministicStrategyEngine(load_strategy_config()), deadline)
    dump('worker_start.json', dict(started_at=utc(), loading_validation_seconds=load_elapsed, memory=memory()))
    status = 'COMPLETE_DIAGNOSTIC_ONLY'
    try:
        result = runner.run_backtest_incremental(data, observed, BacktestConfig(evaluation_timeframe=Timeframe.ONE_MINUTE, required_timeframes=(Timeframe.ONE_MINUTE,)))
        del result
    except StopMeasurement:
        status = 'CLEAN_SOFT_CAP'
    except BaseException:
        observed.finish('FAILED_DIAGNOSTIC')
        raise
    observed.finish(status)

def inventory():
    paths = [Path(inc.__file__), Path(opt.__file__), Path(base.__file__), Path(ict.__file__), Path(runner.__file__), ROOT / 'backend/app/engines/structure/liquidity.py', ROOT / 'backend/app/engines/structure/primitives.py', ROOT / 'backend/app/engines/smc/fvg.py', ROOT / 'backend/app/engines/smc/order_blocks.py']
    records = []
    for path in paths:
        if not path.exists():
            continue
        source = path.read_text(encoding='utf-8')
        tree = ast.parse(source)
        for node in ast.walk(tree):
            kind = None
            if isinstance(node, (ast.For, ast.ListComp, ast.DictComp, ast.SetComp, ast.GeneratorExp)):
                kind = 'iteration'
            elif isinstance(node, ast.Call):
                call = ast.unparse(node.func)
                if call in {'sorted', 'list', 'tuple', 'deepcopy'} or any(call.endswith('.'+suffix) for suffix in ('sort', 'model_dump', 'model_validate', 'DataFrame', 'snapshot_at')):
                    kind = 'copy_sort_validation'
            elif isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Slice):
                kind = 'slice'
            if kind:
                enclosing = [fn for fn in ast.walk(tree) if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and fn.lineno <= node.lineno <= fn.end_lineno]
                function = max(enclosing, key=lambda fn: fn.lineno).name if enclosing else '<module>'
                snippet = ast.get_source_segment(source, node).splitlines()[0][:220]
                records.append(dict(file=path.relative_to(ROOT).as_posix(), line=node.lineno, function=function, kind=kind, source=snippet, evidence='STATIC_SITE_NOT_AUTOMATICALLY_HOT'))
    dump('static_operation_inventory.json', records)

def main():
    started = time.perf_counter()
    protocol = dict(started_at=utc(), overall_cap_seconds=1200, replay_soft_stop_seconds=1080, worker_hard_stop_seconds=1110, reserve_seconds=120, milestones=MILESTONES, regions='M-9..M-5 light wall timings; M-4..M cProfile + detail; one sequential stream; no alternate configuration', scope='DIAGNOSIS_ONLY; no strategy outcomes exported; no P5 or R1-E')
    dump('protocol.json', protocol)
    load_start = time.perf_counter()
    candles = tuple(Candle.model_validate(row) for row in json.loads(Q1.read_text(encoding='utf-8')))
    dataset = build_canonical_dataset_identity({MarketSymbol.BTCUSDT: candles}, Timeframe.ONE_MINUTE)
    dataset_hash = dataset.dataset_hash
    del candles
    before = frozen(dataset_hash)
    dump('frozen_before.json', before)
    validation_load_seconds = time.perf_counter()-load_start
    before_tests = tests('before', 60)
    process = subprocess.Popen([sys.executable, str(Path(__file__)), 'worker', str(started+1080)], cwd=ROOT, stdout=(OUT / 'worker_stdout.txt').open('w', encoding='utf-8'), stderr=(OUT / 'worker_stderr.txt').open('w', encoding='utf-8'))
    forced = False
    try:
        code = process.wait(timeout=max(1, started+1110-time.perf_counter()))
    except subprocess.TimeoutExpired:
        process.kill()
        code = process.wait(timeout=10)
        forced = True
    after_tests = tests('after', min(60, max(1, started+1175-time.perf_counter())))
    # Fresh source/config hashes plus exact dataset bytes establish unchanged canonical data.
    after = frozen(dataset_hash)
    dump('frozen_after.json', after)
    unchanged = before['identity'] == after['identity'] and before['protected_files'] == after['protected_files'] and before['q1_file_sha256'] == after['q1_file_sha256']
    compile_result = subprocess.run([sys.executable, '-m', 'compileall', '-q', 'backend/app', str(OUT)], cwd=ROOT, capture_output=True, text=True, timeout=15)
    (OUT / 'compileall.txt').write_text(compile_result.stdout + compile_result.stderr + f'\nexit_code={compile_result.returncode}\n', encoding='utf-8')
    inventory()
    dump('controller_summary.json', dict(**protocol, ended_at=utc(), wall_seconds=time.perf_counter()-started, initial_dataset_validation_and_freeze_seconds=validation_load_seconds, before_regression=before_tests, after_regression=after_tests, worker_exit_code=code, forced_stop=forced, protected_unchanged=unchanged, protected_file_count=len(before['protected_files']), compileall_exit_code=compile_result.returncode, platform=platform.platform(), python=sys.version, logical_cpus=os.cpu_count()))
    assert unchanged and code == 0 and not forced and compile_result.returncode == 0

if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'worker':
        worker(float(sys.argv[2]))
    elif len(sys.argv) > 1 and sys.argv[1] == 'instrumented_guard':
        from tests.integration.test_p3_incremental_equivalence import test_p3_matches_reference_at_every_transition_fixture_prefix, test_p3_runner_uses_shared_lifecycle_and_execution
        probe = Probes(0, 'cprofile')
        probe.start()
        try:
            test_p3_matches_reference_at_every_transition_fixture_prefix()
            test_p3_runner_uses_shared_lifecycle_and_execution()
        finally:
            probe.stop()
        print('PASS: instrumented/reference every synthetic prefix and shared runner full report equality; no results exported')
    else:
        main()
