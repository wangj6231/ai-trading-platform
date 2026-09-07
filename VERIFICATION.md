# Engineering verification summary

Baseline verification: 2026-09-06 (Asia/Taipei)

GitHub publication preflight: 2026-09-07 (Asia/Taipei)

P3 incremental replay verification: 2026-09-07 (Asia/Taipei)

## Result

The frozen V4.2 engineering baseline completed its scoped regression and
integrity gates without an outstanding critical, high, or medium engineering
finding. The result supports the implemented software invariants; it does not
establish trading profitability, broker execution accuracy, production
readiness, or financial suitability.

| Gate | Result |
| --- | ---: |
| Complete backend suite with PostgreSQL enabled | 867 passed, 0 failed, 0 skipped |
| Dedicated real PostgreSQL integration | 109 passed, 0 failed, 0 skipped |
| Backend line coverage | 90.19% |
| Frontend unit/component tests | 69 passed |
| Frontend statements/lines coverage | 82.61% |
| Frontend branch coverage | 75.73% |
| Frontend function coverage | 78.26% |
| Real Chrome browser cases | 74 passed |
| Ruff, mypy, TypeScript, ESLint, production build, compileall | passed |
| Alembic base -> head -> base -> head on PostgreSQL 16 | passed |

## Security and integrity boundaries exercised

- Production rejects missing, short, and known-placeholder PostgreSQL
  credentials before startup.
- Default Compose keeps PostgreSQL inside the application network; optional
  development access binds to loopback only.
- Sensitive settings use secret-aware types and are excluded from strategy and
  backtest identities.
- PostgreSQL constraints reject impossible signal rows.
- PostgreSQL triggers reject ORM, SQLAlchemy Core, bulk, and raw SQL rewrites of
  protected historical and terminal signal evidence.
- Snapshot, strategy/configuration/source identity, execution evidence, and
  optional AI-validation provenance remain separately versioned and immutable.
- Closed-candle, cutoff, delayed-reveal, multi-timeframe, market-data trust, and
  look-ahead regressions are included in the engineering gates.

## Publication preflight

Before the initial GitHub publication, the repository candidate set was reduced
to source, tests, documentation, configuration templates, and curated research
reports. Third-party PDFs, raw market data, raw provider/model responses,
database files, credentials, local environments, caches, coverage output, and
profiler artifacts are excluded. A no-network secret scan of the actual
candidate set found only documented development/CI placeholders, test fixtures,
and content hashes; no real credential was identified.

The publication session also passed all 23 focused deployment-security tests,
confirmed that rendered default Compose has no PostgreSQL host port, and passed
the real-PostgreSQL regression that attempts a direct SQL rewrite of a terminal
signal's `take_profit`. Both temporary audit listeners were confirmed closed
after testing.

The first GitHub Actions run completed successfully on the publication commit:

| GitHub publication gate | Result |
| --- | ---: |
| Backend with PostgreSQL 16 service | 899 passed |
| Backend line coverage | 90.90% |
| Frontend unit/component tests | 69 passed |
| Frontend statements/lines coverage | 83.76% |
| Frontend branch coverage | 77.37% |
| Frontend function coverage | 89.13% |
| Chromium browser cases | 74 passed |
| Frontend production build | passed |

## P3 incremental replay verification

The P3 assessment preserves the frozen strategy/configuration semantics and
compares complete typed outputs, rather than accepting matching final trade
directions alone.

| P3 gate | Result |
| --- | ---: |
| R1 reference/P3 cutoff comparisons | 1,440 equal |
| Transition-fixture prefix comparisons | 40 equal |
| Instrumented configuration-variant comparisons | 520 equal |
| Fresh targeted differential/lifecycle pytest | 26 passed |
| Q1 measurement reached | 7,591 / 129,600 evaluations |
| Measurement stop | clean at predeclared 1,750-second soft cap |
| Observed aggregate throughput change | 1.493 to 4.338 evaluations/second (about 2.9x) |
| Protected authored/prior artifact hashes | 423 unchanged |
| Reviewed classification | `PERFORMANCE_STILL_INSUFFICIENT` |

The throughput ratio compares runs that stopped at different prefixes and is
not a validated full-Q1 ETA. Later-window cost continued to grow, so P3 remains
an experimental, non-default path. No partial trading output, profitability,
or production-readiness claim was derived from the measurement. Detailed
method, results, and limits are recorded in the
[P3 engineering report](experiments/r1e_p3_incremental/P3_REPORT.md).

## Reproduce

On Windows PowerShell, with an isolated PostgreSQL test URL set for integration
tests:

```powershell
.\scripts\quality-gates.ps1
```

GitHub Actions also runs backend checks against a PostgreSQL 16 service and runs
frontend typecheck, lint, coverage, real-browser tests, and a production build.
