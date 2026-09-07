# AI Trading Platform

這是一個以可重現、可稽核與安全失敗為核心的 AI 輔助技術分析平台。它提供類似簡化版 TradingView 的網頁體驗，只產生與保存研究訊號，不連接券商下單，也不執行真實交易。

> 目前狀態：決定性分析引擎、風險檢查、可選的 OpenAI 二次驗證、PostgreSQL 不可變稽核軌跡、回測框架與 Next.js 分析介面已完成工程基線。BTCUSDT／ETHUSDT 使用 Binance 公開 Spot Kline API 的已收盤 OHLCV；XAUUSD 尚未設定可靠 provider 時會明確拒絕，不補造價格。前端已接上分析 API，保留 unavailable／no-signal 的安全狀態；系統仍不提供下單。

## 履歷重點

| 面向 | 實作成果 |
| --- | --- |
| 後端與資料 | FastAPI、Pydantic、SQLAlchemy、Alembic、PostgreSQL 16；明確交易邊界與錯誤契約 |
| 演算法工程 | 封閉 K 線、時間截止點、多週期對齊、Market Structure、SMC/ICT、Risk Engine |
| 可重現性 | 資料集、策略、設定、程式來源與回測執行皆有 canonical identity；分析與回測共用決定性引擎 |
| 效能工程 | P3 增量重播以完整輸出差異測試守住語意等價；已量測約 2.9 倍整體吞吐改善，並明確保留後段效能不足的停止結論 |
| 資料庫安全 | PostgreSQL CHECK 與 trigger 阻擋無效狀態、直接 SQL 改寫與歷史證據變更 |
| AI 安全邊界 | OpenAI 僅能驗證既有候選，不能創造方向或改寫 Entry／TP／SL；停用時仍可完整運作 |
| 前端品質 | Next.js／TypeScript 儀表板、請求競態防護、明確錯誤狀態、單元與真實瀏覽器測試 |

最新進度與下一階段請見 [PROJECT_STATUS.md](PROJECT_STATUS.md)；公開版驗證摘要見 [VERIFICATION.md](VERIFICATION.md)；安全邊界請見 [SECURITY.md](SECURITY.md)。最新 P3 工程驗證記錄為 899 個後端測試（含 109 個真實 PostgreSQL 測試）、69 個前端測試與 74 個真實 Chrome 案例通過；增量重播的等價性、效能與限制見 [P3 報告](experiments/r1e_p3_incremental/P3_REPORT.md)。這些數字證明的是工程規則與回歸防護，不代表策略獲利、真實成交品質或正式上線可用性。

## 產品範圍

- 初始商品：`XAUUSD`、`BTCUSDT`、`ETHUSDT`
- 初始週期：`1m`、`3m`、`5m`、`15m`、`1h`
- 圖表：K 線、指標、支撐／壓力、結構與訊號疊圖
- 分析：MACD、支撐／壓力、Market Structure、SMC、ICT、多週期分析
- 決策：規則式候選訊號、風險檢查、選用的 OpenAI 二次驗證
- 輸出：`LONG`、`SHORT` 或 `NO_TRADE`
- 保存：行情版本、偵測結果、候選訊號、最終訊號與驗證紀錄，供回測及統計使用

## 不在範圍內

- 券商／交易所下單、倉位管理、資金劃轉或 API 交易金鑰
- 由 OpenAI 自行發明市場結構、Entry、TP 或 SL
- 以測試假資料冒充正式行情或正式訊號
- 未完成形式化、無法回測的 SMC／ICT 規則

## 核心架構

```text
Market Data
  -> Indicator Engine
  -> Market Structure Engine
  -> SMC/ICT Engine
  -> Rule-based Signal Engine
  -> Risk Engine
  -> OpenAI Validation (optional)
  -> Final Signal
  -> Signal Store / Backtest / Statistics
```

### 模組責任

| 模組 | 責任 | 邊界 |
| --- | --- | --- |
| Market Data | 透過可替換 provider 擷取真實 OHLCV，正規化為 UTC timestamp／Decimal 價格，檢查排序、重複與時間缺口 | BTCUSDT／ETHUSDT 使用 Binance 公開 Spot Kline；XAUUSD provider 尚待決定，禁止補造價格 |
| Indicator Engine | 以封閉 K 線計算可設定週期的 EMA、MACD 與 ATR，輸出逐 Candle 結構化結果 | warm-up 不回填；交叉與 histogram 方向只比較當前及前一已計算值 |
| Market Structure Engine | 產生 candidate／confirmed swings、趨勢、support/resistance zones，以及可設定 CLOSE/WICK 與 buffer 的 BOS/MSS 事件 | CHoCH 僅為 MSS display alias；不重複建立第二事件 |
| SMC/ICT Engine | 偵測 displacement、FVG/IFVG、liquidity、order block、CRT 與高機率 entry sequence，並保存可追溯 lifecycle | 只讀取當下可用的已收盤資料；狀態與有效期由版本化設定控制 |
| Multi-timeframe Analysis | 對齊不同週期的已封閉 K 線與結構狀態 | 禁止低週期讀取當時尚未收盤的高週期 K 線 |
| Rule-based Signal Engine | 由可追溯規則產生候選方向與原因碼 | 必須能在停用 OpenAI 時獨立運作與回測 |
| Risk Engine | 驗證 Entry Zone、單一 TP、單一 SL、風險報酬與風險上限 | 所有閾值集中設定，不散落 magic numbers |
| OpenAI Validation | 僅能確認、拒絕、降低信心或解釋既有候選 | 不得新增結構、改方向或創造／移動價位 |
| Signal Store | 保存輸入版本、規則版本、候選、驗證與最終結果 | 支援重播、回測、稽核及統計 |
| API / Frontend | 提供圖表、分析覆蓋層、訊號明細與歷史統計 | 不提供下單控制項 |

