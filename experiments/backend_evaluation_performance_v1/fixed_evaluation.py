"""Compare complete existing StrategyEvaluationResult serialization on a frozen real provider slice."""
from __future__ import annotations
import argparse
import gc
from functools import wraps
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent


def main(args):
    source_root = OUT / "baseline_source" if args.baseline else ROOT
    sys.path.insert(0, str(source_root / "backend"))
    from app.core.strategy_config import load_strategy_config
    from app.engines.strategy_engine import ConcreteDeterministicStrategyEngine
    from app.market_data.timeframes import timeframe_duration
    from app.schemas.strategy import StrategyEvaluationContext
    from app.schemas.types import MarketSymbol, Timeframe
    config = load_strategy_config(source_root / "config/strategy.yaml")
    # The frozen source's REPOSITORY_ROOT retains its own preserved algorithm identity.
    from app.schemas.candle import Candle
    cache = json.loads((OUT / f"baseline_{args.symbol.lower()}_15m.json").read_text(encoding="utf-8"))
    assert cache["symbol"] == args.symbol, "A provider history must never be relabelled as another symbol"
    candles = tuple(Candle.model_validate(row) for row in cache["candles"])
    timeframe = Timeframe.FIFTEEN_MINUTES
    cutoff = candles[-1].timestamp + timeframe_duration(timeframe)
    context = StrategyEvaluationContext(symbol=MarketSymbol(args.symbol), as_of=cutoff, candles_by_timeframe={timeframe: candles})
    engine = ConcreteDeterministicStrategyEngine(config)
    # Each version really reports its own source identity. The equivalence artifact
    # additionally compares behavior under the SAME explicit identity (no production override).
    actual_identity = engine.strategy_identity.model_dump(mode="json")
    if args.comparison_identity:
        from app.schemas.strategy_identity import StrategyIdentity
        baseline = json.loads((OUT / "baseline_contract.json").read_text(encoding="utf-8"))
        engine._strategy_identity = StrategyIdentity.model_validate(baseline["strategy_identity"])
    stages = []
    def wrapped(fn, stage):
        @wraps(fn)
        def measured(*a, **kw):
            start = time.perf_counter()
            meta = {"timeframe": a[1].value, "bars": len(a[0])} if stage == "_analyze_market_structure" else {}
            print(json.dumps({"stage": stage, "event": "start", **meta}), flush=True)
            try:
                return fn(*a, **kw)
            finally:
                row = {"stage": stage, "ms": (time.perf_counter() - start) * 1000, **meta}
                stages.append(row)
                print(json.dumps(row), flush=True)
        return measured
    for name in ("_build_candles_by_target", "_analyze_market_structure", "_calculate_indicators", "_analyze_fvg", "_analyze_liquidity", "_analyze_displacement", "_analyze_order_blocks", "_detect_entry_setups"):
        setattr(engine, name, wrapped(getattr(engine, name), name))
    gc_start = {}
    gc_events = []
    def collection_event(phase, info):
        generation = info['generation']
        if phase == 'start':
            gc_start[generation] = time.perf_counter()
        else:
            gc_events.append({'generation': generation,
                's': time.perf_counter()-gc_start.pop(generation),
                'collected': info['collected'], 'uncollectable': info['uncollectable']})
    if args.gc_events:
        gc.callbacks.append(collection_event)
    previous_gc = gc.isenabled()
    if args.disable_auto_gc:
        gc.disable()
    start, cpu = time.perf_counter(), time.process_time()
    try:
        result = engine.evaluate(context)
    finally:
        if args.gc_events:
            gc.callbacks.remove(collection_event)
        if args.disable_auto_gc and previous_gc:
            gc.enable()
    elapsed, cpu_elapsed = time.perf_counter() - start, time.process_time() - cpu
    serial_start = time.perf_counter()
    payload = result.model_dump(mode="json")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    (OUT / f"{args.label}_fixed_result.json").write_text(canonical + "\n", encoding="utf-8")
    meta = {"label": args.label, "provider": cache["provider"], "symbol": args.symbol, "cutoff": cutoff.isoformat(), "history_hash": cache["content_hash"], "bars": len(candles),
        "actual_strategy_identity": actual_identity, "comparison_identity_pinned": args.comparison_identity,
        "wall_s": elapsed, "cpu_s": cpu_elapsed, "serialization_s": time.perf_counter() - serial_start,
        "result_hash": sha256(canonical.encode()).hexdigest(), "stages": stages, "pid": os.getpid(),
        'automatic_gc_disabled': args.disable_auto_gc, 'gc_total_s': sum(row['s'] for row in gc_events),
        'gc_events': gc_events}
    (OUT / f"{args.label}_fixed_meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(meta), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", action="store_true")
    parser.add_argument("--comparison-identity", action="store_true")
    parser.add_argument('--gc-events', action='store_true')
    parser.add_argument('--disable-auto-gc', action='store_true')
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--label", default="before")
    main(parser.parse_args())
