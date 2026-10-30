"""Diagnostic only: preserve the exact pre-change source, contract and provider history."""
from __future__ import annotations
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "backend"))
from app.core.algorithm_identity import build_algorithm_identity
from app.core.strategy_config import load_strategy_config
from app.core.strategy_identity import build_strategy_identity
from app.market_data.historical import FileHistoricalCandleCache
from app.market_data.timeframes import timeframe_duration
from app.schemas.types import MarketSymbol, Timeframe


def main():
    frozen = OUT / "baseline_source"
    frozen.mkdir(parents=True, exist_ok=False)
    hashes = {}
    paths = list((ROOT / "backend/app").rglob("*.py")) + [ROOT / "config/strategy.yaml"]
    paths += list((ROOT / "frontend/src").rglob("*"))
    paths += [ROOT / "frontend/package.json"]
    for path in paths:
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        hashes[relative.as_posix()] = sha256(path.read_bytes()).hexdigest()
        if relative.parts[0] != "frontend":
            target = frozen / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    cache = ROOT / ".cache/market_data/btcusdt_15m.json"
    if cache.exists():
        shutil.copy2(cache, OUT / "baseline_btcusdt_15m.json")
    config = load_strategy_config()
    contract = {
        "branch": subprocess.check_output(["git", "branch", "--show-current"], cwd=ROOT, text=True).strip(),
        "status": subprocess.check_output(["git", "status", "--short"], cwd=ROOT).decode("utf-8", errors="replace"),
        "source_hashes": hashes,
        "strategy_identity": build_strategy_identity(config).model_dump(mode="json"),
        "algorithm_identity": asdict(build_algorithm_identity()),
        "typed_config": config.model_dump(mode="json"),
        "closed_candle_contract": "UTC aware; candle open + duration <= as_of; canonical last close == as_of",
    }
    for name in ("analysis", "signal", "market"):
        path = ROOT / f"backend/app/schemas/{name}.py"
        contract[f"{name}_schema_sha256"] = sha256(path.read_bytes()).hexdigest()
    data = FileHistoricalCandleCache(ROOT / ".cache/market_data").load(MarketSymbol.BTCUSDT, Timeframe.FIFTEEN_MINUTES)
    if data:
        contract["fixed_history"] = {"provider": data.provider, "count": len(data.candles), "hash": data.content_hash,
            "first": data.candles[0].timestamp.isoformat(), "cutoff": (data.candles[-1].timestamp + timeframe_duration(data.timeframe)).isoformat()}
    (OUT / "baseline_contract.json").write_text(json.dumps(contract, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(json.dumps({"strategy_identity": contract["strategy_identity"], "history": contract.get("fixed_history"), "preserved_source_files": len(hashes)}))


if __name__ == "__main__":
    main()
