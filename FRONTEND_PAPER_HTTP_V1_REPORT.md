# FRONTEND-PAPER-HTTP-V1 report

Date: 2026-10-09, Asia/Taipei. Branch: FRONTEND-PRODUCT-V1.

Final classification: **PASS** — authenticated HTTP integration, not full Paper execution E2E.

## GRILL findings

No other active frontend writer was observed before edits (agent tree and app tasks
checked). Fresh source/hash baseline saved in `docs/frontend-paper-http-v1/baseline.json`.
The reconciliation baseline was re-read; backend AUTH-ACCOUNT-SCOPE-V1 now mounts
`/api/v1/paper/accounts/{account_id}` and normal lifespan resolves real opaque
credentials plus current server-owned account grants. No public onboarding/account
discovery or observation/upload endpoint exists.

| Finding | Action |
|---|---|
| ProductProvider always chose fixture | Request-time server selection and isolated Fixture / HTTP / unavailable sessions. |
| Resource store and DTO aliases had no transport | HttpProductAdapter with independent validated resources; no financial computation. |
| Safe bootstrap needed | Explicit provisioned account and server-only bearer injection; loopback opt-in; no consumer Auth. |
| Existing generic proxy accepted broader headers | Separate bounded Paper proxy, known paths/queries, approved headers, no cookie/host forwarding. Existing strategy proxy behavior retained. |
| Pages had no continuation orchestration | Opaque cursor/asOf/applied filter continuation, refresh and loaded-page scope; no all-history assertion. |
| Trade detail had only prefilled fixture resources | Account-scoped detail, attachment and fill fetch on entry. |
| Metadata conflict needed latest HTTP read | Fetch latest while preserving the mounted draft; explicit reconciliation/retry. |
| Protected state could survive a failed authorization read | 401/403 clear/block all resources and discard pending/late responses. |
| UNKNOWN needed refresh without fixture advancement | Generic read refresh; UNKNOWN is neither REJECTED nor FILLED. |
| No HTTP position action endpoint | Convenience action stays disabled, no synthetic endpoint/quantity. Existing user ticket remains available. |

Frozen backend financial, Paper/Journal/Analytics, DTO, auth, strategy and MTF
semantics are not changed. Existing evidence projection sources are untouched.

## Result and limits

Existing Paper UI supports authenticated Account, orders/submit/cancel/refresh,
positions, paginated trades/Journal, independent trade detail/fills/attachments,
metadata mutation/conflict, and Analytics. HTTP has no fixture financial fallback.
Fixture runtime remains available and explicitly labeled. Only presentation controls
required by HTTP were added; no visual rebuild, consumer login, LIVE broker or upload.

See `FRONTEND_PAPER_HTTP_RUNTIME_CONTRACT.md` for exact configuration and security
boundary. Server credentials/backend origin are not serialized into public runtime
selection, client state, browser storage, fixture data or reports. Account target is
not authorization; backend remains final authority.

## Verification

Artifacts: `docs/frontend-paper-http-v1/`.

| Gate | Result |
|---|---|
| TypeScript | PASS |
| ESLint | PASS |
| Vitest / component / coverage | PASS — 257 tests, 21 files, thresholds unchanged |
| Next production build | PASS — runtime configuration resolved at request time |
| Actual owned authenticated backend checks | PASS — real app lifespan/verifier/ownership/service, no dependency overrides; `owned-backend-checks.json` |
| HTTP desktop/mobile Playwright | PASS — 4 tests, 1440 / 390 / 320px, actual authenticated local HTTP |
| Existing Fixture Paper / Dashboard / chart browser regression | PASS — Fixture 20, Dashboard 8, projection 76, density 11, evidence 8; 123 existing tests |
| Total browser tests | PASS — 127 |
| Visual inspection / horizontal overflow | PASS — desktop Trade detail / 320px detail / 390px Analytics inspected; additional expanded fill references at 320px retain scrollWidth=320 |
| Backend/config/source integrity and diff check | PASS — 272 baseline backend/config files unchanged; scoped frontend differences only; diff check exit 0 |

The owned harness uses a temporary SQLite database, actual provisioning and actual
application lifespan with zero dependency overrides. Controlled server observations
seed LONG/SHORT, scale-in, partial/full close, four-fill Trade, financial admission
rejection and Journal/Analytics evidence before the browser starts. Submission
timeout is an explicit test fault using the existing adapter path, not a strategy or
accounting change. Credentials pass only through a private parent process pipe into
Next server environment, with no raw credential log/file/browser storage.

HTTP tests verify actual MARKET/LIMIT, idempotent command replay and changed-command
409, cancellation, non-filled ACK, UNKNOWN, insufficient balance evidence, version
conflict, cursor pages, attachment PENDING/FAILED, null attribution/R, Analytics and
scope/validation failures. Unit/component tests additionally exercise late response
discard, 401/403 clearing, no fixture fallback, account switching, safe raw errors,
local SUBMITTING and draft preservation. No weakened assertion/threshold is used.

Ordinary issues found during verification were fixed: Windows child-process import
guard in the owned harness; Next's internal localhost URL versus incoming private
authority; native browser fetch receiver binding; UNKNOWN fixture refresh label.
Failed attempts are retained separately
from the final passing verification logs.

Client static assets were scanned for the actual issued bearer and private backend
origin; neither was present. Browser requests carry no bearer, HTML contains no
opaque credential, and localStorage/sessionStorage remain empty. Safe error tests
reject raw exception text and unsupported header/path/query forwarding. The existing
Next launchers still emit a standalone-packaging warning; actual production-build
page tests pass. Deployment packaging is unchanged by this integration.

An owned isolated HTTP review instance remains at `http://127.0.0.1:3013/paper-trading`,
backed by the isolated test server at local port 8013. This is actual authenticated
HTTP with canonical server-generated test observations, not frontend fixture data
and not a production market execution account. Its private process-only credential
and temporary database are separate from the user's existing backend/account.
Preview startup/ownership is recorded under frontend's local cache, not with secrets
in report artifacts. The normal application's default remains the explicit FIXTURE
development configuration until its server HTTP bootstrap is supplied.

## Remaining product/backend evidence

No consumer login/onboarding/account discovery. Setup/upload and attachment delivery
remain NOT_READY. Verified attribution/R/membership/strategy breakdown are absent.
No observation worker was enabled. A browser HTTP ACK is not a fill. Production
account/credential provisioning and deployment auth must use their own approved
server boundary; this private development bridge is not consumer authentication.

**Full Paper execution E2E is not proven.** Preseeded server observations plus HTTP
reads/commands do not constitute browser order → observation/fill → Journal →
Analytics execution E2E. PAPER-E2E-V1 was not started.

STOP after FRONTEND-PAPER-HTTP-V1.