## 訊號契約

- `LONG`／`SHORT` 必須各自包含：一個 Entry Zone、恰好一個 Take Profit、恰好一個 Stop Loss，以及可重算的 Risk/Reward。
- `NO_TRADE` 不得帶有可被誤認為建議下單的 Entry、TP 或 SL；必須保留拒絕原因碼。
- 決定性引擎先建立完整候選，Risk Engine 再檢查價位關係與限制；OpenAI 只能對該候選回傳 `CONFIRM`、`REJECT` 或 `REDUCE_CONFIDENCE`。
- OpenAI 不可覆寫 Entry Zone、TP、SL、Risk/Reward、結構事件或原始行情。
- 每筆結果應保存 `strategy_version`、`config_version`、`data_cutoff_at`、來源 K 線範圍與逐階段 reason codes。

## 避免前視偏差與 repainting

1. 確認型規則只讀取訊號當下已封閉的 K 線。
2. 多週期聚合只使用當時已完整收盤的高週期資料。
3. 結構事件同時保存事件時間與實際確認時間；回測只能在確認後使用。
4. 原始行情、衍生特徵與策略設定需版本化，回測不得以後來修訂的狀態覆蓋歷史決策。
5. 若某演算法需要右側 K 線確認 pivot，訊號可用時間必須延後到確認 K 線收盤後。
6. 任何可 repaint 的視覺輔助都不得直接作為未標註延遲的交易條件。

## 規格與授權邊界

規則來源草案與可執行定義分別整理在 `docs/strategy-spec/` 與 `docs/algorithm-spec/`。每條正式策略規則應包含輸入欄位、封閉 K 線要求、精確條件、可設定閾值、確認時間、失效條件、reason code、正反例測試，以及不使用未來資料的證明。

研究時使用的第三方 PDF 不屬於本專案授權內容，因此刻意由 `.gitignore` 排除，不會發布到 GitHub。倉庫只保留自行撰寫的規格、程式、測試與稽核摘要；這個排除不會改變已凍結策略的定義或驗證結果。

## 建議目錄

```text
ai-trading-platform/
├── backend/
│   ├── app/
│   │   ├── api/                 # FastAPI routes
│   │   ├── core/                # 設定、logging、共用政策
│   │   ├── database/            # SQLAlchemy engine、session、metadata
│   │   ├── engines/             # indicators、structure、SMC/ICT、risk、signal 邊界
│   │   ├── models/              # SQLAlchemy persistence models
│   │   ├── schemas/             # Pydantic API/domain contracts
│   │   └── services/            # 真實外部資料 adapter 邊界
│   └── tests/
│       ├── unit/
│       ├── integration/
│       └── fixtures/            # 僅限明確標註的測試資料
├── frontend/
│   ├── src/
│   │   ├── app/                 # Next.js App Router
│   │   ├── components/          # chart、analysis、signal UI
│   │   ├── lib/                 # API client、chart adapters
│   │   └── types/               # TypeScript contracts
│   └── tests/
├── docs/                     # 架構、策略、演算法、安全與稽核說明
├── PROJECT_STATUS.md         # 履歷用進度、驗證與下一階段
├── SECURITY.md               # 金鑰與資料庫安全政策
├── .env.example
├── docker-compose.yml
├── README.md
└── ROADMAP.md
```

## 後端執行與測試

本機 Python：

```powershell
Set-Location backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Docker Compose：

```powershell
Copy-Item .env.example .env
docker compose config
docker compose up --build -d
docker compose ps
```

Backend container 啟動時會先執行 `alembic upgrade head`。`signals.analysis_snapshot` 使用 PostgreSQL `JSONB` 保存訊號產生當下的 `captured_at`、市場資料截止時間與分析 payload；查詢歷史訊號時直接讀取此快照，不使用目前或未來市場資料重算理由。

可用端點包含 `GET /api/v1/health`、`GET /api/v1/health/ready`、`GET /api/v1/market/candles`、`POST /api/v1/analysis` 與 `POST /api/v1/signals/evaluate`。決定性端點的 request body 只接受 `symbol`、`timeframe` 與可選 `cutoff`，不接受 client OHLC；伺服器自行取得、正規化並檢查行情。runtime pipeline 目前明確配置 `1m` signal timeframe；未配置 timeframe 會 fail closed。歷史 cutoff 預設停用，只有啟用研究設定並提供 `X-Research-Cutoff-Token` 才可使用。XAUUSD 在 real provider 未配置時回傳 `503 MARKET_DATA_PROVIDER_NOT_CONFIGURED`。預設值只供本機開發；部署前必須替換密碼、限制網路暴露並以 secret manager 管理研究 token 與其他 secrets。

## 前端執行與品質檢查

```powershell
Set-Location frontend
npm ci
npm run dev
```

從專案根目錄執行完整品質門檻：

```powershell
.\scripts\quality-gates.ps1
```

也可分別執行 `npm run typecheck`、`npm run lint`、`npm run test:coverage`、`npm run test:browser` 與 `npm run build`。詳細門檻與限制見 [docs/quality-gates.md](docs/quality-gates.md)。
