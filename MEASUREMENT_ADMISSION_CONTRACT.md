# F1 Measurement / Admission Contract

PRODUCT_FOUNDATION_V1 F1。Operational instrumentation/admission 不是 strategy、execution、Journal 或金融權威。
Frozen Paper directional/decimal policies、gateway eligibility、ownership、HTTP financial DTO 均保留。

## GRILL inventory

| Seam / original gap | Classification | F1 implementation |
|---|---|---|
| main.py unrestricted request ID; logger.exception raw exception | SECURITY_GAP | Generated diagnostic identity、bounded transport IDs、safe generic error logging；local opt-in traceback |
| FastAPI parsing preceded no body/header/query cap | RESOURCE_BOUND_GAP | Pure ASGI finite pre-parse buffer、Content-Length/type/deadline checks |
| Next Paper proxy text() then size check | RESOURCE_BOUND_GAP | Byte-bounded stream read/cancel、header/query bounds、safe forwarded IDs |
| SQLAlchemy generic defaults, no query timing | MEASUREMENT_GAP | PG pool/statement/idle timeout controls；engine event duration/count only；no SQL/params |
| Auth resolves current subject/ownership | SAFE_INSTRUMENTATION | Paper dependency scope then cost admission before existing action；no changed grant rules |
| Worker shared range/advisory lock/gateway/checkpoint | SAFE_INSTRUMENTATION | Timings/counts around same calls；financial authority remains gateway |
| Binance every HTTP attempt | SAFE_INSTRUMENTATION | Fixed outcome/status/retry metrics；same app budget across provider callers |
| Journal/Analytics full replay and historical cache growth | MEASUREMENT_GAP | Measured via unchanged queries/transactions/harness；no projection/cache optimization |

No SEMANTIC_CONFLICT found in these infrastructure seams. Resource bounds may return technical errors;
they do not label orders REJECTED, create LOSS or return strategy NO_TRADE.

## Interface and wiring

`HttpAdmissionMiddleware → AdmissionBackend.check(AdmissionContext)` before costly dispatch.
Paper: existing auth → `service.scoped()` → scoped cost check → existing route action.
Provider: same app backend checked before **each** HTTP attempt, including bootstrap/worker/retry.
`Telemetry.emit(event, fixed_fields)` and QueryMeasurement context observe existing calls; finite in-memory diagnostics.
No public telemetry endpoint; no new auth product, financial reducer, queue, provider fallback or broker.

Technical rejection contracts: 400 malformed length, 408 input deadline, 413 body size, 414 query/path,
415 JSON type, 431 headers, 429 resource quota, 503 admission backend/key-budget failure.
Paper proxy retains its existing safe VALIDATION_ERROR / INVALID_RESPONSE envelopes.
Malformed/provider errors keep existing technical taxonomy. Unhandled500 never includes traceback/payload.

## Verification and phase boundary

Tests use the authorized HTTP/admission, Telemetry, Database, existing gateway/worker, and isolated harness seams.
Fake secrets only. Exact results and limits are in [F1 report](PRODUCT_FOUNDATION_F1_REPORT.md).
F1 does not claim D2 performance, production security, DR readiness or public commercial approval.
F2/F3 projections/OIDC/distributed infra remain unimplemented. Limits are deployment settings, not StrategyConfig.
