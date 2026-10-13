# ACCOUNT-MIRROR-BATCH-READ-V1

Classification: **PASS** for scoped canonical mirror batch IO optimization.
Financial/execution authority is unchanged. This is not D2 capacity or
commercial-readiness certification.

## GRILL / red before production fix

The actual path is account row -> `Account.model_validate` -> account hash and
header comparisons -> positions/trades -> `Session.get` mirrors -> every state
and NUMERIC comparison. The original cold read performed one trade SELECT per
canonical trade. Ten trades produced ten trade SELECTs: the focused bounded-IO
test failed before the production edit (`red.xml`). Historical visibility was
already correct; this is IO amplification, not a new accounting rule.

Before optimization, 25 existing-behavior corruption/PIT checks passed
(`corruption_baseline.xml`). An earlier test harness mistakenly expected an ORM
deleted-object exception on an expired missing mirror; original production
actually raised the corruption `ValueError`. The expectation was corrected
against the original parser, not by weakening production behavior.

Pre-change profiles completed all 0/10/50/100/500 shapes on actual PostgreSQL;
the after run reused the same declared shapes/fixture. No baseline resealing or
financial fixture bypass. See the profile for full measurements and limitations.

## Fix and authority

Only production `backend/app/execution/repository.py` changes: named fetch size
100, bounded referenced-PK reads and ephemeral ID lookup. Every canonical
reference still undergoes the exact previous comparison checks. No new cache
authority, history truncation, account-size policy, strategy tuning or financial
predicate. ORM identity-map semantics, expired reload behavior and current
validation before `as_of` fill replay remain protected.

Cold account SQL: **1/12/52/102/502 -> 1/3/3/3/7**.
One-candle observation SQL: **6/17/57/107/507 -> 6/8/8/8/12**.
500-trade account wall sample: **376.781 -> 112.113 ms**.
500-trade observation wall sample: **570.101 -> 368.741 ms**.

Both profiles finished within the 900 s cap (864.612 / 560.170 s) and removed
their owned random DB. This demonstrates the scoped IO reduction, **not** D2
capacity, latency percentile, profitability or production readiness.

## New tests and financial parity

31 new real-PG cases cover cold 10/105-trade reads and batch hydration, missing
mirrors, every old mirror numeric/state/ownership comparison, conflicting and
identical duplicate canonical references, real-PG duplicate PK rejection,
unreferenced extra-row compatibility, cached/expired/dirty identity behavior,
unflushed pending rows, header/hash guards and historical/current-corruption
visibility. No existing financial golden expectation is changed.

The unchanged sealed 10-case financial oracle covers MARKET/LIMIT LONG/SHORT,
scale-in, partial/full close, same timestamp execution sequencing, rejection,
cancel, untouched orders and idempotent replay. It compares canonical accounts,
orders, fills, positions, trades, fees, cash/collateral, Journal and Analytics.
Focused account/Gateway verification: **76 passed**, no failed or skipped tests.
Broader focused verification: **438 passed**, no failed or skipped tests,
including Observation Worker, Paper execution/accounting, Journal/Analytics,
Auth/HTTP and Paper E2E.

Full backend: **1,822 passed, 0 failed, 0 skipped**, 2098.06 s. Its **360
PostgreSQL-marked cases** were matched individually to successful JUnit cases
by the verification helper; they actually executed on PostgreSQL **16.11**,
not SQLite and not skipped. The PostgreSQL count is included in the full total,
not an additional disjoint suite. Focused reruns likewise overlap the full run.
The three full-suite warnings are the existing TestClient and Python 3.12 SQLite
datetime adapter deprecations, not test failures.

Ruff (`app tests`), configured mypy (153 source files), compileall (`app tests`)
and `git diff --check` passed. Existing line-ending warnings and the TestClient
deprecation warning do not represent failing gates. Frontend is unchanged and
not rerun; no new migration is required.

## Changed files

- `backend/app/execution/repository.py` (only production code).
- `backend/tests/integration/test_account_mirror_batch_read.py` (new real-PG tests).
- `backend/tests/fixtures/account_mirror_profile.py` (test-only owned measurement).
- `backend/tests/fixtures/account_mirror_verification.py` (actual-result verification).
- The three `ACCOUNT_MIRROR_BATCH_READ_*.md` documents.
- New evidence under `experiments/account_mirror_batch_read_v1/`; prior task
  artifacts/goldens are not overwritten.

No schema/migration, frontend, Gateway, accounting, Journal, Analytics, auth,
HTTP, strategy, configuration or execution-policy edit. The protected authored
manifest covers existing app/frontend/config files; its legacy directory list
does not cover `backend/migrations`, so no migration-hash assertion is claimed.
No migration file was edited in this task.

## Final integrity evidence

`experiments/account_mirror_batch_read_v1/verification.json` confirms:

- Every PostgreSQL-marked case passed; failures/skips both zero.
- Before/after shapes, fixture hash and strategy/build identity are identical.
- All 260 pre-existing protected app/frontend/config files match the before
  manifest except the intended `backend/app/execution/repository.py` edit.
- The previously sealed financial golden file remains byte-identical to its
  prior artifact manifest: SHA-256
  `6e3dcb0c10d884248e7b473d60de7fc72e62683b3d0a40132175a296599ecd69`.

Evidence files include `red.xml`, `corruption_baseline.xml`,
`focused_account_gateway.xml`, `focused.xml`, `full_backend.xml`,
`before.json`, `after.json`, `quality_gates.json`, `protected_before.json`,
`protected_after.json`, `verification.json` and `artifact_manifest.json`.
`corruption_before.xml` deliberately preserves the initial harness expectation
failure; it is not misrepresented as a passing run. `green_first.xml` preserves
the initial green subset, not the final full-suite total.

The artifact manifest records evidence hashes. Authored task-file hashes are
also recorded separately for the production file, two test-only harnesses,
new test module and three documents. No Git commit/staging/reset was performed;
the unrelated dirty workspace was preserved.

## Remaining boundaries / stop

Complete canonical account JSON/typed trade arrays and hashing remain
history-sized. Batches bound additional mirror lookup memory, not the entire
account. Journal membership/replay, write-side mirror traversal and full order
validation remain separate residuals. No arbitrary history truncation or new
account-size admission policy is introduced. **RUST_NOT_JUSTIFIED** remains
the scoped decision. Stop after final verification/report; no F4 or Rust work.
