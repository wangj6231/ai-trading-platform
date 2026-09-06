# Displacement

## Displacement

### REFERENCE_DEFINED

- **Definition:** entry model 要求朝預期交易方向出現帶 displacement 的 break in structure 或 MSS。[HIGH_PROBABILITY_ENTRY_MODEL, p. 1] ICT block guide 把 displacement 描述為價格 impulsively move away from bullish/bearish OB，並稱它是市場中 displacement 與 institutional sponsorship 的證據。[ICT_BLOCK_TYPES, p. 2]
- **Bullish condition:** bullish intended trade 中，結構 break/MSS 後有上行 displacement；該 displacement leg 應有 FVG。[HIGH_PROBABILITY_ENTRY_MODEL, pp. 1-2]
- **Bearish condition:** bearish intended trade 中，對稱地需要向下 displacement；文件文字允許 intended trade direction，但 entry examples 都是 bullish，未提供 bearish candlestick example。[HIGH_PROBABILITY_ENTRY_MODEL, pp. 1-4]
- **Required OHLC information:** 至少需要一段連續 candle 的 OHLC、起點/終點、range/body、與 prior structure/OB 的關係；參考資料未指定 window。
- **Required market context:** break in structure 或 MSS；ICT OB context 中從已驗證 OB impulsively move away；FVG 可出現在 displacement 後。[HIGH_PROBABILITY_ENTRY_MODEL, pp. 1-2; ICT_BLOCK_TYPES, p. 2]
- **Confirmation requirements:** “impulsively”、“strong reaction” 與 “displacement leg” 沒有數值標準；未說明是否單根或多根 candle、是否必須 close beyond structure。
- **Invalidation:** 未提供。
- **Edge cases:** gap-only move、單根長 wick、連續小 candles、極低/高波動環境、同 leg 多個 FVG、資料缺口。
- **Potential ambiguity:** 最小 body/range、ATR 或百分比正規化、相對成交量、允許回撤、leg 終點、FVG 是否必要。

狀態：`NEEDS_FORMALIZATION`。

### ENGINEERING_PROPOSAL

```text
DisplacementLeg
  direction
  start_bar_ref
  end_bar_ref
  structure_event_ref?
  origin_order_block_ref?
  price_change
  body_sum
  range_sum
  max_adverse_excursion
  fvg_refs[]
  qualification_metrics   # stored only; thresholds unresolved
```

建議先保存可重算 metrics，再由版本化規則判斷 qualification；本文件不選擇 ATR、百分比或 candle-count 閾值。
