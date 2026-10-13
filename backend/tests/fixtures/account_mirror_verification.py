"""Match actual full-suite results to PG markers and this task's sealed profiles."""
from contextlib import redirect_stdout
from hashlib import sha256
import io
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

ROOT = Path(__file__).resolve().parents[3]
ARTIFACTS = ROOT / 'experiments/account_mirror_batch_read_v1'


class Collection:
    marked = []

    def pytest_collection_finish(self, session):
        self.marked = [item.nodeid for item in session.items if item.get_closest_marker('postgresql')]


def verify():
    collection = Collection()
    with redirect_stdout(io.StringIO()):
        code = pytest.main(['--collect-only', '-q'], plugins=[collection])
    if code:
        raise ValueError('collection failed')
    cases = ET.parse(ARTIFACTS / 'full_backend.xml').findall('.//testcase')
    successful = {(item.attrib['classname'], item.attrib['name']) for item in cases
        if item.find('failure') is None and item.find('error') is None and item.find('skipped') is None}
    for identifier in collection.marked:
        module, *names = identifier.split('::')
        classname = module.removesuffix('.py').replace('/', '.')
        if len(names) > 1:
            classname += '.' + '.'.join(names[:-1])
        if (classname, names[-1]) not in successful:
            raise ValueError('marked PostgreSQL case did not actually pass')
    failures = sum(item.find('failure') is not None or item.find('error') is not None for item in cases)
    skipped = sum(item.find('skipped') is not None for item in cases)
    if failures or skipped:
        raise ValueError('full suite must have zero failures/skips')
    baseline = json.loads((ARTIFACTS / 'protected_before.json').read_text(encoding='utf8'))
    current = {relative: sha256((ROOT / relative).read_bytes()).hexdigest() for relative in baseline}
    changed = [relative for relative in baseline if current[relative] != baseline[relative]]
    if changed != ['backend/app/execution/repository.py']:
        raise ValueError('unexpected protected source change')
    before = json.loads((ARTIFACTS / 'before.json').read_text(encoding='utf8'))
    after = json.loads((ARTIFACTS / 'after.json').read_text(encoding='utf8'))
    if before['fixture_hash'] != after['fixture_hash'] or before['identity'] != after['identity']:
        raise ValueError('benchmark fixture or strategy identity drift')
    before_shapes = [row['closed_trades'] for row in before['shapes']]
    after_shapes = [row['closed_trades'] for row in after['shapes']]
    if before_shapes != after_shapes:
        raise ValueError('before/after profiles did not reach identical shapes')
    oracle = 'experiments/execution_gateway_hotpath_v1/golden_before.json'
    sealed_manifest = json.loads((ROOT / 'experiments/execution_gateway_hotpath_v1/artifact_manifest.json').read_text(encoding='utf8'))
    oracle_hash = sha256((ROOT / oracle).read_bytes()).hexdigest()
    if oracle_hash != sealed_manifest[oracle]:
        raise ValueError('pre-optimization financial oracle was changed')
    (ARTIFACTS / 'protected_after.json').write_text(json.dumps(current, indent=2, sort_keys=True), encoding='utf8')
    result = dict(backend_passed=len(cases), failed=failures, skipped=skipped,
        postgresql_marked_passed=len(collection.marked), all_postgresql_cases_matched=True,
        changed_protected_paths=changed, same_profile_identity=True, same_fixture_hash=True,
        postgres_version=after['postgresql_version'], compared_shapes=before_shapes,
        sealed_financial_oracle_unchanged=True, financial_oracle_sha256=oracle_hash)
    (ARTIFACTS / 'verification.json').write_text(json.dumps(result, indent=2, sort_keys=True), encoding='utf8')
    task_files = ['backend/app/execution/repository.py',
        'backend/tests/integration/test_account_mirror_batch_read.py',
        'backend/tests/fixtures/account_mirror_profile.py',
        'backend/tests/fixtures/account_mirror_verification.py',
        'ACCOUNT_MIRROR_BATCH_READ_CONTRACT.md', 'ACCOUNT_MIRROR_BATCH_READ_PROFILE.md',
        'ACCOUNT_MIRROR_BATCH_READ_V1_REPORT.md']
    task_hashes = {relative: sha256((ROOT / relative).read_bytes()).hexdigest() for relative in task_files}
    (ARTIFACTS / 'authored_task_files.json').write_text(json.dumps(task_hashes, indent=2, sort_keys=True), encoding='utf8')
    manifest = {path.relative_to(ROOT).as_posix(): sha256(path.read_bytes()).hexdigest()
        for path in ARTIFACTS.rglob('*') if path.is_file() and path.name != 'artifact_manifest.json'}
    (ARTIFACTS / 'artifact_manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding='utf8')
    print(json.dumps(result))


if __name__ == '__main__':
    verify()
