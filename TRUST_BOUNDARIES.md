# ARCH-01 — Trust Boundaries

每一項列出現有 input/output、owner、validation、time、mutability、tests。
`tests` 表示找到的保護檔，不表示 ARCH-01 重跑通過。未接線能力明列。
檔名除 frontend 外，以下 `tests/` 相對 `backend/`。

## B01 — Browser selection → Next API

- Input / output：symbol/timeframe、optional JSON → `/api/market/candles`、`/api/analysis`、`/api/signals` request。
- Owner：browser 只擁有選擇；不擁有價格、策略結果或 provenance。
- Validation：Next JSON syntax check；型別/enum 最終由 backend request schema 處理。
- Time：每次 selection/retry 新 AbortController；不同 endpoint 沒共享 cutoff token。
- Mutability：UI state 可更新；切換先 loading、cleanup abort；舊回覆不得覆蓋新 selection。
- Tests：`frontend/tests/trading-dashboard-race.test.tsx`、`backend-proxy.test.ts`。缺同 selection 跨 endpoint cutoff 一致性測試（ARCH-F01）。

## B02 — Next proxy → FastAPI transport

- Input / output：固定 backend path + JSON/query → upstream status/body/content-type 或 safe 503/504。
- Owner：server `BACKEND_API_URL`、route handler path；client 不能指定任意 upstream host。
- Validation：proxy 不作 trading schema 認證；POST syntax pass-through、timeout/abort/no-store。
- Time：default 10s transport timeout；不等於 deterministic cutoff，也不保證 server CPU 被取消。
- Mutability：無 signal cache；只傳送此次 response。研究 token 未轉送。
- Tests：`frontend/tests/backend-proxy.test.ts`。prefix 可設定與固定 path 不一致未覆蓋（ARCH-F03）。

## B03 — FastAPI request → evaluation service

- Input / output：`ProductionAnalysisRequest(symbol,timeframe,cutoff?)` → `ServerStrategyEvaluation` 或 AppError。
- Owner：server bindings/config；沒有 caller-supplied production candles、AI verdict、levels 或 weights。
- Validation：Pydantic extra-forbid；provider existence、binding、history sufficiency；輸出 symbol/timeframe/decision chain 檢查。
- Time：cutoff 預設最後可用閉合 source bar；freshness 由 server retrieved_at 與 expected close 判定。
- Mutability：request frozen；service bindings 在 startup 建立；reference engine 不持有 hot market state。
- Tests：`tests/integration/test_deterministic_api.py`、`test_api.py`、`tests/unit/test_signal_schema.py`。

## B04 — Authorized research cutoff → provider-window selection

- Input / output：offset-aware cutoff + `X-Research-Cutoff-Token` → 同次 provider candles 的較早 prefix/provenance。
- Owner：Settings enable/token + evaluation service；不是 browser 自行宣稱 research。
- Validation：`compare_digest`；cutoff 不晚於 retrieval，且精確等於可用 close；不足或窗口外失敗。
- Time：`bar.open_time + duration <= cutoff`；非任意起迄日期的歷史查詢。
- Mutability：建立新的 provenance，沒有覆寫 raw provider history。
- Tests：`tests/integration/test_deterministic_api.py` research authorization/cutoff cases；proxy research passthrough **未實作**。

## B05 — Public vendor → syntax-decoded rows

- Input / output：Binance REST JSON → `ParsedProviderCandle[]`；此輸出仍不可信。
- Owner：provider adapter 只负责 parsing；closed endTime 由 adapter clock 計算。
- Validation：interval/limit/symbol、JSON/row syntax；timeout/transport/5xx bounded retry；429 明確錯誤。
- Time：timestamp 是 candle open，vendor close timestamp 須符合 interval；不得靠刪掉 malformed row 造連續資料。
- Mutability：frozen parsed dataclass；immutable 不等於 market truth。
- Tests：`tests/unit/test_binance_provider.py`、`test_market_data_normalization.py`。

## B06 — Parsed rows → trusted Candle/provenance

