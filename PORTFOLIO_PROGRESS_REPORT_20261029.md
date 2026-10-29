# AI Trading Platform 作品集進度報告

報告日期：2026-10-29（Asia/Taipei）

適用對象：推甄教授、面試 HR、工程面試官

公開範圍：架構、方法、驗證結果、問題與限制；不公開密鑰、資料庫、原始行情、第三方資料或實驗原始輸出

## 摘要

本專案是一個以「可重現、可稽核、安全失敗」為原則的 AI 輔助技術分析與 Paper 交易平台。目前已具備決定性多週期分析、FastAPI/PostgreSQL 後端、Next.js 產品介面、帳戶隔離的 Paper 委託與成交、Journal/Analytics，以及以測試與資料庫約束保護的稽核軌跡。

這不是 LIVE 交易系統，也沒有連接真實券商、操作資金或證明策略獲利。2026-10-29 的本機工作包含新一輪 Journal、歷史歸檔、私有儲存、Supervisor 與 Rust 相容性研究，但其中仍有部分完成、回歸失敗或等待設計決策的項目。因此，本次公開更新只發布可稽核的進度報告；進行中的來源碼另外保存於私有備份庫，避免把未完成實驗誤當成公開 release。

## 我發現的問題、處理方式與原因

### 1. 公開作品集與開發現場不能直接混在一起

**問題：** 工作樹同時包含可展示成果、尚未完成的來源碼、數千個實驗檔與本機證據。全部公開不只會讓教授或 HR 難以判斷真正成果，也可能洩漏不應發布的原始輸出或資料結構。

**處理：** 採用雙層發布。

- 公開 GitHub：只放可閱讀的產品說明、已驗證能力、畫面、限制與證據索引。
- 私有 GitHub：備份目前進行中的來源碼與測試，但仍排除 `.env`、金鑰、資料庫/備份、原始行情、PDF、快取、coverage、build output 與實驗原始輸出。
- `main` 維持 ruleset 保護；公開更新經專用分支與 Pull Request，不直接推送或繞過 required checks。

### 2. 測試命令對啟動目錄有隱含相依

**問題：** 後端單元測試第一次從 `backend/` 執行時，`test_historical_chart_s1b.py` 在 collection 階段找不到 repo-root 的 `experiments` fixture，回報 `ModuleNotFoundError`。這不是產品邏輯失敗，而是測試匯入路徑未完整宣告。

**處理：** 不修改 assertion、不跳過測試，改以明確的 `PYTHONPATH=..;.` 重跑；2,112 項後端單元測試全部通過。後續應把 fixture 轉成正式 test helper 或在測試設定中固定 import root，消除對 shell 啟動位置的依賴。

### 3. 前端建置通過，但依賴安全不能用「能 build」取代

**問題：** Next.js production build 可完成，但工具對目前 16.4.0 顯示已知安全更新提示；`npm audit` 目前仍有 7 個弱點（3 critical、2 high、2 moderate），GitHub Dependabot 也有未結案警示。

**處理：** 本次保留可重現的 build 結果，同時把升級列為獨立安全工作，不在混有大量 WIP 的分支直接升級。升級必須使用專用 worktree/branch，重新跑 TypeScript、ESLint、Vitest、production browser 與 required CI，避免把相依更新與功能開發混在一起。

### 4. Rust 工具鏈若依賴全域 PATH，驗證不可重現

**問題：** 系統 PATH 找不到 Cargo；直接呼叫隔離工具鏈時又分別遇到 default toolchain、`cargo fmt` 與 offline dependency home 未正確解析。

**處理：** 使用專案隔離的 Rust toolchain，明確設定 `PATH`、`CARGO_HOME` 與 `RUSTUP_HOME`，再以 locked/offline 模式執行。8 個 crate 的 fmt、Clippy（`-D warnings`）與合計 224 項測試/compile-fail case 通過。失敗嘗試仍保留在工程紀錄中，沒有被包裝成一次就成功。

### 5. 「換 Rust」容易被誤解成已全面重寫

**問題：** 若只寫「改用 Rust」，會誤導讀者以為 Python 已被取代，或 Rust 自動解決了效能、服務安裝、故障復原與金融正確性。

**處理：** 採漸進式 migration seam，而不是 big-bang rewrite。Python/FastAPI 目前仍是策略、金融行為、認證與資料庫流程的權威；PostgreSQL 仍是金融歷史的權威。Rust 目前只實作可被獨立驗證的窄核心，先做 shadow/parity comparison，通過契約與回滾門檻後才可能切換權威。

## 為什麼選擇 Rust

Rust 是未來系統核心的實作方向，原因是：

1. **型別與不可變契約：** 將金額、識別碼、事件狀態與邊界條件提早轉成編譯期或明確的解析錯誤。
2. **精確數值：** 金融數值需要 Decimal/整數尺度契約，避免把 `f64` 誤差帶進成交與統計。
3. **決定性重播：** Journal projection、analytics grouping 與 UTC 對齊適合做純函式、可重播、可與 Python golden result 比對的核心。
4. **資源與併發控制：** 未來若進入長時間服務與大量事件處理，Rust 能提供較清楚的記憶體所有權與 bounded resource model。
5. **可稽核建置來源：** locked dependency、離線驗證與 build provenance 有助於建立可重現的供應鏈證據。

目前已驗證的 Rust 範圍包含 startup fence、read query/DTO、event projection、analytics counts/decimal/monetary/grouping，以及 UTC alignment。尚未完成 Rust HTTP server、策略引擎、金融 writer、資料庫 schema migration、服務安裝與原生 recovery；因此不能宣稱「平台已完成 Rust 化」。

