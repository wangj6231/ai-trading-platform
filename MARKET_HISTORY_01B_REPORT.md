# MARKET-HISTORY-01B — PASS

2026-09-24. Stage 1 of the authorized GRILL → FIX → VERIFY loop.

## Defect and minimal fix

The permanent regression `test_old_slice_hash_survives_forward_refresh_and_restart`
first failed against the original implementation: identical T candles returned a
different provenance hash after cache append to N. This was provenance leakage,
not future OHLC in the returned slice.

`HistoricalBootstrapService.ensure_history()` now hashes **selected candles** in
both the cache-hit and refresh branches. `FileHistoricalCandleCache` still writes
and verifies the complete persisted-cache hash. No cache format, corruption,
provider, overlap, gap, UTC, partial/future or atomic-write checks were removed.

## Permanent regression evidence

`backend/tests/unit/test_historical_bootstrap.py` covers forward refresh then old
cutoff reread, restart, cold/warm caches, backfill, changed candle content, and
changes to observation time/page count/cache-hit metadata. Existing corruption
rebootstrap test also proves recovery metadata cannot change the same slice hash.

The cache hash changes when its contents grow; an unchanged returned slice hash
does not. Synthetic fixtures only; no real Binance network result is claimed.

## Validation executed at Stage 1

- History/timeframe/MTF/market-data focused tests: **67 passed**.
- Full backend unit suite: **843 passed**, 0 failed, 0 skipped, 408.74 seconds.
- Ruff app/tests, mypy app (107 files), compileall app, git diff --check: **PASS**.
- One existing Starlette/httpx deprecation warning.

## Identity at stage boundary

`strategy_version = deterministic-smc-ict-v1`, unchanged.

`config_hash = 2a4abfbfd2ec5c15754dd9d2f9a12a9874df263bc1f64db668d56db9783394ad`, unchanged.

Source hash:
`b64ff0ed7b80088445111064a46129db1bf8f49d9251ca8c43b9423639e40a8c`
→ `1f0ddea015126ce762c624653e7140a3e482ebee2651474393a549f2bf693217`.

Build hash:
`c3cd97cf7cdd61e2d6c100f8177a7a1aa4dfb85f8b6acd1191d3551ed4f983ec`
→ `b4ebaf876c9f06de83d4d52879a3272b5db9cc19ed9a1c17fce9e59e3b531fd1`.

These are working-tree identities, not a clean/frozen release. Later Stage 2
source/config identity changes are intentional and recorded separately.

## Files and continuation

- Changed: `backend/app/market_data/historical.py`.
- Added regressions: `backend/tests/unit/test_historical_bootstrap.py`.
- Added: this report.

The authorized loop automatically continues to TF-MIGRATE-01B; the earlier
provenance blocker is resolved. No MTF owner decision is reopened.

## Completion re-verification — 2026-10-06

The subsequent migration's complete non-PostgreSQL backend run finished with
**1,055 passed**, 0 failed, 0 errors and 0 skipped: 871 unit and 184 integration
tests. Historical slice, cache-integrity and market-data regressions are included.
Ruff, mypy, compileall and diff checks passed; the frontend regression had
69 passed without frontend source changes. PostgreSQL was not executed because
TEST_POSTGRES_URL is absent and is explicitly **UNVERIFIED**.

TF_MIGRATE_01B_REPORT.md records the intentional Stage 2 config/build identity
changes, detailed validation and PASS classification. The Stage 1 identity and
843-test result above remain the evidence from that earlier stage boundary.
The loop stops after TF-MIGRATE-01B.
