"""F3 diagnostic wrappers around the unchanged F1 owned-PG capacity workload."""
import argparse
from contextlib import ExitStack
import json
import os
from time import perf_counter
from unittest.mock import patch

import psutil

from app.core.telemetry import query_measurement
from app.execution.gateway import ExecutionGateway
from app.observation.repository import ObservationRepository
from app.observation.worker import ObservationWorker
from tests.fixtures.foundation_capacity import owned_database, run_workload

RSS_BUDGET = 768 * 1024 * 1024


def measure(profile, *, wall_cap=600):
    stages = {}
    worker_active = [False]
    process = psutil.Process()

    def wrapped(name, original):
        def call(*args, **kwargs):
            if process.memory_info().rss > RSS_BUDGET:
                raise TimeoutError('fixture RSS budget exceeded')
            if name == 'discovery':
                worker_active[0] = True
            measurement = query_measurement.get()
            count = measurement.count if measurement else 0
            seconds = measurement.seconds if measurement else 0
            started = perf_counter()
            result = original(*args, **kwargs)
            if worker_active[0]:
                stage = stages.setdefault(name, {'calls': 0, 'wall_seconds': 0., 'query_count': 0,
                                                'query_seconds': 0., 'items_returned': 0})
                stage['calls'] += 1
                stage['wall_seconds'] += perf_counter() - started
                stage['query_count'] += measurement.count - count if measurement else 0
                stage['query_seconds'] += measurement.seconds - seconds if measurement else 0
                if isinstance(result, (dict, tuple, list)):
                    stage['items_returned'] += len(result)
            return result
        return call

    original_tick = ObservationWorker.tick

    async def tick(worker):
        started = perf_counter()
        await original_tick(worker)
        stages['worker_cycle'] = {'calls': 1, 'wall_seconds': perf_counter() - started}

    with ExitStack() as stack:
        for cls, method, name in (
            (ObservationRepository, 'targets', 'discovery'),
            (ObservationRepository, 'checkpoint', 'checkpoint'),
            (ObservationRepository, 'capture', 'capture'),
            (ObservationRepository, 'delivered', 'delivery'),
            (ExecutionGateway, 'observe', 'gateway'),
            (ExecutionGateway, 'create_account', 'create_account'),
            (ExecutionGateway, 'submit_order', 'submit_order'),
        ):
            stack.enter_context(patch.object(cls, method, wrapped(name, getattr(cls, method))))
        stack.enter_context(patch.object(ObservationWorker, 'tick', tick))
        with owned_database(os.environ.get('TEST_POSTGRES_URL', '')) as (database, nonce):
            report = run_workload(database, nonce, profile, wall_cap=wall_cap)
        report['isolated_database_removed'] = True
    report['f3_stage_measurements'] = stages
    events = report.pop('worker_metrics')
    report['worker_summary'] = {
        'targets_discovered': stages.get('discovery', {}).get('items_returned', 0),
        'gateway_admissions': stages.get('gateway', {}).get('calls', 0),
        'returned_event_count': stages.get('gateway', {}).get('items_returned', 0),
        'max_retained_admission_lag_seconds': max(
            (e['admission_lag_seconds'] for e in events if 'admission_lag_seconds' in e), default=None),
        'lag_sample_scope': 'bounded F1 telemetry ring; may omit early samples',
    }
    report['rss_budget_bytes'] = RSS_BUDGET
    report['scope'] = 'F3_OWNED_PG_DIAGNOSTIC_NOT_D2_CAPACITY'
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--profile', choices=('small', 'intermediate', 'extended', 'smoke'), required=True)
    args = parser.parse_args()
    report = measure(args.profile)
    print('F3_ARTIFACT_BEGIN')
    print(json.dumps(report, sort_keys=True, indent=2))


if __name__ == '__main__':
    main()
