# FVG and IFVG

## FVG - Fair Value Gap

### REFERENCE_DEFINED

- **Definition:** 價格圖上的一個 range，反映 buyers 與 sellers 之間的 imbalance；參考資料把它描述為 empty square，並說價格回到新形成的 bullish FVG 時預期上升、回到 bearish FVG 時預期下跌。[SMC_CONCEPT, p. 3]
- **Bullish condition:** 圖例顯示上行三燭序列中第一根高點與第三根低點之間存在未重疊區；entry model 要求 MSS 後的 displacement leg 中存在 FVG。[SMC_CONCEPT, p. 3; HIGH_PROBABILITY_ENTRY_MODEL, p. 2]
- **Bearish condition:** 圖例顯示下行三燭序列中第一根低點與第三根高點之間存在未重疊區。[SMC_CONCEPT, p. 3]
- **Required OHLC information:** 圖例支持至少三根 K 線的 high/low；正文沒有正式寫出索引公式。
- **Required market context:** standalone FVG 頁面只要求 imbalance；entry model 另要求 MSS/break 後 displacement leg 中的 FVG。[SMC_CONCEPT, p. 3; HIGH_PROBABILITY_ENTRY_MODEL, pp. 1-2]
- **Confirmation requirements:** 參考資料未說明第三根 candle 是否必須封閉、gap 最小尺寸或中間 candle 的 body/range 條件。
- **Invalidation:** 未提供 fill、close-through、age、touch count 等失效規則。
- **Edge cases:** 零寬 gap、等價觸碰、跨 session gap、缺資料、後續部分填補、同一 leg 多個 FVG。
- **Potential ambiguity:** 圖例可支持三燭 non-overlap 的視覺解讀，但公式、方向符號、邊界及最小尺寸仍不足以直接編碼。

狀態：概念與方向反應為 `REFERENCE_DEFINED`；detector 為 `NEEDS_FORMALIZATION`。

### ENGINEERING_PROPOSAL

```text
ImbalanceZone
  kind = FVG
  direction
  candle_refs[3]
  lower_bound
  upper_bound
  formed_at
  confirmed_at
  fill_state              # unresolved
  displacement_ref?
```

建議表示一個區域而非單點，但 bounds 公式與 fill state machine 必須先核准。

## IFVG - Inversion FVG

### REFERENCE_DEFINED

- **Definition:** 參考資料只展開名稱 “Inversion FVG”，並提供一個 candlestick 圖例。[SMC_CONCEPT, pp. 2, 4]
- **Bullish condition:** 未提供文字。圖例本身沒有明確標示方向名稱或 inversion trigger。
- **Bearish condition:** 未提供文字。
- **Required OHLC information:** 圖例含多根 K 線與一個標為 IFVG 的水平區域，但無法可靠推導公式。
- **Required market context:** 未提供。
- **Confirmation requirements:** 未提供。
- **Invalidation:** 未提供。
- **Edge cases:** 原 FVG 是否必須先完全失效、部分穿越、同 candle 反轉、再次 inversion。
- **Potential ambiguity:** inversion 的觸發價、wick/close 要求、原 FVG 方向、IFVG bounds、有效期及 retest 條件全部缺失。

狀態：`NEEDS_FORMALIZATION`。

### ENGINEERING_PROPOSAL

只建議預留 `ImbalanceZone(kind=IFVG, origin_fvg_ref, direction, bounds, inversion_trigger_ref)`。在 inversion state transition 被人工定義前，不得由 FVG 自動轉成 IFVG。
