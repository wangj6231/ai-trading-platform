# Liquidity

## Liquidity

### REFERENCE_DEFINED

- **Definition:** 參考資料把 liquidity 比喻為 market fuel，並以 swing/equal/relative equal highs/lows 與 trend-line liquidity 示意其位置。[SMC_CONCEPT, p. 9]
- **Bullish condition:** bullish liquidity-based bias 預期 intraday retrace 到 discount、尋找 sell-side liquidity 後買入。[ICT_BLOCK_TYPES, p. 3]
- **Bearish condition:** bearish bias 預期 retrace 到 premium、尋找 buy-side liquidity 後賣出。[ICT_BLOCK_TYPES, p. 3]
- **Required OHLC information:** 高低點序列；若要識別 equal/relative equal 或 trend line，還需多個已確認 pivots。
- **Required market context:** ICT 圖要求 monthly + weekly + daily 同向 bias，然後在 4-hour 及以下 intraday chart 等待 retracement。[ICT_BLOCK_TYPES, p. 3]
- **Confirmation requirements:** 未提供通用 confirmation。Order Block 圖把 “liquidity taken out” 畫為 valid、未 taken out 畫為 invalid。[SMC_CONCEPT, p. 8]
- **Invalidation:** 未提供。
- **Edge cases:** 重疊 liquidity pools、已觸及但未穿越、equal highs/lows 的容差、資料缺口。
- **Potential ambiguity:** Liquidity 頁面的正文與 Order Block 正文非常相似，且沒有可觀測 order-book 定義；只能把標示價位視為概念區域。

狀態：`NEEDS_FORMALIZATION`。

### ENGINEERING_PROPOSAL

```text
LiquidityPool
  side                     # BUY_SIDE | SELL_SIDE
  formation_type           # SWING | EQUAL | RELATIVE_EQUAL | TREND_LINE
  source_swing_refs[]
  price_bounds
  formed_at
  taken_at?
```

所有 formation_type 的判定、價位寬度與 `taken_at` 條件尚未核准。

## Buy-side Liquidity

### REFERENCE_DEFINED

- **Definition:** 圖示位於 swing high、equal highs、relative equal highs 與下降 trend line 的高點側。[SMC_CONCEPT, p. 9]
- **Bullish condition:** 未提供把 BSL 當成 bullish entry 的條件；Order Block 頁面把上方 buy stops 作為 bullish trade 的第一或完整 target。[ICT_BLOCK_TYPES, p. 2]
- **Bearish condition:** bearish liquidity-based bias 指示在 premium 尋找 buy-side liquidity 後賣出。[ICT_BLOCK_TYPES, p. 3]
- **Required OHLC information:** 已確認高點與其價位關係。
- **Required market context:** 可作上方 target，或作 bearish setup 的 liquidity objective；兩者的優先順序未定。
- **Confirmation requirements:** 未提供 taken/swept 的精確條件。
- **Invalidation:** 未提供。
- **Edge cases:** 多個高點群、突破後延續而非反轉、spread/tick 造成的輕微穿越。
- **Potential ambiguity:** buy stops 是概念假設，OHLC 無法證明真實委託存在。

狀態：`NEEDS_FORMALIZATION`。

### ENGINEERING_PROPOSAL

使用 `LiquidityPool(side=BUY_SIDE)`，並將 “target” 與 “setup prerequisite” 分別保存為引用角色，避免單一 pool 被默認為方向訊號。

## Sell-side Liquidity

### REFERENCE_DEFINED

- **Definition:** 圖示位於 swing low、equal lows、relative equal lows 與上升 trend line 的低點側。[SMC_CONCEPT, p. 9]
- **Bullish condition:** bullish liquidity-based bias 指示在 discount 尋找 sell-side liquidity 後買入；entry examples 使用 `SSL + MSS + FVG Retest`。[ICT_BLOCK_TYPES, p. 3; HIGH_PROBABILITY_ENTRY_MODEL, pp. 3-4]
- **Bearish condition:** Order Block 頁面把下方 sell stops 作為 bearish trade 的第一或完整 target。[ICT_BLOCK_TYPES, p. 2]
- **Required OHLC information:** 已確認低點與其價位關係。
- **Required market context:** 可作下方 target，或 bullish setup prerequisite。
- **Confirmation requirements:** 未提供 taken/swept 的精確條件。
- **Invalidation:** 未提供。
- **Edge cases:** 與 BSL 對稱。
- **Potential ambiguity:** `SSL` 與 `LQL` 在 entry example 中同時出現，但 `LQL` 未定義。[HIGH_PROBABILITY_ENTRY_MODEL, p. 3]

狀態：`NEEDS_FORMALIZATION`。

### ENGINEERING_PROPOSAL

使用 `LiquidityPool(side=SELL_SIDE)`，另保存 `role=SETUP_PREREQUISITE|TARGET`。

## Liquidity Sweep

### REFERENCE_DEFINED

