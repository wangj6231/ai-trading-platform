# F4.1 recovery memory

Measurements complete; full regression remains tracked in the phase report.
Evidence: experiments/product_foundation_f4_1/after_final.json (final production
build); earlier after.json is preserved as an intermediate measurement.

## Buffers and lifetime

| Buffer | Row policy | Bytes policy | Lifetime |
|---|---|---|---|
| Joined fill/order recovery source | READ_BATCH_SIZE=100 source pairs | Each canonical document variable-sized; no new financial byte truncation | One server cursor/account transaction |
| Position-display episode source | DISPLAY_SOURCE_BATCH_ROWS=100 | Canonical fill event size; streamed, not tuple materialization | One affected position per capture |
| Canonical mirror validation | Existing mirror batch=100 | Strict existing canonical schema | Existing Account parse |
| Typed origin Account | Complete referenced canonical history | Measured account JSON / RSS, not an invented admission limit | Recovery transaction |
| Replay Account | Existing allocator retains complete history | History-sized; no dropped evidence | Recovery transaction |
| Previous display state | One prior snapshot/current symbol set | Depends on symbol cardinality, not closed-trade count | One capture |
| ORM identity map | Source cursor batches plus current writes | Sampled peak entries / traced allocation / RSS | Closed on transaction exit |

No persistent process cache. Source fetch rows are bounded but the canonical typed
Account and original allocator output are not globally constant-memory. Rebuild is
not promised linear-time: the unchanged allocator and repeated validated capture
can retain growing CPU cost. Financial writes also retain original history checks.
The task does not authorize a replacement financial model or arbitrary history cap.

Resource limits of the measurement harness are cooperative 900 seconds between
seams and sampled RSS 768 MiB, not a hard real-time interrupt inside a DB transaction.
The existing DB transaction and statement deadlines still apply. Allocation tracing
is enabled for AFTER rebuild only; before/after rebuild wall times are consequently
not directly comparable. Normal read samples use the same tracing on both sides.

The 1,000-trade baseline is not fabricated: F4's original capped seed stopped at624
and produced sealed complete shapes only through500. F4.1 reuses those exact five
complete dumps. No1,000 paired result or D2 capacity claim is made.

## AFTER recovery measurements (traced)

| Closed trades | Wall seconds | Traced peak bytes | Peak sampled ORM identities | Canonical account JSON bytes |
|---:|---:|---:|---:|---:|
|0|0.20|1,826,811|2|612|
|10|0.70|1,408,693|55|4,677|
|50|3.27|3,054,034|255|20,118|
|100|7.92|3,751,482|401|39,416|
|500|75.59|6,875,525|401|193,817|

At500: process CPU70.875s, SQL10,032, cursor7.611807s, sampled process RSS146,493,440
bytes. Peak ORM identities plateau at401 in these100/500 samples, not a formal
global bound. Total typed/history allocation still grows. JSON bytes are persisted
representation size, not the Python heap size. A byte-level hard admission policy
is not introduced; larger-account memory remains a future owner frontier if needed.

BEFORE rebuild500 was14.37s without allocation tracing and before the added display
projection capture. It cannot be labeled a before/after performance improvement.
The new derived capture adds writer/recovery work. This is separated from normal
read wins and not hidden in account latency. No future Rust implementation is begun.

The immutable display snapshot itself has one position per historically used
symbol (including the preserved last closed position), not per closed trade.
Its size is not hard-capped at the HTTP position-list limit. The approved symbol
shape bounds the operational footprint; arbitrary symbol cardinality is not proven
constant-memory. No owner-approved account-size restriction is invented here.
