# PRODUCT-FOUNDATION-F4.1 — Dashboard bounded composition

Final classification: PASS — scoped normal PostgreSQL Dashboard read composition.
Not D2 capacity PASS, not an all-path constant-time/memory claim.

User confirmed authorized account/positions/orders, Journal/Analytics, attachment
metadata/status paging and recovery/readiness seams. GRILL/TDD identified full
Account hydration/replay on normal reads, then verified RED/GREEN slices against
frozen canonical/public DTO oracles. The design skill kept display state distinct
from accounting Account and localized admission/recovery.

## Completed implementation slices

- Immutable receipt-visible display snapshots and revocable source admission.
- Normal PostgreSQL account/position DTO reads without full history hydration.
- Selected order list/detail identity; selected attachment Trade scope.
- No per-request full readiness count/join audit on admitted nonempty accounts.
- Source loss/replacement or unreconciled JSON stays NOT_READY until controlled
  recovery; a subsequent fill cannot conceal historical display loss.
- Existing recovery source streamed in100-row batches, no full input list.

Canonical Account/Gateway/financial allocator/Rust/strategy/config/ownership/frontend remain
unchanged. Type-only fill_display Iterable annotation supports streamed source;
the financial/VWAP algorithm is unchanged. Existing public HTTP DTOs unchanged.
Only new migration0014, not edits to old revisions. Two migration-head test literals
advance to0014. Financial sealed golden evidence is not re-generated or re-sealed.

## RED/GREEN evidence

Account summary24 SQL, positions98, order page4 and selected order detail4 failed
history-read budgets; attachment test proved10 unrelated Trade hydration instead
of at most1. Prefix deletion/replacement RED tests exposed unsafe later re-admission;
first-fill initial cash mismatch was separately reproduced before the fix.
Original failures and harness-only mistakes remain archived, not counted as passing.
Final collection adds21 Dashboard cases. Supplemental RED/GREEN contracts proved
missing storage fails closed, empty controlled rebuild must match initial replay,
and cancellation receipts must not acquire a derived readiness dependency. The
earlier empty-recovery experiment was already GREEN and did not reproduce the
claimed later-fill readmission; that inference was withdrawn. The corrected RED
test reproduced only the missing empty-rebuild replay comparison, not a fabricated
financial-loss claim. All raw RED/GREEN artifacts remain available.

## Changed authored files

Production/read composition:

- backend/app/journal/dashboard_reads.py (new distinct display type/read admission).
- backend/app/journal/records.py (derived tables and immutable display update guard).
- backend/app/journal/capture.py (transactional derived capture).
- backend/app/journal/readmodel.py (admission versus expensive audit separation).
- backend/app/journal/service.py (streamed controlled recovery).
- backend/app/journal/attachments.py (selected-trade scope, no whole Account hydration).
- backend/app/paper_http/service.py (bounded existing public read DTOs).
- backend/app/execution/trade_projection.py (Iterable annotation only).
- backend/migrations/versions/20261011_0014_dashboard_read_admission.py (new revision).

Tests/evidence helpers:

- backend/tests/integration/test_dashboard_composition.py (new public-seam regression).
- backend/tests/integration/test_postgresql_attachment_snapshot.py and
  test_postgresql_paper_auth.py (head revision literals only).
- backend/tests/fixtures/f41_canonical_http_oracle.py,
  f41_canonical_attachment_oracle.py, f41_canonical_journal_oracle.py (frozen test-only
  pre-change DTO oracles, never production fallback).
- backend/tests/fixtures/dashboard_composition_profile.py,
  dashboard_composition_evidence.py, dashboard_composition_coverage.py,
  dashboard_recovery_check.py (owned measurements/verification).

Four required root documentation outputs are created. Generated evidence is under
experiments/product_foundation_f4_1. Existing user work is not staged/reset/replaced.

## Protected identity and authority

Protected-file comparison permits only the eight app files and one new migration
above. Frontend source/tests, Rust source, config and all old migrations match the
pre-phase SHA-256 inventory. Frozen financial oracle remains sealed, SHA-256:
6e3dcb0c10d884248e7b473d60de7fc72e62683b3d0a40132175a296599ecd69.

Strategy version remains deterministic-smc-ict-v1; config_hash remains
0c26e108e361b288604b383ca68ea9df80f2595fe919d39cf9ce0dfb57ffeeab;
source_content_hash remains
5c168ba5333c16ad16c65709d631d3241be52ce7771e7117a1656a3a3f828abb;
algorithm_build_hash remains
d4e4a294e7688730671756da13e3913130a0e2e42611ce8ec4efbf4a9281566d.
The canonical strategy manifest excludes these Paper read-composition files. No
claim that application code is wholly unchanged: its actual SHA inventory is recorded.

