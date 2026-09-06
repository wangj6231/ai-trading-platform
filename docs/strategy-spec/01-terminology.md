# Terminology

## 使用原則

本文件只建立參考資料中出現的名詞對照。Canonical ID 是 `ENGINEERING_PROPOSAL`，不是策略判定。

| Canonical ID | 顯示名稱 | 參考資料所述或所示 | 狀態 |
| --- | --- | --- | --- |
| `SWING_HIGH` | Swing High | Liquidity 圖將單一 swing high、equal highs、relative equal highs 與下降 trend line 標為 buy-side liquidity 類型。[SMC_CONCEPT, p. 9] | `NEEDS_FORMALIZATION` |
| `SWING_LOW` | Swing Low | Liquidity 圖將單一 swing low、equal lows、relative equal lows 與上升 trend line 標為 sell-side liquidity 類型。[SMC_CONCEPT, p. 9] | `NEEDS_FORMALIZATION` |
| `BOS` | Break of Structure | 價格突破先前 market structure 的高側或低側。[SMC_CONCEPT, p. 6] | `NEEDS_FORMALIZATION` |
| `MSS` | Market Structure Shift | 趨勢方向因先前價格結構被破壞而發生顯著改變。[SMC_CONCEPT, p. 5] | `NEEDS_FORMALIZATION` |
| `CHOCH` | Change of Character | 參考資料明言與 MSS 是相同概念、不同術語。[SMC_CONCEPT, p. 5] | `REFERENCE_DEFINED` alias；判定仍待形式化 |
| `MSB` | Market Structure Break | ICT block 圖使用的標籤；未提供與 BOS/MSS 的正式關係。[ICT_BLOCK_TYPES, pp. 4-5] | `NEEDS_FORMALIZATION` |
| `FVG` | Fair Value Gap | 買賣雙方不平衡形成的價格區域；文件亦稱其為 empty square。[SMC_CONCEPT, p. 3] | `NEEDS_FORMALIZATION` |
| `IFVG` | Inversion FVG | 只提供名稱與一個 candlestick 圖例。[SMC_CONCEPT, pp. 2, 4] | `NEEDS_FORMALIZATION` |
| `OB` | Order Block | 機構大額訂單造成顯著趨勢變化的最後價格區域；另一文件提供 candle 選取與 validation 提示。[SMC_CONCEPT, p. 8; ICT_BLOCK_TYPES, p. 2] | `NEEDS_FORMALIZATION` |
| `IDM` | Inducement | 被描述為機構刻意設計、吸引散戶在不利價格持倉的價格移動。[SMC_CONCEPT, p. 7] | `NEEDS_FORMALIZATION` |
| `LIQUIDITY` | Liquidity | 被比喻為 market fuel；圖示將高點側分為 buy-side、低點側分為 sell-side。[SMC_CONCEPT, p. 9] | `NEEDS_FORMALIZATION` |
| `BSL` | Buy-side Liquidity | 圖示位於 swing/equal/relative equal highs 與下降 trend line 一側。[SMC_CONCEPT, p. 9] | `NEEDS_FORMALIZATION` |
| `SSL` | Sell-side Liquidity | 圖示位於 swing/equal/relative equal lows 與上升 trend line 一側。[SMC_CONCEPT, p. 9] | `NEEDS_FORMALIZATION` |
| `DISPLACEMENT` | Displacement | 朝預期交易方向的 impulsive move；可伴隨 FVG，並被描述為 institutional sponsorship 的證據。[HIGH_PROBABILITY_ENTRY_MODEL, pp. 1-2; ICT_BLOCK_TYPES, p. 2] | `NEEDS_FORMALIZATION` |
| `PREMIUM` | Premium | bearish liquidity-based bias 中預期 intraday retracement 進入的區域。[ICT_BLOCK_TYPES, p. 3] | `NEEDS_FORMALIZATION` |
| `DISCOUNT` | Discount | bullish liquidity-based bias 中預期 intraday retracement 進入的區域。[ICT_BLOCK_TYPES, p. 3] | `NEEDS_FORMALIZATION` |
| `CRT` | Candle Range Theory | 每一根 K 線是一個 range；一側被 sweep 後，價格被描述為吸引至 opposite wick。[CRT_METHOD, p. 2] | `NEEDS_FORMALIZATION` |

## 用語衝突與保留

- `SMC_CONCEPT` 的 FVG 頁面正文寫作 “Fair Value Index (FVG)”，標題與其餘文件則為 “Fair Value Gap”。本規格保留 `FVG = Fair Value Gap` 作顯示名稱，但把正文命名差異列為來源品質問題。[SMC_CONCEPT, p. 3]
- `MSS` 與 `CHoCH` 可先視為同義顯示名稱；是否需要不同 subtype 尚無參考依據。[SMC_CONCEPT, p. 5]
- `BOS`、`MSS`、`MSB` 不能在未核准前互換。
- `support`、`resistance`、`POI`、`market maker buy/sell model`、`buy/sell side of curve` 在圖中出現，但沒有完整定義。
- `LQL` 出現在 entry example 1，沒有文字展開；不可自行解讀。[HIGH_PROBABILITY_ENTRY_MODEL, p. 3]

## ENGINEERING_PROPOSAL

建議所有儲存層使用 canonical ID，UI 顯示參考資料用語，另保存 `source_term`。對 alias 或未定義標籤使用下列結構：

```text
TermRef
  canonical_id
  source_term
  source_id
  source_page
  formalization_status
```

不得藉 canonicalization 合併尚未證明等價的概念，例如 `BOS` 與 `MSB`。
