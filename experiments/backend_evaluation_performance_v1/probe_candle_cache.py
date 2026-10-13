"""Compare complete real frozen history loads, without issuing market requests."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent

def main(args):
    sys.path.insert(0, str((OUT/'baseline_source' if args.baseline else ROOT)/'backend'))
    from app.database.snapshot_integrity import canonical_sha256
    from app.market_data.historical import FileHistoricalCandleCache
    from app.schemas.types import MarketSymbol, Timeframe
    directory = OUT/f'cache_probe_{args.label}'
    directory.mkdir(exist_ok=True)
    source = OUT/f'baseline_{args.symbol.lower()}_15m.json'
    shutil.copyfile(source, directory/f'{args.symbol.lower()}_15m.json')
    cache = FileHistoricalCandleCache(directory)
    rows = []
    for index in range(3):
        start, cpu = time.perf_counter(), time.process_time()
        history = cache.load(MarketSymbol(args.symbol), Timeframe.FIFTEEN_MINUTES)
        elapsed, cpu_elapsed = time.perf_counter()-start, time.process_time()-cpu
        complete = asdict(history)
        complete['candles'] = [c.model_dump(mode='json') for c in history.candles]
        complete['retrieved_at'] = history.retrieved_at.isoformat()
        complete['symbol'] = history.symbol.value
        complete['timeframe'] = history.timeframe.value
        row = dict(iteration=index, wall_s=elapsed, cpu_s=cpu_elapsed,
                   count=len(history.candles), canonical_sha256=canonical_sha256(complete))
        rows.append(row)
        print(json.dumps(row), flush=True)
    result = dict(label=args.label, baseline=args.baseline, symbol=args.symbol, loads=rows)
    (OUT/f'{args.label}_cache.json').write_text(json.dumps(result, indent=2))

if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--label', required=True)
    parser.add_argument('--baseline', action='store_true')
    parser.add_argument('--symbol', default='BTCUSDT')
    main(parser.parse_args())
