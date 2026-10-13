# Project status

Last updated: 2026-10-14 (Asia/Taipei)

## Current milestone

The repository has progressed from a deterministic analysis baseline to a
portfolio-ready **Paper trading product foundation**. It now combines a
Next.js dashboard, asynchronous strategy evaluation, authenticated and
account-scoped Paper execution, PostgreSQL-backed orders/fills/positions,
automatic Journal capture, analytics, observation work, and retention/read
models.

This is still a research and Paper environment. It has no LIVE broker adapter,
does not hold exchange trading credentials, and does not establish strategy
profitability, production availability, disaster recovery, or commercial
capacity.

## Verified delivered slices

- **Analysis dashboard:** closed-candle market data, deterministic multi-
  timeframe strategy evidence, explicit `LONG` / `SHORT` / `NO_TRADE`, and an
  asynchronous evaluation lifecycle with cancel, failure, stale, and
  unavailable states. Display timeframe remains separate from server-owned
  strategy authority.
- **Paper workflow:** account summary, order ticket, orders, fills, positions,
  Journal, trade detail, attachments, and analytics across desktop and mobile.
  The HTTP-backed path uses server-side bearer credentials and has no fixture
  fallback when the backend fails.
- **Execution integrity:** PostgreSQL constraints and triggers protect order,
  fill, position, trade, attachment, lifecycle, and completion evidence.
  Account-scoped authorization, idempotent commands, concurrency races, and
  direct-SQL mutation attempts are covered by tests.
- **Operational foundation:** bounded request/admission controls, database
  resource budgets, structured telemetry, an observation worker with durable
  checkpoints and active-work projection, and bounded Dashboard composition.
- **Retention and object evidence:** financial retention lifecycle and object
  binary O1/O2 public seams are implemented and tested. O3 deployment adapter,
  market archive, scheduled retention jobs, and destructive purge remain out
  of scope and unimplemented.
- **Native compute seam:** a bounded Rust/PyO3 UTC-alignment implementation can
  run in shadow comparison behind the Python authority. It is parity/safety
  work, not a speedup or authoritative-native claim.

## Latest accepted verification evidence

The figures below come from the latest accepted report for each independently
frozen slice. They are not added together and are not represented as one
simultaneous run.

| Area | Latest accepted evidence |
| --- | --- |
| Backend through object-binary O2 | 2,226 distinct tests passed in disjoint non-PostgreSQL and PostgreSQL 16.11 partitions; 481 actual PostgreSQL cases; Ruff, mypy, compileall, and diff check passed |
| Backend coverage at financial-retention F5-A | 2,071 tests passed; 435 actual PostgreSQL cases; 91.96% combined line coverage with the unchanged 90% gate |
| Frontend and Paper end-to-end | 258 Vitest tests and 129 production-browser cases passed; TypeScript, ESLint, and Next production build passed |
| Rust UTC-alignment seam | 8 Rust unit tests plus fmt/clippy passed; Windows wheel runtime smoke passed; the containing backend checkpoint reported 1,968 tests and 92.07% coverage |

The 2026-10-14 publication preflight additionally passed backend static checks,
299 focused backend security/product tests, 268 frontend coverage tests, 127
browser cases, and the production build. Complete current PostgreSQL and Rust
verification remains delegated to the protected pull request checks rather than
being inferred from this focused local run.

The detailed counting rules, retained failed attempts, environment limits, and
stop conditions live in the phase reports, especially
[PAPER_E2E_V1_REPORT.md](PAPER_E2E_V1_REPORT.md),
[PRODUCT_FOUNDATION_F4_1_REPORT.md](PRODUCT_FOUNDATION_F4_1_REPORT.md),
[PRODUCT_FOUNDATION_F5_REPORT.md](PRODUCT_FOUNDATION_F5_REPORT.md),
[PRODUCT_FOUNDATION_F5_B_REPORT.md](PRODUCT_FOUNDATION_F5_B_REPORT.md), and
[RUST_CORE_BOOTSTRAP_V1_REPORT.md](RUST_CORE_BOOTSTRAP_V1_REPORT.md).

## Security and publication boundary

- Real `.env` files, keys, database files/dumps, raw provider payloads, raw
  market history, generated profiler/coverage output, and third-party PDFs stay
  out of Git.
- Browser code never receives the backend Paper bearer credential. The Next.js
  proxy owns that server-side boundary and rejects missing/malformed settings.
- PostgreSQL is the authority for financial history. Application validation is
  additive; database constraints, triggers, transactions, and immutable
  receipts remain the final local integrity boundary.
- Public screenshots and fixtures are labelled as DEV, fixture, or recorded
  evidence. They are not presented as LIVE execution.
- The protected `main` branch requires pull requests and both repository quality
  checks before merge.
- Next.js is updated to the non-major security release 16.4.0. Remaining npm
  audit findings are confined to development/test tooling and require breaking
  dependency changes; they stay explicitly open for a dedicated upgrade PR.

## Open boundaries and next stages

1. Complete object-storage O3 only after an adapter, encryption, durability,
   timeout, and failure contract is approved and measured.
2. Implement and verify market archive and retention jobs without authorizing
   destructive financial-history purge.
3. Select an actual deployment target, managed-secret flow, private database
   network, backup/WAL policy, and isolated restore drill before any production
   readiness claim.
4. Run predeclared load and failure tests against approved capacity/SLO targets;
   current bounded interfaces are not a commercial-capacity result.
5. Keep Paper execution separate from LIVE broker execution. Any LIVE adapter,
   real credential, automated strategy dispatch, or funds path needs a new
   security and owner-authorization gate.
6. Evaluate strategy quality only with separately locked out-of-sample and
   walk-forward methodology. Engineering regression results are not financial
   performance evidence.

## Portfolio framing

This project demonstrates deterministic financial-domain engineering,
look-ahead prevention, authenticated multi-account Paper workflows,
database-enforced auditability, async job ownership, idempotency and race
handling, responsive full-stack UI delivery, bounded operational interfaces,
and evidence-led verification. It must not be described as a profitable
strategy, financial advice, a LIVE trading system, or production-ready service.
