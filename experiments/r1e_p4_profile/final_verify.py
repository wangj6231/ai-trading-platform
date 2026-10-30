"""Post-report read-only identity/file integrity check; no replay."""
from profile_p4 import OUT, EXPECTED, frozen, dump, utc
import json

before = json.loads((OUT/'frozen_before.json').read_text(encoding='utf-8'))
final = frozen(EXPECTED['dataset_hash'])
changed = [name for name in sorted(before['protected_files'].keys() | final['protected_files'].keys()) if before['protected_files'].get(name) != final['protected_files'].get(name)]
assert not changed
assert before['identity'] == final['identity']
assert before['q1_file_sha256'] == final['q1_file_sha256']
dump('final_integrity_check.json', dict(checked_at=utc(), identity=final['identity'], protected_file_count=len(final['protected_files']), changed_protected_files=changed, q1_file_sha256=final['q1_file_sha256'], profile_not_restarted=True))
print('PASS: frozen identities, Q1 bytes, and all protected authored/prior artifact files unchanged; no replay')
