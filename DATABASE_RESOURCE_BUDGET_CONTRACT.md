# Database Resource Budget Contract — F1

`Database` retains write commit-before-return/rollback and non-committing read scope. Engine measurements
record count/duration only; no financial/private SQL parameters retained. No new schema/migration.

## PostgreSQL deployment controls

| Setting | Default | Bound |
|---|---:|---|
| database_pool_size | 5 | 1–100 |
| database_max_overflow | 10 | 0–100 |
| database_pool_timeout_seconds | 30 | >0–60 |
| database_pool_recycle_seconds | 1800 | 60–86400 |
| database_statement_timeout_ms | 30000 | 1–300000 |
| database_idle_transaction_timeout_ms | 60000 | 1–300000 |
| database_transaction_max_seconds | 120 | >0–600 |
| database_slow_query_seconds | 0.5 | >0–60 |

SQLAlchemy PG QueuePool controls explicit; SQLite test pool remains dialect-compatible, not proof of PG behavior.
PG connect config sets bounded integer statement_timeout/idle_in_transaction_session_timeout and commits setup
before business work. Pool checkout is bounded and reusable after exhaustion; query cancellation rolls transaction back.
Transaction max is a **cooperative pre-commit deadline**, not interruptible Python/whole-request timeout.
No interruption after commit or replay of financial command by instrumentation. Long CPU work remains bounded only
by its original module and next deadline check; don't claim this is hard process isolation. PG statement timeout
and idle-transaction timeout separately bound server SQL resources. Read CPU/whole-operation timeout not added.

Process budget: sum(process_count × (pool_size + overflow)), with connection allowance for concurrent HTTP work,
background work, migration/admin/backup and session advisory locks. Existing worker holds one session lock connection
over network, then needs additional query/transaction connection; pool size1 can exhaust instead of silently deadlock.
Do not apply transaction-pooling proxy to advisory-lock connection. No normal financial row transaction waits for provider
network; existing lock acquire commits prior to retrieval, worker release/cancellation semantics unchanged.
Connection budget is not PostgreSQL max_connections and not D2 capacity. Choose real per-process budgets from F1 runs.

## Measurement / safety

Engine before/after/error events observe SQLAlchemy-executed queries; ContextVar accumulates request/harness count/time.
Raw DBAPI connection setup, migration engines and pool checkout wait are outside this query counter;
checkout bounds are exercised separately, and enclosing HTTP/worker wall timing includes waits.
Transactions emit duration; raw query statements/parameters/URLs/errors never telemetry fields.
Engine hide_parameters=True; SQL echo remains local diagnostics only, forbidden in staging/production Settings.
Detailed traceback similarly opt-in/local; local logs still require trusted handling, no claim of full third-party redaction.
Query/transaction exceptions remain technical failures; no order rejection or cost/eligibility change.

Verification requires actualPG: checkout exhaustion/time, connection recovery/accounting, SHOW timeout,
pg_sleep cancellation, rollback-before-commit deadline and complete existing PG immutability/isolation regression.
Process-scoped TEST_POSTGRES_URL only; no globally configured production DATABASE_URL. Migration helper temporarily
sets/restores its own process DATABASE_URL solely for existing Alembic environment; never emits the value.
No tuned strategy values/financial policies; infra configuration does not change config_hash.
