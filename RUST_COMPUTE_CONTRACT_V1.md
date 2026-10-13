# UTC alignment compute contract V1

One function: `align_v1(bytes) -> bytes`, exposed through PyO3. The Python typed
interface is `evaluate_alignment(RustComputeInputV1) -> RustComputeOutputV1`.
No general-purpose JSON, candle or execution framework is exposed.

Input compact ASCII JSON field order:
`contract_version`, `timeframe`, `timestamps_us`.

- `contract_version`: string `"1"` only.
- `timeframe`: `1m,3m,5m,15m,30m,1h,2h,4h,1d,1w` only.
- `timestamps_us`: array of signed integer microseconds since 1970-01-01 UTC.
  No floats, booleans, null timestamps, strings, sorting or deduplication.
  Python datetime range: -62135596800000000 .. 253402300799999999 inclusive.
- UTC conversion stays Python and uses integer timedelta arithmetic, never
  floating `timestamp()*1e6`. Offsets are normalized, naive timestamps rejected.
- Missing, duplicate and unknown fields, trailing JSON and over-range integers
  are rejected. Whitespace is accepted on native input; output is canonical.

Output compact ASCII JSON field order:
`contract_version`, `first_misaligned_index`, `item_count`.

- First misaligned index is zero-based in supplied batch order, or `null`.
- `item_count` is input length, NOT count before first error.
- Empty array succeeds with null index and count zero, matching the Python
  alignment oracle (the surrounding existing validator rejects empty markets).
- No chronological-order, gap, duplicate, cutoff, closed-candle or OHLC check is
  added here. Existing Python validators retain all these responsibilities.

Intraday/day: exact integer remainder against UTC epoch intervals. Weekly:
`(microseconds + 259200000000) rem_euclid 604800000000 == 0`, ISO Monday UTC.
Microsecond offsets fail, including before the epoch; no truncation/forward fill.
Arithmetic is safe within the validated datetime range; release overflow checks
are enabled. There is no rounding, clock, locale, randomness or null inference.

Limits are schema constants, NOT strategy tuning:
MAX_ITEMS = MAX_BATCH_SIZE = 4096;
MAX_INPUT_BYTES = 131072; MAX_OUTPUT_BYTES = 256.
Larger service histories stream bounded batches without history truncation.

Native errors are fixed codes: `INPUT_TOO_LARGE`, `INVALID_INPUT`,
`OUTPUT_TOO_LARGE`, `INTERNAL_ERROR`. Python additionally maps `UNAVAILABLE`,
`INVALID_OUTPUT`, `SEMANTIC_MISMATCH`. No payload/exception text is logged or
returned. Alignment failure maps to the original `TimeframeAlignmentError`
and original UTC ISO message in Python; existing HTTP error redaction remains.
Unknown output fields, enum/version, duplicate keys, count/index/type errors
fail closed. A native panic is contained/redacted, never treated as success.

Corpus hashes use SHA-256 over compact ASCII input/output in the defined field
order. Cases contain expected outputs/errors from the existing Python oracle;
they must NOT be regenerated from Rust to bless a mismatch.

Python timestamp preparation/oracle failures are preserved before native dispatch
and represented separately in the corpus (runtime-specific error type and no
trusted output). Windows intraday `fromtimestamp` has a narrower supported range
than Python datetime. Raw native integer arithmetic is not an alternate source
of truth for those failures. Successful prepared calls have exact output parity;
malformed wire errors are fixed native codes. The V1 Python facade compares in
both `shadow` and measurement-only `rust` selection.
