# Execution Gateway hot-path contract V1

## Authority and scope

`ExecutionGateway.observe()` remains financial authority. This change optimizes
observation dispatch/persistence, not financial rules, instrument precision,
fees, collateral, execution policy, strategy, authorization or HTTP contracts.
No persistent cache, projection ledger, Rust component or migration is added.

Before production edits, real PostgreSQL F1 small/intermediate profiles and
10 fixed-identity canonical financial scenarios were sealed. Red query tests
demonstrated 5/205 mark SELECTs rather than the required 1/3 batches.

## Transaction-local algorithm

1. Revalidate market schema, OHLC, ordering, continuity, closed-1m cutoff,
   freshness and provider capability exactly as before.
2. Read and validate canonical account state/mirrors; retain account row lock.
3. Stream **every** account order in command sequence, in 100-row fetch batches.
   Validate schema, frozen instrument, immutable intent/hash/mirrors for all
   rows, including cancelled/terminal/non-symbol rows. Retain typed hot orders
   only. This is not a filtered unvalidated projection or cross-request cache.
4. Process candles chronologically in batches of at most
   `OBSERVATION_BATCH_SIZE = 100`. Fetch existing marks for only that account,
   symbol and those closed intervals. No future/full-archive mark lookup.
5. At each candle retain exact acceptance/cursor eligibility and missing-next-
   candle rejection. Iterate hot orders in original command sequence.
6. Proposals still pass through unchanged adapter normalization and repository
   admission: duplicate economics, order/profile/scope, account/position,
   Decimal accounting, available capital, reduction and Journal checks.
   Before admission materialize the latest cursor into its canonical row.
   After any admission/rejection reparse the changed order. A proposal-free
   frozen order reuses its validated immutable fields, with only a cursor copied
   from the validated candle. Remove terminal orders from this local hot set.
7. Compare every existing mark's immutable hash/price. Add every missing mark.
   Coalesce proposal-free cursor writes and flush at batch end. Fill admission
   retains its own existing flushes; this is not a promise of constant SQL for
   fill-bearing batches.
8. **One transaction commits the entire observation**, never each batch.
   Exception at any point rolls back prior batches, fills, Journal, cursors and
   marks. Worker checkpoint/delivery remains after successful Gateway commit.

## Why coalescing is safe

Intermediate pending-order cursor writes were uncommitted implementation work,
not externally available financial facts. Every chronological eligibility check
still occurs, every market mark is preserved, and every fill/sequence is admitted
individually. Admission receives current typed/canonical order state, not a stale
cached cursor. No final row, fill receipt, fee, cash, collateral, Journal or
Analytics value may change. The sealed oracle covers full table evidence as well
as account, Journal, Analytics, order retry and duplicate fill retry.

## Bounds, failures and residual limits

100 is a named operational buffering limit, not a StrategyConfig parameter or
trading threshold. Mark buffers/fetches are bounded by it. Local hot-order/fill
sets still scale with actual account work and have no new hard byte cap; see the
memory report. There is no TTL/eviction of financial authority. Transaction-
deadline/SQL/pool limits, DB triggers, canonical checks and immutable facts
remain. Complete buffer loss simply aborts/rebuilds from PostgreSQL.

This does **not** eliminate full account JSON/mirror validation, canonical
archive scanning once per observation, or per-fill account-history computation.
Those are separately measured residuals, not permission to bypass validation.

No public/D2-capacity, exact broker execution or profitability claim follows
from this isolated fixture benchmark. No Rust rewrite/F4 is authorized here.
