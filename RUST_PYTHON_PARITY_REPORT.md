# Python / Rust UTC alignment parity

Scope: the explicitly owner-approved UTC alignment seam only.

Python oracle corpus was sealed before native verification:
`experiments/rust_core_bootstrap_v1/python_oracle_corpus.json`.
80 cases; SHA-256
`c6a22523249c97613739410f171ad4643f6f09a41265e7feb7e82263f80d87c9`.
Every case records version, input, expected output/error, input/output SHA-256.
Generation uses ONLY the unchanged Python alignment oracle. Sealing refuses
overwrite. Tests also regenerate reference cases from that oracle for CI/runtime
compatibility, never from Rust; the Windows sealed artifact is preserved.

All ten timeframes: empty, aligned, duplicate (alignment alone permits it),
unordered (alignment alone does not sort/reject it), microseconds, first error,
negative epoch and datetime extremes. Successful prepared calls compare exact
native JSON bytes, output types/values and hashes. Windows legacy `gmtime` errors
are preserved BEFORE native dispatch; these have an expected error and no trusted
output. Do not interpret raw integer arithmetic as approval of an unsupported
legacy timestamp. Corpus error expectations are runtime-specific where the
existing Python oracle is platform-dependent; Rust introduces no ambient timezone.

Recorded RED → GREEN evidence in the same artifact directory:

- missing module / missing native extension → actual installed compiled wheel;
- exception stringification → fixed bounded redacted error;
- oracle failure dispatched native first → preserved Python failure/no dispatch;
- service injection absent → explicit scoped service validator;
- factory ignored missing wheel → shadow fails service construction;
- iterator exception overwrote earlier error → original alignment error retained;
- falsey explicit callable selected fallback → explicit selection preserved.

Affected verification: **188 passed** (includes 146 new seam/service tests and 42
existing market/timeframe/trust tests). Rust unit tests: **8 passed**. Full backend
verification: **1968 passed, 0 failed/0 skipped**, including **360 real PostgreSQL
16.11 marked cases**, each matched to actual successful JUnit output. Coverage
**92.07%**. Focused counts and PG counts are subsets, NOT added to the full count.
Final protected-file verification confirms unchanged strategy config/version and
sealed financial golden; source/build identity changes are recorded separately.

Additional evidence: 35,001 timestamp history processed as 8x4096 + 2233 entries;
no truncation. Max batch, excessive bytes/items, malformed wire, unknown enums,
duplicate/extra fields, non-integer/overflow, malformed output/count/index,
panic-like BaseException, empty input, timezone offsets, microsecond first error
across batches, naive datetime, bypassed frozen input, no silent fallback.

Service provenance matches Python exactly; off-grid/future/gap/duplicate/disorder
and OHLC failures retain existing redacted classification. Closed-range child
services inherit the explicit validator. Native-only production selection is
rejected. Shared normalization, Gateway, Worker eligibility and financial golden
inputs/expectations are not changed. No cutover is claimed.
