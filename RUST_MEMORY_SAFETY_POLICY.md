# Rust memory and error safety V1

The authored crate declares `#![forbid(unsafe_code)]`. No owner-authored unsafe,
FFI pointer manipulation, globals, cache, threads or externally growing queues.
This does NOT claim PyO3/CPython/transitive crates are unsafe-free; their required
FFI implementation is part of the dependency trust surface. Future authored
unsafe requires separate owner authorization, rationale, isolation and tests.

Native input borrows Python bytes and rejects >131072 bytes before JSON parsing.
The timestamp deserializer uses a fixed `[i64;4096]` (~32 KiB) and a bounded
counter, never a user-sized Vec. An extra member is rejected without growing
storage. Enum/unknown-key parsing and serde diagnostics remain bounded by the
input byte cap and are replaced by fixed error codes. serde recursion limits
remain enabled. No arbitrary object graph is deserialized.

The result has three fixed fields and maximum 256 bytes. Its serializer creates
a small Vec, whose size is independent of provider count; output is checked
before crossing PyO3. Python staging retains at most one 4096-row chunk plus
bounded UTC/integer/JSON projections. No persistent account/history cache.
The caller's pre-existing market history is not claimed to be globally bounded
by this seam. Measurement reports Python traced allocations and process RSS
separately: tracemalloc cannot observe native allocations.

Release uses unwind panics and overflow checks. `catch_unwind` converts native
evaluation panics to fixed INTERNAL_ERROR. PyO3 exceptions including its
BaseException panic wrapper are redacted at Python. KeyboardInterrupt/SystemExit
are not swallowed. Semantic mismatch/unavailable/invalid output cannot trigger
fallback. Python oracle remains authority in shadow mode.

This is not a sandbox against a malicious compiled extension, abort, allocation
failure, OS termination or corruption inside CPython/third-party FFI. Bounded
inputs reduce resource exposure; they do not promise recovery from OOM. No
global panic hook is installed; unexpected native diagnostic stderr must be
handled by deployment logging/redaction policy, not returned to HTTP clients.

Cargo.lock is required, registry dependencies only; exact PyO3 version pinned.
fmt/clippy/test and dependency audit are recorded. A reviewed lockfile does not
constitute a proof of supply-chain safety. Runtime gets a wheel, not Rust tools.
