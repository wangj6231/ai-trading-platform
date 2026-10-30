"""Read-only source/gate audit; writes this slice's final verification manifest."""
import hashlib
import json
import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/frontend-paper-product-v1"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


frozen = json.loads((OUT / "baseline-authority.json").read_text(encoding="utf-8"))
changed = [name for name, digest in frozen.items() if not (ROOT / name).exists() or sha(ROOT / name) != digest]
assert not changed, f"Frozen authority changed: {changed}"
baseline = json.loads((OUT / "baseline-frontend.json").read_text(encoding="utf-8"))
integration = [name.replace("\\", "/") for name, digest in baseline.items() if sha(ROOT / name) != digest]
allowed = {"frontend/src/app/layout.tsx", "frontend/src/app/page.tsx", "frontend/src/components/trading-dashboard.tsx", "frontend/src/components/signal-panel.tsx"}
assert set(integration) == allowed, integration

unit = (OUT / "vitest.txt").read_text(encoding="utf-8")
assert re.search(r"Tests\s+191 passed \(191\)", unit), "Vitest gate absent"
assert "ERROR: Coverage" not in unit, "Coverage threshold failure"
gates = {"vitest": 191}
for filename, expected in {"paper-browser.txt": 17, "product-browser.txt": 8, "projection-browser.txt": 76, "density-browser.txt": 11, "v2-evidence-browser.txt": 8}.items():
    log = (OUT / filename).read_text(encoding="utf-8")
    assert re.search(rf"\b{expected} passed \(", log), f"Gate absent: {filename}"
    assert not re.search(r"\b\d+ failed\b", log), f"Failed gate: {filename}"
    gates[filename] = expected
assert "Compiled successfully" in (OUT / "build.txt").read_text(encoding="utf-8")
assert "error TS" not in (OUT / "typecheck.txt").read_text(encoding="utf-8")
assert "problem" not in (OUT / "lint.txt").read_text(encoding="utf-8")
diff = subprocess.run(["git", "diff", "--check"], cwd=ROOT, capture_output=True)
(OUT / "diff-check.txt").write_bytes(diff.stdout + diff.stderr)
assert diff.returncode == 0, "git diff --check failed"

sources = {p.relative_to(ROOT).as_posix(): sha(p) for p in sorted((ROOT / "frontend/src").rglob("*")) if p.is_file()}
screens = [p.name for p in sorted(OUT.glob("*.png")) if not p.name.startswith("stage")]
summary = {"classification": "PASS", "scope": "Frontend DEV / FIXTURE visual workflow only; backend Paper execution NOT_IMPLEMENTED", "concurrent_write_check": "36 existing frontend hashes matched verified V3 twice before edits; other active repo chat inspected: backend documentation only", "authority": {"unchanged_sha256_files": len(frozen), "changed": changed}, "existing_source_integration_edits": sorted(integration), "gates": gates, "browser_total": 120, "typecheck_lint_build_diff_check": "PASS", "coverage_thresholds": "unchanged and passed", "responsive_widths": [1440, 768, 390, 320], "frontend_source_sha256": sources, "screenshots": screens, "financial_authority": "Supplied decimal-string fixture snapshots; no production React financial formulas", "backend_tests": "NOT_RUN (frontend-only freeze)", "no_commit_push_deploy": True}
(OUT / "verification-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
print(json.dumps({"classification": "PASS", "frozen_files": len(frozen), "unit_tests": 191, "browser_tests": 120, "screenshots": len(screens)}))
