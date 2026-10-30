# MTF Owner Decision Form

用途：填寫 TF-MIGRATE-01B 前唯一尚未決定的六個 authority choices。請填寫明確值；不要
使用「依市場情況」「多數決」「HTF 自動覆蓋」等未定義語句。

## 1. Role mapping

請為每個 input 指定一個已支援 role，或明確批准新增 role-less/context-only representation。

| Timeframe | Approved role / role-less / context-only |
|---|---|
| 15m | |
| 30m | |
| 1h | |
| 2h | |
| 4h | |
| 1d | |
| 1w | |

## 2. Required set

```text
required_timeframes = [ ... ]
```

## 3. Veto set

```text
veto_timeframes = [ ... ]
```

## 4. Minimum alignment count

```text
mtf_min_aligned_timeframes = ...
```

請說明 count 是針對哪一個 `required_timeframes` set；這不是 majority vote 欄位。

## 5. All-seven availability

```text
all_seven_required = true | false
```

## 6. Per-timeframe max-age / warmup

請以 closed source bars 表示，不使用 partial candle 或 forward fill：

```text
max_age_and_warmup = {
  "15m": {"max_age": "...", "min_closed_bars": "..."},
  "30m": {"max_age": "...", "min_closed_bars": "..."},
  "1h":  {"max_age": "...", "min_closed_bars": "..."},
  "2h":  {"max_age": "...", "min_closed_bars": "..."},
  "4h":  {"max_age": "...", "min_closed_bars": "..."},
  "1d":  {"max_age": "...", "min_closed_bars": "..."},
  "1w":  {"max_age": "...", "min_closed_bars": "..."}
}
```

填妥後仍須通過 schema、PIT、prefix-invariance、identity 與 fail-closed tests；本表本身
不會修改 code/config。
