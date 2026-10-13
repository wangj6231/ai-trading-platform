# RUST-CORE-BOOTSTRAP-V1

Owner-approved seam: **MarketDataService UTC candle alignment batch validation only**.
No OHLC, Decimal, strategy, eligibility, order, fill, accounting, auth, database,
Journal or analytics implementation moves into Rust.

```text
server provider → existing Python parsed-row/type/UTC checks
                → Python UTC normalization → bounded InputV1
                → existing Python alignment oracle + PyO3/Rust shadow
                → exact OutputV1 comparison → existing Python errors
                → existing closed/gap/calendar checks
                → existing Python Candle OHLC/Decimal validation/provenance
```

The shared `normalization.validate_candle_alignment` remains unchanged. Its
Gateway, Worker, research and resampling callers remain Python. Only the market
service factory installs the new callable. Directly constructed services retain
the canonical Python default, and closed-range child services inherit the parent's
explicit validator. No network calls, DB sessions, credentials or candle prices
cross PyO3. No caches, mutable Rust globals, background threads or microservice.

Initial production selection is `shadow`: Python output owns the result, Rust is
compared, mismatch fails closed. Explicit `python` is an operational selection,
not fallback. Native-only `rust` exists at the compute/test interface for parity
and measurement; it is NOT a production setting in V1. A missing wheel must fail
service construction in shadow mode. No silent fallback or native cutover.

The existing StrategyConfig and identity algorithms are not changed. Python
authored-source changes naturally change algorithm build identity. Rust contract,
crate source, lockfile and compiled-wheel hashes are recorded separately. Native
code is not a new deterministic strategy implementation and must not gain
decision authority under the existing Python-only source-manifest policy.

The legacy Python bucket primitive has platform-dependent `gmtime` failures
(observed on Windows for pre-epoch/extreme intraday dates). Python oracle runs
BEFORE native dispatch. Its original failure propagates without a native result;
Rust cannot repair/upgrade it. Native arithmetic alone is not an authority for
dates outside the legacy oracle's supported runtime domain. Even measurement
selection `rust` remains oracle-gated and compared in V1. No native cutover.

Windows: MSVC tools + isolated stable Rust/Cargo + maturin build an abi3 wheel
for CPython 3.12+. Only the installed wheel is needed at runtime. Linux deployment
uses a multi-stage backend image: Rust/compiler/maturin in the builder; compiled
wheel in the Python runtime. Linux wheel/build verification and actual supported
runtime are reported separately; an abi3 tag is not evidence for every Python ABI.
