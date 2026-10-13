"""Join current proofs without relabelling preserved synchronous baseline evidence."""
from hashlib import sha256
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'backend'))
from app.core.strategy_config import load_strategy_config
from app.engines.strategy_engine import ConcreteDeterministicStrategyEngine


def read(name):
    return json.loads((OUT / name).read_text(encoding='utf-8-sig'))


def suite(path):
    root = ET.parse(ROOT / path).getroot()
    cases = root.findall('.//testcase')
    assert not root.findall('.//failure') and not root.findall('.//error'), path
    return {'tests':len(cases), 'skipped':len(root.findall('.//skipped')),
        'unit':sum('tests.unit.' in case.attrib['classname'] for case in cases),
        'integration':sum('tests.integration.' in case.attrib['classname'] for case in cases),
        'snapshot_named':sum('snapshot' in (case.attrib['classname']+' '+case.attrib['name']) for case in cases),
        'reproducibility_or_equivalence_named':sum(any(word in (case.attrib['classname']+' '+case.attrib['name']) for word in ('reproduc','equivalence')) for case in cases),
        'seconds':sum(float(case.attrib.get('time',0)) for case in root.findall('.//testsuite')), 'failures':0, 'errors':0}


def main():
    baseline = read('async_contract_baseline.json')
    for name, digest in baseline['existing_backend_api_schema_sha256'].items():
        assert sha256((ROOT / name).read_bytes()).hexdigest()==digest, name
    assert sha256((ROOT / 'config/strategy.yaml').read_bytes()).hexdigest()==baseline['strategy_config_sha256']
    old = read('baseline_contract.json')
    proxy = 'frontend/src/lib/backend-proxy.ts'
    assert sha256((ROOT / proxy).read_bytes()).hexdigest()==old['source_hashes'][proxy]
    identity = ConcreteDeterministicStrategyEngine(load_strategy_config(ROOT / 'config/strategy.yaml')).strategy_identity.model_dump(mode='json')
    equivalence = [read(f'async_equivalence_{symbol}.json') for symbol in ('btcusdt','ethusdt')]
    for item in equivalence:
        assert item['actual_strategy_identity']==identity
        assert all(row['exact_complete_bytes_equal'] and row['sync_sha256']==row['async_sha256'] for row in item['rows'])
    goldens = [read(f'async_{symbol}_equivalence.json') for symbol in ('btc','eth')]
    assert all(item['equivalence']=='PASS' and item['actual_after_identity']==identity for item in goldens)
    live = read('async_live_concurrency.json')
    assert live['status']=='PASS' and all(job['strategy_identity']==identity for job in live['jobs'])
    browser = read('async_live_browser.json')
    assert browser['status']=='PASS' and not browser['errors'] and all(200<=request['status']<300 for request in browser['requests'])
    frontend_gates = {}
    for name, count in (('async_frontend_coverage.console.txt',137),
                        ('async_final_existing_browser.console.txt',76),
                        ('async_final_product_browser.console.txt',8),
                        ('async_final_live_browser.console.txt',1)):
        console = (OUT / name).read_text(encoding='utf-8')
        assert f'{count} passed' in console, name
        frontend_gates[name] = {'passed':count}
    cleanup = read('async_final_cleanup.json')
    assert not cleanup['remaining_owned'] and not cleanup['temporary_listeners']
    idle = read('async_final_idle_resources_window.json')
    assert len(idle)>=3 and all(len(sample['children'])<=2 for sample in idle)
    assert all(process['one_core_percent']==0 for sample in idle[1:]
               for process in sample['processes'] if process['pid']!=sample['web_pid'])
    metrics = {}
    for name in ('start_BTCUSDT','start_ETHUSDT','health_running','candles_running','status_BTCUSDT','status_ETHUSDT','cancel_running'):
        samples = [row for row in live['observations'] if row['name']==name]
        assert samples and all(row.get('http') in (200,202) and row['s']<10 for row in samples), name
        metrics[name] = {'samples':len(samples), 'max_s':max(row['s'] for row in samples)}
    lifecycles = {job['symbol']:{'created_at':job['created_at'], 'completed_at':job['completed_at'],
        'cutoff':job['cutoff'], 'history_hash':job['market_data_identity']['history_content_hash'],
        'bars':job['market_data_identity']['provenance']['received_candles']} for job in live['jobs']}
    result = {'phase':'ADDITIVE_ASYNC_V1', 'actual_strategy_identity':identity,
        'existing_backend_schemas_config_original_10s_proxy':'UNCHANGED SHA256 VERIFIED',
        'frontend_changes':'explicitly authorized ALLOW_ASYNC_EVALUATION',
        'full_regression':suite('tmp/backend-performance-async-final.xml'),
        'postgresql':{'status':'NOT RUN', 'selection':suite('tmp/backend-performance-async-postgresql.xml'),
            'reason':'isolated TEST_POSTGRES_URL absent; Docker Linux daemon not running'},
        'equivalence':equivalence, 'original_full_engine_goldens':goldens, 'live_metrics':metrics,
        'live_lifecycles':lifecycles, 'actual_browser':browser, 'compute_profile':read('async26_pair_profile_btcusdt.json')['diagnostic_profile'],
        'frontend_final_gates':frontend_gates,
        'frontend_source_sha256':{str(path.relative_to(ROOT)):sha256(path.read_bytes()).hexdigest()
            for path in sorted((ROOT / 'frontend/src').rglob('*')) if path.is_file()},
        'owned_process_cleanup':cleanup,
        'final_idle_workers':'maximum two; zero measured CPU after work',
        'classification':'READY_FOR_LIVE_FRONTEND_RETEST', 'production_ready':False,
        'limits':['ephemeral single app process jobs; bounded lifetime/admission/retention; no cross-process durable job store',
            'compute latency and 166-170MB full output remain substantial; no claimed CPU improvement from asynchronous acknowledgement',
            'real NO_TRADE snapshots here do not return MTF state or score; frontend does not invent them']}
    coverage = ROOT / 'tmp/backend-performance-async-coverage.json'
    if coverage.exists():
        coverage_data = json.loads(coverage.read_text())
        percent = coverage_data['totals']['percent_covered']
        assert percent>=90, f'CI coverage gate failed: {percent}'
        result['coverage_regression']=suite('tmp/backend-performance-async-coverage.xml')
        result['backend_coverage_percent']=percent
    else:
        result['backend_coverage_gate']='RUNNING; completion not yet claimed'
    (OUT / 'async_evidence_summary.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({key:result[key] for key in ('classification','actual_strategy_identity','full_regression','live_metrics','backend_coverage_percent' if coverage.exists() else 'backend_coverage_gate')}))


if __name__=='__main__':
    main()
