# Quality gates

M-09 existed because the asynchronous dashboard and backend proxy boundaries had
no direct regression coverage, while neither application had a repeatable
coverage/static-analysis gate. A passing unit suite therefore did not prevent a
late, aborted response from overwriting the current dashboard selection, and
source quality could drift without failing an automated command.

## Frontend request ownership

Every dashboard effect owns one `AbortController`. Changing symbol, changing
timeframe, retrying, or unmounting aborts that effect. Both success and failure
continuations must check that controller before committing React state. A late
response from an aborted request is ignored; it cannot replace the current
market identity or render an actionable signal.

The proxy remains a transparent, fail-closed boundary. A network failure returns
`503 BACKEND_UNAVAILABLE`, its finite wait boundary returns
`504 BACKEND_TIMEOUT`, and an actual backend error status/body/content type is
preserved. Malformed POST JSON is rejected before forwarding. M-09 owns request
state/race safety; the later M-01/M-02 remediation adds the documented transport
failure contract without changing valid strategy responses.

## Automated gates

Run all repository gates on Windows PowerShell from the repository root:

```powershell
.\scripts\quality-gates.ps1
```

The script runs:

- Ruff over all backend application and test Python files;
- mypy over all 95 backend application source files;
- the backend pytest suite with application line coverage required to remain at
  or above 90%;
- frontend strict TypeScript checking, ESLint, and Vitest coverage.

The frontend Vitest gate measures every `src/**/*.ts` and `src/**/*.tsx` file,
including zero-coverage application files. Its current minimums are 60% for
statements and lines, 55% for branches, and 50% for functions. These floors are
a regression barrier based on the measured repository baseline, not a claim of
complete test coverage; they may be raised as tests expand.

Regular `pytest` and `npm test` remain unchanged. Coverage runs are explicit so
local focused tests are not slowed unexpectedly.

## Compatibility and identity

No API payload, trading rule, persistence schema, historical snapshot, or
strategy configuration changed. There is no Alembic revision. `config_hash`,
`strategy_version`, and historical identities remain unchanged. Source changes
may naturally produce a new `algorithm_build_hash` under the existing H-12/V3
source-identity contract.
