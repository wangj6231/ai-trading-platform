# Rust core bootstrap benchmark

Measured 2026-10-10 on the current Windows development host / CPython 3.12.4.
Artifact: `experiments/rust_core_bootstrap_v1/benchmark.json`.
This is compute measurement, NOT strategy research, execution capacity or R1-E.

Same immutable UTC 15m timestamp rows and input hashes for every mode. One warmup,
five timed runs; table shows median wall time. No prices or trading outcomes.
`rust` here is measurement-only and still Python-oracle-gated, NOT a production
native cutover. Normal deployment remains shadow.

| Rows | Python original (ms) | Shadow (ms) | Oracle-gated native result (ms) |
| ---: | ---: | ---: | ---: |
| 1,000 | 1.45 | 3.52 | 3.25 |
| 4,096 | 5.60 | 12.59 | 13.15 |
| 35,000 | 48.33 | 112.90 | 111.79 |

At 35k: Python five-run CPU 250 ms; shadow 562.5 ms; measurement-native 546.875 ms.
Small CPU durations are quantized by the Windows process-time clock: a recorded
zero is NOT proof of zero CPU cost. Shadow is approximately 2.34x slower in this
sample. **No integrated speedup is claimed.** Oracle validation, datetime/integer
projection, JSON and PyO3 overhead remain deliberately present for safety.

Python-traced peak temporary allocation for 35k: original 486 bytes; shadow
461,393 bytes; measurement-native 461,227 bytes. This excludes already-created
input rows and native allocations. It measures a separate untimed allocation
run, not the wall-time samples. Native storage is bounded by its 4096-entry fixed
array and input/output caps; tracemalloc does not prove native allocation size.

35k sampled RSS peak: original 71,172,096 bytes; shadow 71,565,312 bytes;
measurement-native 72,601,600 bytes. Samples every 5ms may miss short peaks and
are affected by retained input rows, allocator reuse, profile order and host
contention. No process-memory or commercial capacity guarantee is inferred.

Acceptance rationale is a versioned, bounded, memory-safe authored core with
exact oracle gating and redacted fail-closed errors, not an invented performance
advantage. No Rust migration of financial compute, cache or authority follows
from this measurement. No optimization was performed outside the approved seam.
