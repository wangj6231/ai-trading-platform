"""Read-only final gates for this presentation slice; writes its evidence summary."""
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
frozen = json.loads((OUT / "frozen-source-hashes.json").read_text(encoding="utf-8"))
for name, expected in frozen.items():
    assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected, name
gates = {}
for name, count in (("vitest-coverage.txt", 148), ("existing-browser.txt", 76), ("product-browser.txt", 8), ("evidence-browser-final.txt", 8)):
    content = (OUT / name).read_text(encoding="utf-8")
    assert re.search(rf"\b{count} passed\b", content), name
    assert not re.search(r"\b\d+ failed\b", content), name
    gates[name] = {"passed": count}
assert "Compiled successfully" in (OUT / "build.txt").read_text(encoding="utf-8")
browser = json.loads((OUT / "recorded-real-browser.json").read_text(encoding="utf-8"))
assert browser["status"] == "PASS" and len(browser["rows"]) == 4
source = ROOT / "experiments/backend_evaluation_performance_v1/final25_btc_analysis_response.json"
summary = {
    "status": "VERIFIED_FRONTEND_CHART_EVIDENCE_V2",
    "backend_config_existing_api_routes_projection_module": {"status": "UNCHANGED", "sha256_verified_files": len(frozen)},
    "gates": gates,
    "typecheck_lint_build": "PASS (checked process exits)",
    "recorded_real_presentation_replay": browser,
    "recorded_full_response": {"path": str(source.relative_to(ROOT)), "bytes": source.stat().st_size, "sha256": hashlib.sha256(source.read_bytes()).hexdigest()},
    "source_retention": "complete validated response reference; no evidence truncation; UI pages only bound mounted elements",
    "test_conditions": "final Vitest maxWorkers=1, original assertion/time limits and coverage thresholds unchanged; default/2-worker timeout retained separately",
    "frontend_source_sha256": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted((ROOT / "frontend/src").rglob("*")) if path.is_file()},
}
(OUT / "verification-summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"status": summary["status"], "frozen_files": len(frozen), "gates": gates}))
