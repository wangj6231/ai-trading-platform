# Entry Model

## MSS + Displacement + FVG Retest Entry Model

### REFERENCE_DEFINED

- **Definition:** supplied entry model 的順序性描述為：尋找朝預期交易方向的 break in structure 或 MSS，且伴隨 displacement；MSS 後的 displacement leg 中應存在 FVG；兩個 bullish example 的標題流程為 `SSL + MSS + FVG Retest + Entry + Target 1:3RR`。[HIGH_PROBABILITY_ENTRY_MODEL, pp. 1-4]
- **Bullish condition:** 圖例先穿越/觸及標為 SSL 的低點區域，接著 bullish MSS 與上行 displacement 形成 FVG，之後價格 retest FVG/下方區域並上行。[HIGH_PROBABILITY_ENTRY_MODEL, pp. 1-4]
- **Bearish condition:** 文字說明允許 “direction of intended trade”，但沒有 supplied bearish entry example，也沒有 BSL + bearish MSS 的明示 checklist。[HIGH_PROBABILITY_ENTRY_MODEL, pp. 1-2]
- **Required OHLC information:** SSL/reference low、market structure、MSS break、displacement leg、FVG bounds、retest candles、候選 entry 價格/區域、後續 stop/target；多數精確 bounds 未定。
- **Required market context:** 預期交易方向、liquidity event、MSS/break、displacement、FVG。ICT liquidity-based bias 另提出 monthly + weekly + daily 同向，再等待 4-hour 及以下 retracement 到 discount/premium。[ICT_BLOCK_TYPES, p. 3]
- **Confirmation requirements:** MSS、displacement 與 FVG 均未形式化；retest 是 touch、wick entry、body close 或 deeper fill 未說明。沒有規定訊號 candle 必須 closed。
- **Invalidation:** 未提供。圖上的 risk box 不能可靠證明 stop price 公式。
- **Edge cases:** 無 liquidity sweep 但有 MSS、MSS leg 無 FVG、多個 FVG、retest 先後穿越多個 zone、同 candle 形成並 retest、沒有 retest、bullish/bearish context 衝突。
- **Potential ambiguity:** 順序是否嚴格、事件間最大時間、SSL 的 formation/takeout、entry 是點或區域、選哪個 FVG、`LQL` 含義、1:3RR 是否 hard requirement。

狀態：流程輪廓為 `REFERENCE_DEFINED`；完整 entry rule 為 `NEEDS_FORMALIZATION`。

### ENGINEERING_PROPOSAL

```text
EntrySetupCandidate
  model_id = MSS_DISPLACEMENT_FVG_RETEST
  direction
  liquidity_ref
  structure_shift_ref
  displacement_ref
  fvg_ref
  retest_ref
  entry_zone               # unresolved
  stop_candidate_ref?      # supplied by Risk Model only
  target_candidate_ref?    # supplied by Risk Model only
  sequence_timestamps
  rejection_reasons[]
```

建議用有限狀態流程保存事件順序，但不在此指定 transition 條件。任何缺少已核准 component 的 setup 都只能標為 `UNFORMALIZED`，不能輸出交易訊號。

## Order Block Retest Entry

### REFERENCE_DEFINED

- **Definition:** valid OB 後價格可能先離開，再 retrace 並 retest；當價格回到 bullish/bearish OB candle 的 open 時，文件稱可提供 buying/selling opportunity。[ICT_BLOCK_TYPES, p. 2]
- **Bullish condition:** bullish OB validation、向上 displacement、回到 bullish OB candle open；圖例將 buy level 畫在 block 內。[ICT_BLOCK_TYPES, p. 2]
- **Bearish condition:** bearish OB validation、向下 displacement、回到 bearish OB candle open；圖例將 sell level 畫在 block 內。[ICT_BLOCK_TYPES, p. 2]
- **Required OHLC information:** OB candle open/high/low/close、validation、displacement、retrace/retest。
- **Required market context:** valid OB、strong reaction/displacement、可能的 liquidity target。
- **Confirmation requirements:** “returns to the open” 的 touch/through/close 與允許容差未定。
- **Invalidation:** 未提供；OB mean threshold 是 ideal quality statement，不可直接當 entry invalidation。
- **Edge cases:** gap 越過 open、多次 retest、open 位於 spread 無法成交、回測前 block 已被深度穿越。
- **Potential ambiguity:** entry 是精確 open、zone、limit 或 close confirmation；本平台不執行訂單。

狀態：`NEEDS_FORMALIZATION`。

### ENGINEERING_PROPOSAL

以 `EntrySetupCandidate(model_id=ORDER_BLOCK_RETEST, entry_reference=OB_OPEN)` 表示概念，不生成可交易價格，直到容差、zone 與 invalidation 被核准。
