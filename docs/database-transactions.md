# Database transaction contract

## Purpose

This document defines who owns SQLAlchemy sessions and transactions. It is an
application integrity contract: it does not change signal generation, market
analysis, execution simulation, or any trading parameter.

The original M-06 gap was narrow but material. `get_db_session()` opened a
session and closed it after a FastAPI dependency yield, while neither that
dependency nor a production application service defined commit and rollback
semantics. `SignalRepository` correctly used `flush()` without `commit()`, but
there was no canonical production owner that made its writes durable. No public
write API consumed the dependency, so no historical partial write was found;
the ownership contract itself was nevertheless ambiguous.

## Production inventory

| Component | Responsibility |
|---|---|
| `Database.session_factory` | Creates a fresh, non-reusable SQLAlchemy `Session`; sessions are never global or shared between requests/workflows. |
| `Database.transaction()` | Sole generic write transaction owner: create session, begin, yield, commit, rollback on any exception, close. |
| `Database.read_session()` | Non-committing read scope: create session, yield, roll back any implicit read transaction, close. |
| `get_db_session()` | FastAPI read-only dependency backed by `read_session()`. It is not a mutation unit of work. |
| `SignalPersistenceService` | Application service that wraps each signal create or lifecycle transition in exactly one `Database.transaction()`. |
| `SignalRepository` | Performs caller-scoped reads/writes, obtains row locks, and flushes constraints. It never commits, rolls back, or closes. |
| Alembic | Uses Alembic's separate migration transaction machinery; application helpers do not wrap migrations. |

There are no production `AsyncSession`, `scoped_session`, nested transaction,
SAVEPOINT, background database writer, scheduled database writer, or automatic
transaction retry paths. Test-only `session_factory.begin()` and raw engine
transactions exercise low-level PostgreSQL constraints and do not define the
production ownership model.

## Write transaction lifecycle

The production mutation flow is:

```text
API / caller
  -> SignalPersistenceService
     -> Database.transaction(): open + begin
        -> SignalRepository operation(s)
           -> flush pending row and surface immediate constraints
        -> build detached typed response
     -> commit
     -> close session
  -> return success
```

`SignalPersistenceService` returns only after the context manager has completed,
which means the final commit has already succeeded. A commit failure raises a
safe `SignalPersistenceError`; a caller cannot receive the pending success
value. Known integrity failures are mapped without exposing SQL, credentials, or
the database URL. Unexpected database failures are rolled back and propagated
to the existing sanitized application error boundary rather than swallowed.

On every exception, including domain errors, constraint/trigger failures,
unexpected exceptions, and commit-time failures, `Database.transaction()` calls
rollback and then closes the session. Sessions are configured with
`close_resets_only=False`; a closed or failed workflow session cannot be reset
and accidentally reused. A later workflow receives a different session and a
clean transaction.

There is no broad automatic retry. Retrying a non-idempotent write without a
workflow-specific idempotency contract could duplicate history. Canonical
terminal replay remains the only existing idempotent signal transition and is
validated inside a fresh complete transaction.

## Flush is not commit

`SignalRepository.create()` and `SignalRepository.apply_lifecycle()` call
`flush()` so generated IDs, ORM guards, PostgreSQL checks, and triggers fail
inside the caller-owned unit of work. Flush does not make data durable. Closing
a bare repository session without an owning transaction rolls the write back.
There is no `session.commit()` in repository or API code.

This division permits several related writes to remain all-or-nothing. A valid
first write is rolled back if a later statement in the same application
transaction violates a check or trigger. There is no hidden intermediate
repository commit.

## Read-only request behavior

`get_db_session()` is intentionally read-only. It delegates to
`Database.read_session()`, never commits, explicitly ends any implicit SELECT
transaction, and closes deterministically on success or failure. Mutation
handlers must call an application service that owns a write transaction; they
must not write through this dependency and wait for dependency teardown to
commit. This prevents an HTTP success response from preceding a required commit.

The current public analysis and signal-evaluation endpoints do not persist
signals. They use market-data and deterministic evaluation services and do not
open database write transactions. The unimplemented signal query route also has
no persistence mutation. OpenAI validation has no database side effect in this
workflow, so an OpenAI failure cannot leave a partial signal record.

## Signal and snapshot atomicity

A signal is one row containing its Snapshot V2 payload, snapshot hash, strategy
identity, decision, and planned geometry. `SignalPersistenceService.create()`
validates and flushes the complete row, then commits it once. If typed snapshot
validation, identity resolution, hashing, a database check, or the final commit
fails, no partial signal survives.

The repository remains the trusted mapping boundary. Transaction ownership does
not weaken Snapshot V2 revalidation, server-generated hashes, M-05 row-validity
checks, ORM guards, or PostgreSQL immutable-history triggers.

## Lifecycle and execution evidence atomicity

Each lifecycle call is one transaction and one ORM flush:

- `WAITING -> ACTIVE` writes status, activation timestamp, lifecycle events,
  and complete entry execution evidence together.
- `ACTIVE -> TP_HIT` and `ACTIVE -> SL_HIT` write terminal status, close time,
  final lifecycle event, exit/cost evidence, gross/net PnL, gross/net R, and
  financial outcome together.
- `CANCELLED` and `AMBIGUOUS` retain their existing evidence/nullability and
  financial semantics, but are committed as complete units.

If any required field or later statement fails, rollback restores the entire
previous row. There is no status-first/evidence-later commit.

## Row locking and concurrency

`SignalRepository.apply_lifecycle()` obtains the signal with
`SELECT ... FOR UPDATE`. The lock is acquired after `Database.transaction()`
begins and remains held while the repository reads, validates, writes, flushes,
and the application service commits. It is released only on commit or rollback.

For conflicting terminal workers, one transaction commits the canonical state.
The second waits for the row lock, then observes the committed terminal row and
may perform only an identical canonical replay; a different terminal result is
rejected and rolled back. Both sessions are closed. A worker exception also
rolls back and releases its lock so a waiting independent transaction can
continue.

## PostgreSQL authority and limitations

SQLite remains useful for fast session/unit tests, but cannot prove PostgreSQL
row locks, triggers, named checks, or deferred commit failure. Those guarantees
are exercised against the explicitly isolated `ai_trading_test` PostgreSQL 16
database selected through `TEST_POSTGRES_URL`. Production URL validation and
secret ownership are unchanged; application code contains no test URL or
SQLite fallback.

This contract provides deterministic atomic persistence semantics. It is not a
claim of broker execution, profitability, or production readiness.
