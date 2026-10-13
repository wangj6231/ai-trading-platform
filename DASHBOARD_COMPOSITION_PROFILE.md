# F4.1 Dashboard composition profile

Matched final-build measurements complete; full regression is tracked separately.
Primary comparison: before.json versus after_final.json. The earlier after.json
is preserved, not overwritten; final measurement includes the last boundary fixes.

Actual isolated native PostgreSQL16.11, Windows / CPython3.12.4. F4.1 before was
recorded before production changes. Same canonical dumps and cutoffs are restored
into random owned disposable databases for after. No production or research data.

Shapes0/10/50/100/500; no paired1,000 dump exists because the original F4 escalation
hit its declared cap. Do not infer larger-account or D2 capacity.

Normal read samples include allocation tracing on both sides. Record wall, process
CPU, cursor SQL time/count, sampled RSS, traced peak allocations, ORM hydration,
returned cursor rows, response bytes/hash and serialization time. Returned rows
are NOT rows scanned. AFTER representative EXPLAIN ANALYZE/BUFFERS plans run outside
latency samples; node rows are logical visits, not unique physical rows. BEFORE
scanned-row plans were not captured and cannot honestly be reconstructed as that
original measurement. Rebuild is separate and has AFTER-only allocation tracing.

The unchanged canonical audit/list is deliberately reported separately from normal
product paths. Analytics aggregation remains database-history-sized; Journal DTO
cost follows selected page/fill limits, not unrelated closed history. No latency
promise, commercial readiness, profitability inference or Rust expansion.

## Query count, identical canonical inputs

| Closed trades | Account before/after | Positions before/after | Orders before/after | Journal page before/after | Analytics before/after | Attachments before/after |
|---:|---:|---:|---:|---:|---:|---:|
|0|2 / 4|4 / 4|2 / 3|4 / 3|8 / 7|not applicable|
|10|24 / 3|98 / 3|4 / 3|44 / 43|15 / 14|10 / 10|
|50|104 / 3|458 / 3|4 / 3|44 / 43|15 / 14|10 / 10|
|100|204 / 3|908 / 3|4 / 3|44 / 43|15 / 14|10 / 10|
|500|1,008 / 3|4,516 / 3|8 / 3|44 / 43|15 / 14|14 / 10|

All34 response hashes match across completed shapes. Empty-state overhead is not
universally reduced. Selected page10 Journal work is bounded by returned trade/fill
evidence; response size is unchanged. Canonical audit/list retains3,508 SQL at500
before and after and is NOT a normal Dashboard path.

## 500-trade sample

| Seam | Wall before / after seconds | Traced peak before / after bytes | Cursor returned rows before / after |
|---|---:|---:|---:|
|Account|45.488940 / 0.012333|9,532,416 / 67,122|2,001 / 3|
|Positions|86.873221 / 0.009473|18,766,795 / 47,703|6,502 / 3|
|Orders page10|0.488033 / 0.021253|1,984,842 / 144,421|12 / 13|
|Journal page10|0.221430 / 0.378350|512,564 / 571,679|33 / 33|
|Analytics|0.140658 / 0.115887|478,829 / 498,517|13 / 13|
|Attachments|0.505536 / 0.034672|1,993,698 / 167,244|9 / 11|

These single traced samples are not percentile/SLO measurements; improvement is
not claimed for every route. Account AFTER: CPU0.015625s, cursor0.002312s, sampled
RSS142,020,608bytes, response752bytes. Positions response577bytes. Account/positions
hydrate one admission and one display snapshot, not Account/Trade/Fill history.
Attachment scope hydrates exactly one selected canonical Trade; two source/reference
rows validate this two-snapshot page. Exact artifacts are authoritative.

Actual500 Account EXPLAIN: account identity index returns1, admission primary-key
index returns1, account/sequence snapshot index under LIMIT returns1, with0 rows
removed by filter. The unique account/sequence index supplies current latest-state
lookup. Historical cutoffs may traverse later sequence entries; no constant-time
arbitrary-history claim.

BEFORE phase224.472226s; final AFTER137.539484s includes heavier traced rebuild and unchanged
audit. Phase totals are not normal Dashboard latency. AFTER plans run outside read
timing; recovery measurements are described separately.

Full per-shape CPU/RSS/serialized bytes and plans are retained in JSON rather than
summarized into misleading overall averages. Worker/Gateway/provider workloads are
not measured by this read-only profile. No provider requests occur in this harness.
