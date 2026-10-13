# Gateway memory profile V1

Evidence: test-only RSS sampling (50ms F1 /250ms PG sampler), one tracemalloc
admission per profile, canonical history diagnostic and source inspection.
RSS is sampled, not an exact native allocation peak. `tracemalloc` omits native
allocators; its retained snapshot is not total allocations over the run.

| Shape |Peak RSS before/after bytes|Sample temporary traced peak before/after bytes|
|---|---:|---:|
|100 accounts|119,291,904 /120,463,360|265,974 /307,509|
|500 accounts|122,097,664 /123,154,432|523,776 /670,180|

The batch tradeoff modestly increases temporary memory; no memory-reduction
claim. Sample traced peaks are~0.225%→0.258% /0.432%→0.547% of same-sample RSS.
They are memory footprint ratios, **not allocator CPU-time shares**.
Retained after500 sample55,679bytes versus160,696before; relevant top allocations
are recorded in JSON. No sampled admission exceeded768MiB.

## Collections and lifetime

|Collection|Measured / source bound|Lifetime / risk|
|---|---|---|
|Validated market candle tuple|41 /201 per F1 admission; worker has existing catch-up cap|Input/admission; reparsed per account, O(range), not a user cache|
|Original order `.all()` archive|10 per F1 account;101 in history diagnostic|Formerly entire account history retained during admission|
|New streamed inactive orders|Fetch batch100;105-terminal corruption test crosses boundary|Cursor/iteration only; all rows validated, inactive model discarded|
|Typed hot orders / latest cursor map|10 per F1 account;no new global hard entry/byte cap|Account transaction only; O(pending work), never retained on Gateway|
|Changed order map / terminal list|Subset of touched account orders|100-candle processing region; can scale with actual fills/pending orders|
|Mark lookup / pending mark rows|At most100 existing +100 new per region (disjoint intervals)|One batch; fill-triggered flush/region flush releases pending work|
|Returned fills|0 in F1 worker;goldens cover real fixture fills|One call, O(actual fills); no new hard cap, cannot discard truth to bound memory|
|Account positions/trades JSON + typed arrays|0 worker-history trades;0/10/50 diagnostic,583/4,398/18,879 canonical bytes|Full account validation/per-fill update; size grows with history, not solved here|
|Trade/position mirrors / Journal memberships|N+1/full replay remains in existing readers|Request/transaction only; residual large-account risk, not a new cache|
|Gateway instruments / registry|Startup configured symbol/provider set, not per-user growth|Long lived; finite configuration but no new hard100-symbol enforcement|
|DB pool|F1 size3,overflow0|Bounded;4 sampled PG sessions includes separate observer|
|Telemetry|F1 ring4096, fixed dimension totals|Bounded long-lived operational evidence, no financial authority|
|Profiler counters/cProfile/tracemalloc|Two sampled calls,one allocation snapshot,20 retained top sites|Test-only; excluded from production|

Exact deep-object bytes per collection/native allocator time are UNKNOWN; RSS
and traced sample peaks above are measured rather than guessed totals. Canonical
serialized account bytes are not an estimate of Python object size.

There is **no new persistent account buffer/cache**. All request-local state is
discarded after commit/rollback; complete loss cannot erase PostgreSQL facts.
No eviction drops eligible orders, observations or fills. Existing transaction,
statement, pool and worker catch-up bounds remain; hot-order total and historical
account JSON are not claimed fully memory bounded.

Any later persistent buffer must define MAX_ENTRIES, MAX_BYTES, TTL if appropriate,
ownership, eviction/backpressure, rebuild and occupancy/eviction metrics before
activation. Financial authority must not depend on it. A future account-size
admission policy is not silently introduced in this task.
