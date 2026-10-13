# PRODUCT-FOUNDATION-F4 — Journal / Analytics read model V1

Final classification: PARTIAL_PASS.

The Journal detail/page and Analytics cutover is verified. Account/position and
attachment-composition paths still retain canonical history loading; therefore
the whole Dashboard is not claimed history-independent or D2 capacity-ready.

## Scope / GRILL findings

F4 removes normal Journal detail/page and Analytics account-history replay and
N+1 hydration, not canonical financial validation. User approved the existing
Journal list/detail, Analytics.evaluate, authorized HTTP pagination and new
rebuild/readiness seams. Frozen pre-change implementations are parity oracles.
TDD/diagnosis skills required measured RED tests before cutover; design vocabulary
kept the recovery/read interface localized. No Rust expansion or financial tuning.

Canonical account/allocator/fills/trades remain financial authority. Derived
history only admits receipt-time visibility and accelerates selected reads.
Analytics money comes from canonical terminal Trade NUMERIC columns. Financial
commands never read this projection to decide a fill, cash or PnL.

## Reproduction and measured improvement

Before cutover, 10-trade detail required74 SQL, Analytics77, one-item HTTP page98;
focused query-budget tests failed (`red_detail.xml`, `red_analytics.xml`,
`red_page.xml`). At500, detail3,508 / Analytics3,515 / page10 4,516 SQL.
Same sealed canonical dumps/cutoffs after: detail8 / Analytics15 / page10 44.
Empty Analytics overhead is3→8, not a universal speedup claim.
Final500 Analytics wall12.5712→0.055884s, cursor1.0177→0.030109s. The final after
sample was collected after the large regression workloads finished. These are
single samples on restored identical data, not controlled repeated SLO certification.

Baseline escalation0/10/50/100/500/1,000 used a900s cooperative cap and768MiB seam
RSS guard. The1,000 attempt stopped after624 seeded trades at902.1567s. No1,000
completed comparison or D2 commercial capacity PASS. Final after profiles reached
all sealed completed shapes in70.6331s. Actual PG16.11, Windows/CPython3.12.4.
Plans/index sizes, typed+canonical parity, bounded allocation samples and added
projection INSERT WAL are preserved in experiments/product_foundation_f4.
Incremental projection adds2 application SQL; measured INSERT WAL1,160bytes.
This is not full financial-command WAL and not a claimed WAL reduction.

## Architecture / integrity

`capture_fill` appends one version1 immutable Trade state per canonical fill in
the same ledger transaction. Event identity and account/sequence uniqueness
deduplicate. `known_at=received_at`, inclusive cutoff, canonical sequence for
equal timestamps. No historical overwrite. Canonical sequences may jump; they
are not assumed contiguous. A RED sequence7→23 test exposed that assumption;
readiness now compares canonical fill count and max sequence, plus source joins.
An ICU-locale RED test also exposed noncanonical symbol ordering (`alpha,Zeta`
instead of `Zeta,alpha`). Sorting only the bounded distinct-symbol set preserves
the original Python ordering; the unchanged financial-output oracle now passes.

Account FOR SHARE guards read completeness against canonical commits/rebuild.
Source loss/mismatch/storage absence→NOT_READY, existing redacted HTTP503; never
fabricated empty/stale aggregates. Detail validates only the selected strict
state, immutable hash and canonical fill/mirror references. Scalar-only account
identity is not an accounting Account. Journal/Analytics outputs and existing
HTTP DTOs/cursors remain unchanged.

Normal page <=101 inspected states /100 returned items; fill page <=101 rows;
source IO batch100; existing detail1,000-fill and HTTP2MiB guard remain. Analytics
symbol groups <=101 inspected /100 returned; overflow NOT_READY, not truncation.
No retained per-account cache or projection authority. PostgreSQL exact sums and
existing Decimal ratios preserve signed average_loss, positive gross_loss, flat
denominator, null PF/R/attribution, stable extrema and LONG/SHORT splits.

Controlled per-account rebuild locks/validates canonical Account/mirrors, deletes
only derived rows, streams canonical fill/order input, reuses original allocator,
checks final account hash and source readiness, and commits atomically. Failures
roll back replacement; no automatic request rebuild. Upgrade existing accounts
requires explicit recovery before derived reads. Canonical evidence is not backfilled
or mutated. Nonempty downgrade/re-upgrade/source-insert-failure tests are included.

## Regression/harness repairs (not financial changes)

Old migration-head assertions expected0012 and now expect new0013. Original
financial golden artifact SHA remains6e3dcb0c10d884248e7b473d60de7fc72e62683b3d0a40132175a296599ecd69.
Its fixture now pins the original four Journal/reference tables rather than
automatically hashing a newly added DERIVED table. It preserves original Decimal
JSON spelling AND independently verifies current typed/canonical transport parity.
No original financial assertion, table or sealed hash is removed/resealed.

