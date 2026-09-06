# Ambiguities and Required Decisions

## 使用方式

下表的 **Reference definition** 欄為 `REFERENCE_DEFINED`；其餘欄是尚未解決的規格工作。**Suggested options** 全部是 `ENGINEERING_PROPOSAL` 候選，並未被選定、核准或實作。

後續 runtime 決策不會回寫或擴充 reference 定義。就本次 M-08 範圍，
Target/Risk 的現行工程決策已窄化為：exactly one nearest opposing-liquidity
TP，`min_rr` 只驗證、不生成 target，沒有 fixed-RR fallback 或
`TARGET_FIRST`。因此下表 Target/Risk 列中的其他 suggested options 是歷史
候選，不是可選產品能力；現行契約以 `docs/risk-target-contract.md` 為準。

| Concept | Reference definition | Missing information | Engineering decision required | Suggested options |
| --- | --- | --- | --- | --- |
| Swing High | Liquidity 圖把明顯局部高點標為 swing-high liquidity。[SMC_CONCEPT, p. 9] | Pivot window、high/close、prominence、確認延遲、nested scale | 定義可重現的 swing-high predicate 與 `confirmed_at` | 固定左右 bars；波動調整 window；多尺度 pivots。必須選一種並建立 fixtures |
| Swing Low | Liquidity 圖把明顯局部低點標為 swing-low liquidity。[SMC_CONCEPT, p. 9] | 與 Swing High 對稱的全部細節 | 定義 swing-low predicate | 與 Swing High 使用相同家族的對稱選項 |
| BOS | 價格突破先前 structure 的 high side 或 low side。[SMC_CONCEPT, p. 6] | Broken level 選擇、wick/close、距離、方向延續分類 | 決定 break basis、比較符號、level scope | Wick-through；candle close beyond；close beyond 加最小 buffer |
| MSS | 趨勢因先前價格結構被破壞而顯著改變。[SMC_CONCEPT, p. 5] | Prior trend、significant、破壞 level、是否需 sweep/displacement | 定義 trend state、shift trigger 與確認時間 | 結構序列轉換；反向 swing close break；反向 break 加 displacement |
| CHoCH | 與 MSS 相同概念、不同術語。[SMC_CONCEPT, p. 5] | 是否需要產品層獨立 subtype | 決定 alias 或獨立事件 | UI alias；保存 source alias；人工新增差異規格後再拆分 |
| MSB | ICT 圖用作 market structure break 標籤。[ICT_BLOCK_TYPES, pp. 4-5] | 與 BOS/MSS 的關係、方向與 predicate | 決定 canonical mapping | 保持獨立 unresolved term；對應 BOS；對應 generic structure break。未有證據前首選保持未合併 |
| Liquidity | 被比喻為 market fuel；圖示 highs/lows 與 trend-line pools。[SMC_CONCEPT, p. 9] | OHLC proxy、zone width、形成與消耗狀態 | 定義可觀測 liquidity-pool 模型 | 單一 swing level；等高低群組；trend-line touch 群組；各類分開建模 |
| Buy-side Liquidity | 位於 swing/equal/relative equal highs 及下降 trend line 一側。[SMC_CONCEPT, p. 9] | Equal tolerance、pool bounds、taken 條件 | 定義 high clustering 與消耗事件 | Tick tolerance；百分比 tolerance；波動調整 tolerance |
| Sell-side Liquidity | 位於 swing/equal/relative equal lows 及上升 trend line 一側。[SMC_CONCEPT, p. 9] | 與 BSL 對稱的全部細節；`LQL` 未定義 | 定義 low clustering；決定是否拒絕未知 LQL | 與 BSL 對稱；`LQL` 保持 unsupported，不建立 alias |
| Liquidity Sweep | CRT 說 high/low 被 swept 後指向 opposite wick，且 sweeping candle 必須 closed。[CRT_METHOD, pp. 2, 4] | Touch vs cross、wick/close、close-back-inside、buffer、同 candle 雙掃 | 定義 sweep interaction 與確認 | Wick cross；wick cross + close back inside；close cross；分成 sweep 與 breakout 兩種事件 |
| Inducement | 機構刻意設計、吸引散戶在不利價位進場的價格移動。[SMC_CONCEPT, p. 7] | 可觀測代理、level 選擇、方向、與 MSS 的差異 | 移除意圖宣稱並定義純價格 proxy，或不實作 | Internal swing before OB；liquidity level between BOS and OB；維持 documentation-only |
| Premium | Bearish bias 下預期向上修正進入 premium，再尋找 BSL 賣出。[ICT_BLOCK_TYPES, p. 3] | Dealing range、anchors、equilibrium、bounds | 定義 range source 與 premium formula | 已確認 swing range；session range；higher-timeframe range；不採用直到文件補充 |
| Discount | Bullish bias 下預期 retrace 進入 discount，再尋找 SSL 買入。[ICT_BLOCK_TYPES, p. 3] | 與 Premium 對稱 | 定義 range source 與 discount formula | 與 Premium 採同一 range 的對稱區域；或不採用 |
| FVG | Buyers/sellers imbalance 的 price range/empty square；圖示 bullish/bearish 三燭 gap。[SMC_CONCEPT, p. 3] | 正式三燭公式、最小寬度、第三燭封閉、bounds、fill/invalidation | 定義 formation 與 lifecycle | Strict wick non-overlap；加最小 tick；加 volatility filter；partial/full fill states |
| IFVG | 只有 Inversion FVG 名稱與圖例。[SMC_CONCEPT, pp. 2, 4] | 原 FVG、inversion trigger、方向、retest、失效全部缺失 | 必須補充 reference-backed state transition | Close-through original FVG；full traversal；retest after break；或保持不實作 |
| Order Block | 最後機構交易區；另有最低 down-close/最高 up-close candle、trade-through validation 與 body 50% mean threshold 提示。[SMC_CONCEPT, p. 8; ICT_BLOCK_TYPES, p. 2] | 搜尋 window、support/resistance、most range、body/wick、liquidity takeout、hard invalidation | 統一兩份來源並定義 candidate/validated/invalid states | Body-only bounds；wick bounds；雙 bounds；50% 作 quality score 或 hard rule；liquidity 作 prerequisite 或 metadata |
| Breaker Block | 舊 OB 在 swing/structure violation 後翻轉角色並於回測反應。[ICT_BLOCK_TYPES, p. 5] | Candle direction 文字與圖示關係、violation、retest、失效 | 核准 bullish/bearish state transition | OB invalidation + opposite close；swing violation + retest；逐 supplied example 建 golden fixtures 後決定 |
| Mitigation Block | Structure shift 後回到 reference point，受困部位減輕損失並可能延續新方向。[ICT_BLOCK_TYPES, p. 4] | Points 1/2/3、origin candle、retest、bullish mirror | 定義 reference sequence 與 block bounds | 三 pivot sequence；last candle zone；保持 qualitative until more examples |
| Rejection Block | Price high/low 的 long wicks，外側 liquidity 被 run 後反向；bearish return to range low 為 sell trigger。[ICT_BLOCK_TYPES, p. 6] | Wick ratio、candle count、range bounds、bullish trigger | 定義 wick cluster 與 trigger | 單 candle wick ratio；多 candle extreme cluster；body-to-wick zone |
| Reclaimed Order Block | 舊 OB 在 market-maker curve 另一側被 reclaim，伴隨 minor displacement 與新 HH/LL。[ICT_BLOCK_TYPES, pp. 7-8] | Curve 模型、minor displacement、reclaim trigger | 先形式化 curve 或排除概念 | 狀態機模型；以 key-level tap + continuation；documentation-only |
| Propulsion Block | 曾 trade into OB、接手支撐/阻力的 candle；圖示 50% mean threshold 品質提示。[ICT_BLOCK_TYPES, pp. 9-10] | 互動 candle、take-over、reaction、50% 是 hard/soft | 定義 origin interaction 與 lifecycle | Wick enters OB；body enters OB；close within OB；50% 作 score 或 invalidation |
| Vacuum Block | Volatility event/session open 造成、range 中無 trades 的 gap。[ICT_BLOCK_TYPES, pp. 11-12] | Event source、無成交證據、fill、corrective/exhaustion | 決定資料粒度與 session/event 模型 | Tick/trade data verification；bar gap proxy；僅對有 session 的 instrument；不支援 24/7 crypto session gap |
| Displacement | 朝預期方向的 impulsive structure move；可離開 OB 並留下 FVG。[HIGH_PROBABILITY_ENTRY_MODEL, pp. 1-2; ICT_BLOCK_TYPES, p. 2] | 單/多 candle、range/body threshold、波動正規化、回撤、FVG 必要性 | 定義 metrics 與 versioned thresholds | Body/range ratio；ATR normalized move；N-bar cumulative move；必須/不必伴隨 FVG |
| Entry model | `SSL + MSS + FVG Retest + Entry + Target 1:3RR` bullish examples；MSS 後 displacement leg 應有 FVG。[HIGH_PROBABILITY_ENTRY_MODEL, pp. 1-4] | 嚴格順序、最大間隔、FVG 選擇、retest、entry zone、bearish mirror | 定義 state machine 與每個 transition | Strict sequential events；bounded windows；first/nearest/largest FVG；touch/partial fill/close confirmation |
| OB retest entry | Price retrace 到 valid OB candle open 可形成 buying/selling opportunity。[ICT_BLOCK_TYPES, p. 2] | Open tolerance、zone、confirmation、多次 retest | 定義 entry reference 與 freshness | Exact open；tick buffer；body zone；first retest only；每次 retest 降級 |
| Invalidation | 沒有統一規則；數處只寫 ideal 50% behavior。[ICT_BLOCK_TYPES, pp. 2, 9-10] | Hard vs soft、wick/close、timeout、structure invalidation | 每個 model 定義獨立 invalidation | Price-level touch；candle close；opposite structure event；bar-count expiry |
| Stop Loss | Bullish OB low / bearish OB high 被稱為相對安全；bearish rejection stop 可略高於最高 wick。[ICT_BLOCK_TYPES, pp. 2, 6] | Buffer、bid/ask、trigger、gap、同 candle ordering | 定義 single-stop selection 與 execution-neutral backtest policy | Exact extreme；fixed ticks；percentage；volatility buffer；worst-case same-bar resolution |
| Target | Buy stops/sell stops 可作 first/full TP；rejection 尋找 opposing liquidity；CRT 指向 opposite wick。[ICT_BLOCK_TYPES, pp. 2, 6; CRT_METHOD, p. 2] | 多候選排序、唯一 TP、target freshness、RR 與 liquidity 衝突 | 定義 exactly-one target policy | Nearest opposing liquidity；CRT opposite wick；RR-derived target；先過風險限制再選單一候選 |
| Risk/Reward | 兩個 bullish entry examples 標為 Target 1:3RR。[HIGH_PROBABILITY_ENTRY_MODEL, pp. 3-4] | 公式、entry zone 基準、3.0 是否最低值、費用 | 決定 RR 計算與門檻 | Zone near/far/mid price；gross/net RR；3.0 作範例、minimum 或 target construction。未核准前不採用 |
| CRT | 每根 candle 是 range；一側被 sweep 後指向 opposite wick；Power of Three；sweeping candle 必須 closed；第三 candle open 上/下 entry 提示。[CRT_METHOD, pp. 2-6] | Range candle、sweep、close 位置、第三燭、entry bounds、SL、target、expiry、timeframe | 定義完整三燭 state machine | Fixed 3 consecutive bars；session-aligned bars；wick sweep + close-back；entry zone bounded by open and range edge；保持 target/SL unresolved |

## 形式化完成條件

每一列只有在下列項目全部完成後，才能從 `NEEDS_FORMALIZATION` 轉為可實作：

1. 選定且記錄一個 engineering decision，說明為何不採其他選項。
2. 寫出只依賴當時可見、已封閉 OHLC 的精確 predicate。
3. 定義所有 `>`、`>=`、邊界、tick rounding、時間窗口與 timeframe 對齊。
4. 定義 `event_at`、`confirmed_at`、`invalidated_at`。
5. 提供至少一個 positive、negative、edge、anti-look-ahead fixture。
6. 若規則使用右側確認，明確延後可用時間。
7. 若來源互相衝突，先取得人工核准，不以一般 SMC/ICT 知識裁決。
8. 更新規則版本與來源頁面 mapping。

在完成上述條件前，任何 suggested option 都不得進入 production code、回測或 UI 訊號。
