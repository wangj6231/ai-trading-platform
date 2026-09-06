# Order Blocks

## Order Block

### REFERENCE_DEFINED

- **Definition:** 一份文件稱 OB 為大型市場參與者執行大額訂單、造成顯著趨勢變化時使用的最後價格區域。[SMC_CONCEPT, p. 8] 另一份文件把 bullish OB 描述為靠近 support 的最低 down-close candle，且其 open-close range 最大；bearish OB 則為靠近 resistance 的最高 up-close candle，且其 open-close range 最大。[ICT_BLOCK_TYPES, p. 2]
- **Bullish condition:** 候選 candle 是靠近 support 的最低 down-close candle；後續較新 candle trade through 該最低 down-close candle 的 high，構成文件所述 validation。[ICT_BLOCK_TYPES, p. 2] SMC 圖另把 liquidity taken out 的例子標為 valid OB。[SMC_CONCEPT, p. 8]
- **Bearish condition:** 候選 candle 是靠近 resistance 的最高 up-close candle；後續較新 candle trade through 該最高 up-close candle 的 low。[ICT_BLOCK_TYPES, p. 2]
- **Required OHLC information:** candle open、close、high、low；候選 candle 的 open-close range；較新 validation candle；support/resistance context；liquidity interaction。
- **Required market context:** 重要 support/resistance、預期較大訂單進場及向相反方向的 strong reaction；但這些 context 沒有量化。[ICT_BLOCK_TYPES, p. 2]
- **Confirmation requirements:** 文件明確提供 trade-through validation；並稱理想 bullish OB 不應跌破 candle body 50% mean threshold，bearish 不應漲過該 threshold。Mean threshold 由 open/close 量測，建議只用 bodies；wicks 可用但被稱為 discretionary。[ICT_BLOCK_TYPES, p. 2]
- **Invalidation:** 沒有正式失效規則。“Ideally” 不穿越 50% 不能直接等同 hard invalidation；SMC 圖的 liquidity not taken out 被標為 invalid example，但未提供完整時序。[SMC_CONCEPT, p. 8; ICT_BLOCK_TYPES, p. 2]
- **Edge cases:** 同區間多個 down/up-close candles、相同 body range、doji、缺乏 support/resistance、validation 與 liquidity takeout 同根、wick 與 body 給出不同 bounds、已多次 retest。
- **Potential ambiguity:** “lowest/highest candle”、“most range”、“near support/resistance”、“traded through”、“strong reaction”、“liquidity taken out” 均缺精確算法。兩份文件的 broad institutional-area 定義與單根 candle 選取也未建立優先順序。

狀態：`NEEDS_FORMALIZATION`。

### ENGINEERING_PROPOSAL

```text
OrderBlockZone
  direction
  origin_candle_ref
  body_bounds
  wick_bounds
  mean_threshold
  support_resistance_ref?
  liquidity_interaction_ref?
  validation_bar_ref?
  state                    # CANDIDATE | VALIDATED | MITIGATED | INVALIDATED
```

建議同時保存 body/wick bounds，避免過早選擇；state transition 全部尚待核准。

## Breaker Block

### REFERENCE_DEFINED

- **Definition:** 圖例顯示舊 order block 在結構與 swing level 被違反後翻轉角色，價格返回該 zone、受到反應並延續新方向。[ICT_BLOCK_TYPES, p. 5]
- **Bullish condition:** 圖例：價格先形成 short-term low，該 low 被 violated，sell stops 被 run、賣方受困；價格穿越 old high 後回測，原 bearish order block 轉為 bullish breaker 並作 support。[ICT_BLOCK_TYPES, p. 5]
- **Bearish condition:** 頁面文字寫作：bearish breaker 是最近 swing low 中、old high 被 violated 前的 down-close candle；底部範例顯示 high violated、structure shift 後形成 bearish breaker。[ICT_BLOCK_TYPES, p. 5]
- **Required OHLC information:** swing highs/lows、候選 up/down-close candle、old high/low、violation bar、return/retest bars。
- **Required market context:** 原 order block、market structure break、流動性/stop run 與 higher-timeframe level 在圖中出現。
- **Confirmation requirements:** 圖示需要舊 swing 被 violated、價格返回舊 zone 並 respect；沒有 close/wick 或最小反應規則。
- **Invalidation:** 未提供 breaker 被穿越多少或以何種價格失效。
- **Edge cases:** 多個候選 candle、同一 zone 多次 flip、swing 被 wick-only violation、未回測即延續、bullish/bearish 定義文字與圖示標籤不易對齊。
- **Potential ambiguity:** 頁面底部兩句原文的 candle direction、recent swing 與 violated old high/low 關係容易產生方向混淆；必須逐案例核准，不可用一般 ICT 知識修正。

狀態：`NEEDS_FORMALIZATION`。