NUMERIC exponent/trailing-zero spelling differences in initial model_dump hashes
are retained in after.json; typed Decimal and canonical transport equality are
separate required checks. Initial harness restore attempts/spelling evidence and
earlier after profiles remain archived. Financial triggers/FKs stay enabled.

## Changed files

Production: backend/app/journal/{analytics,capture,records,service}.py;
new readmodel.py and readmodel_analytics.py;
backend/app/paper_http/{errors,service}.py;
new migrations/versions/20261011_0013_journal_readmodel.py. No old migration edit.

Tests: new integration/test_journal_readmodel.py, unit/test_journal_readmodel_limits.py;
fixtures/f4_canonical_{journal,analytics}_oracle.py,
journal_readmodel_{profile,after,verify,coverage}.py;
gateway_hotpath_golden.py; two existing PG migration-head assertions in
test_postgresql_attachment_snapshot.py and test_postgresql_paper_auth.py.

Docs: this report; JOURNAL_ANALYTICS_READMODEL_CONTRACT.md,
JOURNAL_ANALYTICS_REBUILD_CONTRACT.md, JOURNAL_ANALYTICS_READMODEL_PROFILE.md;
CAPACITY_TEST_PLAN.md, PRODUCT_FOUNDATION_VERIFICATION_MATRIX.md. Generated
measurement/JUnit/hash/manifest artifacts under experiments/product_foundation_f4.

## Protected identities

strategy_version=deterministic-smc-ict-v1

config_hash=0c26e108e361b288604b383ca68ea9df80f2595fe919d39cf9ce0dfb57ffeeab

source_content_hash=5c168ba5333c16ad16c65709d631d3241be52ce7771e7117a1656a3a3f828abb

algorithm_build_hash=d4e4a294e7688730671756da13e3913130a0e2e42611ce8ec4efbf4a9281566d

No StrategyConfig, frontend, Rust UTC interface or Execution/accounting core
authored-file change. Algorithm manifest excludes these Journal/HTTP changes;
protected authored-file hashes separately record all nine admitted changes.

## Validation

Current full collection: **1,984 distinct backend nodes, all with passing latest
results; 0 unresolved failures/errors/skips and no missing or unexpected nodes**.
This is complete partitioned execution plus post-fix reruns, NOT a single
uninterrupted all-green invocation. `verification_counts.json` matches JUnit
node identities against the current full and PostgreSQL collections.

| Execution | Passed | Failed initially | Skipped | Wall seconds |
|---|---:|---:|---:|---:|
| Complete non-PG partition | 1,607 | 2 | 0 | 3,894.90 |
| Complete real-PG partition | 372 | 2 | 0 | 3,143.58 |
| Final affected seams (including newly added sequence case) | 188 | 0 | 0 | 264.74 |
| Complete worker warmup rerun | 8 | 0 | 0 | 12.94 |

All **374 currently collected PostgreSQL nodes actually executed and passed**
with PostgreSQL16.11; SQLite does not substitute for that evidence. Two initial
PG failures exposed locale-dependent symbol ordering and an old-schema attachment
migration test using a new reader. The bounded symbol-order RED/green fix and
old-schema oracle / explicit NOT_READY / head-upgrade-rebuild test repair are
covered by the clean affected-seam run. The non-PG failures were existing 10s
worker readiness timeouts during concurrent heavy test workloads. No worker code
or deadline was relaxed: the full eight-test suite subsequently passed alone.
This is not proof of platform capacity or a definitive CPU-causality diagnosis.

The earlier interrupted combined run is diagnostic only. Full coverage combines
complete partitions and fresh affected seams; changed app files use ONLY the
fresh final source-version line maps. Final **91.86%**, above the unchanged90%
gate. Partial collection coverage is not claimed as full coverage.
PG integration uses process-scoped TEST_POSTGRES_URL only, not global DATABASE_URL.
Ruff, mypy156 source files, compileall and diff check passed. Frontend/Rust are
unchanged and not rerun; no historical counts substitute for new results.
The separately owned PostgreSQL test cluster on port56464 was cleanly stopped
after verification; its temporary data is retained, not recursively deleted.
The pre-existing port56463 infrastructure was not stopped or reconfigured.

## Remaining measured boundaries / stop

Canonical audit list, account/position/attachment composition and full per-account
rebuild retain historical work. Exact DB aggregate/readiness scans and tag cursor
metadata digests remain O(selected history); no constant-time summary claim.
Allocator rebuild holds canonical typed per-account history; future very-large
generation recovery and worst-case100×1,000 embedded-fill payloads need separate
load evidence. No account history is truncated.
Selected canonical Trade JSON contains fixed scalar fields, not Position/Account
lot/history arrays. Each fill appends one such bounded state. Internal detail
without HTTP limits can enumerate a selected episode's source fills; it is not
the bounded normal HTTP path.
Existing transaction deadlines may require operational recovery scheduling.
No bounded CPU-heavy Rust kernel is
justified by these samples. D2/DR/public readiness remains NOT_VERIFIED.
STOP after F4; no F5, Rust expansion or commercial activation is authorized.
