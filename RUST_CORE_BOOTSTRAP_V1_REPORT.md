# RUST-CORE-BOOTSTRAP-V1

Status: **PASS — owner-approved Windows-first UTC alignment bootstrap**.
Python remains authority in production shadow mode; no native cutover.
Linux packaging/CI recipes exist but have NOT been executed locally. This PASS
is not Linux deployment verification or commercial/financial readiness.

## Approved scope / GRILL

Owner confirmed the only seam: market-service UTC candle alignment batch
validation. Shared Python oracle is unchanged. No OHLC, Decimal, strategy,
Gateway admission, Worker eligibility, accounting, auth, Journal or analytics
migrated. No frontend, database schema or migrations changed.

Windows legacy pre-epoch/extreme intraday timestamps can raise OSError. RED test
proved a native-first bridge could overwrite that behavior. Oracle now runs first
and its failure prevents native dispatch. Native integer math does not repair
the legacy oracle. This task does not change its platform behavior.

## Identity / preserved financial authority

`strategy_version = deterministic-smc-ict-v1` remains unchanged.
`config_hash = 0c26e108e361b288604b383ca68ea9df80f2595fe919d39cf9ce0dfb57ffeeab`
remains unchanged. The operational implementation setting is NOT StrategyConfig.
Identity schema/manifest algorithms are unchanged; authored Python source changes
naturally change build identity:

| Identity | Before | After |
| --- | --- | --- |
| algorithm_build_hash | `fb974e3a0b55180b45f5a7e14a8f840dbe0aa6b0217abf0631a35854bdbc27ad` | `d4e4a294e7688730671756da13e3913130a0e2e42611ce8ec4efbf4a9281566d` |

Current source_content_hash:
`5c168ba5333c16ad16c65709d631d3241be52ce7771e7117a1656a3a3f828abb`.
The before artifact records StrategyIdentity/build hash plus individual protected
file hashes; it does not independently record the old aggregate source hash.

Rust source/lock/wheel hashes are separately recorded in the authored/artifact
manifest; they are not silently inserted into StrategyIdentity. Python remains
authoritative. A future authoritative native cutover is outside this task.
Sealed financial golden SHA-256:
`6e3dcb0c10d884248e7b473d60de7fc72e62683b3d0a40132175a296599ecd69`.
No golden expectations are rewritten to approve the native seam.

## Architecture / controls

MarketDataService factory → server-owned operational shadow selection → bounded
InputV1 → Python oracle + PyO3 → OutputV1 strict validation/comparison → existing
Python errors/market validation. Direct services default Python; range services
inherit the parent's validator. No automatic fallback. Missing wheel fails
construction. Native-only production setting is not enabled.

Rust stable 1.99.0 / Cargo / PyO3 0.29.0 / maturin 1.15.0. Windows CPython 3.12.4
wheel built, installed and imported with Rust/Cargo removed from runtime PATH.
Wheel SHA-256:
`effb2a3b906a85901f94cecace010306766a152e9dddd8e1e8266ff58f2a0627`.
Cargo.lock: 22 registry dependencies, no Git dependency; three direct crates.
OSV batch scan executed with no reported advisories for those locked versions;
this is not a security proof. No cargo-audit claim is made.

Authored Rust forbids unsafe. Fixed 4096-entry storage, 131072-byte input cap before
parsing, 256-byte output cap, unwind containment, redacted fixed error codes,
strict Python output validation and bounded error telemetry. No Rust global,
cache, DB handle, network, auth object or price. See the memory policy for FFI,
OOM/abort and third-party limitations.

## Final executed evidence

- Affected suites: 188 passed.
- Rust unit tests: 8 passed; fmt/clippy --all-targets -D warnings passed.
- Ruff, mypy (154 source files), compileall, diff check passed.
- Windows wheel/runtime smoke without Rust: passed.
- Linux Docker builder/runtime packaging and CI native gates added; not yet
  executed locally because Docker Desktop Linux engine was unavailable. No Linux
  production-readiness or cross-ABI verification claim.
- Benchmark: shadow is slower (35k 112.90ms vs Python 48.33ms); no speedup claim.
- Full backend: **1968 passed, 0 failed, 0 skipped** in 2564.51s. Includes
  **146 new** seam/service cases; affected 188 are a subset, not additional cases.
- Real PostgreSQL: **360 marked cases passed**, individually matched against
  successful JUnit entries, **0 failed/0 skipped**. Isolated native server
  **16.11**, not 16.15; process-scoped TEST_POSTGRES_URL only. No global
  DATABASE_URL set and no schema migration introduced by this task.
- Coverage **92.0725%** (92.07% displayed), existing 90% gate retained.
- 3 warnings: existing Starlette/httpx and SQLite datetime-adapter deprecations;
  no warnings were suppressed or dependencies changed to hide them.
- Final 237→238 protected-file comparison: exactly eight pre-existing scoped
  changes plus the new `rust_alignment.py`. StrategyConfig/version, migrations,
  frontend/src, financial/Worker/Gateway domains and sealed financial golden
  remain unchanged. Source/build hashes change naturally as documented above.
- `verification.json`, `authored_task_files.json`, `artifact_manifest.json`
  record actual results, protected deltas and source/lock/wheel evidence.

## Changed/created files

Existing scoped edits: `.dockerignore`, `.env.example`, `.gitignore`,
`.github/workflows/ci.yml`, `README.md`, `backend/Dockerfile`,
`backend/pyproject.toml`, `backend/app/core/config.py`,
`backend/app/market_data/service.py`, `backend/app/services/market_data.py`.

New core: `backend/app/market_data/rust_alignment.py`,
`rust/utc_alignment/{Cargo.toml,Cargo.lock,pyproject.toml,src/lib.rs}`.

New tests: `backend/tests/unit/test_rust_alignment.py`,
`backend/tests/unit/test_rust_alignment_service.py`.
Evidence helpers: `backend/tests/fixtures/rust_core_evidence.py`,
`rust_alignment_corpus.py`, `rust_alignment_benchmark.py`,
`rust_dependency_scan.py`, `rust_core_quality.py`, `rust_core_verification.py`.

Six root Rust architecture/contract/safety/parity/benchmark/final documents;
generated evidence under `experiments/rust_core_bootstrap_v1/` (no prior artifact
overwritten). Existing dirty worktree changes are not attributed to this task.

## Evidence boundaries / remaining limitations

- RED artifacts reproduce missing module/wheel, unsafe exception formatting,
  oracle failure ordering, absent service/factory wiring, first-error ordering
  and falsey explicit callable fallback. Corresponding GREEN artifacts and full
  suite passed; source inspection alone was not used as verification.
- 80-case sealed Python corpus covers all ten timeframes and records expected
  output/error, version and input/output hashes. Tests compare successful native
  bytes exactly and preserve platform-dependent oracle errors.
- Named batch/item/input/output limits are 4096/4096/131072/256. A 35,001-row
  service regression proves streaming, not arbitrary history truncation.
- The protected before/after scope is app, migrations, frontend/src, config and
  selected build/settings files. `.dockerignore`, README and new test/doc files
  have final task hashes, not a claimed pre-change protected manifest entry.
- No frontend or Linux suite is represented as rerun. No official R1-E,
  commercial capacity claim, Rust financial migration or new provider execution.
- Shadow deliberately retains Python validation/projection/JSON overhead and is
  slower in the measured integrated path. Performance is NOT the acceptance
  justification. Dependency advisories, ABI portability and OOM/abort remain
  explicit limitations, not guarantees.

Stop after this bootstrap. No other Rust domain, LIVE broker, tuning or research
replay is authorized by this report.