### ENGINEERING_PROPOSAL

`BreakerBlock(origin_order_block_ref, violated_swing_ref, structure_break_ref, new_direction, retest_ref, state)`；不建議在未釐清 source 方向敘述前自動由 OB 轉換。

## Mitigation Block

### REFERENCE_DEFINED

- **Definition:** bearish 圖例描述：price 先推入 resistance，之後 break structure 並 shift lower；回到 reference point “1” 時，從 1 到 2 swing 的 long positions 有機會減輕 2 到 3 下跌造成的損失，之後可能形成更低 swing。[ICT_BLOCK_TYPES, p. 4]
- **Bullish condition:** 底部圖示 higher low、structure shift 與 bullish mitigation block，並標示 underwater shorts closing positions；沒有完整文字流程。[ICT_BLOCK_TYPES, p. 4]
- **Bearish condition:** 在 bearish long-term draw on liquidity 下，short-term rally 回到先前 bearish level，被視為另一個 selling opportunity。[ICT_BLOCK_TYPES, p. 4]
- **Required OHLC information:** reference points 1/2/3、structure break/shift、retracement、last down candle 或 zone bounds；bullish 需要對稱結構但來源未正式定義。
- **Required market context:** higher-timeframe support/resistance、longer-term directional belief/draw on liquidity。
- **Confirmation requirements:** 價格 break down、return to point 1；沒有回測 candle close 或 reaction threshold。
- **Invalidation:** 未提供。
- **Edge cases:** reference point 1 的 candle 選擇、回測深度、沒有形成新 lower low、bullish 鏡像是否完全對稱。
- **Potential ambiguity:** 圖中文字稱 focus on “last down candle” 作 bearish sell level，與其他 OB candle direction 用語未建立一致規則；1/2/3 不是算法化 pivots。

狀態：`NEEDS_FORMALIZATION`。

### ENGINEERING_PROPOSAL

`MitigationBlock(direction, reference_1, swing_2, displacement_or_break_3, origin_candle_ref, htf_context_ref, retest_ref)`；所有 reference 的選取及 confirmation 未決。

## Rejection Block

此概念未在使用者指定清單中，但 supplied reference 對它有明確內容，因此在此保存，不代表排入實作。

### REFERENCE_DEFINED

- **Definition:** bearish rejection block 在 price high 處由 candle highs 的 long wicks 形成；bullish rejection block 在 price low 處由 candle lows 的 long wicks 形成。[ICT_BLOCK_TYPES, p. 6]
- **Bullish condition:** 價格穿到 candle bodies 下方、run out sell-side liquidity，之後向上反應。[ICT_BLOCK_TYPES, p. 6]
- **Bearish condition:** 價格穿到 candle bodies 上方、run out buy-side liquidity，之後下跌。[ICT_BLOCK_TYPES, p. 6]
- **Required OHLC information:** 多根 candle bodies、wick highs/lows、後續 return/reaction。
- **Required market context:** high/low formation 與外側 liquidity。
- **Confirmation requirements:** bearish 圖說價格回到 rejection-block range 的 low 時為 sell trigger；沒有 bullish 對稱 trigger 的文字。[ICT_BLOCK_TYPES, p. 6]
- **Invalidation:** 未提供。Bearish example 的 stop 可稍高於 highest wick，但 stop placement 不等同定義失效。[ICT_BLOCK_TYPES, p. 6]
- **Edge cases:** 只有一根 long wick、wick 長度門檻、body 高低不一致、多個同高 wick。
- **Potential ambiguity:** block range 的上下界、long wick 閾值、需要幾根 candle、run liquidity 判定。

狀態：`NEEDS_FORMALIZATION`。

### ENGINEERING_PROPOSAL

`RejectionBlock(direction, candle_refs[], body_boundary, extreme_boundary, liquidity_ref, trigger_ref)`；wick ratio 與最小 candle count 未決。

## Reclaimed Order Block

### REFERENCE_DEFINED

- **Definition:** reclaimed bullish OB 是先前用來買入並造成小幅上行 displacement 的 candle；在 buy side of curve 應形成新 higher highs，sell side 的 old OB 會成為 reclaimed longs。Bearish 定義為先前賣出並造成小幅下行 displacement 的 candle；sell side 應形成新 lower lows，buy side 的 old OB 會成為 reclaimed shorts。[ICT_BLOCK_TYPES, pp. 7-8]
- **Bullish condition:** market maker buy model 從 drop into support 轉為 bounce off support；old blocks 在另一側被 reclaimed，價格形成 higher highs。[ICT_BLOCK_TYPES, p. 7]
- **Bearish condition:** market maker sell model從 rally into resistance 轉為 retracement；old bearish blocks 在回落過程被 reclaimed，價格形成 lower lows。[ICT_BLOCK_TYPES, p. 8]
- **Required OHLC information:** old OB candles、minor displacement、support/resistance turning point、new HH/LL、return/tap sequence。
- **Required market context:** buy/sell side of curve、market maker buy/sell model。
- **Confirmation requirements:** 未提供 “reclaimed” 的 wick/close/tap 公式。
- **Invalidation:** 未提供。
- **Edge cases:** curve 的 turning point 未確認、minor displacement 尺度、多個 old blocks、HH/LL 未正式定義。
- **Potential ambiguity:** side of curve、key level tap、old block 到 reclaimed block 的狀態轉移都無算法。

