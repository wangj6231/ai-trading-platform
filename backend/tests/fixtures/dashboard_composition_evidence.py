"""Generated F4.1 verification summaries; never a trusted runtime source."""
from dataclasses import asdict
from hashlib import sha256
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET

from app.core.algorithm_identity import build_algorithm_identity
from app.core.strategy_config import load_strategy_config
from app.core.strategy_identity import strategy_config_hash
from tests.fixtures.dashboard_composition_profile import OUTPUT
from tests.fixtures.journal_readmodel_profile import ROOT, protected


def run():
    before = json.loads((OUTPUT / 'before.json').read_text(encoding='utf8'))
    after = json.loads((OUTPUT / 'after_final.json').read_text(encoding='utf8'))
    assert after.get('completed'), 'incomplete measurement is not a complete profile'
    comparisons = []
    for old, new in zip(before['shapes'], after['shapes'], strict=True):
        assert (old['closed_trades'], old['fixture_dump_sha256'], old['cutoff']) == (
            new['closed_trades'], new['fixture_dump_sha256'], new['cutoff'])
        for name, sample in old['reads'].items():
            current = new['reads'][name]
            assert sample['result_hash'] == current['result_hash'], (old['closed_trades'], name)
            comparisons.append(dict(closed_trades=old['closed_trades'], seam=name,
                response_hash_equal=True, before_sql=sample['sql_count'], after_sql=current['sql_count'],
                before_wall=sample['wall_seconds'], after_wall=current['wall_seconds'],
                before_returned_rows=sample['cursor_returned_rows'], after_returned_rows=current['cursor_returned_rows'],
                before_allocated_peak=sample['python_traced_peak_bytes'], after_allocated_peak=current['python_traced_peak_bytes']))
    (OUTPUT / 'comparison.json').write_text(json.dumps(comparisons, indent=2), encoding='utf8')
    previous = json.loads((OUTPUT / 'protected_before.json').read_text(encoding='utf8'))
    current = protected()
    changed = sorted(k for k in previous.keys() | current.keys() if previous.get(k) != current.get(k))
    allowed = ('backend/app/journal/', 'backend/app/paper_http/service.py',
        'backend/app/execution/trade_projection.py', 'backend/migrations/versions/20261011_0014_')
    assert all(k.startswith(allowed) for k in changed), changed
    identity = dict(config_hash=strategy_config_hash(load_strategy_config()), algorithm=asdict(build_algorithm_identity()))
    assert identity['config_hash'] == before['config_hash']
    assert identity['algorithm']['algorithm_build_hash'] == before['algorithm_identity']['algorithm_build_hash']
    golden = ROOT / 'experiments/execution_gateway_hotpath_v1/golden_before.json'
    assert sha256(golden.read_bytes()).hexdigest() == '6e3dcb0c10d884248e7b473d60de7fc72e62683b3d0a40132175a296599ecd69'
    (OUTPUT / 'protected_final.json').write_text(json.dumps(dict(identity=identity, changed=changed,
        files=current, financial_golden_unchanged=True), indent=2, sort_keys=True), encoding='utf8')
    suites = ('full_non_postgresql.xml', 'full_postgresql.xml')
    if all((OUTPUT / name).exists() for name in suites):
        cases = {}
        for name in suites:
            for case in ET.parse(OUTPUT / name).findall('.//testcase'):
                key = case.attrib.get('classname', '') + '::' + case.attrib.get('name', '')
                assert key not in cases, 'overlapping partition is not counted twice'
                cases[key] = case
        overrides = OUTPUT / 'final_affected_seams.xml'
        if overrides.exists():
            for case in ET.parse(overrides).findall('.//testcase'):
                key = case.attrib.get('classname', '') + '::' + case.attrib.get('name', '')
                cases[key] = case  # latest affected-seam result, never double counted
        def collection(marker=None):
            command = [sys.executable, '-m', 'pytest', '--collect-only', '-q']
            if marker:
                command += ['-m', marker]
            result = subprocess.run(command, capture_output=True, text=True, encoding='utf8', check=True,
                env={**os.environ, 'PYTHONIOENCODING': 'utf8'})
            nodes = [line for line in result.stdout.splitlines() if line.startswith('tests/') and '::' in line]
            return {path.replace('/', '.').removesuffix('.py') + '::' + name
                    for path, name in (node.split('::', 1) for node in nodes)}
        expected, pg = collection(), collection('postgresql')
        counts = dict(expected=len(expected), executed=len(cases),
            missing=sorted(expected - cases.keys()), unexpected=sorted(cases.keys() - expected),
            passed=sum(not any(c.find(t) is not None for t in ('failure', 'error', 'skipped')) for c in cases.values()),
            failed=sum(c.find('failure') is not None for c in cases.values()),
            errors=sum(c.find('error') is not None for c in cases.values()),
            skipped=sum(c.find('skipped') is not None for c in cases.values()),
            postgresql_expected=len(pg), postgresql_executed=len(pg & cases.keys()),
            postgresql_passed=sum(not any(cases[k].find(t) is not None for t in ('failure', 'error', 'skipped'))
                for k in pg & cases.keys()), partition_policy='two disjoint complete collections plus latest affected-seam replay; unique nodes, no historical counts',
            superseded_partition_failures=sum(len(ET.parse(OUTPUT/name).findall('.//failure')) for name in suites),
            final_affected_seam_replay=overrides.exists())
        (OUTPUT / 'verification_counts.json').write_text(json.dumps(counts, indent=2), encoding='utf8')
        assert not any(counts[k] for k in ('missing', 'unexpected', 'failed', 'errors', 'skipped')), counts
        assert counts['passed'] == counts['expected']
        assert counts['postgresql_passed'] == counts['postgresql_expected']
    (OUTPUT / 'artifact_manifest.json').write_text(json.dumps({p.name: sha256(p.read_bytes()).hexdigest()
        for p in OUTPUT.iterdir() if p.is_file() and p.name != 'artifact_manifest.json'},
        indent=2, sort_keys=True), encoding='utf8')
    print(json.dumps(dict(profile_response_hashes_equal=len(comparisons), changed=changed, identity=identity)))


if __name__ == '__main__':
    run()
