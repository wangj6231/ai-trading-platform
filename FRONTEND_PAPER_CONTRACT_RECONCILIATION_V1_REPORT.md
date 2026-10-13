# FRONTEND-PAPER-CONTRACT-RECONCILIATION-V1

Date: 2026-10-09 (Asia/Taipei). Branch: FRONTEND-PRODUCT-V1.

Final classification: **PASS**.

## Scope and authority

Reconcile the existing Paper product with `PAPER_HTTP_API_CONTRACT.md`, `FRONTEND_HTTP_MAPPING.md`, pagination/error contracts and actual `backend/app/paper_http/models.py`. Backend financial/execution authority wins. Existing backend, strategy, configuration and evidence projection are not edited. Default runtime remains DEV/FIXTURE. No Paper HTTP router/proxy, authentication, credentials, LIVE broker, financial formula, strategy attribution resolver or upload/delivery resolver is enabled.

The read-only GRILL found no conflicting backend contract or new product decision. SHA-256 baseline covers 269 backend/config files, including previously untracked execution/Journal/Paper modules; existing dirty changes are retained.

## GRILL mismatch classifications and reconciliation

| Mismatch | Classification | Resolution |
|---|---|---|
| Required Account.name despite backend null | FRONTEND_FIX / PRESENTATION_ONLY | Optional nullable name; display account ID when absent, without storing a fabricated name. |
| Dropped account cash/available/reserved/numeric policy/plural valuation facts | FRONTEND_FIX | Preserve supplied facts separately; cash aliases Balance; no single-symbol scalar selected. |
| Account realized PnL confused with net fixture examples | FRONTEND_FIX | Explicit gross label. Recorded backend gross `6` and net trade `5.39` remain distinct; fixture examples use authored gross values. |
| Missing command identity | FRONTEND_FIX | Required commandId; same unchanged intent retry reuses it. HTTP body preparation carries command_id, excludes owner/account/plan. |
| SUBMITTING accepted as a server order status | FRONTEND_FIX | Removed from canonical Order; local busy badge only, with no temporary order/fill/position record. |
| Submission/cancellation outcome merged | FRONTEND_FIX | Preserve separate statuses, command identity, cancelled time and error code. UNKNOWN is not rejection. |
| Required average order fill price | NOT_READY | Null remains null; no VWAP calculation. |
| Historical Trade extends live Position | FRONTEND_FIX | Independent schemas. Trade no longer requires valuation, unrealized PnL, allowed actions or inherited realized scalar. |
| Historical positionId required | FRONTEND_FIX | Nullable; explicit unavailable reference in detail. |
| Per-position unrealized PnL unavailable | BACKEND_GAP / NOT_READY | Preserve null and NOT_READY_NO_POSITION_PROJECTION. Never repeat account PnL per position/trade. |
| Dropped fill receipt/source/role/provenance | FRONTEND_FIX | Preserve all supplied fills and exact decimal text with their scoped identities. |
| Notes/tags required when annotations are null | FRONTEND_FIX | Read facts remain null; empty editor text is clearly a local draft. Initial concurrency token zero follows backend create semantics. |
| Missing metadata concurrency | FRONTEND_FIX | Required expectedVersion, SAVED/CONFLICT/ERROR result. Conflict preserves draft, disables overwrite and requires explicit newer-version reload. |
| setup edit capability absent | UNSUPPORTED / NOT_READY | Optional nullable model; disable editor without capability; HTTP serializer rejects setup. Fixture-only setup remains clearly scoped. |
| Required strategy/plan/name/levels/reference/timeframe | NOT_READY | Attribution/plan can be absent/null; historical UI shows No verified strategy attribution. No inference from opaque plan references. |
| R / initial risk unavailable | NOT_READY | Preserve null; no client R calculation. |
| Attachment storage reference treated as URL | FRONTEND_FIX | Preserve bounded string storage reference separately. Never convert it into URL. READY may lack delivery URL. |
| Attachment source/provenance required | FRONTEND_FIX | Nullable source/provenance and explicit Source unavailable. PENDING/FAILED/READY retain separate states. |
| User upload absent from HTTP | UNSUPPORTED / NOT_READY | Disable/hide without capability; K recorded fixture exposes NOT_READY. Existing labeled local fixture uploads remain session-only. |
| Analytics requires includedTradeIds/local completeness validation | FRONTEND_FIX / NOT_READY | Optional nullable membership with supplied status; no reconstruction from Journal pages. |
| Strategy analytics absent | NOT_READY | Preserve NOT_READY_NO_VERIFIED_ATTRIBUTION and reject invented strategy rows. |
| Negative fixture grossLoss | FRONTEND_FIX | Canonical positive magnitude and authored positive fixture losses. Average loss remains its supplied signed statistic. |
| One complete ProductSnapshot required | FRONTEND_FIX | Independent Resource states for Account, Orders, Positions, Trades, Journal, Analytics, detail and attachment pages. Unloaded data is null, not fake empty evidence. |
| Arrays erase pagination/cutoff | FRONTEND_FIX | Page retains items/nextCursor/hasMore/asOf. UI labels loaded-page scope; no account-history completeness assertion. Cursor is opaque. |
| Position action convenience lacks HTTP endpoint | UNSUPPORTED | Existing scripted positionAction explicitly FIXTURE_ONLY/optional. UI disables it when adapter operation is absent; no synthetic backend endpoint or quantity calculation. |
| Proxy drops required future headers | FRONTEND_FIX | Explicit request/response header allowlists; native Headers/tuple merge supported; no cookies/host forwarding. |
| Required fixture scenario/session assumptions | FRONTEND_FIX | Move into optional fixtureOnly classification. Canonical resource store needs neither scenario nor fixture session. |

