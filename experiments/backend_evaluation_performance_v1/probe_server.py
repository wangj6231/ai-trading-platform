"""External-only phase timings and stack samples around the real production app."""
from __future__ import annotations
from collections import Counter
from functools import wraps
import json
import gc
import os
from pathlib import Path
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "backend"))
import uvicorn
from app.core.config import Settings
from app.engines.strategy_engine import ConcreteDeterministicStrategyEngine
from app.main import create_app
from app.market_data.historical import FileHistoricalCandleCache, HistoricalBootstrapService
from app.market_data.providers.binance import BinancePublicMarketDataProvider
from app.services.strategy_evaluation import DeterministicStrategyEvaluationService
from app.services import evaluation_execution
from app.services import strategy_evaluation
from app.schemas.analysis import AnalysisResult

label = os.environ.get("PERF_PROBE_LABEL", "before")
handle = (OUT / f"{label}_stages.jsonl").open("a", encoding="utf-8", buffering=1)


def emit(stage, event, **fields):
    handle.write(json.dumps({"stage": stage, "event": event, "wall": time.time(), "pid": os.getpid(),
        "thread": threading.get_ident(), **fields}, default=str) + "\n")


def wrap_sync(cls, name, stage):
    fn = getattr(cls, name)
    @wraps(fn)
    def measured(*args, **kwargs):
        start = time.perf_counter()
        cpu = time.process_time()
        meta = {}
        if name == "evaluate":
            ctx = args[1]
            meta = {"symbol": ctx.symbol.value, "cutoff": ctx.as_of.isoformat(), "config_identity": args[0].strategy_identity.model_dump(mode="json"),
                "bars": {key.value: len(value) for key, value in ctx.candles_by_timeframe.items()}}
        elif name == "_analyze_market_structure":
            meta = {"timeframe": args[2].value, "bars": len(args[1])}
        emit(stage, "start", gc_enabled=gc.isenabled(), **meta)
        try:
            result = fn(*args, **kwargs)
            return result
        finally:
            emit(stage, "end", ms=(time.perf_counter() - start) * 1000,
                cpu_ms=(time.process_time()-cpu)*1000, gc_enabled=gc.isenabled(), **meta)
    setattr(cls, name, measured)


def wrap_async(cls, name, stage):
    fn = getattr(cls, name)
    @wraps(fn)
    async def measured(*args, **kwargs):
        start = time.perf_counter()
        emit(stage, "start")
        try:
            result = await fn(*args, **kwargs)
            if stage == "history_load":
                emit("history_provenance", "result", **result.provenance.__dict__ if hasattr(result.provenance, "__dict__") else {"provider": result.provenance.provider, "hash": result.provenance.content_hash, "count": len(result.candles), "cache_hit": result.provenance.cache_hit})
            return result
        finally:
            emit(stage, "end", ms=(time.perf_counter() - start) * 1000)
    setattr(cls, name, measured)


for name in ("_build_candles_by_target", "_analyze_market_structure", "_calculate_indicators", "_analyze_fvg", "_analyze_liquidity", "_analyze_displacement", "_analyze_order_blocks", "_detect_entry_setups", "evaluate"):
    wrap_sync(ConcreteDeterministicStrategyEngine, name, name)
wrap_sync(ConcreteDeterministicStrategyEngine, '__init__', 'worker_engine_init')
wrap_sync(AnalysisResult, 'model_dump_json', 'public_json_serialization')
wrap_sync(evaluation_execution, 'serialize_response', 'public_bytes_serialization')
wrap_sync(evaluation_execution, '_evaluate_response', 'worker_response_total')
wrap_sync(strategy_evaluation, '_response_flight_key', 'flight_key')
wrap_sync(FileHistoricalCandleCache, "load", "history_cache_normalize")
wrap_async(HistoricalBootstrapService, "ensure_history", "history_load")
wrap_async(DeterministicStrategyEvaluationService, "evaluate", "service_total")
wrap_async(DeterministicStrategyEvaluationService, '_prepare', 'complete_data_prepare')
wrap_async(evaluation_execution.IsolatedEvaluationRunner, 'response_payload', 'complete_payload_dump')
wrap_async(BinancePublicMarketDataProvider, "_request_payload", "provider_request")

main_thread = threading.get_ident()


def sample():
    counts = Counter()
    while True:
        time.sleep(.25)
        frame = sys._current_frames().get(main_thread)
        rows = []
        while frame:
            filename = frame.f_code.co_filename
            if "ai-trading-platform" in filename:
                rows.append(f"{Path(filename).name}:{frame.f_code.co_name}:{frame.f_lineno}")
            frame = frame.f_back
        key = " > ".join(rows[:8])
        counts[key] += 1
        if sum(counts.values()) % 20 == 0:
            emit("sample_stacks", "sample", counts=dict(counts))


threading.Thread(target=sample, daemon=True).start()
app = create_app(Settings(_env_file=None))

wrap_async(DeterministicStrategyEvaluationService, "response", "service_response_total")


@app.middleware("http")
async def request_timing(request, call_next):
    start = time.perf_counter()
    emit("http", "start", path=request.url.path, request_id=request.headers.get("X-Request-ID"))
    try:
        response = await call_next(request)
        emit("http", "end", path=request.url.path, status=response.status_code, ms=(time.perf_counter() - start) * 1000)
        return response
    finally:
        emit("http_wait", "end", path=request.url.path, ms=(time.perf_counter() - start) * 1000)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PERF_PROBE_PORT", "8010")), log_level="warning")
