"""Freeze real ETH Binance history for additional symbol-specific equivalence."""
import asyncio
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "backend"))
from app.core.config import Settings
from app.core.strategy_config import load_strategy_config
from app.core.time import utc_now
from app.market_data.timeframes import timeframe_bucket_start, timeframe_duration
from app.schemas.types import MarketSymbol, Timeframe
from app.services.market_data import build_market_data_service, build_historical_bootstrap_service
from app.services.strategy_history import strategy_history_start


async def main():
    destination = OUT / "baseline_ethusdt_15m.json"
    if destination.exists():
        raise RuntimeError("Refusing to overwrite frozen ETH input")
    settings = Settings(_env_file=None)
    market = build_market_data_service(settings)
    try:
        history = build_historical_bootstrap_service(settings, market)
        timeframe = Timeframe.FIFTEEN_MINUTES
        cutoff = timeframe_bucket_start(utc_now(), timeframe)
        start = strategy_history_start(load_strategy_config().pipelines[MarketSymbol.ETHUSDT], cutoff)
        result = await history.ensure_history(symbol=MarketSymbol.ETHUSDT, timeframe=timeframe,
            required_candles=int((cutoff-start) / timeframe_duration(timeframe)), end_at=cutoff)
        shutil.copy2(settings.market_data_history_cache_dir / "ethusdt_15m.json", destination)
        print(json.dumps({"provider": result.provenance.provider, "symbol": "ETHUSDT",
            "cutoff": cutoff.isoformat(), "bars": len(result.candles), "history_hash": result.provenance.content_hash}))
    finally:
        await market.aclose()


if __name__ == "__main__":
    asyncio.run(main())
