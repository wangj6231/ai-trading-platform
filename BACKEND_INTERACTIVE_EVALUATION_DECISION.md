# Interactive evaluation: product decision for the next slice

Status: ALLOW_ASYNC_EVALUATION accepted by the user on 2026-10-07. Pre-async regression completed with 1172 PASS; additive API/dashboard is implemented and current full non-PostgreSQL regression is 1183 PASS. Complete real-history byte equivalence and initial real API/browser gates PASS. Final coverage 91.06% and independent live/header/mobile gate PASS. READY_FOR_LIVE_FRONTEND_RETEST; PostgreSQL remains NOT RUN. See ASYNC_EVALUATION_V1_REPORT.md; no production-ready claim.

## Verified constraint

The unchanged synchronous dashboard requests a complete signal and complete analysis together. Ordinary current backend: BTC signal 15.154 s / analysis body 19.401 s; ETH 17.751 s / 21.861 s. Complete analysis is 166,170,523 / 169,870,373 bytes. The unchanged real frontend proxy source returns technical 504 BACKEND_TIMEOUT at 10.014 / 10.007 s. Health and candles remain available. Full fixed-history engine and public projections equal the preserved original.

The current performance phase is therefore not complete. These observations do not prove that further execution optimization is impossible. They do establish that retained changes do not meet the existing frontend interaction deadline. Increasing the timeout, shrinking history, disabling evidence and serving the preceding cutoff are excluded by the user's instructions.

## Proposed next slice: an explicit pending evaluation

Keep the current full synchronous APIs and their schemas for compatibility and audit. Add a separate asynchronous dashboard workflow, with user approval of the new product/API behavior:

1. Submit `{symbol}` to a new evaluation-job endpoint. Return a bounded job handle and explicit PENDING state promptly, before CPU work completes.
2. Show evaluation in progress. Fetch chart candles independently. Poll the owned job's status through small responses, with the same 10-second per-request deadline.
3. When the original complete deterministic evaluation and validation finish, expose the original full result. Never label technical failure, cancellation or pending work as NO_TRADE.
4. Each job fixes its real closed 15m cutoff and complete authority/data identity. A newly closed candle requires an explicitly new evaluation; an older job cannot silently become the current decision.
5. Bound admission, lifetime and retained bytes. Specify handle visibility and authorization using the existing live/research boundary before implementation. Client cancellation, expiry and shutdown must stop and reap owned work. No partial evaluation enters a completed-result store.

Acceptance: actual cold BTC/ETH jobs acknowledge within the existing deadline, preserve complete golden equivalence and data provenance, finish within the measured explicit evaluation budget, leave health/candles available, and cancel without residual CPU work. Browser tests must distinguish PENDING / technical unavailable / deterministic NO_TRADE. This improves interaction while disclosing computation time; it must not be reported as a faster engine.

## Accepted decision

The user authorizes additive asynchronous evaluation API/UI, while preserving existing synchronous endpoints and response schemas, full deterministic semantics, all data/provenance checks and the original proxy deadline. Explicit states are PENDING, RUNNING, COMPLETED, FAILED and CANCELLED; pending/technical states must never expose invented decisions or trade levels. Poll only by evaluation ID; stop on terminal state/unmount/symbol change and never re-evaluate from GET. Expose only provable strategy/cutoff/history identities and execution timestamps. Safe deduplication is optional and needs full identity; symbol-only reuse is forbidden.

Keep compute profiling separate from product responsiveness. Complete sync/async full-field equivalence, API lifecycle/error/cancellation/duplicate tests, health/candles/status/second-evaluation concurrency, existing backend/snapshot/reproducibility/PostgreSQL/frontend regressions and real default-proxy verification are required. Ordinary implementation choices do not require another question. Stop only for a necessary strategy, existing public API, data-consistency or security-boundary change.

This is a genuine product/data-interface and job-ownership decision under the user's stop rule. It does not authorize Auth, Journal, Analytics, broker execution, AI services, payment or notification features. No commits, pushes, merges or deployment.
