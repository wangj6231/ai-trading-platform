# F3 browser regression — unresolved, no frontend changes

Two ordinary complete runs each return five passes and one desktop refresh
timeout. The error is preserved in paper_browser.xml and paper_browser_final.xml.
Playwright reports one failed test; JUnit represents it as one error, not an
assertion failure. The focused tracing probe passes and the complete tracing run
passes all six. No assertions, timeout, retries or source code were changed.

The test submits an authenticated MARKET intent, injects a synthetic closed
candle through the private server Gateway driver, then clicks a visible per-order
refresh and waits ten seconds for a new account response. Failing snapshots show
the order already FILLED, its refresh action absent, and account summary still
10000 rather than9999.9USDT. The same mobile test passes; both desktop/mobile A–H
financial workflows pass. These facts do not prove that the narrow refresh test
or the production UI is correct.

Ranked hypotheses before targeted diagnosis:

1. The asynchronous post-submit refresh races the private observation. Its order
   response can become terminal before the test's refresh click while the account
   response represents the earlier state. Trace overhead predicts lower failure
   probability, but no failing network trace exists to establish the exact order.
2. The per-order command fails to refresh account state. The current source AND
   compiled client contain command→refresh; that alone cannot rule out a runtime
   branch/race. A root-cause-specific regression would still be required.
3. HTTP response rejection/timeout. No definitive failing response evidence was
   captured; this remains unverified rather than being labeled a strategy result.

The real worker is disabled in this browser harness; Gateway.observe is called
through private test control. Therefore it is a separate runtime path from F3
candidate discovery, NOT proof of a pre-F3 defect or immunity from timing effects.
The passing trace must not replace the failing ordinary regression gate.

Overall F3 is REGRESSION_FAILED. Candidate/backend checks passed and the remaining
Gateway performance bottleneck is separately documented. Frontend source/tests
remain unchanged; no financial validation is weakened to force a green browser
result. Root cause/fix needs a separately scoped verification/frontend task.
Do not start F4 automatically.

Raw tracing artifacts stay local diagnostic material, not publication-ready
evidence. Reported state comes from synthetic owned test accounts only, with no
bearer credentials or internal secret output in this note.
