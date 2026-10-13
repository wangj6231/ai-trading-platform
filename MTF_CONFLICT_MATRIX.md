# MTF-SPEC-01 — MTF Conflict Matrix

本矩陣只描述目前 engine/algorithm spec 已有的 deterministic conflict 行為，以及新產品
七個 input 在尚未完成 mapping 時的未決事項。它不新增 role、veto、score weight 或 trading
predicate。

## 1. Boundary assumptions

| 項目 | 已批准/已存在語義 | 分類 |
|---|---|---|
| decision clock | closed 15m candle | `SUPPORTED_PROPOSAL`（產品 baseline） |
| canonical source | 15m | `SUPPORTED_PROPOSAL`（產品 baseline） |
| input set | 15m, 30m, 1h, 2h, 4h, 1d, 1w | `SUPPORTED_PROPOSAL` |
| conflict authority | server MTF gate + deterministic reason code | `EXISTING`（舊 configured target） |
| candidate direction | ICT entry setup direction；不是 timeframe count 自行創造 | `EXISTING` |
| resolution | one `LONG`/`SHORT`/`NO_TRADE` | `EXISTING`/product contract |
| strategy selector | none; client chart selection has no authority | `SUPPORTED_PROPOSAL` |

## 2. State-level matrix

符號：B = `BULLISH`、S = `BEARISH`、R = `RANGE` 或非方向狀態、U = unavailable/stale、
I = incomplete bucket。下列 alignment 結果只有在該 timeframe 已進入 configured target、
required/veto membership 已確定時才適用。

| Candidate direction | Required state pattern | Veto state | Current engine outcome | Reason/status | Classification |
|---|---|---|---|---|---|
| LONG | bullish count 達 `mtf_min_aligned_timeframes`，沒有 opposing veto | none; veto states available | `ALIGNED` / `LONG_ELIGIBLE` | trade allowed if other gates pass | `EXISTING` |
| SHORT | bearish count 達 threshold，沒有 opposing veto | none; veto states available | `ALIGNED` / `SHORT_ELIGIBLE` | trade allowed if other gates pass | `EXISTING` |
| LONG | any configured veto timeframe = S | S veto | `CONFLICTING` / `NO_TRADE` | `MTF_VETO_CONFLICT` | `EXISTING` |
| SHORT | any configured veto timeframe = B | B veto | `CONFLICTING` / `NO_TRADE` | `MTF_VETO_CONFLICT` | `EXISTING` |
| LONG | opposite bearish alignment also passes | may be none | `CONFLICTING` / `NO_TRADE` | `MTF_BIDIRECTIONAL_ALIGNMENT` or opposite-aligned | `EXISTING` |
| SHORT | opposite bullish alignment also passes | may be none | `CONFLICTING` / `NO_TRADE` | `MTF_BIDIRECTIONAL_ALIGNMENT` or opposite-aligned | `EXISTING` |
| either | configured signal-timeframe alignment required, signal state opposite | opposite signal state | `CONFLICTING` / `NO_TRADE` | `MTF_SIGNAL_TIMEFRAME_CONFLICT` | `EXISTING` |
| either | directional count below threshold | none | `PARTIALLY_ALIGNED` / `NO_TRADE` | `MTF_NOT_ALIGNED` | `EXISTING` |
| either | required state absent and count/veto cannot safely pass | U | `PARTIALLY_ALIGNED` or `CONFLICTING` / `NO_TRADE` | `MTF_STATE_UNAVAILABLE` | `EXISTING` |
| either | required state stale | U (stale) | no eligible alignment | `MTF_STATE_STALE`/`MTF_STATE_UNAVAILABLE` | `EXISTING` |
| either | required target bucket incomplete | I | `NO_TRADE` | `MTF_INCOMPLETE_BUCKET` | `EXISTING` |
| either | source candle not closed at cutoff | I/U | no derived evidence | `NO_TRADE` / input failure | `EXISTING` |

## 3. Higher/lower timeframe disagreement examples