- Input / output：provider rows + declared schedule + server clock → `ValidatedMarketData`。
- Owner：`app/market_data/service.py:MarketDataService`；`app/services/market_data.py` 是 factory/import，不是第二個 validator。
- Validation：typed Decimal/UTC、alignment、unique ascending、gap、no unclosed/future、OHLCV；重新建 Candle，產生 provenance。
- Time：UTC open/close/retrieved/expected cutoff 各自有含義；calendar coverage 不足 fail closed。
- Mutability：Candle/response 為 typed output；不修補缺 bar、不 fabricate XAUUSD；provider availability 非 hash 保證。
- Tests：`test_market_data_trust_boundary.py`、`test_market_session_calendar.py`、`test_candle.py`、`test_utc_datetime_contract.py`。

## B07 — Validated source → live StrategyEvaluationContext

- Input / output：canonical source candles/provenance → UTC context。
- Owner：`DeterministicStrategyEvaluationService`；canonical source 選自 StrategyConfig。
- Validation：provider/binding/min-history/staleness + context closed/ascending validator；client OHLC 不進入此邊界。
- Time：context.as_of 為 source 最後 close；每個 higher bar 都須已閉合。
- Mutability：context frozen，但 nested dict 不是一般用途不可變資料庫；內部 caller 不應 mutate 或 model_construct 繞過。
- Tests：`test_deterministic_api.py`、`test_strategy_engine_orchestration.py`；無實測並行 request/CPU deadline 契約（ARCH-F04）。

## B08 — Context → feature engines

- Input / output：cutoff prefix + canonical pipeline config → indicators/structure/SMC/ICT typed snapshots。
- Owner：共用 `Concrete.evaluate` 與其 feature seams；provider、AI、frontend 不擁有 predicate。
- Validation：source gap/staleness/unsupported session gates、各 engine input checks；按確認時間開放 evidence。
- Time：pivot open ≠ confirmed_at；liquidity snapshot/history、FVG/OB lifecycle 保留歷史可知性。
- Mutability：reference 呼叫生成結果；hot internals mutable、immutable projections 避免 repaint；容器權威限 owner。
- Tests：`test_indicators.py`、`test_market_structure.py`、`test_structure_breaks.py`、`test_liquidity.py`、`test_fvg.py`、`test_order_blocks.py`、`test_displacement.py`、`test_high_probability_entry.py`。

## B09 — Features → MTF/score/risk/candidate

- Input / output：exactly-one READY-now setup + evidence → LONG/SHORT candidate 或 NO_TRADE。
- Owner：coordinator、MTF/score/risk engines；Entry/one TP/one SL 不由 execution/AI 改寫。
- Validation：MTF veto、signed score、risk rejection、typed geometry/RR；missing stages 可是 nullable，不能当 pass。
- Time：current setup confirmation 必須等於 as_of；僅 cutoff-visible target evidence。
- Mutability：candidate frozen，snapshot 另受嚴格 V2 freeze；NO_TRADE 不帶 actionable candidate。
- Tests：`test_multi_timeframe.py`、`test_signal_score.py`、`test_risk_engine.py`、`test_risk_target_contract.py`、`test_strategy_engine_orchestration.py`。

## B10 — Reference seam → incremental/hot-owned state

- Input / output：同 context/typed upstream、owned state → 與 reference 相同完整 evaluation。
- Owner：单一 replay engine instance；`_active_symbol`/state dictionaries/owned adapters 不是外部 API。
- Validation：existing prefix/reset/config signatures；內部 immutable-history reuse 不等於所有 input 均可略驗。
- Time：append/backfill/rewind 依 owner reset/rebuild；cached future versions 不應跨 rewind 可見。
- Mutability：hot indices mutable；diagnostic state_hash 包含 retained fields，非 StrategyIdentity；P7-B link cache 目前待完整驗證。
- Tests：`test_optimized_equivalence.py`、`test_p3_incremental_equivalence.py`、`test_p5_hot_state_equivalence.py`、`test_p6_ict_delta.py`、`test_hot_*.py`、`test_displacement_link_projection.py`。並行共用保證 UNVERIFIED。

