# Roadmap

原則：每一階段都必須保持可執行、可測試、可回滾；未完成項目不可在文件或 UI 宣稱已實作。SMC／ICT 在規則形式化與範例核准前不得進入訊號引擎。

## Phase 0 - 架構與基礎設施（本階段）

- [x] 建立前端、後端、測試與策略模組目錄骨架
- [x] 建立系統架構、模組邊界、訊號契約與 anti-look-ahead 原則
- [x] 收錄並標準化命名四份本地策略參考 PDF
- [x] 建立 `.env.example` 與 PostgreSQL `docker-compose.yml`
- [x] 明確標示 SMC／ICT 為未實作，將主觀或不完整條件列為 `NEEDS_FORMALIZATION`

驗收：`docker compose config` 通過，PostgreSQL 服務定義具 healthcheck；本階段不產生任何交易訊號。

## Phase 1 - 可執行的應用骨架與資料模型

- 建立 FastAPI health/readiness API、Pydantic settings、SQLAlchemy 2.x 與 migrations
- 建立 Next.js、TypeScript、Tailwind CSS 與 Lightweight Charts 最小頁面
- 定義 instrument、timeframe、OHLC candle、feature snapshot、structure event、candidate signal、final signal、validation audit 資料模型
- 建立後端 pytest 與前端單元測試基線，加入 Dockerfile 與完整 compose services
- 以 migration 建立 PostgreSQL schema；不得加入假 production signals

驗收：前後端、資料庫可由 compose 啟動，health checks 通過，自動測試通過。

## Phase 2 - 真實行情與決定性指標

- 選定並記錄 XAUUSD、BTCUSDT、ETHUSDT 的行情供應商、授權、symbol mapping、rate limits 與缺漏處理
- 擷取真實 OHLC，統一 UTC、decimal precision、closed-candle 狀態及 provenance
- 支援 `1m`、`3m`、`5m`、`15m`、`1h`，驗證 resampling 不讀取未來資料
- 實作可設定 MACD 與基礎支撐／壓力；所有閾值集中管理
- 建立固定 fixtures、邊界測試、缺口／重複 K 線測試與數值基準測試

驗收：相同輸入與設定必須產生相同輸出；測試資料明確標註且不冒充正式行情。

## Phase 3 - Market Structure 與 SMC/ICT 規格形式化

- 將四份 PDF 的每一條候選規則轉成可審查的 specification table
- 為 swing、BOS、MSS/CHoCH、displacement、liquidity、FVG/IFVG、各類 block、CRT 與 entry model 定義精確條件
- 每條規格記錄來源頁面、輸入、閾值、確認延遲、失效條件、reason code、正例與反例
- 對文件互相衝突或仍主觀的條件維持 `NEEDS_FORMALIZATION`，不得自行決定
- 建立 golden fixtures 與無前視偏差的測試設計，先審查後實作

驗收：所有欲實作規則均已由人員核准且能以有限、確定的 OHLC 序列驗證。

## Phase 4 - 決定性 Market Structure 與 SMC/ICT Engine

- 僅實作 Phase 3 已核准規格
- 分離 tentative 與 confirmed events，保存 `event_at`、`confirmed_at` 與輸入範圍
- 實作多週期對齊，禁止在歷史時點讀取未封閉的高週期 K 線
- 加入 property、regression、boundary 與 replay tests

驗收：固定資料集可重現；逐事件可追溯至規則版本與來源 K 線；不存在未揭露 repainting。

## Phase 5 - Signal Engine 與 Risk Engine

- 以規則組合產生 `LONG`、`SHORT`、`NO_TRADE` 候選與 reason codes
- `LONG`／`SHORT` 只允許一個 Entry Zone、恰好一個 TP、恰好一個 SL
- 驗證方向、價位關係、最低 RR、風險上限、資料新鮮度與衝突訊號
- 對不完整、不一致或超限候選輸出 `NO_TRADE`，不補造價位
- 將所有參數納入版本化設定並加入決定性測試

驗收：不啟用 OpenAI 也可完整產生、拒絕、保存及回測訊號。

## Phase 6 - OpenAI Secondary Validation

- 以 feature flag 預設關閉，API key 只透過環境／secret manager 注入
- 使用嚴格 structured output，只允許 `CONFIRM`、`REJECT`、`REDUCE_CONFIDENCE` 與解釋
- 驗證回應不得改變方向、結構、Entry、TP、SL 或 RR；錯誤、timeout、schema mismatch 採 fail-safe 政策
- 保存 prompt/version、候選 hash、回應、latency 與 validation outcome，不保存 secrets
- 加入 mocked contract tests；mock 只存在於明確標註的測試中

驗收：關閉或移除 OpenAI 時，決定性策略與回測結果仍可運作。

## Phase 7 - Backtesting 與統計

- 建立 event-driven replay，模擬當時可見資料與確認延遲
- 定義單一 TP/SL 的同 K 線碰觸政策、spread/slippage、手續費與資料缺口政策
- 保存策略／設定／資料版本，提供 reproducibility manifest
- 報告 win rate、expectancy、profit factor、drawdown、coverage、NO_TRADE 原因與樣本數
- 將 in-sample、validation、out-of-sample 分離，避免資料洩漏與過度調參

驗收：測試可證明資料 cutoff、多週期對齊與事件順序沒有前視偏差。

## Phase 8 - 分析介面

- 顯示真實 K 線、成交資料狀態、指標與可開關的結構 overlays
- 顯示候選／最終訊號、單一 Entry Zone、TP、SL、RR、信心與 reason codes
- 清楚區分 deterministic 結果與 OpenAI validation 結果
- 顯示行情延遲、K 線是否封閉、策略版本與 `NO_TRADE` 原因
- 提供歷史訊號與回測統計，不提供下單按鈕

驗收：前端 unit tests、API contract tests、錯誤與 stale-data 狀態通過。

## Phase 9 - 安全、觀測與部署準備

- 認證授權、rate limiting、audit log、metrics、tracing、backup/restore 與資料保留政策
- secrets 管理、dependency/container scanning、TLS 與最小權限部署
- 行情中斷、OpenAI 故障、DB unavailable 與 stale data 的 degraded-mode 演練
- 完成 end-to-end、load、recovery 與 deployment runbook 驗證

驗收：完成部署證據前，只能視為開發／研究工具，不宣稱 production-ready。
