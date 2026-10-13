# EXECUTION-ARCH-01 — Execution Gap Analysis

> Status superseded 2026-10-08: 以下為 Stage0 歷史設計／inventory，不代表目前 implementation。
> PAPER_DECIMAL_V1 已 OWNER-FROZEN，numeric gate 已 COMPLETE；內部 core/adapter/projection
> 與 additive ledger 已實作。當前唯一政策權威為 [PAPER_DIRECTIONAL_V1_POLICY.md](PAPER_DIRECTIONAL_V1_POLICY.md)，
> 實際接口／限制／本輪驗證見 [PAPER_ACCOUNT_V1_REPORT.md](PAPER_ACCOUNT_V1_REPORT.md)。
> 下文的 pending/BLOCKED/尚未實作 敘述均屬批准前狀態；User/Auth/public writes、LIVE、Journal 仍未實作。

2026-10-08。EXECUTION-ARCH-01B 更新：永久 synthetic directional PAPER profile 已由 owner 凍結；Final owner D1–D7已批准，僅versioned numeric arithmetic context/residual未指定。沒有改 audit finding 狀態或啟用任何執行功能。

## 1. 分類

- EXISTING：目前 source 可確認存在，不代表部署／外部 provider 已驗證。
- SAFE_ADDITIVE：不改 strategy／legacy execution 語義的獨立設計提案；未實作。
- OWNER_DECISION_REQUIRED：財務、execution 或產品語義不能由工程默認。
- SEMANTIC_CONFLICT：直接重用／解讀目前模型會混淆不同 authority 或 units。
- BLOCKED：缺少前置決策／可信能力，不能進入 implementation。

## 2. Concrete findings／smallest seam

| ID | Evidence／問題 | Classification | 最小處理邊界（不實作） |
|---|---|---|---|
| EA-01 | `backend/app/schemas/execution.py:180` 無 quantity/currency/account；simulated PnL 是 per-unit 價格差 | SEMANTIC_CONFLICT | 新 execution-domain fills 與 monetary accounting profile，保留 existing research schema |
| EA-02 | Spot provider 只有 market authority；owner 已選 `PAPER_DIRECTIONAL_V1` synthetic directional net-position LONG／SHORT | SAFE_ADDITIVE（owner 已批准） | 不再問 cash Spot；仍不暗示 broker 借幣／margin 能力 |
| EA-03 | 只有 `backend/app/models/signal.py:97` signals；無 User/TradingAccount/journal auth | public write API BLOCKED | owner 允許 internal-only core/service/repository；不發明 browser ownership，也不因缺 auth 重開整體 core 決策 |
| EA-04 | persistence service initialized；evaluate 無 create/apply caller，history GET 未實作 | EXISTING（局部 capability） | durable plan → order → fill 接線另建；不宣稱 existing product 閉環 |
| EA-05 | `backend/app/database/signal_repository.py:135,224` signal 鎖／terminal 同內容 replay | EXISTING；當 broker dedup 用則 SEMANTIC_CONFLICT | command idempotency 與 fill composite uniqueness 獨立；不能靠 snapshot hash 去重 |
| EA-06 | `backend/app/database/db.py:27` service commit owner、repo 只 flush | EXISTING | 後續 short transaction/inbox/outbox 模式可 SAFE_ADDITIVE；network outside DB lock |
| EA-07 | `backend/app/models/signal.py:403` ORM guards 及 migrations 0004/0006 triggers | EXISTING | 保留原 guards；新 event/fill guards 需獨立；現況不保證 DELETE 不可用 |
| EA-08 | database/types.py:58精確保存finiteDecimal；finalowner凍結USDT/noFX/serverprofilevalidation，但nonterminatingdivision無fixedcontext | OWNER_DECISION_REQUIRED（唯一numericclarification） | WMA302/3實測precision/mode影響PnL；不能以storageexactness冒充arithmeticpolicy |
| EA-09 | `backend/app/metrics/financial.py:91,116` simulation observations；win/loss 來自 net PnL 正負；drawdown 是 net R curve | EXISTING | 可重用 classifier，不宣稱 account-equity analytics；新 monetary read model 需要 units/currency gate |
| EA-10 | SignalRecord `pnl_r` 是 planned legacy；`BacktestTrade.pnl_r` 是 actual simulation net R | SEMANTIC_CONFLICT | Journal 不得用同名欄位無標籤混合；保留 source/evidence kind/metric domain |
| EA-11 | `MarketDataProvider` 與 `MarketDataService` 有 provider pattern，但 first symbol match 不適合 execution | SAFE_ADDITIVE | explicit account-bound execution registry，不與 market registry 耦合 |
| EA-12 | `backend/app/services/evaluation_execution.py` CPU execution 命名易混淆 | EXISTING | 文件明確限定語義；此次不 rename production module |
| EA-13 | 沒有 Order/Fill/inbox/outbox/reconciliation/PAPER connector | SAFE_ADDITIVE（目標），目前 BLOCKED | canonical event/gateway adapter seam 先批准；不將 ack 當 Trade |
| EA-14 | Owner已批准WMA/partialclose/over-closeREJECT、fee0.001USDT/noFX、scopedmonotonicsequence | SAFE_ADDITIVE（owner-frozen，未實作） | unsupportedcorrection/bust/profile仍quarantine；不擴成新的owner模型題 |
| EA-15 | universal「新 broker 只加 adapter」可能遇到不同 instrument/settlement | SEMANTIC_CONFLICT | promise 限已支持 canonical financial profile；unsupported capability explicit reject |

