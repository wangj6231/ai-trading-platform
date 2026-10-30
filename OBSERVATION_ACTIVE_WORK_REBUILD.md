# Observation active-work rebuild — V1

This is a server/operator maintenance action, not an authenticated browser API.
The projection is a PostgreSQL logical view over canonical orders/accounts, with
one measured pending-order index and a versioned definition fingerprint. It contains no
copied order status, cursor or financial balances. Cache/projection loss cannot
erase a canonical financial fact.

## Procedure

1. Verify the operator targets the intended database/region and has the approved
   maintenance authorization. Record the migration head and canonical ledger
   hashes/counts. Do not use browser-supplied work or ownership.
2. Pause observation scheduling, or leave workers running in `NOT_READY` if the
   view/index/fingerprint is missing. There is **no unbounded PG fallback**.
   Existing Gateway transactions finish; advisory stream ownership remains in
   force. Do not delete checkpoints, rewind orders, or skip backlog.
3. Call `ObservationRepository(database).rebuild()` from the controlled server
   maintenance context. This invokes `install_v1` in one owned DDL transaction.
   View, source indexes and schema fingerprint become visible atomically. No
   financial row backfill/update occurs. Repeated rebuilds are idempotent.
4. Rebuild uses PostgreSQL DDL locks and the existing statement timeout. Index
   recreation can block writers. Use a maintenance window; it is not an online
   concurrent-index build or a latency promise. On failure, rollback restores
   the prior committed schema; a missing projection remains unavailable.
5. At one fixed cutoff run `shadow_parity(gateway, symbol, cutoff)` against the
   old canonical discovery and new view in one `REPEATABLE READ` transaction.
   Compare **account identity and exact first-open cursor**, not only counts.
   Validate all supported symbols, budgets and required indexes.
6. Resume scheduling only after parity/health succeeds. Replay the same contiguous
   eligible range from canonical per-order cursors. Checkpoints only suppress a
   previously delivered same-cutoff batch; they never manufacture order progress.

## Failure / recovery invariants

- Missing view/index, drifted definition, missing/wrong schema version, invalid
  index or excessive work/account cardinality: `ACTIVE_WORK_NOT_READY`, no
  provider fetch, no partial candidate dispatch.
- New/cancelled/filled/rejected/partial orders are read from the same committed
  canonical facts. No outbox drain, process cache or asynchronous refresh needed.
- Crash after financial commit but before delivery checkpoint: immutable order
  cursor/fill identity and Gateway retry authority remain unchanged. Open-position
  valuation work remains discoverable.
- A privileged database administrator can rewrite schema and its fingerprint.
  This is not a cryptographic defense against the trusted DBA. Application roles
  must not have DDL or fingerprint-write permission in deployment.
- Deployment grants must allow the internal worker to read the work view/schema
  and its existing canonical/checkpoint tables. Rebuild/migration uses a separate
  privileged maintenance context; the runtime worker does not repair schema
  automatically. There is no browser/database grant or new public rebuild route.
  Local tests use the owned test-cluster role, not a verified production role
  deployment or PostgreSQL RLS implementation.
- A malformed canonical ledger is not repaired by this view. Gateway retains
  its full canonical validation and rejects corrupted selected state.

Real-PG loss/drift/index-loss/rebuild, transaction rollback/commit, restart and
migration downgrade/re-upgrade tests protect this procedure. See the F3 report
for newly executed counts; no unperformed disaster recovery/capacity claim.
