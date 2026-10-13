# ACCOUNT-MIRROR-BATCH-READ-V1 profile

Source artifacts: `experiments/account_mirror_batch_read_v1/before.json` and
`after.json`. These are owned isolated fixture measurements, not strategy
research, product SLO percentiles or D2 capacity proof.

## Admission / comparability

UTC measurement windows: before `2026-10-10T06:54:12.015634+00:00` ->
`2026-10-10T07:08:36.627594+00:00`; after
`2026-10-10T13:12:26.634602+00:00` -> `2026-10-10T13:21:46.804948+00:00`.
The runs are sequential, not concurrent; different ambient system activity is
not controlled, so deterministic query counts are stronger evidence than a
single wall/CPU sample.

Shared identity references:

- Strategy version: `deterministic-smc-ict-v1` (same protected identity source).
- Config hash: `0c26e108e361b288604b383ca68ea9df80f2595fe919d39cf9ce0dfb57ffeeab`.
- Source content hash: `62381446a4f1614b71e19408890463381a411afd5ab2f66d953fcf6da5e971ef`.
- Algorithm build hash: `fb974e3a0b55180b45f5a7e14a8f840dbe0aa6b0217abf0631a35854bdbc27ad`.
- Fixture hash: `5ec80513fe9ba8fcefd5aba2f390146245d1999b0fdfd53cdcfcf3eee6988e95`.

The execution repository is outside the current deterministic-strategy source
closure; unchanged strategy hashes do **not** mean no execution source changed.
The separate protected authored-file manifest identifies that one production
edit explicitly.

- Windows, Python 3.12.4, actual PostgreSQL **16.11** (native isolated cluster,
  localhost port 56463). Only process-scoped `TEST_POSTGRES_URL` was supplied;
  the existing isolated Alembic harness temporarily restores its own environment.
- Predeclared sequential shapes: 0, 10, 50, 100, 500 closed trades, one account.
  Real Gateway open-at-100/close-at-110 fills construct canonical history, with
  one pending untouched LIMIT-at-90 order at each sample. No raw financial seed
  bypass, no network provider/strategy call, no history truncation.
- Cooperative cap 900 seconds; RSS admission cap 768 MiB, checked between
  complete commands/actions, never by interrupting a financial transaction.
  All five shapes completed: before **864.612 s**, after **560.170 s**. Neither
  run reached the cap. Both random owned databases were removed normally.
- Identical fixture hash and deterministic strategy/build identity; independent
  random account/trade IDs mean profile account hashes are diagnostic, **not**
  a cross-run financial equality oracle. Financial parity uses the previously
  sealed fixed-identity golden scenarios instead.
- Fresh-session account read and first one-candle observation are untraced
  timings. Separate instrumented reads use tracemalloc and schema/hash wrappers.
  Do not compare instrumented wall times to untraced wall times.

## Account read: before -> after

All times below are milliseconds. Delta is after minus before.

| Closed trades | SQL before -> after (delta) | Wall before -> after (delta) | SQL cursor before -> after |
|---:|---:|---:|---:|
| 0 | 1 -> 1 (0) | 2.794 -> 3.733 (+0.939) | 0.605 -> 0.693 |
| 10 | 12 -> 3 (-9) | 11.676 -> 11.588 (-0.088) | 2.985 -> 1.836 |
| 50 | 52 -> 3 (-49) | 45.006 -> 16.572 (-28.434) | 13.036 -> 2.118 |
| 100 | 102 -> 3 (-99) | 91.892 -> 26.874 (-65.018) | 26.249 -> 3.445 |
| 500 | 502 -> 7 (-495) | 376.781 -> 112.113 (-264.668) | 109.485 -> 10.484 |

At 500 trades, SQL count falls 98.61%, sampled wall time falls about 70.24%.
At 0/10 trades no meaningful latency improvement is established by this single
sample. Cold trade SELECTs become 0/1/1/1/5 rather than 0/10/50/100/500;
position SELECTs remain zero for the empty account, otherwise one.

## First one-candle observation: before -> after

| Closed trades | SQL before -> after (delta) | Wall ms before -> after (delta) | Process CPU ms before -> after |
|---:|---:|---:|---:|
| 0 | 6 -> 6 (0) | 14.826 -> 15.032 (+0.205) | 15.625 -> 0 |
| 10 | 17 -> 8 (-9) | 23.260 -> 19.703 (-3.557) | 0 -> 15.625 |
| 50 | 57 -> 8 (-49) | 73.634 -> 44.412 (-29.222) | 78.125 -> 46.875 |
| 100 | 107 -> 8 (-99) | 120.000 -> 77.560 (-42.440) | 125 -> 78.125 |
| 500 | 507 -> 12 (-495) | 570.101 -> 368.741 (-201.360) | 562.5 -> 343.75 |

