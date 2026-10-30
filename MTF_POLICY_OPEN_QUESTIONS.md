# MTF-POLICY-02 — Remaining Open Questions

Owner-approved product decisions have been removed from this list. TF-MIGRATE-01B 之前只剩下
以下六項；本文件不替 owner 選值，也不把現有舊 config 當成新 policy 的答案。

## 六項 unresolved choices

| # | Choice | Current evidence | Exact owner input required | Safe behavior while open | 分類 |
|---|---|---|---|---|---|
| Q1 | `role_by_timeframe` | 只有舊 1h/15m/5m/3m/1m hierarchy；新七 input 沒有完整 mapping | 為 15m、30m、1h、2h、4h、1d、1w 各指定 role，或批准 role-less/context-only representation | unmapped input 不進新 pipeline；現有 schema 不可默認 role-less | `OWNER_DECISION_REQUIRED` |
| Q2 | `required_timeframes` | engine 支持 configured required subset；舊 config 只證明舊 `3m` | 明確列出新 strategy required subset | 不把七個 input 自動等同 required | `OWNER_DECISION_REQUIRED` |
| Q3 | `veto_timeframes` | engine/tests 支持 configured veto；舊測試不等於新 membership | 明確列出新 strategy veto subset | HTF 不因名稱自動 veto/override | `OWNER_DECISION_REQUIRED` |
| Q4 | `mtf_min_aligned_timeframes` | count 是 required set 上的 configurable integer；沒有 majority evidence | 指定 count domain/value 與 required-set 關係 | 不自行選 4/7、不轉 majority vote | `OWNER_DECISION_REQUIRED` |
| Q5 | `all_seven_required` | current engine 並非所有 target 都必須 available；product policy 未指定 | `true` 或 `false`，並說明 optional missing 的處理 | 未決時 new pipeline disabled/fail closed | `OWNER_DECISION_REQUIRED` |
| Q6 | per-timeframe max-age/warmup | max-age configurable；daily/weekly warmup 尚無 approved contract | 指定每個 timeframe 的 max-age、最小 closed bars、gap/freshness policy | 不用 partial/future/forward-filled state | `OWNER_DECISION_REQUIRED` |

## 已凍結、不是 open question

| Frozen item | Evidence | Status |
|---|---|---|
| one MTF strategy / one decision | TF-ARCH-02、shared coordinator/backtest path | `EXISTING` |
| canonical source = 15m | product contract、TF-MIGRATE-01A PASS | `SAFE_DEFAULT` |
| evaluation clock = closed 15m | product contract、PIT/resampler tests | `SAFE_DEFAULT` |
| `mtf_signal_timeframe = 15m` migration target | schema equality invariant；15m domain supported | `SAFE_DEFAULT` |
| inputs = 15m/30m/1h/2h/4h/1d/1w | canonical resampling domain/tests | `SAFE_DEFAULT` |
| HTF evidence = market structure/MTF alignment only | current coordinator/spec | `EXISTING` |
| cross-TF MACD/SMC/ICT/SNR aggregation prohibited | no supporting rule/implementation | `UNSUPPORTED` |
| dealing range disabled | current gate disabled；3m display-only | `SAFE_DEFAULT` |
| chart/realtime quote has zero strategy authority | product/TF contract | `SAFE_DEFAULT` |
| no majority, no weights, no HTF automatic override | no approved predicate | `UNSUPPORTED` |

## Decision form requirements

Owner 的回答只需填寫 [MTF_OWNER_DECISION_FORM.md](MTF_OWNER_DECISION_FORM.md)。
完成後才可建立 canonical StrategyConfig、更新 StrategyIdentity，並開始 TF-MIGRATE-01B。

在此之前：

- 不修改 active 1m/3m config；
- 不啟用七-input pipeline；
- 不添加跨 timeframe indicator 或 SMC/ICT predicate；
- 不以 default、available bars 或 chart selection 推導六項答案。
