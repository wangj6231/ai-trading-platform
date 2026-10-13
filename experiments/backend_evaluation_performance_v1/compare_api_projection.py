"""Compare existing public projections using the complete preserved engine golden."""
import argparse
import asyncio
import inspect
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent


async def main(args):
    source = OUT / 'baseline_source' if args.baseline else ROOT
    sys.path.insert(0, str(source / 'backend'))
    from app.database.snapshot_integrity import canonical_sha256
    from app.schemas.strategy import StrategyEvaluationResult
    from app.schemas.market import MarketDataProvenance
    from app.schemas.analysis import ProductionAnalysisRequest
    from app.services.strategy_evaluation import ServerStrategyEvaluation
    from app.api.signals import evaluate_signal
    from app.api.analysis import run_analysis
    prefix = 'before' if args.symbol == 'BTCUSDT' else 'before_eth'
    meta = json.loads((OUT / (prefix + '_fixed_meta.json')).read_text())
    cache = json.loads((OUT / ('baseline_' + args.symbol.lower() + '_15m.json')).read_text())
    result = StrategyEvaluationResult.model_validate_json((OUT / (prefix + '_fixed_result.json')).read_bytes())
    provenance = MarketDataProvenance(provider=meta['provider'], data_mode='SERVER_PROVIDER',
        symbol=args.symbol, timeframe='15m', first_candle_at=cache['candles'][0]['timestamp'],
        last_candle_at=cache['candles'][-1]['timestamp'], data_cutoff_at=meta['cutoff'],
        expected_latest_closed_candle_at=meta['cutoff'], retrieved_at=meta['cutoff'],
        requested_candles=meta['bars'], received_candles=meta['bars'], lag_seconds=0)
    server_result = ServerStrategyEvaluation(provenance=provenance, result=result)
    request = ProductionAnalysisRequest(symbol=args.symbol)
    class PreservedResultService:
        async def evaluate(self, *a, **kw):
            return server_result
        async def evaluate_connected(self, *a, **kw):
            return server_result
    evidence = dict(symbol=args.symbol, input_hash=meta['history_hash'], cutoff=meta['cutoff'],
        engine_golden_hash=meta['result_hash'], fixed_provenance='diagnostic-only cutoff retrieval time', projections={})
    for name, route in [('signal', evaluate_signal), ('analysis', run_analysis)]:
        if args.baseline:
            kwargs = dict(request=request, service=PreservedResultService(), research_token=None)
            if 'http_request' in inspect.signature(route).parameters:
                kwargs['http_request'] = None
            response = await route(**kwargs)
        else:
            from app.services.evaluation_response import signal_response, analysis_response
            response = (signal_response if name == 'signal' else analysis_response)(provenance, result)
        payload = response.model_dump(mode='json')
        evidence['projections'][name] = canonical_sha256(payload)
        del payload
    path = OUT / ('api_projection_' + args.symbol.lower() + ('_before' if args.baseline else '_after') + '.json')
    if not args.baseline:
        before = json.loads(path.with_name('api_projection_' + args.symbol.lower() + '_before.json').read_text())
        assert before == evidence, 'Complete public projection differs from preserved original route'
    path.write_text(json.dumps(evidence, indent=2)+'\n')
    print(json.dumps(dict(**evidence, equivalence='REFERENCE' if args.baseline else 'PASS')), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline', action='store_true')
    parser.add_argument('--symbol', default='BTCUSDT')
    asyncio.run(main(parser.parse_args()))
