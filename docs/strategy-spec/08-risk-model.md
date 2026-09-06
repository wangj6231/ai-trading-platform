# Risk Model Concepts

本文件只整理參考資料中的風險概念，不設定平台風險參數，也不計算實際訊號。

## Current engineering resolution

下列 `REFERENCE_DEFINED`／`NEEDS_FORMALIZATION` 記錄保持原始參考資料邊界，
不因後續工程決策而改寫。現行 runtime 已另行核准一個窄化的工程合約：
setup 提供一個 structural invalidation、Risk Engine 選擇一個最近的 opposing
liquidity target、`min_rr` 僅作拒絕門檻，且輸出 exactly one TP。沒有
`FIXED_RR` fallback、TP ladder 或 `TARGET_FIRST`。完整可執行契約見
`docs/risk-target-contract.md` 與 `docs/algorithm-spec/risk-algorithm.md`。

## Invalidation

### REFERENCE_DEFINED

- **Definition:** supplied references 沒有統一、明確命名的 “invalidation” 規則。
- **Bullish condition:** bullish OB 被描述為理想上不跌破 candle body 50% mean threshold；bullish propulsion block 亦理想上不跌破其 50% mean threshold。[ICT_BLOCK_TYPES, pp. 2, 9]
- **Bearish condition:** bearish OB 被描述為理想上不漲過 body mean threshold；bearish propulsion 圖示價格進入 block 後 close under mean threshold。[ICT_BLOCK_TYPES, pp. 2, 10]
- **Required OHLC information:** 相關 zone bounds、mean threshold、後續 high/low/close。
- **Required market context:** 失效應引用特定 setup/zone；參考資料沒有全域規則。
- **Confirmation requirements:** “ideally” 與 “should not” 不是明確 hard failure；未說明 intrabar 或 candle-close confirmation。
- **Invalidation:** 本概念本身的失效不適用；需要為每一 setup 定義 invalidation event。
- **Edge cases:** price 恰好等於 threshold、wick 穿越後收回、gap 穿越、資料修訂、多週期 zone 重疊。
- **Potential ambiguity:** quality downgrade、entry cancellation、stop trigger 與 structure invalidation 是否為同一事件。

狀態：`NEEDS_FORMALIZATION`。

### ENGINEERING_PROPOSAL

```text
InvalidationRuleRef
  setup_ref
  invalidation_type       # PRICE_LEVEL | CANDLE_CLOSE | STRUCTURE_EVENT | TIMEOUT
  level_ref?
  comparison?
  evaluation_timeframe
  triggered_at?
```

列舉值只是候選設計；每一 model 必須獨立核准。

## Stop Loss Concepts

### REFERENCE_DEFINED

- **Definition:** OB guide 稱 bullish OB low 或 bearish OB high 是 “relatively safe stop loss placement”。[ICT_BLOCK_TYPES, p. 2]
- **Bullish condition:** bullish OB-based trade 的 stop 概念位於 bullish OB low；bullish rejection block 的對稱 stop 沒有文字說明。[ICT_BLOCK_TYPES, p. 2]
- **Bearish condition:** bearish OB-based trade 的 stop 概念位於 bearish OB high；bearish rejection block 可把 stop 放在 highest wick 稍上方。[ICT_BLOCK_TYPES, pp. 2, 6]
- **Required OHLC information:** origin block high/low、rejection wick extreme、entry bounds、instrument tick size；文件未討論 spread/slippage。
- **Required market context:** stop source 必須與使用的 setup 相符。
- **Confirmation requirements:** 未提供何時 stop level 固定、是否使用 wick、body 或 buffer。
- **Invalidation:** stop 被觸發的 `>=`/`>`、bid/ask、intrabar ordering 未定。
- **Edge cases:** 同 candle 同時觸及 stop/target、gap-through stop、entry zone 有寬度、stop distance 為零、價格精度。
- **Potential ambiguity:** “slightly above” 沒有 buffer；“relatively safe” 不是統計證明；參考資料沒有 CRT 或 FVG 專屬 stop。

狀態：stop 位置概念為 `REFERENCE_DEFINED`；可執行規則為 `NEEDS_FORMALIZATION`。

### ENGINEERING_PROPOSAL

`StopCandidate(level, source_concept, source_ref, buffer_policy_ref, fixed_at)`。Risk Engine 最終只能選一個 stop，但 selection/buffer/trigger policy 尚未決。

## Target Concepts

### REFERENCE_DEFINED

- **Definition:** OB guide 建議把上方 buy stops／下方 sell stops 作第一 TP 或完整 TP；rejection block 尋找 opposite-side resting liquidity；CRT 說一側 high/low 被 sweep 後，價格被吸引至 opposite wick。[ICT_BLOCK_TYPES, pp. 2, 6; CRT_METHOD, p. 2]
- **Bullish condition:** bullish OB 以上方 buy stops 為 target；bullish CRT 以 CRT high/opposite wick 為方向性目標；entry examples 標示 Target 1:3RR。[ICT_BLOCK_TYPES, p. 2; CRT_METHOD, p. 6; HIGH_PROBABILITY_ENTRY_MODEL, pp. 3-4]
- **Bearish condition:** bearish OB 以下方 sell stops 為 target；bearish CRT 以 CRT low/opposite wick 為目標。[ICT_BLOCK_TYPES, p. 2; CRT_METHOD, p. 5]
- **Required OHLC information:** entry、stop、candidate liquidity/high/low target、價格精度。
- **Required market context:** target 可由 liquidity objective、CRT opposite wick 或 RR example 產生；來源沒有給出衝突時的選擇規則。
- **Confirmation requirements:** target 形成時點與是否需未觸及 liquidity 未定。
- **Invalidation:** 未提供 target 過期、被提前觸及或 setup 失效後的處理。
- **Edge cases:** 多個 liquidity targets、target 在 entry 錯誤一側、1:3RR level 超過/早於 liquidity、同 candle hit stop and target。
- **Potential ambiguity:** 1:3RR 是兩個範例標籤，不能推為全域 minimum；“first TP or full TP” 與產品要求 exactly one TP 需要明確 selection decision。

狀態：候選來源為 `REFERENCE_DEFINED`；唯一 TP 選擇為 `NEEDS_FORMALIZATION`。

### ENGINEERING_PROPOSAL

`TargetCandidate(level, source_concept, source_ref, rr_from_entry_stop)`。Risk Engine 可在核准政策後從候選中選 exactly one target；目前不得排序或選取。

## Risk/Reward

### REFERENCE_DEFINED

- **Definition:** 兩個 entry example 顯示 “Target 1:3RR”，未提供公式。[HIGH_PROBABILITY_ENTRY_MODEL, pp. 3-4]
- **Bullish condition:** example 為 bullish setup，圖示 target distance 大於 stop distance。
- **Bearish condition:** 未提供 bearish example。
- **Required OHLC information:** entry price 定義、single stop、single target。
- **Required market context:** 只出現在該 entry model examples。
- **Confirmation requirements:** 未說明以 entry zone 哪一點計算。
- **Invalidation:** 未提供低於 1:3 是否拒絕。
- **Edge cases:** zone entry、fees/spread、zero risk、rounding。
- **Potential ambiguity:** 1:3 是示意、target rule 或 minimum threshold。

狀態：`NEEDS_FORMALIZATION`。

### ENGINEERING_PROPOSAL

未來可保存 `risk_distance`、`reward_distance`、`rr_ratio` 與計算價格來源；不在本階段設定 3.0 threshold。
