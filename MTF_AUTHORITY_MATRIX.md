# MTF-POLICY-02 — Frozen MTF Authority Matrix

這份矩陣將已批准的產品 boundary 與尚未批准的 authority mapping 分開。每一列最後的
分類只使用 `EXISTING`、`SAFE_DEFAULT`、`OWNER_DECISION_REQUIRED`、`UNSUPPORTED` 之一。

## Input timeframe matrix

| Timeframe | Frozen role/evidence scope | Frozen authority | Current evidence | Owner decision still required | 分類 |
|---|---|---|---|---|---|
| `15m` | canonical source、closed evaluation clock、approved signal-timeframe；alignment role 未定 | source/clock 是必需 boundary；required/veto/optional 尚未定 | TF-MIGRATE-01A source/PIT/resample；schema equality invariant | role、required、veto、count、age/warmup | `OWNER_DECISION_REQUIRED` |
| `30m` | derived input；只能在 owner mapping 後提供 structure/alignment evidence | 未批准前沒有 decision authority | canonical 15m resample；無 MTF role registry mapping | role、required/veto、count、age/warmup | `OWNER_DECISION_REQUIRED` |
| `1h` | derived input；舊 `MARKET_BIAS` 不自動移植 | 不因 HTF 名稱自動 veto/override | 舊 hierarchy/veto tests 僅證明舊 pipeline semantics | 新 role、required/veto、count、age/warmup | `OWNER_DECISION_REQUIRED` |
| `2h` | derived input；只限 structure/alignment scope | 未批准前沒有 decision authority | canonical resample；無 role integration | role、required/veto、count、age/warmup | `OWNER_DECISION_REQUIRED` |
| `4h` | derived input；只限 structure/alignment scope | 未批准前沒有 decision authority | canonical resample；無 role integration | role、required/veto、count、age/warmup | `OWNER_DECISION_REQUIRED` |
| `1d` | UTC-derived input；只限 structure/alignment scope | 未批准前沒有 decision authority | 00:00 UTC resample；無 daily role contract | role、required/veto、count、age/warmup | `OWNER_DECISION_REQUIRED` |
| `1w` | ISO Monday UTC-derived input；只限 structure/alignment scope | 未批准前沒有 decision authority | Monday 00:00 resample；無 weekly role contract | role、required/veto、count、age/warmup | `OWNER_DECISION_REQUIRED` |

### Role-less / context-only boundary

產品 policy 允許「input 不代表 authority」這個暫時狀態，但現有 implementation 不能直接
表示它：`MTFRole` 沒有 context-only/role-less enum，snapshot role 為必填，
`INITIAL_HIERARCHY[timeframe]` 也沒有新 timeframe mapping。故：

- role mapping 的 policy：`OWNER_DECISION_REQUIRED`；
- 直接用現有 schema 表示 role-less/context-only：`UNSUPPORTED`；
- 不得把 30m/2h/4h/1d/1w 靜默標為 bias、structure、setup 或 trigger。

## Frozen authority surfaces

| Surface | Frozen policy | Existing support | Remaining owner choice | 分類 |
|---|---|---|---|---|
| canonical source | server-owned 15m | TF-MIGRATE-01A | none | `SAFE_DEFAULT` |
| evaluation clock | closed 15m only | PIT/resampling tests | none | `SAFE_DEFAULT` |
| `mtf_signal_timeframe` | migration target 15m；必須與 `signal_timeframe` 相等 | schema equality invariant；15m domain valid | none（migration implementation 仍待後續） | `SAFE_DEFAULT` |
| input domain | exactly 15m/30m/1h/2h/4h/1d/1w | canonical resampler tests | none | `SAFE_DEFAULT` |
| higher-TF evidence | structure + MTF alignment only | current coordinator/MTF spec | none | `EXISTING` |
| cross-TF indicators/SMC/SNR | prohibited | no supporting implementation/spec | none | `UNSUPPORTED` |
| dealing range | disabled | current gate disabled | none | `SAFE_DEFAULT` |
| chart authority | zero | product/TF contract | none | `SAFE_DEFAULT` |
| realtime quote authority | zero; display-only | market-data boundary | none | `SAFE_DEFAULT` |
| HTF automatic override | prohibited | no approved predicate | none | `UNSUPPORTED` |
| majority vote / new score weights | prohibited | no approved rule | none | `UNSUPPORTED` |

## Remaining authority choices

| Surface | What is unresolved | Evidence currently available | 分類 |
|---|---|---|---|
| `role_by_timeframe` | role for each seven input, or approved role-less representation | only old hierarchy is implemented; new mappings absent | `OWNER_DECISION_REQUIRED` |
| `required_timeframes` | exact required subset | old config only proves old `3m` required | `OWNER_DECISION_REQUIRED` |
| `veto_timeframes` | exact veto subset | configured veto semantics exist; membership is not approved | `OWNER_DECISION_REQUIRED` |
| `mtf_min_aligned_timeframes` | count domain/value over approved required set | current engine uses configurable count, not fixed majority | `OWNER_DECISION_REQUIRED` |
| `all_seven_required` | whether every input must be closed/fresh/mapped | current engine does not require every target by default | `OWNER_DECISION_REQUIRED` |
| per-timeframe max-age/warmup | freshness and minimum history per input | max-age is configurable; daily/weekly policy not approved | `OWNER_DECISION_REQUIRED` |

## Fail-closed matrix

| Condition | Behavior | 分類 |
|---|---|---|
| duplicate/gap/invalid/incomplete canonical source | reject; no forward fill or external HTF override | `EXISTING` |
| missing/stale required or veto state | unavailable/stale reason; no neutral substitution | `EXISTING` |
| unresolved role/authority | new pipeline disabled/configuration unavailable | `SAFE_DEFAULT` |
| configured veto/opposite/bidirectional conflict | existing MTF conflict reason and `NO_TRADE` | `EXISTING` |
| ordinary disagreement before count/veto approval | no majority or HTF override; remain unresolved/fail closed | `SAFE_DEFAULT` |

## Authority ownership

| Boundary | Trusted owner | Timestamp/cutoff | Mutability | Tests/spec |
|---|---|---|---|---|
| canonical 15m OHLCV | server market-data/resampler | complete UTC bucket closed by cutoff | append-only source | TF-MIGRATE-01A/PIT tests |
| MTF structure/alignment | deterministic MTF engine | source close and confirmation <= decision cutoff | derived snapshot/versioned config | MTF unit tests |
| role/required/veto/count/age policy | canonical StrategyConfig after owner decision | applies at evaluation cutoff | identity-bound, not client-owned | StrategyConfig/StrategyIdentity tests |
| chart/realtime quote | display layer | never strategy evidence | mutable display state | product/TF contract |

## Migration gate

The policy is frozen, but enablement waits for the six unresolved decisions and their explicit
schema/config implementation. The old 1m active pipeline remains unchanged until a separate
TF-MIGRATE-01B task performs that migration and its tests.