## 3. GRILL scenarios

| Scenario | 不可接受的捷徑 | Required boundary |
|---|---|---|
| LONG order accepted，尚無 fill | 建 Trade/Journal actual entry | 只 Order ack；confirmed fill 才建 Trade |
| SHORT recommendation，尚無 authorized OrderIntent 或 fill | 自動建立 synthetic position | frozen directional profile 不等於 execution authorization；confirmed fill 才建 Trade |
| fill delivered 兩次 received_at 不同 | 兩次 quantity/fees/PnL | economic composite key + hash，delivery receipts 另列 |
| timeout 後 provider 實際成交 | 新 ID 重送／當拒單 | UNKNOWN submission + 原 ID reconciliation |
| cancel ack 後 partial fill 晚到 | 丟棄 fill／改原 history | ingest/reconcile，保持 filled/received 兩個時間 |
| 手續費用另一 asset，沒有 FX | zero fee 或當 USDT 扣 | unknown valuation，不給完整 net monetary result |
| 同 canonical fills 由不同 adapter 提供 | Journal 有 broker 分支 | shared admission/reducer，same approved profile 同結果 |
| LIVE unavailable | fallback PAPER 仍顯示 LIVE 成功 | technical failure、no fallback |
| browser 改 execution price/localStorage | authoritative actual trade | server admission/account auth，不信 client execution truth |
| 已 commit 但 response 斷線 | retry 重算 economic state | durable dedup，ack after commit |

## 4. Owner decision tree／stop frontier

Owner 已凍結 `PAPER_DIRECTIONAL_V1 / SYNTHETIC_DIRECTIONAL / ONE_WAY_NET_POSITION`；原 cash Spot／synthetic 選擇已解決，不重開。PAPER 是永久 provider，不是 demo 或 LIVE fallback；V1 不含 margin／borrowing／funding／liquidation／hedge mode。

Final owner已批准全部七組financialchoices；舊16項未決清單已由明確D1–D7替代。新的唯一frontier是accountversionedDecimalcontext/full-close residual，實測302/3不能finiteexact。詳見 [PAPER_DIRECTIONAL_V1_POLICY.md](PAPER_DIRECTIONAL_V1_POLICY.md) §9；不是重開財務模型或publicauth。

## 5. Verification matrix（未執行新 tests）

| Existing protection | Existing test file evidence | 未來 execution-domain 最小 tests |
|---|---|---|
| gap/ambiguity/cost arithmetic | `backend/tests/unit/test_execution_policy.py` | PAPER policy 若重用需 translation/equivalence；不得改 expected 策略結果 |
| lifecycle separation | `backend/tests/unit/test_signal_lifecycle.py` | order cancel ≠ signal cancel、ack ≠ fill、partial/late fills |
| immutable execution history | `backend/tests/unit/test_signal_persistence.py` | new event/fill Core/ORM/raw SQL immutability、dedup conflict |
| service-owned transactions | `backend/tests/unit/test_database_transactions.py` | ingress atomic rollback、commit failure、ack loss retry |
| true PG locking/NUMERIC/constraints | `backend/tests/integration/test_postgresql_persistence.py` | account concurrency、composite fill uniqueness、currency/quantity exact roundtrip |
| canonical financial metrics | `backend/tests/unit/test_financial_metrics.py` | actual monetary profile golden cases、legacy/research/PAPER/LIVE separation |
| deterministic identity/cutoff | `backend/tests/unit/test_strategy_identity.py` 及 backtest regression files | execution facts 不改 StrategyIdentity/Snapshot；journal as-of received_at |

Existing tests 只是 source inventory，沒有重新執行，不能引用舊 passed counts 為此次成果。新 adapter/reducer 不在 repo，沒有新 contract tests 可宣稱 passed。

## 6. Delivery／non-goals

本次作者只新增五份 execution architecture 文件，沒有修改 production code、config、tests、DB/migrations、frontend、strategy、risk、execution policy 或 historical hash。現有 dirty worktree 屬其他工作，未 reset／覆寫。

本次對 `backend/app`、`backend/tests`、`backend/migrations`、`config`、`frontend/src`、`frontend/tests`、`scripts` 的 285 個非快取檔案作前後 SHA-256 比對：backend/config/scripts 未變；documentation 作業期間有其他寫入者改動 7 個 frontend source/test 檔案。本次沒有碰那些檔案，不宣稱整個 shared worktree 靜止或已重新通過 quality gates。`git diff --check` 沒有 whitespace error；這不等於執行測試。

EXECUTION-ARCH-01 原始交付的 hash 檢查屬上一輪歷史證據，不代表本輪重新驗證。EXECUTION-ARCH-01B 本輪狀態見 [PAPER_ACCOUNT_V1_REPORT.md](PAPER_ACCOUNT_V1_REPORT.md)。

目前結論：provider/event/account 與 frozen directional profile 已明確；**implementation 仍為 BLOCKED**，只需numericprecision/rounding/residualrule補充，D1–D7高階金融決策不再未決。沒有開始 PAPER-ACCOUNT-V1 implementation、broker execution、optimization 或新 audit。
