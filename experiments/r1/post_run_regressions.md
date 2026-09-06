# R1 post-run safety regressions

Executed after BOTH historical runs and successful byte-level comparison on 2026-09-06.

The exact seven-file pytest command in pre_run_regressions.md was repeated.
Actual result: 109 passed, 0 failed, 0 skipped, 1 existing non-failing Starlette
TestClient deprecation warning, 92.94 seconds. No full-engineering or PostgreSQL
suite result is inferred from this focused run.

Python compileall -q app tests ../experiments/r1 passed in the same checked
command. Research empty-summary checks also verified zero counts/rates and null
means/distribution statistics, without another historical strategy evaluation.

Both report.json, decisions.json and candidates.json byte comparisons passed;
reproducibility.json preserves each pair of SHA-256 digests. Input/source/config
identities and 256 protected authored paths remained unchanged.

