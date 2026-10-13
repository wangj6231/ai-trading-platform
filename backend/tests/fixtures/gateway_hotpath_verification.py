"""Join actual JUnit results to PostgreSQL markers and protected-file hashes."""
from contextlib import redirect_stdout
from hashlib import sha256
import io
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

ROOT = Path(__file__).resolve().parents[3]
ARTIFACTS = ROOT / 'experiments/execution_gateway_hotpath_v1'


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
    xml = ET.parse(ARTIFACTS / 'full_backend.xml')
    cases = xml.findall('.//testcase')
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
    changed = []
    protected = {}
    for line in (ARTIFACTS / 'protected_before.txt').read_text(encoding='utf8').splitlines():
        previous, relative = line.split(' ', 1)
        relative = relative.replace('\\', '/')
        current = sha256((ROOT / relative).read_bytes()).hexdigest()
        protected[relative] = current
        if previous.lower() != current:
            changed.append(relative)
    if changed != ['backend/app/execution/gateway.py']:
        raise ValueError('unexpected protected source change')
    for profile in ('small', 'intermediate'):
        before = json.loads((ARTIFACTS / 'before' / f'{profile}.json').read_text(encoding='utf8'))
        after = json.loads((ARTIFACTS / 'after' / f'{profile}.json').read_text(encoding='utf8'))
        if before['fixture_hash'] != after['fixture_hash'] or before['identity'] != after['identity']:
            raise ValueError('benchmark fixture or strategy identity drift')
    (ARTIFACTS / 'protected_after.json').write_text(json.dumps(protected, indent=2, sort_keys=True), encoding='utf8')
    result = dict(backend_passed=len(cases), failed=failures, skipped=skipped,
        postgresql_marked_passed=len(collection.marked), all_postgresql_cases_matched=True,
        changed_protected_paths=changed, same_profile_identity=True, same_fixture_hash=True)
    (ARTIFACTS / 'verification.json').write_text(json.dumps(result, indent=2, sort_keys=True), encoding='utf8')
    manifest = {str(path.relative_to(ROOT)).replace('\\', '/'): sha256(path.read_bytes()).hexdigest()
        for path in ARTIFACTS.rglob('*') if path.is_file() and path.name != 'artifact_manifest.json'}
    (ARTIFACTS / 'artifact_manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding='utf8')
    print(json.dumps(result))


if __name__ == '__main__':
    verify()
