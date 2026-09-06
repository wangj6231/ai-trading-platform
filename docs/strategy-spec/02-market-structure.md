# Market Structure

## Swing High

### REFERENCE_DEFINED

- **Definition:** 沒有文字定義。Liquidity 圖只把一個明顯局部高點標為 “Swing High Liquidity”。[SMC_CONCEPT, p. 9]
- **Bullish condition:** 未提供。
- **Bearish condition:** 未提供；圖例把 swing high 上方視為 buy-side liquidity 的一種位置。[SMC_CONCEPT, p. 9]
- **Required OHLC information:** 圖例支持至少需要一系列價格高低點，但沒有指定使用 `high`、`close` 或何種 pivot window。
- **Required market context:** 未提供；BOS/MSS、breaker、liquidity 等概念會引用先前高點。
- **Confirmation requirements:** 未提供。
- **Invalidation:** 未提供。
- **Edge cases:** equal highs、relative equal highs、trend-line highs 被畫成不同 liquidity 類型，但沒有分群容差。[SMC_CONCEPT, p. 9]
- **Potential ambiguity:** 左右 lookback、等高容差、wick/close、最小 prominence、右側確認延遲、nested swings 全部未定。

狀態：`NEEDS_FORMALIZATION`。

### ENGINEERING_PROPOSAL

只建議資料表示，不建議公式：`SwingPoint(type=HIGH, pivot_bar_id, price, confirmed_at, scale_id, evidence_bar_ids)`。`scale_id`、確認方式與 price 欄位選擇必須先由人工決定。

## Swing Low

### REFERENCE_DEFINED

- **Definition:** 沒有文字定義。Liquidity 圖只把一個明顯局部低點標為 “Swing Low Liquidity”。[SMC_CONCEPT, p. 9]
- **Bullish condition:** 圖例把 swing low 下方視為 sell-side liquidity 的一種位置。[SMC_CONCEPT, p. 9]
- **Bearish condition:** 未提供。
- **Required OHLC information:** 圖例支持至少需要一系列價格高低點，但沒有指定 `low`、`close` 或 pivot window。
- **Required market context:** 未提供；BOS/MSS、breaker、liquidity 等概念會引用先前低點。
- **Confirmation requirements:** 未提供。
- **Invalidation:** 未提供。
- **Edge cases:** equal lows、relative equal lows、trend-line lows 沒有量化區隔。[SMC_CONCEPT, p. 9]
- **Potential ambiguity:** 與 Swing High 相同，另包含負價格、tick size 與 gap 對 low 比較的影響。

狀態：`NEEDS_FORMALIZATION`。

### ENGINEERING_PROPOSAL

建議使用與 Swing High 相同的 `SwingPoint`，僅 `type=LOW`；不預先決定偵測器。

## BOS - Break of Structure

### REFERENCE_DEFINED

- **Definition:** 價格突破先前 market structure 的時刻，可能發生在 high side 或 low side。[SMC_CONCEPT, p. 6]
- **Bullish condition:** 圖例在轉為上升結構後，價格陸續突破先前高點並標示 BOS。[SMC_CONCEPT, p. 6]
- **Bearish condition:** 圖例在下降結構中，價格突破先前低點並標示 BOS。[SMC_CONCEPT, p. 6]
- **Required OHLC information:** 需要價格序列及某個已識別的 prior structure level；未說明 break 使用 wick 或 close。
- **Required market context:** 必須先有 “previous market structure”；其產生方式未定義。
- **Confirmation requirements:** 只寫 “breaks through”，沒有 candle-close、距離或 displacement 要求。
- **Invalidation:** 未提供。
- **Edge cases:** wick 穿越後收回、同價觸碰、gap 穿越、同根 K 線同時穿越高低兩側、nested structure。
- **Potential ambiguity:** structure level 選擇、方向延續與反轉的區分、BOS 與 MSB/MSS 的關係均未定。

狀態：`NEEDS_FORMALIZATION`。

### ENGINEERING_PROPOSAL

```text
StructureBreak
  kind = BOS
  direction
  broken_level_ref
  break_bar_id
  observed_extreme
  confirmation_basis      # unresolved: WICK | CLOSE | OTHER
  confirmed_at
```

`confirmation_basis` 必須經決策後才可產生事件。

## MSS - Market Structure Shift

### REFERENCE_DEFINED

- **Definition:** 趨勢方向因先前價格結構 pattern 被破壞而出現顯著改變。[SMC_CONCEPT, p. 5]
- **Bullish condition:** 圖例顯示下降結構破壞後轉向上升；entry model 要求朝預期交易方向出現 MSS/break 並伴隨 displacement。[SMC_CONCEPT, p. 5; HIGH_PROBABILITY_ENTRY_MODEL, p. 1]
- **Bearish condition:** 定義可對稱涵蓋上升轉下降，但參考資料沒有文字化 bearish checklist。
- **Required OHLC information:** 價格序列、先前趨勢、被破壞的 structure level；未說明 wick/close。
- **Required market context:** 必須先有可識別趨勢與 prior price structure pattern。
- **Confirmation requirements:** “significant change” 與 “destruction” 未量化。Entry model 另要求 displacement，但不能證明所有 MSS 的定義都必須包含 displacement。[HIGH_PROBABILITY_ENTRY_MODEL, p. 1]
- **Invalidation:** 未提供。
- **Edge cases:** range market、短暫反向 wick、連續雙向 break、不同 swing scale 給出相反趨勢。
- **Potential ambiguity:** significant 的尺度、trend 定義、被破壞 level、與 BOS 的先後／分類、是否必須 liquidity sweep 或 displacement。

狀態：`NEEDS_FORMALIZATION`。

### ENGINEERING_PROPOSAL

建議 `StructureShift` 引用 `prior_trend_state`、`broken_level_ref`、`trigger_bar_id`，並可選擇引用 `displacement_ref`；不可把 displacement 設為必填，除非 entry model 規格另行核准。

## CHoCH - Change of Character

### REFERENCE_DEFINED

- **Definition:** 參考資料明言 CHoCH 與 MSS 是相同概念、不同術語。[SMC_CONCEPT, p. 5]
- **Bullish condition:** 與 MSS 相同，沒有獨立條件。
- **Bearish condition:** 與 MSS 相同，沒有獨立條件。
- **Required OHLC information:** 與 MSS 相同。
- **Required market context:** 與 MSS 相同。
- **Confirmation requirements:** 沒有獨立要求。
- **Invalidation:** 未提供。
- **Edge cases:** 外部使用者可能期待 CHoCH 與 MSS 不同，但 supplied references 不支持此區分。
- **Potential ambiguity:** 是否只作 UI alias，或需要獨立 subtype。

狀態：別名關係為 `REFERENCE_DEFINED`；偵測條件仍為 `NEEDS_FORMALIZATION`。

### ENGINEERING_PROPOSAL

預設僅把 `CHoCH` 保存為 `source_term`，canonical event 使用 `MSS`。若產品要分開，必須新增參考依據與人工決策。
