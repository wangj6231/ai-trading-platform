# F4 measured read amplification

Evidence: `experiments/product_foundation_f4/before.json`, `after.json`, sealed
`fixture_*.dump`, RED/green/shadow JUnit, plans and manifest. All data is synthetic
canonical Gateway activity in owned PostgreSQL databases, NOT strategy research.

## Baseline and caps

Windows, CPython 3.12.4, actual PostgreSQL 16.11, process-scoped TEST_POSTGRES_URL.
Requested closed-trade shapes: 0, 10, 50, 100, 500, 1,000. Cooperative 900-second
command cap, 768 MiB RSS guard at command seams. Completed shapes through 500;
escalation to 1,000 stopped at 624 seeded trades, 902.1567 seconds. No 1,000-trade
measurement is claimed. The owned baseline DB was removed. No hard watchdog or
within-900-seconds guarantee is claimed for a command already in progress.

After restores EXACT sealed canonical IDs/facts/cutoffs from those dumps, not a
new random fixture. Dump hashes are checked. Only the migration-seeded derived
observation schema singleton is omitted from restore; canonical/reference facts
are not omitted. Restore orders dependencies and preserves ALL financial
triggers/FKs; public search_path is explicitly used for existing triggers.
Failed harness attempts are retained, not presented as production regressions.

## SQL count comparison

| Closed trades | Detail before → after | Analytics before → after | Journal page (10) before → after |
|---:|---:|---:|---:|
| 0 | not applicable | 3 → 8 | 4 → 4 |
| 10 | 74 → 8 | 77 → 15 | 98 → 44 |
| 50 | 354 → 8 | 357 → 15 | 458 → 44 |
| 100 | 704 → 8 | 707 → 15 | 908 → 44 |
| 500 | 3,508 → 8 | 3,515 → 15 | 4,516 → 44 |

Empty/small report has fixed validation overhead; no claim that every shape is
faster. The unbounded canonical audit `list_trades()` intentionally retains the
old replay and amplification. It is NOT the HTTP page/Analytics runtime path.

The final 500-row Analytics sample: wall 12.5712s → 0.055884s, SQL cursor 1.0177s →
0.030109s, process CPU 12.2344s → 0.015625s. Final after measurement followed the
large regression workloads (all completed shapes in70.6331s). Timings are single
observations, not repeated controlled SLO/throughput certification or a precise
speedup ratio. SQL-count reduction is the primary structural evidence. Earlier
concurrently loaded after profiles remain archived; capacity runs are still needed.

## Correctness and hash spelling

Typed Analytics and canonical HTTP serialization equal the frozen canonical
oracle at every restored shape/filter; `analytics_shadow` preserves both hashes.
The initial harness hashed `model_dump(mode='json')`, retaining Decimal exponent/
trailing-zero spelling. SQL NUMERIC results may have a different spelling while
being the SAME exact Decimal and SAME canonical transport. These original hash
inequalities are preserved, not overwritten or dismissed without the independent
typed/canonical checks. Journal page/detail/fill hashes match directly.

The original financial golden artifact is not resealed. Its test harness pins
the original four Journal/reference tables (not the new derived table), retains
the original canonical Analytics JSON spelling, and ALSO asserts new Analytics
typed and canonical-transport equality before calculating the old financial hash.
No canonical row, monetary expectation or financial comparator is removed.

## PostgreSQL plans and write cost

`explain_visibility`/`explain_closed` contain actual ANALYZE/BUFFERS plans;
`projection_sizes` contains index bytes. No forced planner hint is used. The
read model has event PK, account/sequence uniqueness, account/trade/knowledge/
sequence lookup and account/close/knowledge range index. Small all-account
aggregation can legitimately choose a sequential scan; it is NOT constant-time.
Application cursor returned-row counts are NOT actual scanned-row estimates;
inspect plan nodes/loops/filter removals for database scan evidence.

Isolated incremental terminal projection capture adds 2 application SQL calls,
roughly 3.08–4.23ms in final measured shapes 10–500. EXPLAIN (ANALYZE,WAL,BUFFERS) for the
same derived INSERT reports 1,160 WAL bytes in these samples. Source triggers/FKs
remain enabled. These probes do NOT mutate canonical financial rows. They measure
added projection work, NOT a before/after full close command or a fleet WAL budget.
Trigger-internal SELECTs are not separately counted as application cursor calls.

The baseline field `read_wal_bytes` was sampled across the dump interval and is
cluster WAL, NOT a reliable read-operation or financial-close WAL attribution.
It is not used for a claimed WAL reduction. Connections and after RSS are limited
samples, not continuous fleet peak proof; baseline cursor families/ORM hydration
are in before.json. No fabricated missing measurements or commercial budget.

## Memory and residuals

Normal HTTP page: ≤101 state rows, ≤100 returned items, ≤1,000 embedded fills per
item, existing 2 MiB response guard. Fill page: ≤101 rows, no complete fill array.
Canonical Trade snapshots contain only fixed scalar fields and bounded
Identifiers/Decimal values; unlike Position/Account they have no lot/fill arrays.
Snapshot count grows linearly with admitted fills. HTTP detail embeds at most
1,000 canonical fill references. Internal audit/detail without HTTP limits can
still enumerate a complete selected episode; no financial history is truncated.
Source stream/recovery IO batch is 100. Analytics distinct groups: ≤101 inspected,
≤100 returned; overflow NOT_READY, never a truncated aggregate. Per-symbol SQL
queries are bounded by this reporting resource guard.

Instrumented final after Analytics traced peak allocation at500 is112,336 bytes;
uninstrumented Analytics sampled process RSS is143,298,560 bytes. These are
contextual/warmed measurements, not retained
per-account cache size. Account JSON text at 500 trades is 193,817 bytes; baseline
pg_column_size is compressed/TOAST size and must not be called JSON wire bytes.

Readiness joins/counts and exact canonical aggregates still scan index-selected
DB history. Tag cursor digest streams historical metadata. Explicit canonical
audit/rebuild still owns typed per-account history; no truncation. Existing
account/position/attachment request paths retain separate financial validation
amplification, outside this Journal/Analytics cutover. Large-account / generation
rebuild, worst-case 100×1,000 embedded fill payloads and D2 scale need separate
load evidence; these small shapes do not prove those targets.

## Rust gate

No Rust migration, interface expansion or bounded CPU aggregation candidate is
justified by these samples. At 500, SQL cursor/wall ≈54%; process CPU/wall ≈28%
(overlapping measures, not a complete additive partition). Serialization/hash
and allocation remain separately instrumented. CPU-heavy financial allocator
and explicit canonical audit/rebuild were NOT optimized here. Existing Rust UTC
alignment source/config remains unchanged.
