# R1 pre-run safety regressions

Executed before the first historical strategy evaluation on 2026-09-06.

From backend, using its existing .venv Python:

```text
python -m pytest -q tests/unit/test_backtest_lookahead.py tests/unit/test_backtest_canonical_data.py tests/unit/test_market_data_trust_boundary.py tests/integration/test_strategy_engine_orchestration.py tests/unit/test_algorithm_identity.py tests/unit/test_strategy_identity.py tests/unit/test_backtest_reproducibility.py
```

Actual result: 109 passed, 0 failed, 0 skipped, 1 non-failing existing Starlette
TestClient deprecation warning, 56.28 seconds. These 109 are the combined
research preflight regressions, NOT a PostgreSQL integration test run.

Frozen source/config identity and Alembic source head matched before acquisition
and after preparation. No strategy evaluation on the R1 dataset occurred during
acquisition, semantic validation, canonical resampling, or identity construction.
