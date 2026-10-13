# Journal execution consumption contract

The server execution repository admits the confirmed fill and runs the canonical allocator as before.
After canonical account/trade persistence flushes, `capture_fill(session, updated_account, event)` inserts
only Journal identity, fill association and entry/exit screenshot job metadata in the **same transaction**.

The updated event-symbol position retains the affected Trade ID even when quantity becomes zero.
First opening fill creates one Journal identity and ENTRY_CHART job; same-direction fills remain ENTRY references.
Partial reductions become EXIT references; the canonical Trade is not closed yet.
Final reduction closes the canonical Trade and schedules exactly one EXIT_CHART job.
Journal lifecycle is derived from canonical closure and referenced entry/exit quantities, not copied mutable financial state.

Fill identity remains `(execution_source, trading_account_id, external_fill_id)`; event ID references the immutable fact.
Journal association has one event_id primary key, and jobs have stable server hashes and unique trigger keys.
An additional partial unique index enforces one ENTRY_CHART and one EXIT_CHART per trade, even across different fills.
Same economic replay returns the original execution receipt, so neither fees nor Journal rows/jobs are applied twice.
Concurrent ingestion remains under the original account lock; no financial operation occurs in a separate Journal transaction.

Database failure before commit produces no partial-success acknowledgement. Fill, account, Trade, reference and pending
job roll back together, and safe retry can admit once. Image rendering/storage happens outside ingestion;
its failure never undoes already committed financial state. There is no renderer in this phase.

Late receipt is visible only from server received_at, never backdated to filled_at.
Rebuild reuses immutable order profiles and the same `apply_fill`, preserving sequence and flat-to-flat identity.
It does not overwrite execution or create strategy risk evidence. Existing reference conflicts require explicit investigation.
Paper and a test-only independent connector use this same Journal consumption seam; provider/source are provenance only.
