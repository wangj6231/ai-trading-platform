# Frontend dependency security upgrade

Date: 2026-10-29 (Asia/Taipei)

## Scope

This change is a dedicated dependency-security update based on protected
`main` commit `66def00f039eebcd142d965a8d88f8824b9f8af9`. It is intentionally
separate from the in-progress product/Journaling work and from portfolio PR
#17. It does not change backend, database, trading, or financial behavior.

## Findings

The pre-upgrade `npm audit` reported 10 vulnerabilities across the installed
frontend dependency tree: 3 critical, 5 high, and 2 moderate. The affected
packages included Next.js, Vitest/tinypool/@vitest/mocker, Vite,
brace-expansion, sharp, source-map-js, and Zod.

GitHub Dependabot separately reported 17 open alerts on the default branch.
Several entries refer to the same package/advisory through both
`package.json` and `package-lock.json`, so the alert count is not the same as
the npm vulnerability count.

## Upgrade decision

| Package | Before | After | Reason |
| --- | --- | --- | --- |
| Next.js | 16.3.3 | 16.4.3 | Patched critical/high Next.js advisories |
| eslint-config-next | 16.3.3 | 16.4.3 | Keep framework lint rules aligned |
| Vitest | 3.2.7 | 4.1.12 | First selected line covering current mocker/tinypool fixes without jumping to Vitest 5 |
| @vitest/coverage-v8 | ^3.2.7 | 4.1.12 | Match the Vitest runtime exactly |
| Vite | 6.4.3 | 6.4.5 | Patched launch-editor and dev-server advisories without a Vite major upgrade |
| Zod | ^4.1.0 | 4.6.7 | Patched oversized-collection resource exhaustion |

The lockfile also resolves patched transitive versions through a normal
`npm audit fix`. No `--force`, legacy peer-dependency bypass, or security
exception was used.

## Compatibility changes

Vitest 4 removes the typed `coverage.all` option and uses an ESM-first config
path. The configuration was therefore renamed from `vitest.config.ts` to
`vitest.config.mts`, the removed option was deleted, and `__dirname` was
replaced by `import.meta.dirname`. Coverage include/exclude behavior and all
thresholds remain enforced.

The first development-dependency install exposed an npm 10.7.0 Arborist
`edgesOut` internal error under the machine's Node 20.15.1 because it reused a
mixed incremental dependency tree. A later npm 11 lockfile passed locally but
failed the first PR CI install because the repository workflow actually uses
Node 20.20.2/npm 10 and required additional optional native dependency
metadata. The final lockfile was therefore rebuilt from a clean temporary
directory with npm 10, then verified with `npm ci` and the complete frontend
gate in an ASCII-path candidate mirror matching the CI path shape. The local
worktree's non-ASCII parent path still triggers the npm 10 Arborist `edgesOut`
bug even without `node_modules`; this is a local package-manager path defect,
not a relaxed gate. The failed attempts did not require a forced install or
relaxed peer-dependency policy.

## Verification

- Clean npm 10 `npm ci`: PASS.
- `npm audit --audit-level=low`: 0 vulnerabilities.
- TypeScript `tsc --noEmit`: PASS.
- ESLint: PASS.
- Vitest 4.1.12 coverage: 69/69 tests PASS; statements 75.59%, branches
  68.28%, functions 72.17%, lines 79.26%.
- Playwright: 74/74 required browser tests PASS on the `main` baseline.
- Next.js 16.4.3 production build: PASS.

These results prove dependency compatibility for the current public `main`
frontend baseline. They do not prove strategy profitability, LIVE trading,
production readiness, or the separate in-progress PR #17 feature set.