狀態：`NEEDS_FORMALIZATION`。

### ENGINEERING_PROPOSAL

`ReclaimedOrderBlock(origin_order_block_ref, curve_side, displacement_ref, reclaim_bar_ref, direction)`；curve model 未形式化前不得產生。

## Propulsion Block

### REFERENCE_DEFINED

- **Definition:** bullish propulsion block 是曾向下交易進 bullish OB、之後接手成為較高價格支撐的 candle；bearish propulsion block 是曾向上交易進 up candle/bearish OB、之後成為較低價格阻力的 candle。[ICT_BLOCK_TYPES, pp. 9-10]
- **Bullish condition:** bullish context、多個 bullish OB；candle 回到 bullish OB 後形成 propulsion block。理想上價格不跌破 propulsion candle 的 50% mean threshold，回測時應有 strong reaction。[ICT_BLOCK_TYPES, p. 9]
- **Bearish condition:** underlying context bearish；價格 pullback 進 bearish OB，candle 成為 resistance。價格回到 propulsion block low 被標為 sell trigger，圖例顯示 close under 50% mean threshold。[ICT_BLOCK_TYPES, p. 10]
- **Required OHLC information:** origin OB、interaction candle OHLC、body midpoint、後續 retrace/reaction。
- **Required market context:** 與 propulsion 方向一致的 underlying context。
- **Confirmation requirements:** 需要先 trade into OB 並接手 support/resistance；strong reaction 未量化。
- **Invalidation:** “ideally” 不穿過 mean threshold，不足以定義 hard invalidation。
- **Edge cases:** wick 進入但 body 未進入、多個 OB 重疊、50% 碰觸、形成後沒有 retest。
- **Potential ambiguity:** 何謂 takes over role、哪個 candle 成為 block、body/wick bounds 與 mean-threshold close/wick 判定。

狀態：`NEEDS_FORMALIZATION`。

### ENGINEERING_PROPOSAL

`PropulsionBlock(origin_order_block_ref, propulsion_candle_ref, direction, mean_threshold, retest_ref, reaction_ref)`；state transitions 未決。

## Vacuum Block

### REFERENCE_DEFINED

- **Definition:** volatility event 造成、由與事件直接相關的 liquidity vacuum 形成的 price-action gap；例子包括 NFP 或 futures session open。Gap 中沒有 trades，可用 candle/range 的 high 與 low 表示。[ICT_BLOCK_TYPES, pp. 11-12]
- **Bullish condition:** 市場在較高價格開盤形成 bullish gap；bullish OB/down candle 可能阻止 gap 完全填補並提供 buying opportunity。完整回補後可有另一 buying opportunity，但上行後不希望再次跌回 fully filled block。[ICT_BLOCK_TYPES, p. 11]
- **Bearish condition:** 市場在較低價格開盤形成 bearish gap；bearish OB/up candle 可能阻止完全填補並提供 selling opportunity。完整回補後可有另一 selling opportunity，但下行後不希望再次漲回 fully filled block。[ICT_BLOCK_TYPES, p. 12]
- **Required OHLC information:** 相鄰交易時段/事件前後的 gap bounds、後續 fill、可能的 OB candle。
- **Required market context:** volatility event 或 session open；corrective move in trend 被標為 more probable，potential exhaustion gap 被標為 less probable。[ICT_BLOCK_TYPES, pp. 11-12]
- **Confirmation requirements:** 需要可證明 gap range 中無 trades；單純 OHLC 可能不足以證明細粒度成交缺口。
- **Invalidation:** fully filled 後再次進入 block 的描述偏向品質提示，未定義正式失效。
- **Edge cases:** 市場資料缺漏誤認為 gap、24/7 crypto 無 session open、corporate/rollover adjustment、跨供應商不同 prints。
- **Potential ambiguity:** event window、無成交證據、100% filled 邊界、corrective vs exhaustion 分類。

狀態：`NEEDS_FORMALIZATION`。

### ENGINEERING_PROPOSAL

`VacuumBlock(direction, pre_event_bar_ref, post_event_bar_ref, gap_bounds, event_ref, fill_fraction, origin_order_block_ref?)`；必須先決定行情粒度與缺漏資料政策。