| Example | Evidence-backed interpretation | New seven-timeframe decision |
|---|---|---|
| old 1h = S, 15m/5m/3m = B; 1h configured as veto | 1h veto blocks bullish candidate even with three lower B states | **Do not generalize** until new veto membership is approved |
| required B and S counts both meet threshold | bidirectional alignment is rejected | **Keep** as a general safety invariant |
| candidate LONG, configured signal timeframe = S and alignment required | signal-timeframe conflict rejects | **Keep only if** new signal-timeframe field remains formally required |
| one higher timeframe missing, other states B | current low threshold may still count B if missing state is not veto | mapping required: all-seven-required vs subset; no hidden default |
| higher timeframe stale but lower states fresh | stale state is insufficient; if veto state, it cannot silently pass | target membership and stale policy must be explicit |

## 4. Missing/stale/incomplete matrix

| Condition at cutoff | What is known | Allowed action | Forbidden action | Classification |
|---|---|---|---|---|
| 15m source candle open + 15m > cutoff | source not closed | no evaluation / `NO_TRADE` | use current tick or partial 15m | `EXISTING` |
| 30m/HTF bucket has missing constituent | bucket incomplete | mark unavailable; block if required by configured gate | forward-fill, interpolate, use final full-history bar | `EXISTING` |
| target state confirmed after cutoff | future evidence | ignore event | include future state | `EXISTING` |
| target state source bar closes after cutoff | future bar | ignore event | expose it through MTF snapshot | `EXISTING` |
| state older than configured max age | stale | treat as insufficient | treat stale as neutral/bullish/bearish | `EXISTING` |
| optional/non-required target missing | no state | only proceed if formally allowed by required/veto policy | invent fallback or silently make it required | `UNRESOLVED` for new set |
| required/veto mapping absent from config | authority undefined | fail closed / configuration unavailable | default to majority or nearest timeframe | `SUPPORTED_PROPOSAL` safety boundary |

## 5. Seven-input conflict authority matrix

| Input | Existing role evidence | Existing required evidence | Existing veto evidence | New contract decision |
|---|---|---|---|---|
| 15m | old `MARKET_STRUCTURE`; new evaluation clock/source | old config no | old config no | role, required membership and veto `UNRESOLVED` beyond clock/source |
| 30m | none | none | none | `UNRESOLVED` |
| 1h | old `MARKET_BIAS` | old tests/config show it can be required in custom test, not production config | old test demonstrates veto | new authority `UNRESOLVED`; do not automatically retain veto |
| 2h | none | none | none | `UNRESOLVED` |
| 4h | none | none | none | `UNRESOLVED` |
| 1d | none | none | none | `UNRESOLVED` |
| 1w | none | none | none | `UNRESOLVED` |

## 6. No-majority-vote guard

Current algorithm uses a configurable count over `mtf_required_timeframes`, not a hard-coded
majority of all available timeframes. The count only has meaning after required and veto sets are
server-configured. The following are explicitly **not** supported proposals:

- `4 of 7` or any other fixed majority chosen because it sounds balanced;
- “HTF wins over LTF” without naming the timeframe and veto rule;
- average/weighted direction across timeframes;
- converting `RANGE` or missing state into the direction with the larger count;
- adding MTF score weights to compensate for unresolved role mapping.

## 7. Conflict resolution state machine

```text
validate 15m source and cutoff
        ├─ invalid/incomplete → NO_TRADE
        ▼
lookup only closed, confirmed, non-stale configured states
        ├─ authority/membership missing → NO_TRADE (configuration unavailable)
        ├─ opposing veto → NO_TRADE / MTF_VETO_CONFLICT
        ├─ both directions aligned → NO_TRADE / BIDIRECTIONAL
        ├─ candidate direction aligned → eligible (subject to score/risk)
        └─ otherwise → NO_TRADE / NOT_ALIGNED
```

The state machine is a representation of existing engine behavior, not permission to assign new
roles to 30m/2h/4h/1d/1w. Score and risk remain downstream safety gates and cannot upgrade an MTF
`NO_TRADE`.

## 8. Unresolved decisions before migration

1. Which of the seven inputs are `required` versus optional?
2. Which, if any, have veto authority?
3. Is `mtf_min_aligned_timeframes` a count over all required states or a named role group?
4. Must all seven states be available before a candidate can be released?
5. Does the 15m evaluation clock also act as the configured `mtf_signal_timeframe`?
6. Which timeframe supplies the optional dealing range/premium-discount gate?
7. Are higher-timeframe structure states the only MTF evidence, or is a separate approved
   multi-timeframe MACD/SNR/SMC evidence contract required?

Until these are answered by strategy/product authority, the safe implementation outcome is
configuration unavailable or `NO_TRADE`, never a guessed mapping.
