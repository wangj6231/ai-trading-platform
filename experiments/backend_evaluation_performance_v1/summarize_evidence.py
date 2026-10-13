"""Aggregate recorded measurements; no strategy re-evaluation or new comparator."""
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent


def read(name):
    return json.loads((OUT / name).read_text(encoding='utf-8-sig'))


def main():
    contract = read('baseline_contract.json')
    frozen = {name: sha256((ROOT/name).read_bytes()).hexdigest() == digest
        for name, digest in contract['source_hashes'].items()
        if name.startswith(('frontend/', 'config/', 'backend/app/schemas/'))}
    assert all(frozen.values())
    cases = list(ET.parse(ROOT/'tmp/backend-performance-final-current.xml').getroot().iter('testcase'))
    counts = Counter('unit' if '.unit.' in case.get('classname', '') else 'integration' for case in cases)
    failures = [case.get('name') for case in cases if case.find('failure') is not None or case.find('error') is not None]
    assert not failures
    skipped = [case.get('name') for case in cases if case.find('skipped') is not None]
    resources = read('final25_after_cancel_idle_resources_window.json')
    cancellation = read('final25_cancel_resources_window.json')
    old_pids = set(cancellation[0]['children'])
    idle_pids = set(resources[0]['children'])
    assert len(idle_pids) == 2
    assert not old_pids & idle_pids
    assert all(set(row['children']) == idle_pids for row in resources)
    cpu_idle = max(point['one_core_percent'] or 0 for row in resources
        for point in row['processes'] if point['pid'] in idle_pids)
    assert cpu_idle == 0, 'A ready worker must not keep evaluating after cancellation'
    memory = {label: dict(
        max_children=max(len(row['children']) for row in read(label+'_resources_window.json')),
        peak_worker_bytes=max(point['working_set_bytes'] for row in read(label+'_resources_window.json')
            for point in row['processes'] if point['pid'] != row['web_pid']))
        for label in ('final25_btc', 'final25_eth')}
    assert all(row['max_children'] <= 2 for row in memory.values())
    evidence = dict(
        final_tests=dict(total=len(cases), categories=dict(counts), failures=failures, skipped=skipped,
            snapshot_named_cases=sum('snapshot' in case.get('name', '') for case in cases),
            reproducibility_equivalence_module_cases=sum(any(name in case.get('classname', '') for name in ('reproducibility', 'equivalence')) for case in cases)),
        frozen_files_checked=len(frozen), frozen_frontend_config_schemas='UNCHANGED',
        complete_golden=dict(BTCUSDT=read('loop25_btc_equivalence.json'), ETHUSDT=read('loop25_eth_equivalence.json')),
        complete_api_projection=dict(BTCUSDT=read('api_projection_btcusdt_after.json'), ETHUSDT=read('api_projection_ethusdt_after.json')),
        fixed_performance=dict(before_btc=read('before_fixed_meta.json'), after_btc=read('loop25_btc_fixed_meta.json'),
            before_eth=read('before_eth_fixed_meta.json'), after_eth=read('loop25_eth_fixed_meta.json')),
        live=dict(BTCUSDT=read('final25_btc_http.json'), ETHUSDT=read('final25_eth_http.json')),
        default_proxy=read('final25_proxy.json'),
        cancellation=read('final25_cancel_http.json'),
        cancellation_after_idle=dict(samples=len(resources), bounded_ready_workers=len(idle_pids),
            cancelled_pids=sorted(old_pids), ready_pids=sorted(idle_pids),
            max_ready_worker_one_core_percent=cpu_idle),
        memory=memory,
        health=dict(idle=read('final25_idle_health_window.json'),
            BTCUSDT=read('final25_btc_health_window.json'), ETHUSDT=read('final25_eth_health_window.json')),
        classification='PERFORMANCE_STILL_INSUFFICIENT',
        postgresql=dict(status='NOT RUN', reason='TEST_POSTGRES_URL absent', skipped=109))
    (OUT/'final_evidence_summary.json').write_text(json.dumps(evidence, indent=2)+'\n')
    print(json.dumps(dict(tests=evidence['final_tests'], frozen_files=len(frozen), after_cancel=evidence['cancellation_after_idle'])))


if __name__ == '__main__':
    main()
