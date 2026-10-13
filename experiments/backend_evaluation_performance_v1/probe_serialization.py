"""Measure public serialization on a complete frozen real engine result."""
import gc
import json
from pathlib import Path
import sys
import time
from hashlib import sha256

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'backend'))

from pydantic import TypeAdapter
from app.core.time import evaluation_temporal_scope
from app.schemas.strategy import StrategyEvaluationResult
from app.schemas.market import MarketDataProvenance
from app.schemas.analysis import AnalysisResult
from app.services.evaluation_response import analysis_response


def main():
    meta = json.loads((OUT / 'before_fixed_meta.json').read_text())
    cache = json.loads((OUT / 'baseline_btcusdt_15m.json').read_text())
    gc.disable()  # Match the existing one-use worker policy, both candidates.
    result = StrategyEvaluationResult.model_validate_json((OUT / 'before_fixed_result.json').read_bytes())
    provenance = MarketDataProvenance(provider=meta['provider'], data_mode='SERVER_PROVIDER',
        symbol='BTCUSDT', timeframe='15m', first_candle_at=cache['candles'][0]['timestamp'],
        last_candle_at=cache['candles'][-1]['timestamp'], data_cutoff_at=meta['cutoff'],
        expected_latest_closed_candle_at=meta['cutoff'], retrieved_at=meta['cutoff'],
        requested_candles=meta['bars'], received_candles=meta['bars'], lag_seconds=0)
    response = analysis_response(provenance, result)
    adapter = TypeAdapter(AnalysisResult)
    rows = []
    for name, function in [('original', lambda: response.model_dump_json().encode('utf-8')),
                           ('bytes', lambda: adapter.dump_json(response)),
                           ('bytes', lambda: adapter.dump_json(response)),
                           ('original', lambda: response.model_dump_json().encode('utf-8'))]:
        with evaluation_temporal_scope():
            start, cpu = time.perf_counter(), time.process_time()
            body = function()
            rows.append(dict(name=name, wall_s=time.perf_counter()-start,
                cpu_s=time.process_time()-cpu, bytes=len(body), raw_hash=sha256(body).hexdigest()))
        del body
    assert len({row['raw_hash'] for row in rows}) == 1
    (OUT / 'loop19_serialization_probe.json').write_text(json.dumps(rows, indent=2)+'\n')
    print(json.dumps(rows))


if __name__ == '__main__':
    main()
