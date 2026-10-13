"""External-only complete engine and public serialization CPU profile."""
import cProfile
import argparse
import gc
import json
from pathlib import Path
import pstats
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT/'backend'))
from app.core.strategy_config import load_strategy_config
from app.engines.strategy_engine import ConcreteDeterministicStrategyEngine
from app.schemas.candle import Candle
from app.schemas.strategy import StrategyEvaluationContext
from app.schemas.market import MarketDataProvenance
from app.schemas.types import Timeframe
from app.services.evaluation_response import analysis_response
from app.services.evaluation_execution import serialize_response
from app.core.time import evaluation_temporal_scope


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--label', default='loop12')
    parser.add_argument('--disable-auto-gc', action='store_true')
    parser.add_argument('--worker-serialization', action='store_true')
    args = parser.parse_args()
    cache = json.loads((OUT/'baseline_btcusdt_15m.json').read_text())
    meta = json.loads((OUT/'before_fixed_meta.json').read_text())
    candles = tuple(Candle.model_validate(row) for row in cache['candles'])
    context = StrategyEvaluationContext(symbol='BTCUSDT', as_of=meta['cutoff'],
        candles_by_timeframe={Timeframe.FIFTEEN_MINUTES: candles})
    engine = ConcreteDeterministicStrategyEngine(load_strategy_config(ROOT/'config/strategy.yaml'))
    if args.disable_auto_gc:
        gc.disable()
    profile = cProfile.Profile()
    result = profile.runcall(engine.evaluate, context)
    profile.dump_stats(str(OUT/f'{args.label}_engine.prof'))
    pstats.Stats(profile).strip_dirs().sort_stats('cumulative').print_stats(35)
    provenance = MarketDataProvenance(provider=cache['provider'], data_mode='SERVER_PROVIDER',
        symbol='BTCUSDT', timeframe='15m', first_candle_at=candles[0].timestamp,
        last_candle_at=candles[-1].timestamp, data_cutoff_at=meta['cutoff'],
        expected_latest_closed_candle_at=meta['cutoff'], retrieved_at=meta['cutoff'],
        requested_candles=len(candles), received_candles=len(candles), lag_seconds=0)
    response = analysis_response(provenance, result)
    serializer = cProfile.Profile()
    if args.worker_serialization:
        with evaluation_temporal_scope():
            body = serializer.runcall(serialize_response, response)
    else:
        body = serializer.runcall(response.model_dump_json)
    serializer.dump_stats(str(OUT/f'{args.label}_serializer.prof'))
    pstats.Stats(serializer).strip_dirs().sort_stats('cumulative').print_stats(20)
    print('complete_public_bytes', len(body) if isinstance(body, bytes) else len(body.encode('utf-8')))
    print('serializer_regime', 'actual worker complete TypeAdapter + invocation temporal scope' if args.worker_serialization else 'legacy diagnostic DTO model_dump_json without temporal scope')


if __name__ == '__main__':
    main()