Existing strategy display timeframes, canonical closed 15m clock, MTF roles, evidence timestamps and projections remain untouched.

## Final implementation

`frontend/src/lib/product/contracts.ts` defines the reconciled canonical models, pages, independent resource states, command and versioned metadata seams. `resource-store.ts` validates scoped resource updates independently; no transport runs there. `http-contract.ts` is pure response aliasing/validation and request-body preparation, not an HTTP adapter. Financial strings pass through exactly; best/worst display values are extracted from supplied summaries, never recomputed.

The fixture store keeps its complete pre-authored session script behind `FixtureSnapshot` and emits the new canonical resource view. Script-only live Trade values and embedded attachments are explicitly `FIXTURE_ONLY`; canonical UI reads attachment resources independently. Default ProductProvider still creates `createFixtureProduct()`.

Existing Paper pages retain their layout. Necessary changes are nullable labels, gross meaning, unavailable attribution/membership/strategy analytics, disabled setup/upload/action capabilities, loaded-page scope and explicit metadata conflict/reload handling.

Scenario **K — Recorded HTTP contract / nullable evidence** uses a byte-identical copy of `backend/tests/fixtures/paper_http_v1.json`, labeled FIXTURE_ONLY. That is saved trusted-scope TestClient evidence, not a live account/server response or deployed Paper execution. A–J and the technical error fixture remain operational. No `/api/paper` request is made by the browser tests.

## Header / concurrency preparation

Allowed inbound headers: Authorization, Idempotency-Key, If-Match, X-Request-ID, X-Correlation-ID. Allowed upstream response headers: Content-Type, Cache-Control, ETag, X-Request-ID, X-Correlation-ID. Headers are forwarded only to the configured backend path; Cookie/Host/forwarded routing headers are not copied. No credentials are fabricated or persisted.

Actual V1 idempotency authority is body **command_id**, and metadata concurrency authority is body **expected_version**. PATCH returns quoted-version ETag. Header preservation does not claim the backend implements Idempotency-Key or If-Match semantics. Existing timeout and safe error/status/body behavior remain intact.

## Verification

Artifacts: `docs/frontend-paper-contract-reconciliation-v1/`.

| Gate | Result |
|---|---|
| TypeScript | PASS |
| ESLint | PASS |
| Vitest / coverage / relevant components | PASS — 220 tests, 19 files; existing coverage thresholds retained |
| Next production build | PASS |
| Paper production Playwright + recorded contract desktop/mobile | PASS — 20 tests, including 1440 / 390 / 320px recorded-contract cases |
| Existing Dashboard / projection / evidence browser regression | PASS — Dashboard 8, projection 76, density V3 11, evidence V2 8 |
| All browser suites | PASS — 123 tests |
| git diff --check | PASS; line-ending notices only |
| Backend/config SHA-256 / concurrent-write check | PASS — all 269 baseline files unchanged; scoped existing frontend differences match this reconciliation |

New tests cover every requested null/NOT_READY/idempotency/version/membership/gross-loss/pagination/provider case plus account isolation before account load, response/request header preservation, and no fake stored-object URL. Existing proxy test now checks the actual native Headers value rather than assuming a plain object; error status/body/Accept assertions remain.

Recorded-contract Trade Detail and Analytics screenshots were created at 1440, 390 and 320px in the artifact directory. Desktop Trade Detail, 320px Trade Detail and 390px Analytics were visually inspected: null fields and unavailable capabilities are explicit, high-precision decimal strings remain intact, and there is no horizontal page overflow. Browser regression also checks all existing product pages at 1440 / 768 / 390 / 320px. These are browser renders of fixture evidence, not live Paper HTTP execution.

Local preview was restarted from this final build at `http://127.0.0.1:3002/paper-trading`; HTTP 200 / Paper Trading content verified. Scenario K is available in DEV/FIXTURE controls. Only the verified task-owned frontend preview process was replaced, using the existing frontend-only launcher. Backend runtime/configuration was not changed. Existing production browser/preview launchers emit the Next standalone-launch warning; the production page/browser gates pass, and this reconciliation does not change deployment packaging.

## Remaining backend data / next phase

Account display names, scalar multi-symbol valuation, per-position unrealized projection, verified strategy attribution/initial risk/R/setup, order average fill price, attachment delivery URLs/uploads, Analytics membership and strategy breakdown remain absent or NOT_READY by current backend evidence. None was supplied artificially.

Pagination request orchestration and HTTP persistence are intentionally future HTTP integration work; current seams preserve pages and UI scope without claiming full history. Default fixture pages are complete pre-authored demo collections. The backend Paper router remains default-deny/unmounted pending its own authenticated wiring. This reconciliation does not imply production readiness or successful HTTP execution.

STOP after reconciliation. FRONTEND-PAPER-HTTP-V1 was not started.
