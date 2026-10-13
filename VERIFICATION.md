# Engineering verification summary

Updated: 2026-10-14 (Asia/Taipei)

## Interpretation

Verification in this repository proves software contracts and regression
guards for a research/Paper system. It does not prove strategy profitability,
LIVE execution quality, production availability, disaster recovery, or
commercial capacity.

Counts below belong to named, independently frozen milestones. A later slice
may intentionally rerun only the affected domain. Results are therefore shown
with their scope and are never added together.

## Latest milestone evidence

| Milestone | Accepted result | Boundary |
| --- | --- | --- |
| Object binary O2 / current backend collection | 2,226 distinct backend tests passed in disjoint complete partitions; 481 PostgreSQL 16.11 cases; 0 failed, errored, or skipped | Coverage, frontend, and Rust were not rerun in O2 |
| Financial retention lifecycle F5-A | 2,071 backend tests passed; 435 PostgreSQL cases; 91.96% combined line coverage; Ruff/mypy/compileall passed | No purge, scheduler, archive, cloud object store, DR, or capacity claim |
| Paper execution E2E | 1,663 backend tests passed, including 251 PostgreSQL cases; 258 Vitest tests; 129 production-browser cases; typecheck, ESLint, and production build passed | Paper only; no LIVE broker or production-readiness claim |
| Dashboard bounded composition F4.1 | 2,005 distinct backend nodes passed; 395 PostgreSQL cases; 91.89% combined line coverage | Normal bounded composition, not all-path O(1) work or a capacity pass |
| Rust UTC-alignment bootstrap | 8 Rust unit tests, fmt, and clippy passed; Windows wheel runtime smoke passed; containing backend checkpoint 1,968 tests and 92.07% coverage | Python remains authoritative; shadow was slower in the recorded benchmark |

Detailed evidence and counting rules:

- [PRODUCT_FOUNDATION_F5_B_REPORT.md](PRODUCT_FOUNDATION_F5_B_REPORT.md)
- [PRODUCT_FOUNDATION_F5_REPORT.md](PRODUCT_FOUNDATION_F5_REPORT.md)
- [PAPER_E2E_V1_REPORT.md](PAPER_E2E_V1_REPORT.md)
- [PRODUCT_FOUNDATION_F4_1_REPORT.md](PRODUCT_FOUNDATION_F4_1_REPORT.md)
- [RUST_CORE_BOOTSTRAP_V1_REPORT.md](RUST_CORE_BOOTSTRAP_V1_REPORT.md)

## 2026-10-14 publication preflight

Fresh checks against the staged publication candidate passed:

| Gate | Fresh result |
| --- | --- |
| Backend static checks | Ruff passed; mypy passed for 166 source files; compileall passed |
| Focused backend security/product regression | 299 passed; deployment security, account scope, Paper HTTP, async jobs, observation worker, Journal/Analytics, retention, user binary, and automatic snapshot O2 |
| Frontend unit/component coverage | 268 passed; statements/lines 90.17%, branches 81.49%, functions 76.50% |
| Frontend browser matrix | 127 passed: 76 chart/MTF, 8 product, 8 evidence, 11 density, 20 Paper fixture/reconciliation, and 4 authenticated HTTP |
| TypeScript / ESLint / production build | passed / passed / passed |
| Candidate secret scan | no high-confidence credential prefix, private-key block, credentialed database URI, or public-browser secret variable found |
| Staged diff check | passed |

Dependency review upgraded Next.js and `eslint-config-next` from 16.3.3 to
16.4.0 and applied the available non-breaking transitive fixes. The resulting
`npm audit` still reports 9 development-tool findings: 2 critical and 2
moderate in the Vitest/tinypool chain, plus 5 high findings in the Next ESLint
plugin globbing chain. The available automated remedies require breaking
Vitest 5 or an incompatible ESLint-config downgrade, so they are deliberately
not hidden or force-applied in this product milestone. They require a dedicated
dependency-upgrade review and fresh full gates.

The focused backend run is not substituted for the complete PostgreSQL suite.
Rust was not available on this Windows host. The protected pull request must
therefore pass both required GitHub Actions jobs; the backend job builds/tests
Rust 1.99.0 and runs the complete pytest collection against PostgreSQL 16 with
the unchanged 90% coverage gate.

## Security and integrity boundaries exercised

- Missing, weak, or known-placeholder production credentials fail closed.
- Browser-facing code does not receive the backend Paper bearer credential.
- Account scope is enforced across Paper commands, reads, async jobs, Journal,
  attachments, and completion paths.
- PostgreSQL constraints and triggers reject invalid state transitions and
  mutation/deletion of protected financial, lifecycle, attachment, completion,
  and strategy evidence.
- Idempotent replay, request races, concurrent completion, transaction rollback,
  and direct-SQL attacks have explicit regression coverage.
- Closed-candle, cutoff, delayed-reveal, multi-timeframe, source-provenance, and
  look-ahead rules remain part of the deterministic strategy gates.
- Observation work uses bounded admission, durable checkpointing, and explicit
  failure/backpressure rather than fabricating readiness.
- Binary reads are bounded and content-verified. The current local seam is not
  certification of a deployed object store, encryption service, renderer, or
  cleanup authority.

## Publication preflight

Before a public push, the candidate set is limited to source, tests,
documentation, configuration templates, curated reports, and labelled UI
evidence. The following remain local:

- `.env` files, credentials, private keys, and database connection secrets;
- database files, dumps, retained object bytes, and user uploads;
- raw provider responses and raw market-history payloads;
- third-party PDFs, local environments, dependency/build caches, profiler data,
  raw coverage output, and machine-specific logs.

The publication branch is scanned for sensitive filenames and credential
patterns before push. GitHub Secret Scanning and Push Protection are enabled,
and protected `main` requires the backend/PostgreSQL and frontend/browser checks
through a pull request.

## Reproduce

GitHub Actions is the authoritative cross-platform publication gate. It builds
the pinned Rust extension, runs Rust fmt/clippy/tests, then executes backend
Ruff, mypy, and the complete pytest suite against PostgreSQL 16 with the 90%
coverage threshold. The frontend job runs TypeScript, ESLint, Vitest coverage,
Chromium browser tests, and a production Next.js build.

For a local Windows run, use an isolated test PostgreSQL URL and then run:

```powershell
.\scripts\quality-gates.ps1
```