## 目前進度

| 領域 | 狀態 | 可驗證成果 |
| --- | --- | --- |
| 決定性分析 | 已交付 | 已收盤 K 線、時間截止點、多週期對齊、技術結構與風險契約；防止 look-ahead |
| Paper execution | 已交付公開基線 | 帳戶隔離的委託、成交、持倉、Journal、附件與 Analytics；無 LIVE provider |
| PostgreSQL 完整性 | 已交付公開基線 | CHECK、trigger、transaction、immutable receipt 與直接 SQL mutation 防護 |
| 前端產品介面 | 已交付公開基線 | Next.js/TypeScript 響應式分析與 Paper workflow，server-only credential boundary |
| Journal Product V2 | `PARTIAL_PASS` | 新 Journal 工作區與統計介面通過前端測試；完整 backend/E2E authority 尚未成立 |
| Market archive F5-C | 提案驗證完成、未接受 | 保存證據顯示測試與 coverage 過門檻；仍等待 owner acceptance，F5-D 未開始 |
| Object/private storage O3 | `PARTIAL_PASS` | contract 與部分 runtime seam 已建立；部署 adapter、durability/restore 證據未完成 |
| Worker Supervisor V2 | `REGRESSION_FAILED` | 已找到 ownership/close/installation trust 問題；S4 尚未 ready |
| Rust migration | PoC / shadow parity | 8 crates、224 項測試/compile-fail case；Python 與 PostgreSQL 仍是權威 |

## 2026-10-29 新鮮驗證

以下是本次發布前在目前工作樹執行的結果；它們不是公開 PR exact-head CI，也不互相加總成單一認證數字。

| 驗證 | 結果 |
| --- | --- |
| Backend static | Ruff PASS；mypy PASS（192 source files）；compileall PASS |
| Backend unit | 2,112 passed，5 warnings，24 分 54 秒；未包含完整 PostgreSQL partition/coverage gate |
| Frontend | TypeScript PASS；ESLint PASS；301 Vitest passed（25 files） |
| Frontend coverage | statements/lines 90.98%；branches 81.87%；functions 75.79% |
| Next production build | 編譯與重跑完成；依賴安全升級仍是 blocker，不能因 build 成功而關閉 |
| Rust | 8 crates fmt + Clippy `-D warnings` + locked/offline tests PASS；合計 224 cases |
| GitHub secret scanning | 0 個 open alert（檢查當下） |
| Branch protection | `Protect main` ruleset active；公開更新必須通過 PR 與兩個 required checks |

Rust 224 cases 分布：counts 40、decimal 27、monetary 79、projection 34、read DTO 11、read query 11、startup fence 14、UTC alignment 8。

## 尚未完成與明確限制

- 尚未完成完整 PostgreSQL 16 integration partition、全量 coverage 與最新公開 commit 的 GitHub Actions exact-head 驗證。
- Journal V2 的 backend-owned reconciliation、完整 E2E 與 production data authority 尚未完成。
- Market archive 尚未完成 owner acceptance 與 F5-D；不能描述為 production archive/restore。
- O3 私有物件儲存仍缺實際部署 adapter、加密/耐久/timeout 證據與隔離 restore drill。
- Supervisor V2 仍有 regression；Windows ownership、close tail、installation trust 與 recovery 不可宣稱已解決。
- Rust 尚未取代 Python 服務，也沒有 Rust financial writer 或 production service。
- Next.js/npm 與 Dependabot 安全警示尚待專用升級 PR。
- 尚未驗證策略獲利、真實滑價/延遲/手續費、LIVE broker 安全、商用容量、災難復原或 production readiness。

## 給教授與 HR 的作品集閱讀方式

這個專案的重點不是「AI 自動賺錢」，而是如何把容易產生幻覺與資料洩漏的金融原型，轉成有明確權威、錯誤契約、資料庫完整性、回歸測試與公開限制的工程系統。可以從下列能力評估：

- 將金融規則形式化並防止 look-ahead。
- 用 PostgreSQL 約束與不可變證據保護交易歷史。
- 建立 account scope、idempotency、race handling 與 server-only credential boundary。
- 對效能或語言遷移先定義 parity、rollback 與 fail-closed gate。
- 誠實保留 `PARTIAL_PASS`、`REGRESSION_FAILED`、尚未接受與不在範圍內的結論。

## 公開與私有資料邊界

公開庫可以包含程式架構、契約、已挑選的來源碼、測試方法、合成/標示清楚的 fixture、截圖與報告。下列內容不進入公開庫，也不因建立私有備份就放寬：

- 真實 `.env`、API key、token、密碼、憑證或含認證資訊的 URL。
- SQLite/PostgreSQL 資料庫、dump、WAL、備份或使用者資料。
- 原始行情、provider payload、第三方 PDF 或授權不明內容。
- 大量實驗原始輸出、coverage/profiler、cache、build artifact、log。
- 任何可被誤認為真實成交、獲利或 LIVE 營運的未標示證據。

## 下一步

1. 將本報告透過 PR #17 發布，等待 `Backend and PostgreSQL` 與 `Frontend and browser` required checks。
2. 在獨立 worktree/branch 修正 Next.js/npm/Dependabot 安全警示，完整回歸後另開 PR。
3. 為 Journal V2 補上 backend-owned reconciliation 與真實 E2E authority。
4. 依 owner 決策完成 archive F5-C acceptance，再決定是否進入 F5-D。
5. Rust 僅沿已定義的 shadow/parity/rollback gate 擴展，不越過 Python/PostgreSQL authority。