At 500 trades, observation SQL count falls 97.63%, sampled wall time falls about
35.32%. The history-sized order scan and full canonical validation remain;
this is not constant-time observation.

## CPU, memory, hydration, connections

| Closed trades | Account CPU ms before -> after | Account RSS bytes before -> after | Canonical JSON bytes | Instrumented allocation peak bytes before -> after |
|---:|---:|---:|---:|---:|
| 0 | 0 -> 0 | 112988160 -> 112861184 | 579 | 25910 -> 25526 |
| 10 | 15.625 -> 15.625 | 115245056 -> 115376128 | 4394 | 87297 -> 113656 |
| 50 | 31.25 -> 0 | 117800960 -> 118415360 | 18875 | 220216 -> 398307 |
| 100 | 109.375 -> 31.25 | 119934976 -> 120430592 | 36973 | 421473 -> 747761 |
| 500 | 328.125 -> 109.375 | 122241024 -> 122159104 | 181774 | 1998983 -> 2000752 |

Hydrated totals are **unchanged**: one position and N trades for nonempty
accounts. The new test with 105 trades observes at most 100 trade ORM loads
per query, and two trade queries. The 500-trade profile reads five batches;
it does not skip 495 validation objects.

Batching trades increased the traced temporary peak at 10/50/100 trades, as
expected from retaining a batch rather than one row. At 500, whole-account
typed data dominates and peaks stay around 2 MB. This is not a persistent cache
or a memory improvement claim. The final instrumented RSS sample is 123092992
bytes; the small samples cannot establish absolute process peaks.

The observer samples connections every 20 ms: longer reads saw two connections
(application plus observer); a zero sample means **NOT OBSERVED**, not zero DB
connections. Windows CPU accounting is coarse (15.625 ms quantization); a zero
CPU sample does not mean no CPU work. Process CPU includes native driver and
instrumentation threads, not just Python bytecode.

## Stage attribution / limitations

At 500 trades, instrumented account read:

| Measured stage | Calls before / after | Wall ms before -> after |
|---|---:|---:|
| `Account.model_validate` | 1 / 1 | 24.663 -> 33.003 |
| `content_hash` | 1 / 1 | 45.631 -> 54.227 |
| `document` mirror serialization/JSON | 501 / 501 | 105.883 -> 116.191 |
| Trade SELECT cursor family | 500 / 5 | 227.221 -> 23.607 |
| Position SELECT cursor family | 1 / 1 | 0.687 -> 1.013 |
| Entire instrumented read | 1 / 1 | 1153.874 -> 509.670 |

All canonical validations remain. Stage wrappers are inclusive and SQL-family
timers have separate instrumentation overhead from F1 telemetry; do not sum
overlapping columns or treat their differences as exclusive CPU attribution.
ORM hydration is measured separately by row count; its wall time is **not
isolated** from fetch, Python assembly and comparisons. No allocator-time
percentage or lock-wait attribution is claimed. F1 SQL cursor time excludes
server-cursor fetch, ORM hydration and commit. No new WAL/write metric was
collected by this read-focused task; projection/financial write architecture
was not changed.

Journal membership reads are a **separate residual**, not optimized here:
total Journal SQL at 0/10/50 trades changes 2/83/403 -> 2/74/354 only because
the embedded account mirror portion was batched. At 50, remaining query families
still include per-fill order/membership and per-trade header/annotation reads.
Journal wall sample changes 412.085 -> 470.849 ms: no Journal latency improvement
claim. No Journal profiles at 100/500 were predeclared.

## Remaining complexity and Rust

Complete canonical account JSON validation, full-history tuples/hashing,
per-reference serialization, historical fill replay, Journal membership reads,
`save_account` mirror upserts and observation order validation remain outside
this scoped change. A future account-size admission/product limit would need
an owner decision; no such limit or truncation is implemented.

**RUST_NOT_JUSTIFIED** for this task. Batch SQL removes the reproduced IO
amplification; these samples do not isolate a bounded deterministic CPU kernel
whose rewrite is justified. Future profiling may isolate validation work, but
native acceleration must not move transaction/financial authority. No Rust,
F4, cache, provider, strategy or frontend work is started.
