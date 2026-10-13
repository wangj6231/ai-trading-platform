"""F5 source freeze and actual JUnit/collection verification; no market results."""
from contextlib import redirect_stdout
from hashlib import sha256
import io
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

import pytest

ROOT = Path(__file__).resolve().parents[3]
OUTPUT = ROOT / 'experiments/product_foundation_f5'


def authored_hashes():
    from tests.fixtures.journal_readmodel_profile import protected
    return protected()


class Collection:
    def __init__(self):
        self.expected = {}

    def pytest_collection_finish(self, session):
        for item in session.items:
            module, *names = item.nodeid.split('::')
            classname = module.removesuffix('.py').replace('/', '.')
            if len(names) > 1:
                classname += '.' + '.'.join(names[:-1])
            self.expected[(classname, names[-1])] = bool(item.get_closest_marker('postgresql'))


def run():
    if sys.argv[1:] == ['freeze']:
        from app.core.strategy_config import load_strategy_config
        from app.core.strategy_identity import strategy_config_hash
        payload = {'files': authored_hashes(), 'config_hash': strategy_config_hash(load_strategy_config()),
            'golden_sha256': sha256((ROOT / 'experiments/execution_gateway_hotpath_v1/golden_before.json').read_bytes()).hexdigest()}
        path = OUTPUT / 'source_freeze.json'
        if path.exists():
            raise ValueError('refusing to overwrite final-source freeze')
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding='utf8')
        print('F5 final-source freeze recorded')
        return
    frozen = json.loads((OUTPUT / 'source_freeze.json').read_text(encoding='utf8'))
    current = authored_hashes()
    if current != frozen['files']:
        raise ValueError('authored production source changed after final-source freeze')
    collection = Collection()
    with redirect_stdout(io.StringIO()):
        code = pytest.main(['--collect-only', '-q'], plugins=[collection])
    if code:
        raise ValueError('current test collection failed')
    actual = {}
    durations = {}
    for name in ('nonpostgresql', 'postgresql'):
        tree = ET.parse(OUTPUT / (name + '.xml'))
        durations[name] = float(tree.find('testsuite').attrib['time'])
        for case in tree.findall('.//testcase'):
            key = (case.attrib['classname'], case.attrib['name'])
            if key in actual:
                raise ValueError('partitions overlapped')
            if any(case.find(tag) is not None for tag in ('failure', 'error', 'skipped')):
                raise ValueError('regression has failure/error/skip: ' + str(key))
            actual[key] = name
    if set(actual) != set(collection.expected):
        raise ValueError('missing/unexpected tests in final verification')
    if any((actual[key] == 'postgresql') != marked for key, marked in collection.expected.items()):
        raise ValueError('PostgreSQL partition does not match actual marker collection')
    coverage = json.loads((OUTPUT / 'coverage.json').read_text(encoding='utf8'))
    baseline = json.loads((ROOT / 'experiments/product_foundation_f4_1/protected_final.json').read_text(encoding='utf8'))['files']
    changed = sorted(path for path, old in baseline.items() if current.get(path) != old)
    result = {'tests_passed': len(actual), 'tests_failed': 0, 'tests_errors': 0, 'tests_skipped': 0,
        'postgresql_passed': sum(collection.expected.values()), 'postgresql_version': '16.11',
        'partition_wall_seconds': durations, 'coverage_percent': coverage['totals']['percent_covered'],
        'config_hash': frozen['config_hash'], 'golden_sha256': frozen['golden_sha256'],
        'authored_files_unchanged_during_final_validation': True,
        'existing_protected_files_changed_from_f4_1': changed,
        'new_protected_files': sorted(current.keys() - baseline.keys()),
        'policy': 'two complete disjoint final-source partitions; no historical/aborted results counted'}
    (OUTPUT / 'verification.json').write_text(json.dumps(result, indent=2, sort_keys=True), encoding='utf8')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    run()
