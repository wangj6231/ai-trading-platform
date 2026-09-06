# CRT - Candle Range Theory

## CRT

### REFERENCE_DEFINED

- **Definition:** 每一根 candle 是一個 range；當 high 或 low 被 swept，價格被描述為 drawn to the opposite wick。[CRT_METHOD, p. 2]
- **Bullish condition:** 圖例顯示 Candle 1 accumulation 建立 range，Candle 2 manipulation 掃低側，Candle 3 distribution 向上。Bullish entry 提示為在第三根 candle 的 open 下方買入，圖示目標方向朝 CRT high。[CRT_METHOD, pp. 3, 6]
- **Bearish condition:** 圖例顯示 Candle 2 掃高側、Candle 3 向下 distribution。Bearish entry 提示為在第三根 candle 的 open 上方賣出，圖示目標方向朝 CRT low。[CRT_METHOD, pp. 3, 5]
- **Required OHLC information:** 至少三根依序 candle 的 open/high/low/close、CRT range high/low、sweeping candle 的 closed 狀態、第三根 candle open。
- **Required market context:** 文件稱使用 “Power of Three”：Candle 1 accumulation、Candle 2 manipulation、Candle 3 distribution。[CRT_METHOD, p. 3]
- **Confirmation requirements:** 有效 CRT 要求 sweeping liquidity 的 candle 必須 closed。[CRT_METHOD, p. 4] 文件沒有文字說明 sweeping candle 必須 close 回 CRT range 內。
- **Invalidation:** 未提供。沒有 stop、最大等待時間、第三根 candle 未到 opposite wick 或再穿 sweep extreme 的失效規則。
- **Edge cases:** Candle 2 同時掃 high/low、僅觸及而未穿越、gap 穿越、Candle 3 open 等於 entry boundary、Candle 3 先到 target 再回到 entry、超過三根才 distribution、不同 timeframe/session 對齊。
- **Potential ambiguity:** 哪一根 candle 的 high/low 定義 CRT range、sweep 的比較符號與 wick/close、Candle 2 close 位置、第三根 candle 的完整辨識、entry “above/below open” 的 zone bounds、entry confirmation、SL、target 是否精確 opposite wick。

狀態：三燭敘事、closed-candle 要求與 entry 相對第三根 open 的方向為 `REFERENCE_DEFINED`；deterministic CRT rule 為 `NEEDS_FORMALIZATION`。

### ENGINEERING_PROPOSAL

```text
CRTCandidate
  range_candle_ref
  range_high
  range_low
  manipulation_candle_ref
  swept_side              # HIGH | LOW
  sweep_interaction_ref
  manipulation_closed_at
  distribution_candle_ref?
  direction?
  third_candle_open?
  entry_zone?             # unresolved
  target_ref?             # unresolved opposite wick candidate
  invalidation_ref?       # unresolved
```

建議把 accumulation/manipulation/distribution 保存為獨立角色，且只有 manipulation candle 封閉後才能進入下一個候選狀態。這只是 anti-look-ahead 資料設計，不代表 sweep 或 entry 條件已核准。

## 待核准的 CRT 狀態流程

以下只是 `ENGINEERING_PROPOSAL` 的流程外殼：

```text
RANGE_IDENTIFIED
  -> SWEEP_TENTATIVE
  -> SWEEP_CANDLE_CLOSED
  -> DISTRIBUTION_CANDIDATE
  -> ENTRY_ELIGIBLE | INVALIDATED | EXPIRED
```

每一條 transition 的 OHLC predicate、timeout、entry zone、stop 與 target 全部是 `NEEDS_FORMALIZATION`，目前不得實作。
