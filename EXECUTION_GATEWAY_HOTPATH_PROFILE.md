# Execution Gateway hot-path measured profile V1

## Evidence admission

Windows / Python 3.12.4 / real PostgreSQL **16.11**. Process-scoped
`TEST_POSTGRES_URL`, owned nonce databases; none is a production database.
Artifacts: `experiments/execution_gateway_hotpath_v1/{before,after}`. Existing
F1 generator/fixture/hash and pools (3, overflow0, timeout1s) are identical A/B.
Shapes: 100 accounts/1,000 pending LIMIT orders/10 closed history trades;
500/5,000/50. The pending accounts have no prior trades; separate history-rich
diagnostics below prevent misleading attribution. Shared provider stub has one
request per shape, zero real provider/network/execution claims.

Both current baselines were completed before production changes. Initial PG
port connection attempts failed and are not baseline evidence. Two cProfile
sample admissions and one middle-admission tracemalloc sample perturb each
profile identically. Formatting-only profiler line changes do not change timing
logic. Read-only resource sampler adds one connection.

Limits predeclared: cooperative600s F1 command admission; cooperative1800s
worker/Gateway admission; RSS768MiB at Gateway admission. No hard mid-transaction
interrupt. The 500 baseline took886.986s: **it exceeds600s despite the legacy
`timed_out=false`**, but stays within1800s. No escalation past500 accounts.

## Same-profile before → after

| Metric | 100 accounts | 500 accounts |
|---|---:|---:|
| Whole workload wall s |42.193 →11.474|886.986 →98.737|
| Gateway wall s |32.803 →2.164|833.248 →46.998|
| Whole SQL statements |21,105 →9,105|353,469 →56,469|
| Gateway SQL statements |12,600 →600|303,000 →6,000|
| Whole SQL cursor s |14.240 →3.396|359.799 →28.835|
| Gateway SQL cursor s |11.603 →0.645|345.114 →14.371|
| Whole process CPU s |31.563 →9.094|621.906 →81.359|
| Gateway process CPU s |24.875 →1.672|581.063 →40.109|
| Sampled peak RSS bytes |119,291,904 →120,463,360|122,097,664 →123,154,432|
| Sampled connections, including observer |3 →3|4 →4|
| Sampled lock waits |0 →0|0 →0|
| Cluster-wide WAL delta bytes |86,446,152 →7,163,608|2,162,654,320 →71,252,864|
| Worker cycle wall s |33.343 →2.729|836.563 →51.494|
| Last retained admission lag s |33.259 →2.648|836.429 →51.356|
| Gateway admissions |100 →100|500 →500|
| Provider calls |1 →1|1 →1|
| Order parses |82,000 →1,000|2,010,000 →5,000|

Gateway wall reduction:93.40% /94.36%; Gateway SQL reduction:95.24% /98.02%.
Whole-workload wall reduction:72.80% /88.87%. These are actual observations,
not retroactively invented acceptance thresholds. Two runs per shape (one before,
one after) do not establish production percentile capacity. SQL event counters
count statements/executemany, not individual affected rows or every wire-level
cursor fetch. SQL cursor time excludes fetch/hydration/commit and contains driver
CPU; CPU and SQL percentages overlap. WAL is cluster-wide, not exclusively this
DB, although capacity profiles ran sequentially without other test workloads.

## Dominant baseline attribution (500 Gateway wall833.248s)

1. Per-candle order UPDATE:100,500 executemany calls,284.104s (~34.1% wall).
2. Repeated `ExecutionRepository.parse_order`:2,010,000 calls,219.804s
   (~26.4%, inclusive of schema/hash/document children).
3. Coordinator/ORM/commit residual:207.210s (~24.9%, child-subtracted), not
   falsely labeled pure accounting or allocator time.
4. Mark SELECT:100,500 /32.179s; mark INSERT:100,500 /31.712s.
5. Account read1.024s / lock-account0.567s; pool acquisition0.365s. No sampled
   contention evidence; this is not proof of no sub-250ms lock waits.

After: mark SELECT/INSERT and order UPDATE each1,500 statements (3 batches/account)
instead of100,500. Mark INSERT7.889s, UPDATE3.970s, SELECT1.599s. Order parsing
0.855s. Per-candle observation hashing remains:106,000 hash calls /6.006s,
including initial order/account hash verification. No accounting `apply_fill`
cost is observed in this worker shape because LIMIT90 never touches market100.
Financial parity comes from separate golden/scenario tests, not this no-fill run.

## CPU, hydration, JSON, validation and per-candle work

Test wrappers retain inclusive and child-subtracted stage wall/CPU/call/SQL totals.
Full tables live in each JSON; first/last cumulative/self cProfile tables are
beside it. Baseline500: `document`3,015,000 /100.870s; `content_hash`2,111,000
/47.900s; Order schema2,010,000 /58.078s; frozen InstrumentProfile schema
2,010,000 /28.499s. These are nested costs, **not** additional independent
components to add to the219.804s parse total.

After500: `document`20,000 /1.293s, Order/Profile schemas5,000 /0.217s /0.111s.
ORM order hydration now streams100 rows; inactive history is not retained.
Mark ORM objects remain bounded to each100-candle batch. Late cProfile captures
three flushes (formerly201), SQLAlchemy unit-of-work/hydration, canonical JSON,
model copies, full market OHLC validation and commit. For the late after sample,
134,949 calls /0.241s, OHLC validation201 calls /0.073s, flush3 /0.043s,
commit~0.021s. A sampled cProfile timing is not the average unprofiled admission.
Pure allocator time/native PG CPU/network bytes are UNKNOWN, not invented zero.

## Separate history diagnostic / residual

`before/history.json` and `after/history.json`, not mixed into F1 A/B:

| Closed trades |Canonical account bytes|Account-read SQL|One-candle Gateway SQL before/after|Trade SELECTs|
|---:|---:|---:|---:|---:|
|0|583|1|6 /6|0|
|10|4,398|12|17 /17|10|
|50|18,879|52|57 /57|50|

50-trade account read~39ms before /53ms after in single diagnostic samples;
one-candle observe~51ms /76ms. **No speedup claimed here.**
`parse_account()` still validates the complete JSON and each position/trade
NUMERIC mirror with per-record gets. Current observe does not replay fill history
on its default account read; historical `as_of` reads/Journal can. Every fill
still reparses/recomputes account history. Narrow future candidate: batch mirror
reads while retaining every comparison; not a cache/validation exemption.

## Actual PostgreSQL plan

`mark_plans.json`: 205 canonical marks, replay split100/100/5; actual planner
chooses Seq Scan on this tiny fixture, returns100/100/5, removes105/105/200,
node times0.046/0.037/0.034ms. Existing `(account_id,symbol,valuation_at)` PK
index32,768bytes. No forced planner settings, speculative index or migration.
Large-ledger plan/capacity remains unverified; no fabricated index-use claim.
