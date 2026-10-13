"""Summarize saved diagnostics only; never imports or executes strategy logic."""
from __future__ import annotations
import csv
from hashlib import sha256
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent

def load(name):
    return json.loads((OUT / name).read_text(encoding='utf-8'))

def dump(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False)+'\n', encoding='utf-8')

def csv_write(name, rows):
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with (OUT / name).open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

def main():
    regions = [load(path.name) for path in sorted(OUT.glob('region_*.json'))]
    with (OUT / 'evaluation_timings.csv').open(encoding='utf-8') as stream:
        evals = list(csv.DictReader(stream))
    stage_rows, calls = [], []
    for region in regions:
        for row in region['stages']:
            elapsed = sum(float(item['engine_seconds']) for item in evals if int(item['milestone']) == row['milestone'] and item['mode'] == row['mode'])
            n = row['evaluations']
            stage_rows.append({key: row[key] for key in ('milestone', 'mode', 'function', 'category', 'calls', 'inclusive_seconds', 'exclusive_seconds')} | dict(evaluations=n, seconds_per_evaluation=row['inclusive_seconds']/n, engine_percent=100*row['inclusive_seconds']/elapsed))
            calls.append(dict(milestone=row['milestone'], mode=row['mode'], function=row['function'], category=row['category'], evaluations=n, calls=row['calls'], calls_per_evaluation=row['calls']/n,
                input_items_total=json.dumps(row['input_lengths'], sort_keys=True), input_items_per_call=json.dumps({key: value/row['calls'] for key, value in row['input_lengths'].items()}, sort_keys=True),
                historical_state_items_total=json.dumps(row['state_lengths'], sort_keys=True), historical_state_items_per_call=json.dumps({key: value/row['calls'] for key, value in row['state_lengths'].items()}, sort_keys=True),
                direct_sequence_return_items=row['output_items'] if row['output_items'] else None, availability='collection sizes measured only in cprofile regions; not inferred predicate visits; structured outputs are in state_cardinality.csv'))
    # Required unexercised stages are explicit, without fabricating elapsed times.
    required = ['analyze_multi_timeframe', 'calculate_signal_score', 'calculate_risk_plan', 'replay_signal_lifecycle', '_evaluate_execution']
    absent = [name for name in required if not any(row['function'].endswith('.'+name) for row in stage_rows)]
    csv_write('stage_timings.csv', stage_rows)
    csv_write('stage_call_counts.csv', calls)
    sorts = [item for region in regions for item in region['sorts']]
    csv_write('sort_timings.csv', sorts)
    profiles = sorted(int(path.stem.split('_')[1]) for path in OUT.glob('cprofile_*.json'))
    for label, milestone in [('early', profiles[0]), ('late', profiles[-1])]:
        (OUT / f'{label}_cprofile.txt').write_text(f'Milestone {milestone}; five predeclared cProfile evaluations. No replay restart.\n'+(OUT/f'cprofile_{milestone}.txt').read_text(encoding='utf-8'), encoding='utf-8')
    worker, controller = load('worker_summary.json'), load('controller_summary.json')
    dump('resource_summary.json', dict(controller=controller, worker=worker, loading=load('worker_start.json'), cpu_one_core_percent=100*worker['replay_cpu_seconds']/worker['replay_wall_seconds'],
        resource_note='Windows GetProcessMemoryInfo; worker-only process CPU. CPU/wall is one-core equivalent, not all-core percent. No peak individual stage allocation attribution.'))
    comparison = []
    early = {row['function']: row for row in stage_rows if row['milestone'] == profiles[0] and row['mode'] == 'wall'}
    for late in [row for row in stage_rows if row['milestone'] == profiles[-1] and row['mode'] == 'wall']:
        first = early.get(late['function'])
        if first:
            comparison.append(dict(function=late['function'], category=late['category'], early_ms_per_evaluation=first['seconds_per_evaluation']*1000, late_ms_per_evaluation=late['seconds_per_evaluation']*1000,
                growth_ratio=late['seconds_per_evaluation']/first['seconds_per_evaluation'] if first['seconds_per_evaluation'] else None, late_engine_percent=late['engine_percent']))
    csv_write('early_late_comparison.csv', comparison)
    # Exact list-predicate visits inferred from measured loop-helper calls and observed sorted-list sizes.
    combinations = []
    for milestone in profiles:
        region = next(item for item in regions if item['stages'][0]['milestone'] == milestone and item['stages'][0]['mode'] == 'cprofile')
        by_fn = {row['function'].split('.')[-1]: row for row in region['stages']}
        mss_sorts = [s for s in region['sorts'] if s['file'].replace('\\', '/').endswith('ict/high_probability_entry.py') and s['line'] == 442]
        mss_stable = bool(mss_sorts) and all(s['total_items'] == s['calls']*s['max_items'] for s in mss_sorts)
        mss_n = mss_sorts[0]['max_items'] if mss_sorts else None
        sweep_n = by_fn.get('_direction_from_sweep', {}).get('calls', 0)
        matching_n = by_fn.get('_desired_structure_direction', {}).get('calls', 0)
        legs_n = by_fn.get('_desired_displacement_direction', {}).get('calls', 0)
        min_mss = mss_sorts[0]['total_items']-(mss_sorts[0]['calls']-1)*mss_n if mss_sorts else None
        combinations.append(dict(milestone=milestone, evaluations=region['evaluations'], sweep_loop_iterations=sweep_n,
            matching_mss_list_builds=matching_n, mss_collection_size=mss_n, mss_size_stable_in_region=mss_stable,
            matching_mss_predicate_visits=matching_n*mss_n if mss_stable else None,
            matching_mss_predicate_visits_lower_bound=matching_n*min_mss if min_mss is not None else None,
            matching_mss_predicate_visits_upper_bound=matching_n*mss_n if mss_n is not None else None,
            matching_displacement_predicate_visits=legs_n,
            fvg_selection_calls=by_fn.get('_select_fvg', {}).get('calls', 0),
            ob_selection_calls=by_fn.get('_select_order_block', {}).get('calls', 0),
            caveat='MSS visits exact only if sorted MSS size is stable; leg helper is called once per leg predicate; short-circuit next() generator visits not counted. No setup/decision outcomes exported.'))
    dump('ict_match_work.json', combinations)
    # Measured function attribution, not an invented standalone implementation.
    dump('hot_path_inventory.json', dict(call_path=['run_backtest_incremental -> run_backtest(_optimized=True)', '_IndexedCandleSeries.closed -> StrategyEvaluationContext', 'Observer.evaluate -> IncrementalDeterministicStrategyEngine (inherits ConcreteDeterministicStrategyEngine.evaluate)', 'P3 incremental stage seams -> reference ICT -> unchanged gated MTF/score/risk', 'shared runner validation/lifecycle/execution, if reached'],
        stages=stage_rows, unexercised_stages=absent, note='Stage inclusive values nest state/helper timings; do not sum across categories. Root engine-stage percentages use light wall-only region denominators. Runner stages are outside engine denominator.', early_late=comparison))
    static = load('static_operation_inventory.json')
    dump('history_scan_inventory.json', dict(static_iteration_sites=[row for row in static if row['kind']=='iteration'], measured_state_file='state_cardinality.csv', measured_input_lengths_file='stage_call_counts.csv', measured_ict_work=combinations,
        caution='Static sites include fallback/reference/diagnostic code. Only sites on measured call paths are runtime claims; source-confirmed scan length is not a measured short-circuit predicate count. See report for active/archive split.'))
    profile_details = {}
    for milestone in profiles:
        records = load(f'cprofile_{milestone}.json')
        profile_details[milestone] = dict(
            validation=[row for row in records if any(s in row['function'] for s in ('validate', 'normalize_utc'))],
            copying_serialization=[row for row in records if any(s in row['function'] for s in ('model_dump', 'model_validate', 'deepcopy', 'DataFrame', 'to_python', 'to_json', 'snapshot_at', 'sort'))])
    dump('copy_sort_validation_inventory.json', dict(static_sites=[row for row in static if row['kind']!='iteration'], measured_sorts=sorts, measured_profiles=profile_details,
        caveat='Built-in list/tuple constructors and slice copies can be charged to caller self time; no invented standalone duration. Cumulative validator durations overlap parent stages/core validators.'))
    dump('diagnostic_summary.json', dict(milestones=profiles, unexercised_stages=absent, early_late=comparison, ict_work=combinations,
        root_late_ranking=sorted([row for row in comparison if row['category']=='engine_stage'], key=lambda row: row['late_ms_per_evaluation'], reverse=True)))

def manifest():
    dump('artifact_manifest.json', dict(note='Excludes this manifest and generated __pycache__; all artifact files are P4 diagnosis, not research output.', files={path.relative_to(OUT).as_posix(): dict(sha256=sha256(path.read_bytes()).hexdigest(), bytes=path.stat().st_size) for path in sorted(OUT.rglob('*')) if path.is_file() and path.name!='artifact_manifest.json' and '__pycache__' not in path.parts}))

if __name__ == '__main__':
    import sys
    manifest() if len(sys.argv)>1 and sys.argv[1]=='manifest' else main()
