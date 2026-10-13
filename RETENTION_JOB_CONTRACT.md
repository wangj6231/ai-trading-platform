# F5 financial retention — dry-run operation only

Scope: the four **TEST_SEAMS_CONFIRMED** financial lifecycle seams. This is not an object/archive job contract or a system-wide retention scheduler.

## Authority

`FinancialRetentionService.dry_run_candidate()` admits only current verified owner scope or an explicitly server-provisioned admin subject. It locks the canonical account, derives lifecycle expiry from immutable events, validates retained canonical account/mirrors, and generates hash-only evidence. It does not DELETE, cascade, weaken guards, mark sources removed or fabricate empty history.

ACTIVE: NOT_ELIGIBLE regardless of deletion-request age. CLOSED before expiry: NOT_ELIGIBLE. CLOSED at/after expiry: advisory candidate with evidence/readiness/blockers. Missing/corrupt retained evidence: NOT_READY; database outages are technical failures, never an approved purge.

## Execution/resource behavior

One authorized account per operation; existing database transaction deadline, statement timeout and pool limits apply. Scans fetch at most 100 rows per chunk in deterministic primary-key order. A serialized row over 8 MiB prevents a complete optional manifest. This does not truncate or cap financial history; canonical account validation can remain O(history) and history-sized in memory.

No durable job/checkpoint, background deletion, retry queue or global sweep is implemented. Repeating a dry-run recalculates current evidence without financial mutation; identical retained data produces identical inventory hashes. Lifecycle retries retain original accepted event identities/timestamps. No failed or incomplete operation is represented as a successful purge.

## Destructive frontier

Purge remains unimplemented and separately owner-authorized. Before any future purge, require complete candidate manifest, account/lifecycle identities, policy/expiry, rows/objects/reference inventory, reason, fresh readiness, approved operation, audit, bounded batches/checkpoints, restart behavior and verified retained recovery sources. Object inventory, archive hydration, deployed encryption/jurisdiction, DR verification and their test seams are **NOT_CONFIRMED / NOT_IMPLEMENTED in this slice**.
