# Journal / Analytics read model V1

## Authority and admitted scope

Canonical ExecutionEvent → allocator → canonical Trade → immutable Journal
membership remains financial authority. No strategy, execution policy, Decimal
policy, cash, collateral, fees, lifecycle or Rust interface changes are admitted.
The derived `journal_read_states` table never feeds ExecutionGateway, accounting,
order admission or a balance calculation. Browser/provider input cannot write it.

`capture_fill()` receives the already validated canonical Account/event after
allocation. It records one schema-V1 Trade state per admitted fill, in the SAME
financial transaction. This history is necessary for OPEN/partial/PIT detail;
only the one terminal snapshot of each closed episode participates in Analytics.
Values are copied from canonical Trade, not calculated using a new PnL formula.

## Identity, knowledge and readiness

Primary identity is canonical event_id; account + execution_sequence is unique.
known_at is immutable event.received_at, NOT filled_at/closed_at/server wall time.
cutoff inclusion is `known_at <= as_of`. Equal timestamps use canonical sequence.
Old snapshots are never overwritten by later fills. Schema version is 1, not a
StrategyConfig setting or independent financial contract/version.

Account FOR SHARE serializes reads against financial commits and controlled
rebuild. Readiness requires count to match canonical fill count and maximum
sequence to match canonical last_sequence, plus source/membership/scope/receipt
checks. Canonical sequence is strictly increasing, NOT assumed contiguous.
Missing/deleted rows are NOT_READY, even if the requested trade still exists.
No partial generation, stale success or canonical replay fallback is served.
Missing table/storage errors become JournalReadNotReady; HTTP uses the existing
redacted EXECUTION_INTERNAL_ERROR with status 503, not an empty financial report.

## Canonical validation vs read admission

Financial commands retain full Account JSON, position/trade mirrors, Decimal,
immutability, reconciliation and fill admission validation, unchanged.
Normal reads select immutable account identity/provider/environment scalars,
NOT a partially validated accounting Account or full history document.
Trade detail reparses the selected strict Trade, checks state hash/scalars,
canonical final/current mirror when applicable, and canonical fill evidence.
Analytics financial SUM/count inputs come from canonical ExecutionTradeRecord,
not cached projected money. Terminal read-state disagreement fails closed.
Rebuild reparses the FULL canonical Account and uses the SAME canonical allocator;
the final replay must equal the canonical Account. A projection is never used to
repair canonical financial facts. Hashes detect inconsistent documents; they are
not signatures against a privileged database administrator.

## Normal read paths and bounds

- HTTP Journal/Trade page: scoped keyset query, at most limit+1 state rows;
  existing page limit 100, embedded detail fills limit 1,000 and HTTP 2 MiB guard.
  One account readiness check per page; hydrate selected trades only.
- HTTP fill page: at most limit+1 fill/reference rows. Does NOT assemble the
  complete trade fill list to return a single page.
- HTTP detail: selected trade only, existing 1,000-fill bound; attachments are
  served separately via their existing bounded page contract.
- Analytics: PostgreSQL exact NUMERIC aggregates + bounded best/worst queries;
  no Account history, order history, fill history or JournalTrade arrays hydrated.
- SQLite test adapter: stream batches of 100 scalar canonical trade rows into
  Decimal accumulators. Never SQLite SUM/CAST to binary float.
- `JournalService.list_trades()` remains explicit legacy/canonical audit
  enumeration with an unbounded tuple output. Normal HTTP/Analytics MUST NOT
  call it. Existing position HTTP composition still uses that legacy path;
  position/dashboard-account financial read optimization is outside F4.

No long-lived per-account cache exists. Buffers live for one read/transaction.
Per-symbol Analytics output uses MAX_ANALYTICS_SYMBOL_GROUPS=100 (the approved
foundation target shape), with at most 101 distinct rows inspected. Overflow
returns explicit NOT_READY, never a partial financial aggregate. This is a
reporting resource budget, not StrategyConfig or account-history truncation.
Initial production instrument scope is BTCUSDT/ETHUSDT. This is NOT evidence of
unlimited-symbol reporting or 10M-trade capacity. Internal audit/detail outputs
and per-account canonical rebuild state are explicitly not bounded normal HTTP
buffers; no financial history is truncated to make a benchmark pass.
Canonical Trade state has fixed scalar fields and bounded identifiers/numbers,
not Position lots or Account history arrays. Per-fill history therefore does not
copy the full growing Account. Raw privileged database corruption is not trusted
canonical input; neither hashes nor resource bounds are administrator signatures.

## Cursor and metadata parity

Order is opened_at, trade_id, with explicit PG C / SQLite BINARY ordering to
match Python stable identifier ordering. Cursor remains signed, opaque,
subject/account/resource/filter scoped and pinned to a server knowledge cutoff.
No symbol/global trade-ID lookup bypasses TrustedPrincipal/account ownership.

Annotations remain mutable current metadata, NOT an invented append-only PIT
history. When updated_at is after cutoff they are absent, exactly as before.
Tag continuation uses the EXACT old digest over episode-order `(trade_id,
annotations)` pairs, streamed in batches of 100. Membership changes still 409;
missing filtered anchors still 422. This retains an O(history) metadata scan for
tag cursors, but no financial replay or full history allocation. Untagged page
selection is keyset/indexed. Attachment future-completion masking is unchanged.

## Analytics invariants

Financial win/loss/breakeven derive from canonical net_pnl; flats enter the existing
resolved-trade win-rate denominator. gross_loss is positive magnitude of NET
losses; average_loss signed. gross_pnl, total_fees and net_pnl stay separate.
No-loss profit_factor remains null. average_r/r_observations and absent strategy
attribution remain their original null/zero/NOT_READY contracts.
Best/worst ordering remains `(net_pnl, closed_at, trade_id)` with sign reversal
only for best. Averages/ratios use existing PAPER_DECIMAL_V1 divide/multiply;
PostgreSQL sums exact NUMERIC. Symbol groups use bounded Python codepoint sorting
independent of deployment collation (real PostgreSQL ICU RED/GREEN regression).
No new expectancy, R, strategy or setup attribution.

## Limitations / operational obligations

Readiness/source checks and exact aggregation still scan index-selected history
in PostgreSQL; this is not a constant-time all-history summary. Rebuild and audit
remain expensive per-account operations. Controlled replacement is serialized
with account writes; timeout rolls the whole replacement back. Huge-account
generation/checkpoint rebuild is a future separate task, not implemented here.
F4 does not prove D2 commercial capacity, DR readiness or public activation.