## B11 — Research OHLC → canonical historical dataset

- Input / output：`HistoricalOHLCInput` + required timeframes → derived series、effective dataset identity。
- Owner：research caller 負責資料來源授權/封存；runner 負責 canonical validation；不是 public production OHLC input。
- Validation：unique series、ascending/continuous、UTC aligned complete buckets；supplied required HTF 比較 timestamp + 全 OHLCV。
- Time：只閉合 bucket；effective source 截至最後可評估 close；不把不完整尾端當已使用 evidence。
- Mutability：完整 archive 在 runner owner，傳 engine 的只有 closed prefixes；不允許 vendor HTF 取代 canonical truth。
- Tests：`test_backtest_canonical_data.py`、`test_backtest_reproducibility.py`、`test_incremental_resampling.py`。

## B12 — Backtest runner → engine / result handoff

- Input / output：ordered `(as_of,symbol)` contexts → candidates/invalidations → `_RuntimeSignal`。
- Owner：runner 驗證 ID/content/time/identity；engine 決策；wrapper 不選 engine class。
- Validation：config/identity match、cutoff、唯一 candidate、不得以同 ID rewrite；invalidation 須已知 candidate 且此時首次確認。
- Time：reference filter 或 optimized bisect 都以 close<=as_of；不存在授權 future candle pointer。
- Mutability：runner runtimes mutable；original candidate/evidence 不改寫。
- Tests：`test_backtest_runner.py`、`test_backtest_lookahead.py`、`test_p3_incremental_equivalence.py`。Concrete invalidation 產出未接線（ARCH-F07）。

## B13 — Candidate/lifecycle → execution → metrics

- Input / output：immutable plan + visible OHLC/prior state/canonical costs → lifecycle、entry/exit evidence、actual financial metrics。
- Owner：`engines/signal/lifecycle.py`、`backtesting/execution.py`、`metrics/financial.py`；非 strategy/DB labels。
- Validation：entry 可執行性、stop/target gap precedence、same-bar AMBIGUOUS、typed execution consistency、Decimal classification。
- Time：open-known gap 可用 candle open timestamp；intrabar ordering 未知不得猜；無 future inspection。
- Mutability：runtime 演進；terminal evidence 不重解；metrics read-only，legacy planned R 不混 net R。
- Tests：`test_signal_lifecycle.py`、`test_entry_execution_policy.py`、`test_execution_policy.py`、`test_financial_metrics.py`、`test_backtest_lookahead.py`。

## B14 — Deterministic analysis → Snapshot V2

- Input / output：context/evaluation/config/score evidence → strict `AnalysisSnapshot` V2。
- Owner：server `build_analysis_snapshot`；generic metadata 不得攜帶 hidden decision/time evidence。
- Validation：canonical identity、symbol/timeframe、每個 evidence 的 cutoff/links、schema limits；create repository 另 reparse。
- Time：captured_at/data_cutoff 是決策知識時點，後來 AI/成交/terminal 另存。
- Mutability：V2 frozen typed history；V1 read-only legacy；不重算舊 reason、不改舊 hash。
- Tests：`test_snapshot_integrity_v2.py`、`test_strategy_identity.py`、`test_signal_persistence.py`、PG snapshot tests。

## B15 — Internal deterministic context → OpenAI validation

- Input / output：typed structured context → typed final-validation result/evidence V1；目前 public routes 未呼叫。
- Owner：server-configured model/service；AI 僅 confirm/reject/reduce confidence/explain，不能改 direction/levels。
- Validation：Structured Outputs、bounded schema、exact candidate echo、min confidence/failure policy；技術錯誤與 rejection 分開。
- Time：request_started_at/completed_at/validated_at 是 AI 事件時間；input hash 保存當次 context，不倒灌 deterministic snapshot。
- Mutability：typed evidence frozen，persisted 後不可改；legacy 無 evidence 不補認證。
- Tests：`test_openai_validation.py`、`test_signal_persistence.py`、PG AI provenance tests、frontend `api-safety.test.ts`/`signal-panel.test.tsx`。