## Final measurements

Identical owned real-PG canonical shapes0/10/50/100/500 and cutoffs: all34 public
response hashes equal. Final source measurement is after_final.json; intermediate
after.json is retained. At500, Account SQL1,008→3 and Positions4,516→3. Selected
orders8→3 and attachments14→10; Journal44→43 and Analytics15→14. Journal's sampled
wall time increased, so no universal speedup is claimed. Detailed wall/CPU/RSS,
allocations, returned rows, bytes and representative EXPLAIN plans are in the
profile documents/JSON. Original BEFORE scanned-row plans were not captured;
returned rows are not relabeled as scanned rows.

The optional1,000 shape was not executed in F4.1: it has no paired sealed dump,
because F4's original capped escalation stopped at624. This phase reuses the five
complete identical shapes rather than fabricating larger-account results.

## Final verification and counting policy

| Evidence | Actual result |
|---|---|
| Complete non-PG partition |1,610 passed,0 failed/skipped;36m37s|
| Initial complete PG partition |390 passed,1 compatibility failure,0 skipped;28m12s|
| Final affected-seam replay, current production source |379 passed,0 failed/skipped;9m25s|
| Current collected unique backend nodes, latest evidence |2,005 passed,0 failed/errors/skipped;0 missing/unexpected|
| Actual PG16.11 unique nodes within that collection |395 passed,0 failed/skipped|
| New Dashboard public-seam cases |21 passed, included above, not added twice|
| Final combined coverage, unchanged90% gate |91.88915174045286% (91.89%)|
| Ruff / mypy |PASS / PASS (157 source files)|
| compileall / git diff --check |PASS / PASS|

The complete collection was run as two disjoint partitions; this is NOT a claim of
one uninterrupted final all-green2,005-case command. The initial PG failure was an
existing assertion requiring the word "rebuild" in the new NOT_READY message.
Production wording was corrected without weakening its test. The379-case final
replay covers all eight changed app files, the failed regression, and the four
cases added after original collection. verification_counts.json maps latest
results to all currently collected nodes and asserts no omissions/duplicates.
Raw failing evidence remains preserved. No historical suite counts are substituted.

Partial PG/focused coverage runs individually reported69.98%/51.15% against the
whole-app90% threshold, so those command exits are not called successful coverage
gates. Final coverage combines unchanged-file full-collection evidence with ONLY
final-seam evidence for changed app files (no stale changed-file line maps), then
the original configured coverage report gate passes at91.89%. No threshold reduced.

Re-executed suites include F4 Journal/Analytics, account mirror batching, Gateway
golden/hot path, Observation Worker, Paper accounting/execution, Auth/HTTP, Paper
E2E, attachments, strategy identity, PIT/look-ahead and Rust alignment. Existing
real-PG migration roundtrips downgrade below0014, re-upgrade to0014, reject reads
until controlled recovery, and verify canonical evidence remains unchanged.
TEST_POSTGRES_URL was process-scoped to isolated PostgreSQL; DATABASE_URL was not
globally set. Owned temporary database helpers restore their process environment.
Frontend was unchanged and not rerun.

## Remaining limitations and stop boundary

- Durable display storage grows with fills and distinct historical symbol footprint;
  no F5 retention/purge or persistent process cache is introduced.
- Controlled recovery source is streamed100 rows at a time, but the unchanged typed
  canonical/replay Account remains history-sized; total recovery work is not bounded.
- Financial writer validation and canonical audit/list deliberately retain complete
  source checks. A full audit DTO still requires full historical output.
- Analytics aggregation and Journal query planning can still perform history-dependent
  database work. PASS concerns removal of full-history Dashboard composition/hydration
  and per-request readiness audits, not O(1) database analytics or all account sizes.
- Least-privilege runtime DB credentials and schema/trigger integrity are deployment
  requirements; this certificate is not arbitrary privileged DBA-tamper protection.
- No new hard financial account-size policy, commercial capacity, or Rust feasibility
  approval is inferred from these measurements.

The design skill kept display evidence separate from financial authority; GRILL/TDD
kept unsafe recovery/failure states visible and required canonical DTO parity.
STOP after F4.1. F5, Rust expansion and financial semantics changes were not started.
