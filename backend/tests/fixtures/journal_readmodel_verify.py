"""Generated F4 verification evidence, never a production identity source."""
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
from tests.fixtures.journal_readmodel_profile import OUTPUT, ROOT, protected


def run():
    before = json.loads((OUTPUT/'protected_before.json').read_text(encoding='utf8'))
    after = protected()
    changed = sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))
    fixed = ('frontend/', 'config/', 'rust/')
    if any(k.startswith(fixed) for k in changed):
        raise AssertionError('protected frontend/config/Rust changed')
    oracle = ROOT/'experiments/execution_gateway_hotpath_v1/golden_before.json'
    digest = sha256(oracle.read_bytes()).hexdigest()
    if digest != '6e3dcb0c10d884248e7b473d60de7fc72e62683b3d0a40132175a296599ecd69':
        raise AssertionError('sealed financial oracle changed')
    identity = dict(config_hash=strategy_config_hash(load_strategy_config()), algorithm=asdict(build_algorithm_identity()),
        changed_protected_files=changed, protected_hashes=after, financial_oracle_sha256=digest)
    if identity['config_hash'] != json.loads((OUTPUT/'before.json').read_text(encoding='utf8'))['config_hash']:
        raise AssertionError('StrategyConfig changed')
    (OUTPUT/'protected_after.json').write_text(json.dumps(identity, indent=2, sort_keys=True), encoding='utf8')
    suites = ('final_non_postgresql.xml', 'final_postgresql.xml', 'final_read_seams.xml',
        'warmup_final.xml', 'final_affected_seams.xml')
    if all((OUTPUT/name).exists() for name in suites):
        # Disjoint complete collection plus final affected-seam replays. Latest
        # seam result replaces the same node, never pads counts with duplicates.
        cases_by_key = {}
        for name in suites:
            for case in ET.parse(OUTPUT/name).findall('.//testcase'):
                cases_by_key[case.attrib.get('classname', '')+'::'+case.attrib.get('name', '')] = case
        collected = subprocess.run([sys.executable, '-m', 'pytest', '--collect-only', '-q'],
            capture_output=True, text=True, encoding='utf8',
            env={**os.environ, 'PYTHONIOENCODING': 'utf-8'}, check=True)
        all_nodes = [line.strip() for line in collected.stdout.splitlines() if line.startswith('tests/') and '::' in line]
        expected = {path.replace('/', '.').removesuffix('.py')+'::'+name for path, name in (n.split('::', 1) for n in all_nodes)}
        collected = subprocess.run([sys.executable, '-m', 'pytest', '--collect-only', '-q', '-m', 'postgresql'],
            capture_output=True, text=True, encoding='utf8',
            env={**os.environ, 'PYTHONIOENCODING': 'utf-8'}, check=True)
        nodes = [line.strip() for line in collected.stdout.splitlines() if line.startswith('tests/') and '::' in line]
        (OUTPUT/'expected_postgresql_nodes.json').write_text(json.dumps(nodes, indent=2), encoding='utf8')
        keys = {path.replace('/', '.').removesuffix('.py')+'::'+name for path, name in (n.split('::', 1) for n in nodes)}
        cases = list(cases_by_key.values())
        pg = [c for k,c in cases_by_key.items() if k in keys]
        counts = dict(backend_expected=len(expected), backend=len(cases),
            missing_nodes=sorted(expected-cases_by_key.keys()), unexpected_nodes=sorted(cases_by_key.keys()-expected),
            failed=sum(c.find('failure') is not None for c in cases), errors=sum(c.find('error') is not None for c in cases),
            skipped=sum(c.find('skipped') is not None for c in cases), postgresql_expected=len(keys), postgresql_executed=len(pg),
            postgresql_passed=sum(not any(c.find(tag) is not None for tag in ('failure','error','skipped')) for c in pg))
        (OUTPUT/'verification_counts.json').write_text(json.dumps(counts, indent=2), encoding='utf8')
    artifacts = {p.relative_to(ROOT).as_posix(): sha256(p.read_bytes()).hexdigest() for p in OUTPUT.iterdir()
                 if p.is_file() and p.name != 'artifact_manifest.json'}
    (OUTPUT/'artifact_manifest.json').write_text(json.dumps(artifacts, indent=2, sort_keys=True), encoding='utf8')


if __name__ == '__main__':
    run()