## B16 — Internal create/update → repository/UoW

- Input / output：`SignalPersistenceCreate` 或 lifecycle+execution → committed `SignalPersistenceRead`。
- Owner：PersistenceAuthority 綁 canonical config；Repository validate/flush；PersistenceService transaction commit/rollback/close。
- Validation：reparse V2、AI、execution、create schema；server identity/hash；same ID/levels、canonical idempotent replay。
- Time：created_at 源於 snapshot；AI/activation/close 分開；terminal UTC/cost evidence 必須與 event 相符。
- Mutability：new create immutable intent；entry/terminal 分階段封存；read/list 不 mutation、不 commit。
- Tests：`test_signal_persistence.py`、`test_database_transactions.py`、`test_database.py`、`test_postgresql_persistence.py`。

## B17 — Repository/SQL/ORM → PostgreSQL

- Input / output：transactional SQL → constrained `signals` JSONB/NUMERIC/TIMESTAMPTZ rows。
- Owner：DB locks/constraints/triggers + server repository；DB superuser/DDL owner 是另一個管理信任域。
- Validation：SELECT FOR UPDATE、ORM guards、migration checks/triggers；SQLite 不能代替 PG locking/JSONB 行為。
- Time：UTC-aware app type，PostgreSQL instant semantics；session timezone 不改 historical instant。
- Mutability：terminal/intent/snapshot/AI/entry history immutability；only canonical no-op replay；migration head 為 source 0006。
- Tests：real PG `test_postgresql_persistence.py` 包含 raw SQL/Core/ORM、concurrency、rollback、hash、migration roundtrip；本次未重新執行。

## B18 — Canonical config/source/data/run → identities

- Input / output：StrategyConfig/source closure/canonical OHLCV/run spec → StrategyIdentity、CanonicalDatasetIdentity、BacktestRunIdentity。
- Owner：server/library identity builders；caller filename、AI content、raw provider label 不取代 canonical identity。
- Validation：strict schema、canonical Decimal/UTC/ordering、source manifest closure/no missing dependencies、strategy binding。
- Time：config 不存 timestamps；run spec 明確窗口；dataset 只含 effective used bars；export wall-clock 不是決策證據。
- Mutability：identity values frozen；config/source/data 改變就要對應新 hash；Git dirty/SHA 是 provenance，state_hash 是 diagnostic。
- Tests：`test_algorithm_identity.py`、`test_strategy_identity.py`、`test_backtest_reproducibility.py`、`test_snapshot_integrity_v2.py`。

## B19 — Backend DTO → chart/signal ViewModel

- Input / output：untrusted HTTP JSON → Zod-validated display DTO → chart primitives/panel。
- Owner：backend 擁有 evidence，frontend 只投影；不產生金融權威。
- Validation：enum、finite numbers、symbol/timeframe、trade geometry、AI mode、FVG/OB lifecycle chronology/status；顯示不用不安全 assertion 假裝通過。
- Time：pivot 與 confirmation 分開；zones 起於 created/validated、終於可信 terminal；terminal 不因新 candles 延長。
- Mutability：VM/renderer 隨新 response 重建；數字僅 display。選擇 race 有保護，但三個回覆 provenance 在 VM 中未聯結。
- Tests：frontend `api-safety.test.ts`、`chart-lifecycle.test.ts`、`price-chart-geometry.test.tsx`、`signal-panel.test.tsx`、`trading-dashboard-race.test.tsx`、browser `terminal-layout.spec.ts`。

## 邊界例外總結

B10/B11/B15/B16 是 trusted internal/research 呼叫面，不是現有公開 JSON API。
typed/frozen 不是 authentication；B17 的管理權限可超出 row guards。B01/B19 的 UI
一致性不能替代 B06/B08 的資料與策略驗證。所有缺口／未驗證假設保持未修正，見
[SYSTEM_ARCHITECTURE.md](SYSTEM_ARCHITECTURE.md)。
