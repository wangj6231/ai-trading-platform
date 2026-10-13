"""Owned, bounded artifact recording; no provider data or market outcomes."""
from hashlib import sha256
import json
from pathlib import Path
import sys

from app.core.strategy_config import load_strategy_config
from app.core.strategy_identity import build_strategy_identity

ROOT = Path(__file__).resolve().parents[3]
ARTIFACTS = ROOT / "experiments/rust_core_bootstrap_v1"


def record(name: str) -> None:
    files = [path for directory in ("backend/app", "backend/migrations", "frontend/src", "config")
             for path in (ROOT / directory).rglob("*") if path.is_file() and "__pycache__" not in path.parts]
    files += [ROOT / "backend/Dockerfile", ROOT / "backend/pyproject.toml",
              ROOT / ".github/workflows/ci.yml", ROOT / ".env.example", ROOT / ".gitignore"]
    result = {"identity": build_strategy_identity(load_strategy_config(ROOT / "config/strategy.yaml")).model_dump(mode="json"),
              "files": {path.relative_to(ROOT).as_posix(): sha256(path.read_bytes()).hexdigest() for path in files},
              "financial_oracle_hash": sha256((ROOT / "experiments/execution_gateway_hotpath_v1/golden_before.json").read_bytes()).hexdigest()}
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    (ARTIFACTS / f"protected_{name}.json").write_text(json.dumps(result, sort_keys=True, indent=2), encoding="utf8")
    print(json.dumps({"identity": result["identity"], "files": len(files)}))


if __name__ == "__main__":
    if sys.argv[1] not in {"before", "after"}:
        raise ValueError("invalid evidence phase")
    record(sys.argv[1])
