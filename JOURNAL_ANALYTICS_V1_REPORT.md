# JOURNAL-ANALYTICS-V1 report

2026-10-08. Classification: **PASS — internal analytics over current canonical V1 evidence**.

## GRILL → contract → tests → implementation

Canonical Trade/Journal remains the only trade financial authority. New analytics is an internal query/read service,
not another ledger. Account/receipt-aware Journal reads supply resolved actual trades; aggregate arithmetic reuses
the frozen Decimal helpers. No trade-level price/basis/fee/PnL calculation is introduced.

Factual review found no product denominator conflict. Existing product fixtures contain nullable empty metrics and
zero-loss PF; research/backtest denominator differs and is explicitly NOT reused. The owner's positive gross_loss
magnitude is followed, not a negative frontend display fixture. Existing frontend is untouched and not HTTP-wired here.

Red tests first reproduced the missing service, missing CLOSED aggregation and ignored filter/invalid query behavior.
Each scoped implementation was verified. A test-only rejecting provider identity mismatch and duplicate pytest module
basename were corrected without changing production execution. An independent read-only source GRILL found no concrete
contract/source defect; this is not a substitute for runtime tests.

## Financial and query semantics

- Only receipt-visible CLOSED confirmed executed trades, then date/symbol/side/result filters.
- Win-rate percentage uses wins+losses+breakeven; empty rate/averages/best/worst are null, counts/sums zero.
- Gross winning/losing aggregate names use final net PnL, with positive gross_loss magnitude.
  Authoritative pre-fee gross_pnl and total_fees are separately summed; average loss stays signed.
- Profit factor null at zero loss magnitude; otherwise exact Decimal positive net gains / net losses magnitude.
- Average trade PnL % is not portfolio return. Best/worst ties use earliest closed_at then smallest trade ID.
- USDT is validated from the canonical account, never presumed from provider name or a browser.
- Internal account scope is not Auth; no public route was introduced. No writes, cache or aggregate persistence.
- as_of is knowledge time, closed date range is execution time [from,to); future knowledge cutoffs and invalid queries reject.

## Evidence-dependent limits

The frozen canonical Journal model permits only null R and null strategy attribution.
Therefore actual V1 average_r=null/r_observations=0; by_strategy is empty with explicit
NOT_READY_NO_VERIFIED_ATTRIBUTION, and a strategy filter rejects NOT_READY.
Unattributed actual trades remain valid overall/LONG/SHORT/symbol members. Opaque plans and editable notes/tags are not
converted into strategy identity or risk. Tests verify the null/unavailable path; no positive attributed-trade or non-null
monetary-R capability is claimed. Those require separate approved upstream evidence, not an analytics workaround.

## PostgreSQL query / performance GRILL

Real PostgreSQL 16.11 executed focused scope/filter/Decimal/receipt/breakdown/replay tests.
The explicit two-fill plan probe: Sort over Seq Scan, 2 rows, 27 kB sort memory, SQL execution 0.074 ms;
this timing is one small probe, NOT service throughput or a scalability benchmark.
Existing keys protect fill identity/sequence and scoped references, but there is no account-leading fill/close-date
analytics index. The reused Journal path validates/replays full account history and loads detail metadata; cost grows
with account history and is not optimized here. No cache/materialization/index migration was added without workload evidence.
Broader capacity and future query/index work remain unverified, not a production-readiness claim.

## Files changed

New:
- backend/app/journal/analytics.py
- backend/app/journal/analytics_models.py
- backend/tests/unit/test_journal_analytics.py
- backend/tests/integration/test_postgresql_journal_analytics.py
- JOURNAL_ANALYTICS_CONTRACT.md
- JOURNAL_ANALYTICS_QUERY_CONTRACT.md
- JOURNAL_ANALYTICS_V1_REPORT.md

Updated: JOURNAL_API_CONTRACT.md only.
No existing production execution/Journal allocator/capture/read code, schema, migration, StrategyConfig or frontend changed.
Other pre-existing dirty worktree changes are preserved and not attributed to this phase.

## Final verification

Fresh final-tree results:

| Gate | Result |
|---|---|
| Focused analytics | **57 passed**: 32 unit + 25 real PostgreSQL, 0 failed/0 skipped; 13.89 seconds |
| Full backend | **1,477 passed, 0 failed, 0 skipped**; 1,831.59 seconds (30:31) |
| PostgreSQL subset of full run | **197 passed**, including 25 new analytics cases; no unexpected skips |
| Actual PostgreSQL version | **16.11**, Visual C++ 1944, 64-bit, isolated owned local cluster |
| Ruff | Passed |
| mypy | Passed, 133 source files |
| compileall app/tests/migrations | Passed |
| git diff --check | Passed; existing unrelated frontend line-ending warnings only |
| Scoped new authored files whitespace check | Passed |
| Analytics source/test/config freeze hashes | Unchanged during final full-suite verification |
| Prior Journal/capture/execution boundary hashes | Unchanged against the preceding capture phase |
| Frontend / coverage | Not rerun or claimed; frontend untouched |

The 197 PostgreSQL count is the selected subset of the successful full backend run, not a separate all-PG rerun.
Tests used process-scoped TEST_POSTGRES_URL only; no global product DATABASE_URL was set.
Existing isolated-database fixtures executed migration round trips; no new schema or Alembic revision was required.
Earlier phase counts and the earlier incomplete/failing development runs are not proof for this final tree.
One pre-existing Starlette/httpx deprecation warning remains; it is not a failed test.
The owned isolated PostgreSQL cluster was stopped cleanly after verification; its files were retained,
and no unrelated database service was stopped.

Canonical config_hash remains `0c26e108e361b288604b383ca68ea9df80f2595fe919d39cf9ce0dfb57ffeeab`.
Strategy config file SHA-256 remains `1ac232ca49f381f7b5fb4f99340d568557d6efe5082751e9078872ead3eae06d`.
No strategy or execution/accounting parameter was changed.

Tests cover empty/WIN/LOSS/fee-only loss/BREAKEVEN/mixed, open/partial/ACK/cancelled/rejected exclusions,
LONG/SHORT/symbol/null-strategy groups, null R, zero-loss PF, deterministic tie order/serialization,
scope/date/as-of/late receipt, duplicate/rebuild, provider independence, exact Decimal/NUMERIC values and low ambient precision,
query forgery/constructed bypass, read-only execution state, and annotation/attachment isolation.
No coverage or frontend result is claimed without a fresh run.

## Stop

No Auth, public HTTP/ownership shortcut, frontend mapping, LIVE, rendering, GPT/Telegram/billing, trade policy changes,
strategy optimization, R-risk evidence, FX or invented strategy attribution.
Stop after JOURNAL-ANALYTICS-V1; do not start PAPER-HTTP-API-V1.
