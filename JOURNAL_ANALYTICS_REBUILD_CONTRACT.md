# Derived Journal recovery V1

## Operator interface

`JournalService.rebuild_read_model(account_id)` is internal/server-owned, not a
browser HTTP write. Verify ownership/operational authorization before invoking
from any future job. It acquires the existing canonical account write lock,
validates full Account and mirrors, deletes ONLY that account's derived read
states, and streams canonical fill/order source rows in batches of 100.

Reconstruction uses existing replay_steps/apply_fill and capture_fill, preserving
immutable Journal references, attachment job deduplication, annotations and
terminal attachment receipts. Original canonical trade/fill/cash/fees/state
are not rewritten. Final reconstructed account hash must equal canonical state;
readiness must match source watermark. Failure rolls back deletion AND writes.

The existing reference/job `rebuild()` stays idempotent and also reconstructs
missing read states. Conflicting existing read states are NOT silently accepted;
use controlled derived replacement after investigating canonical disagreement.

## Completeness and concurrency

One account transaction replaces all derived history atomically. Readers lock
account FOR SHARE and see old complete state, new complete state, or explicit
NOT_READY if the projection was lost. They cannot see intermediate rebuild rows.
Canonical financial fills/rebuilds serialize using the SAME account lock. No
outbox/queue/Redis/Kafka is needed because capture and ledger commit are local to
one PostgreSQL transaction. A failed projection insert rolls back financial fill
admission; retry uses existing command/fill identities and original receipt.

Duplicate events do not add snapshots; conflicting event identity/state does
not update immutable history. PostgreSQL and ORM reject derived-state UPDATE.
DELETE/TRUNCATE is allowed for derived recovery, unlike canonical ledger deletion;
completeness checks reject loss. Missing table is explicitly unavailable, not
empty. Alembic re-upgrade recreates an empty projection, NOT trusted fake history.

## Knowledge-time replay

Rebuild orders canonical sources by filled_at / execution_sequence under existing
monotonic admission invariants. Snapshot known_at remains original received_at.
Historical reads use inclusive known_at cutoff; late receipt never rewrites the
previous visible prefix. Equal filled_at rows retain canonical execution sequence.
Metadata and attachment completion visibility retain their own existing cutoff
rules. No current annotations are invented for an old prefix.

## Bounds and deployment gate

Source IO is batched 100; canonical per-account typed state and allocator history
are still required, not truncated. This is not a system-wide 10M-trade in-memory
rebuild. Operators must run per-account recovery within configured transaction
deadline; failure leaves old state or NOT_READY. No request auto-rebuilds.
Deployment upgrading existing accounts must run controlled rebuild before serving
their derived reads. Fresh empty accounts return an empty report legitimately;
legacy non-empty accounts fail NOT_READY until fully reconstructed.

Reconciliation must compare canonical oracle/normalized transport with direct
incremental state and reconstructed state at identical cutoffs. This is a
recoverable read optimization, not a new source of financial authority.
