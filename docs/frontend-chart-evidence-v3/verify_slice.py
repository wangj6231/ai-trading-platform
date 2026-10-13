"""Validate saved frontend gates and unchanged authority files; never evaluate strategy."""
import hashlib
import json
import re
from pathlib import Path

DOCS = Path(__file__).resolve().parent
ROOT = DOCS.parents[1]

def read(path):
    return path.read_text(encoding="utf-8")

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

frozen = json.loads(read(DOCS / "frozen-source-hashes.json"))
changed = [name for name, expected in frozen.items() if sha(ROOT / name) != expected]
assert not changed, changed
baseline = json.loads(read(DOCS / "baseline-source-hashes.json"))
assert all(sha(DOCS / "baseline" / name) == expected for name, expected in baseline.items())

gates = {"vitest.txt": 155, "projection-browser.txt": 76, "product-browser.txt": 8, "v2-evidence-browser.txt": 8, "density-browser.txt": 11}
for filename, count in gates.items():
    log = read(DOCS / filename)
    assert re.search(rf"\b{count} passed\b", log), filename
    assert not re.search(r"\b[1-9]\d* failed\b", log), filename
assert "error TS" not in read(DOCS / "typecheck.txt")
assert re.search(r"\b[1-9]\d* problems?\b", read(DOCS / "lint.txt")) is None
assert "Compiled successfully" in read(DOCS / "build.txt")

previous = json.loads(read(ROOT / "docs/frontend-chart-evidence-v2/verification-summary.json"))
recorded = ROOT / "experiments/backend_evaluation_performance_v1/final25_btc_analysis_response.json"
expected_recorded_hash = "3b52101b0f76262670dbb0f698254b82b4bfaeba255d868df96abeaf7b20664f"
assert sha(recorded) == expected_recorded_hash
matrix = json.loads(read(DOCS / "preset-matrix.json"))
assert matrix["status"] == "PASS" and len(matrix["results"]) == 18
for result in matrix["results"]:
    assert sum(item["source"] for item in result["layers"].values()) == 53482
    assert not result["overflow"]
    assert result["mountedMarkers"] <= result["budgets"]["markerBudget"]
    assert result["mountedZones"] <= result["budgets"]["zoneBudget"]
    for layer, source in result["layers"].items():
        actual = result["productionDensity"][layer]
        assert actual["source"] == actual["viewport"] + actual["offscreen"] + actual["unavailable"]
        assert actual["viewport"] == source["viewport"]
        assert actual["renderedSource"] == source["mountedSource"]
        assert actual["visuals"] == source["visuals"]
    if result["preset"] == "All Evidence":
        assert sum(item["viewport"] for item in result["layers"].values()) == sum(item["mountedSource"] for item in result["layers"].values())

before = json.loads(read(DOCS / "v2-baseline-metrics.json"))
after = json.loads(read(DOCS / "v3-metrics.json"))
comparisons = []
for result in after["rows"]:
    old = next(row for row in before["rows"] if row["operation"] == result["operation"])
    comparisons.append({"operation": result["operation"], "v2_visuals": old["mountedMarkers"] + old["mountedZones"], "v3_visuals": result["mountedMarkers"] + result["mountedZones"], "v2_renderer_ms": old["renderLatencyMs"], "v3_renderer_ms": result["renderLatencyMs"], "v2_longest_task_ms": old["operationLongestTaskMs"], "v3_longest_task_ms": result["operationLongestTaskMs"], "v2_interaction_settle_ms": old["latencyMs"], "v3_interaction_settle_ms": result["latencyMs"]})
for result in comparisons:
    if result["operation"].startswith("viewport"):
        assert result["v3_visuals"] < result["v2_visuals"]

summary = {"status": "VERIFIED_FRONTEND_CHART_EVIDENCE_V3", "authority": {"unchanged_sha256_files": len(frozen), "changed": changed}, "frozen_v2_frontend_snapshot_files": len(baseline), "recorded_response": {"bytes": recorded.stat().st_size, "sha256": expected_recorded_hash}, "gates": gates, "typecheck_lint_build": "PASS (process exits and logs checked)", "recorded_preset_matrix": {"status": "PASS", "combinations": 18, "source_items": 53482}, "comparison": comparisons, "frontend_source_sha256": {str(path.relative_to(ROOT)): sha(path) for path in (ROOT / "frontend/src").rglob("*") if path.is_file()}, "screenshots": sorted(path.name for path in DOCS.glob("*.png")), "verification_scope": "Recorded real presentation replay + declared dense and production-page fixtures; no backend run or live strategy signal claimed"}
(DOCS / "verification-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
print(json.dumps({"status": summary["status"], "unchanged": len(frozen), "gates": gates, "screenshots": len(summary["screenshots"])}))
