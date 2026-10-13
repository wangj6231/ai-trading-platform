# Journal analytics query V1

Approved seam: internal JournalAnalyticsService.evaluate(account_id, query=None), over the existing real Journal/Execution services.
Test seams: this read interface with confirmed gateway fills and real PostgreSQL; no mocked internal financial collaborators.

Query: as_of, closed_from, closed_to, symbol, side, result, strategy. Strict UTC, enums and bounded identifiers;
unknown fields and constructed bypasses reject. closed_from is inclusive, closed_to exclusive; inverted/empty ranges reject.
Dates refer to canonical execution closed_at, not order acceptance or UI time.
as_of defaults once to injected server time; future knowledge cutoffs reject. Receipt-visible replay comes first,
then CLOSED/date/dimension filtering. Scope/as_of/currency are always included in the response.

Account metadata is validated through ExecutionRepository; financial rows are obtained through the existing JournalService
receipt-aware replay, never SQL SUM over current CLOSED rows filtered only by closed_at.
Immutable account currency is checked independently; no account monetary total is used as a substitute for trade metrics.
Each read retains existing account read locks and rollback-only transaction behavior.
No SQL/query caller may provide trusted PnL, strategy identity or classification.

Strategy is a future filter seam only: current trusted attribution is null, so a requested strategy filter raises
AnalyticsNotReady, not a fake zero-return named strategy report. Missing account/corrupt evidence/unsupported currencies
fail explicitly; no silent zero-PnL fallback. An existing account with zero eligible trades yields a valid empty report.

No pagination is applied before aggregation. A future paginated detail UI must not aggregate only its page.
Existing account/fill/order/trade identity constraints remain intact. No migration, materialized summary or alternate ledger.
The current Journal path validates/replays full account history and loads detail metadata; this phase does not optimize it.
PostgreSQL plan evidence and the tested cardinality are recorded in the final report; no unmeasured scalability promise.
