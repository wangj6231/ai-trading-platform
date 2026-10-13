# F5-B O1 — USER_UPLOAD final receipt admission

Policy: OWNER_APPROVED. Public server-module interface: `JournalService.register_upload(account_id, trade_id, metadata, *, attachment_id=None, principal=None)`. This remains trusted server receipt registration, **not an HTTP upload endpoint** or independent proof of binary storage. The new O1 `UserBinaryService` always supplies a server-authenticated principal; ownership is rechecked under the same final account lock. Legacy internal server callers without a principal retain their existing call shape; browser assertions are never trusted receipts.

## Approved admission / replay rules

- New USER_UPLOAD is rejected if CLOSED when its receipt is authoritatively admitted. Receipt insertion and closure use the same canonical account row lock. The clock is read after acquiring that lock; caller upload-start time grants no admission authority.
- An object written while ACTIVE but without a committed trusted receipt has no READY Journal evidence if closure wins admission. It is only orphan/staging inventory; there is no cleanup or deletion implementation/authority.
- A receipt committed while ACTIVE survives later closure. Exact equivalent replay with its original **server-held attachment identity**, scoped trade and existing receipt metadata returns that original identity without changing timestamps or adding a row.
- Changed metadata, different trade/account/type or a new identity is not equivalent replay. No admin bypass exists.
- Identity is a bounded strict execution-domain Identifier, not an arbitrary object/path/token. Omitted identity preserves the legacy fresh-upload call: each invocation requests a new receipt and must be ACTIVE. Callers requiring retry must retain the same server identity across attempts.
- A return occurs only after successful database transaction completion. No successful receipt is returned after rollback.

## Implemented evidence limits

The existing typed metadata fields are status, scoped opaque storage key, MIME, size and failure reason. They are revalidated, including model-constructed input. Matching these fields alone is **legacy metadata receipt replay**, not content-byte/hash/object-version certification. Subsequent O1 binary validation/readback and scoped availability are separately implemented by `UserBinaryService`, documented in `USER_BINARY_O1_CONTRACT.md`. Legacy receipts are not retroactively certified. O2 structured object-version/origin binding and O3 production adapter certification remain unstarted.

No new HTTP body field, client ownership assertion, upload route, signed URL, object deletion, staging cleaner or renderer is added. Automatic snapshot completion is unchanged and its post-closure policy remains unresolved. Legacy metadata is not retroactively promoted to verified binary evidence. No financial amount, lifecycle event, retention anchor, strategy configuration or Rust interface changes.

## Tests / oracles

Tests use the public Journal receipt/read interfaces and existing authenticated lifecycle commands. Existing Paper scenarios create and close the trade; owner-approved CLOSED/new-receipt and original-receipt replay rules are independent expected behavior. Storage metadata is explicitly fixture evidence, not a real object upload. PostgreSQL tests run the same public admission behavior against owned isolated PostgreSQL. No private methods or internal mock collaborators are tested.

Current focused evidence and remaining work are recorded in `PRODUCT_FOUNDATION_F5_B_REPORT.md`. F5-B and overall F5 remain PARTIAL_PASS; no O2/O3 or MARKET_ARCHIVE/RETENTION_JOBS cutover follows.