- **Definition:** 沒有通用文字定義。CRT 說明 high 或 low 被 swept 後，價格被吸引到 opposite wick；有效 CRT 要求 sweeping liquidity 的 candle 已封閉。[CRT_METHOD, pp. 2, 4]
- **Bullish condition:** CRT 圖示先掃 CRT low，再形成 bullish distribution；bullish rejection block 則在 candle bodies 下方運行 sell-side liquidity 後向上反應。[CRT_METHOD, p. 6; ICT_BLOCK_TYPES, p. 6]
- **Bearish condition:** CRT 圖示先掃 CRT high，再形成 bearish distribution；bearish rejection block 在 bodies 上方運行 buy-side liquidity 後下跌。[CRT_METHOD, p. 5; ICT_BLOCK_TYPES, p. 6]
- **Required OHLC information:** reference high/low、sweeping candle high/low/open/close 與其 closed 狀態。
- **Required market context:** 必須先有被 sweep 的 reference liquidity；CRT、rejection block、OB validation 對 reference 的要求不同。
- **Confirmation requirements:** CRT 只明確要求 sweeping candle closed，沒有明說必須收回 range 內。[CRT_METHOD, p. 4]
- **Invalidation:** 未提供。
- **Edge cases:** 僅觸及、wick 穿越後收外、close 穿越、同根雙向 sweep、gap 越過、連續多次 sweep。
- **Potential ambiguity:** sweep/taken out/run liquidity 是否等價，及判斷使用 `>` 還是 `>=`。

狀態：`NEEDS_FORMALIZATION`。

### ENGINEERING_PROPOSAL

`LiquidityInteraction(pool_ref, interaction_type, trigger_bar_id, extreme_price, close_price, confirmed_at)`；`interaction_type` 候選可包含 `TOUCH`、`WICK_THROUGH`、`CLOSE_THROUGH`，但何者構成 sweep 尚未決定。

## Inducement

### REFERENCE_DEFINED

- **Definition:** 機構刻意設計的策略性價格移動，用來吸引散戶在不利價格進場；文件警告不要把 IDM 與 MSS 混淆。[SMC_CONCEPT, p. 7]
- **Bullish condition:** 圖例顯示 bullish context 中，BOS 後存在一個標為 IDM 的內部低點，價格後續進入 OB 再向 target 上行；沒有文字化條件。[SMC_CONCEPT, p. 7]
- **Bearish condition:** 未提供對稱文字或圖例。
- **Required OHLC information:** 僅由圖例可知需要結構轉折與相關 OB/target；精確欄位未定。
- **Required market context:** 圖例含 BOS、OB 與 target。
- **Confirmation requirements:** 未提供。
- **Invalidation:** 未提供。
- **Edge cases:** IDM 與普通 pullback、liquidity pool、MSS 的區分。
- **Potential ambiguity:** “deliberately engineered” 無法從 OHLC 證明參與者意圖，必須轉成純價格代理規則才可回測。

狀態：`NEEDS_FORMALIZATION`。

### ENGINEERING_PROPOSAL

不得儲存或宣稱機構意圖。可保留 `InducementCandidate(structure_refs, candidate_level, observed_at)`，但 detector 在可觀測代理條件核准前不得實作。

## Premium

### REFERENCE_DEFINED

- **Definition:** bearish liquidity-based bias 中，預期 intraday chart 向上修正並進入的區域，之後尋找 buy-side liquidity 賣出。[ICT_BLOCK_TYPES, p. 3]
- **Bullish condition:** 未提供。
- **Bearish condition:** monthly、weekly、daily bearish 時，等待 4-hour 及以下開始向上修正，進入 premium 並尋找 BSL。[ICT_BLOCK_TYPES, p. 3]
- **Required OHLC information:** 參考資料未說明用哪個 dealing range 或如何由 OHLC 計算。
- **Required market context:** 高週期 bearish alignment。
- **Confirmation requirements:** 未提供。
- **Invalidation:** 未提供。
- **Edge cases:** range 更新、不同 timeframe range 衝突、價格超出 range。
- **Potential ambiguity:** 50% equilibrium、range anchors、inclusive bounds 全部未定；不能把 OB 的 50% mean threshold 自動套用到 premium。

狀態：`NEEDS_FORMALIZATION`。

### ENGINEERING_PROPOSAL

僅保留 `PriceArrayZone(kind=PREMIUM, range_ref, bounds)` schema；`range_ref` 與 bounds 算法未決。

## Discount

### REFERENCE_DEFINED

- **Definition:** bullish liquidity-based bias 中，預期 intraday chart retrace 進入的區域，之後尋找 sell-side liquidity 買入。[ICT_BLOCK_TYPES, p. 3]
- **Bullish condition:** monthly、weekly、daily bullish，等待 4-hour 及以下開始 retracing，進入 discount 並尋找 SSL。[ICT_BLOCK_TYPES, p. 3]
- **Bearish condition:** 未提供。
- **Required OHLC information:** 未定義 dealing range 或計算公式。
- **Required market context:** 高週期 bullish alignment。
- **Confirmation requirements:** 未提供。
- **Invalidation:** 未提供。
- **Edge cases:** 與 Premium 對稱。
- **Potential ambiguity:** 不能自行假設為 range 的下半部。

狀態：`NEEDS_FORMALIZATION`。

### ENGINEERING_PROPOSAL

僅保留 `PriceArrayZone(kind=DISCOUNT, range_ref, bounds)` schema；偵測器保持未實作。
