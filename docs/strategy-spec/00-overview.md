# Strategy Specification Overview

## 目的與狀態

本目錄把專案內四份 SMC/ICT 參考 PDF 轉成可審查的策略規格草案。它不是交易演算法，也沒有授權任何規則進入 Signal Engine。

目前整體狀態：`NEEDS_FORMALIZATION`。

只有直接出現在參考文件文字或清楚標註圖例中的內容，才會列為 `REFERENCE_DEFINED`。所有資料結構、欄位、列舉值與候選判定方式均列為 `ENGINEERING_PROPOSAL`，在人工核准前不得當成策略規則。

## 參考資料

下列來源檔名只保留作為引用識別；PDF 原檔因第三方授權限制，不包含在公開 GitHub 倉庫中。

| Source ID | 檔案 | 頁數 | 本規格使用範圍 |
| --- | --- | ---: | --- |
| `SMC_CONCEPT` | `docs/references/SMC_CONCEPT.pdf` | 10 | SMC、FVG、IFVG、MSS/CHoCH、BOS、Inducement、Order Block、Liquidity、setup 圖例 |
| `ICT_BLOCK_TYPES` | `docs/references/ICT_BLOCK_TYPES.pdf` | 12 | Order Block、liquidity-based bias、mitigation/breaker/rejection/reclaimed/propulsion/vacuum blocks、entry/risk 提示 |
| `HIGH_PROBABILITY_ENTRY_MODEL` | `docs/references/HIGH_PROBABILITY_ENTRY_MODEL.pdf` | 4 | MSS + displacement、displacement leg 中的 FVG、SSL + MSS + FVG retest、1:3RR 範例 |
| `CRT_METHOD` | `docs/references/CRT_METHOD.pdf` | 6 | Candle Range Theory、Power of Three、封閉 K 線要求與第三根 K 線 entry 提示 |

頁碼引用格式為 `[SOURCE_ID, p. N]`。圖例只證明圖中明確標註的關係，不自動證明 wick/close、容差、lookback 或時序等未寫出的規則。

## 證據分類

### REFERENCE_DEFINED

- 直接由參考資料文字敘述。
- 或由有方向、名稱及價位標籤的圖例明確表達。
- 仍可同時是 `NEEDS_FORMALIZATION`：概念存在不代表已足以編碼。

### ENGINEERING_PROPOSAL

- 為了將來可保存、回測與稽核而提出的資料表示。
- 不補造交易條件，不選定任何尚有爭議的參數。
- 欄位可先存在，但偵測器必須保持未實作，直到相關決策被核准。

### NEEDS_FORMALIZATION

- 參考資料缺少可重現的布林條件、數值閾值、確認時點、失效條件或邊界處理。
- 不得以一般網路上的 SMC/ICT 定義或工程人員的既有知識填補。

## 共同規格欄位

每一個被分析的概念均使用下列欄位：

1. Definition
2. Bullish condition
3. Bearish condition
4. Required OHLC information
5. Required market context
6. Confirmation requirements
7. Invalidation
8. Edge cases
9. Potential ambiguity
10. Proposed deterministic representation

## 規格覆蓋

| 文件 | 主要概念 |
| --- | --- |
| `01-terminology.md` | 名詞、別名、來源與規格狀態 |
| `02-market-structure.md` | Swing High、Swing Low、BOS、MSS、CHoCH |
| `03-liquidity.md` | Liquidity、Buy-side Liquidity、Sell-side Liquidity、Liquidity Sweep、Inducement、Premium、Discount |
| `04-fvg-ifvg.md` | FVG、IFVG |
| `05-order-blocks.md` | Order Block、Breaker Block、Mitigation Block，並記錄其餘 supplied block 類型 |
| `06-displacement.md` | Displacement |
| `07-entry-model.md` | Entry models |
| `08-risk-model.md` | Invalidation、Stop Loss concepts、Target concepts |
| `09-crt.md` | CRT |
| `10-ambiguities.md` | 所有缺口與待核准選項 |

## 全域限制

- 所有確認型事件將來只能使用當時已封閉的 K 線。
- 若 swing/pivot 需要右側 K 線，事件可用時間必須晚於其確認 K 線收盤時間。
- 多週期分析不得在歷史時點使用當時尚未封閉的高週期 K 線。
- 參考資料中的插圖不是精確比例尺；不得從圖形像素反推閾值。
- `1:3RR` 只出現在兩個 entry example，不視為全域風險規則。[HIGH_PROBABILITY_ENTRY_MODEL, pp. 3-4]
- 本規格不包含真實或模擬交易訊號，不包含下單功能，也不實作任何 detector。

## ENGINEERING_PROPOSAL：共同事件外殼

以下僅是跨模組一致的候選資料外殼：

```text
StrategyObservation
  concept
  direction                 # BULLISH | BEARISH | NEUTRAL
  status                    # TENTATIVE | CONFIRMED | INVALIDATED
  instrument
  timeframe
  source_bar_ids[]
  event_at
  confirmed_at
  invalidated_at?
  price_bounds?
  context_refs[]
  reference_evidence[]      # SOURCE_ID + page
  rule_version
  config_version
  reason_codes[]
```

此表示不決定任何偵測公式。各概念的 `confirmed_at`、`price_bounds`、失效事件及 reason codes 仍為 `NEEDS_FORMALIZATION`。
