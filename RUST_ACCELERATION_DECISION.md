# Rust decision — Execution Gateway hot path V1

Classification: **RUST_NOT_JUSTIFIED** for this task. No Rust implemented.

## Explicit measured ratios

Denominator is summed Gateway wall per shape, not whole setup time.

|Ratio|100 before/after|500 before/after|
|---|---:|---:|
|SQL cursor seconds /Gateway wall (DB+driver IO proxy)|35.37% /29.80%|41.42% /30.58%|
|Python-process CPU seconds /Gateway wall|75.83% /77.27%|69.73% /85.34%|
|Sample traced temporary peak /same-sample RSS|0.225% /0.258%|0.432% /0.547%|

These are deliberately **not** an exclusive100% pie: Python process CPU includes
native driver/JSON/Pydantic work and sampler threads; cursor time includes
Python/native driver CPU. Allocations' CPU-time percentage is UNKNOWN (not
isolated by this instrumentation). Memory ratio is bytes, not time. Native
PostgreSQL CPU and pure network wait attribution remain UNKNOWN.

## Evidence-led conclusion

Before500, repeated SQL UPDATE~284s and repeated order validation~220s dominated.
Transaction-local batches/reuse reduced Gateway833.248→46.998s with unchanged
canonical financial output and no low-level rewrite. Native acceleration would
not have removed those round trips or repeated work.

Remaining after500 includes~14.371s SQL cursor work,~6.006s hashing and ORM/market
schema/copy/commit work. CPU utilization alone is not evidence that financial
Decimal accounting needs Rust: these F1 worker profiles perform **zero fills**,
so accounting `apply_fill` CPU is not measured. A late sample shows full OHLC
validation and ORM persistence as substantial residuals. The separate50-trade
diagnostic retains52 account-read queries; changing language does not fix N+1.

If later evidence isolates a bounded deterministic pure computation as dominant,
an independent feasibility study could keep Python as golden oracle and define
exact Decimal/error/ordering/serialization equivalence. DB transactions, locks,
auth, idempotency, account/position checks and financial authority must remain
in the existing system. This is a condition for a future owner-authorized task,
not a recommendation to begin Rust/F4 now.
