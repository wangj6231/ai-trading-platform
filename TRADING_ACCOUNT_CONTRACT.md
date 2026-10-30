# EXECUTION-ARCH-01 — Trading Account Contract

> Status superseded 2026-10-08: 以下為 Stage0 歷史設計／inventory，不代表目前 implementation。
> PAPER_DECIMAL_V1 已 OWNER-FROZEN，numeric gate 已 COMPLETE；內部 core/adapter/projection
> 與 additive ledger 已實作。當前唯一政策權威為 [PAPER_DIRECTIONAL_V1_POLICY.md](PAPER_DIRECTIONAL_V1_POLICY.md)，
> 實際接口／限制／本輪驗證見 [PAPER_ACCOUNT_V1_REPORT.md](PAPER_ACCOUNT_V1_REPORT.md)。
> 下文的 pending/BLOCKED/尚未實作 敘述均屬批准前狀態；User/Auth/public writes、LIVE、Journal 仍未實作。

2026-10-08；EXECUTION-ARCH-01B 設計更新。Account/user/auth entities 目前不存在。Owner 已允許未來 internal-only core/service/repository；缺 User 不阻擋 internal slice，但禁止 unauthenticated public execution-write API。Final owner D1–D7已批准；僅accountdivision的versionedprecision/rounding/residual待補充，未進implementation。

## 1. Account identity

| Field | Proposed contract | 分類 |
|---|---|---|
| `account_id` | server-generated stable ID；execution events/fills/order intents 都 account scoped | SAFE_ADDITIVE |
| `owner_user_id` | future User FK，由 authenticated server principal 派生；目前沒有可用 User model | BLOCKED；不能由 body owner_id 代替 auth |
| `environment` | strict PAPER / LIVE，建立後不可把歷史 PAPER 改成 LIVE | SAFE_ADDITIVE |
| `execution_provider` | server registry key；PAPER 為第一候選，LIVE 未啟用 | SAFE_ADDITIVE |
| `execution_source` / connection binding | 穩定 source namespace；綁定 provider + environment + external account/connection identity | SAFE_ADDITIVE；換帳戶需新 binding，不能重新標記既有 fills |
| settlement/denomination currency | Owner凍結USDT；只USDT-quoted instruments，不是Spotinventory | SAFE_ADDITIVE（已批准，未實作） |
| `reporting_currency` | Owner凍結USDT，無FX；其他currencyUNSUPPORTED/NOT_READY | SAFE_ADDITIVE（已批准，未實作）；不等同USD |
| `accounting_profile_version` | owner 凍結 `PAPER_DIRECTIONAL_V1`：SYNTHETIC_DIRECTIONAL／ONE_WAY_NET_POSITION，LONG／SHORT | SAFE_ADDITIVE（owner 已批准語義，不是現有 schema）；final D1–D7已批准，numeric precision/residual待補充 |
| `status` | proposed ACTIVE / SUSPENDED / CLOSED；允許哪些新 commands由 server gate | SAFE_ADDITIVE；具體 onboarding/closure policy 未批准 |
| `created_at` / `updated_at` | server strict UTC；event timestamps另外保存 | SAFE_ADDITIVE |
| credential reference | server-only secret reference，不存明文、不返回 browser、不寫 event | SAFE_ADDITIVE；LIVE設定尚未設計/啟用 |

Account status 不抹除歷史；SUSPENDED/CLOSED 可禁止新 orders，但仍需 ingest/reconcile 已在外部執行的 fills。不能把停用帳戶誤當成交不曾存在。Closure 有未完成order的處置由 later owner policy定義，不自行 liquidation。

PAPER monetary account為USDT cash/reserved/available/realized/unrealized/equity；1x collateral在confirmedfill原子驗資，submit/ack不reserve。Positiveinitialbalancecreationdefault10000，建立後不可改；reset新ledger/version，不改歷史。NoFX、noSpotinventory；不能用float或把USDT当USD。

## 2. Ownership 與 authorization

- Authentication 在 gateway 前；account ID 是 lookup，不是 permission。每次 command/query/event ingestion 均驗 account/source scope。
- PlannedTrade、Order、TradeFill、Trade、Journal、screenshots 都直接或由受驗證 FK鏈綁 account；foreign-owner signal plan link 不可自動授權 execution。
- Provider ingestion使用 server-controlled connection映射account，不信 incoming payload任意 account ID。
- Registry selection、environment、capabilities、credentials均server-owned，client不可改source跳LIVE或fallback到PAPER。
- 即使 local PAPER，也不能以 browser localStorage 或 demo owner 當可信身份。若 owner選single-user operator mode，需另有明示部署/auth契約；本階段不選模式。
- Journal notes/tags 可由owner修改且需bounds；immutable fills、financial computation、strategy snapshot不得隨notes更新。

## 3. Account concurrency（提案）

Command idempotency與filluniqueness處理retry；owner明定fill-timefunds/collateralandfeeatomicgate，submit/ack不authoritativecapitalreserve。Order同時eligible時按PAPERimmutablemonotonicsequence處理；network在DBlocks外。Closing在negativeequity允許，over-closeREJECT，無liquidation。

未來 ingestion transaction 至少原子化 fill+processed marker+approved ledger projection；同account concurrent fills需 row lock/version協調。Existing signal `SELECT FOR UPDATE` 不會自動鎖新account，也未具上述 reservation/account交易語义。

## 4. Frozen profile／remaining financial frontier

模型選擇已結束：PAPER 不是 Spot inventory，而是 versioned synthetic directional net position。PAPER 歷史不能改標 LIVE；不模擬 margin、borrowing、funding、liquidation、hedge mode。Market provider 仍與 execution provider 分開。

這些values均已由finalowner明確批准：userquantity、MARKET/LIMIT、closed1m fill/mark、WMA、over-closeREJECT、fee0.001USDT、RNULL、1xcollateral與balance/equity。唯一需補充是D5 versionedDecimalprecision/rounding/fullclose residual。見 [PAPER_DIRECTIONAL_V1_POLICY.md](PAPER_DIRECTIONAL_V1_POLICY.md)，不再重問已凍結金融政策。

## 5. Existing evidence 與 future tests

現有 `models/signal.py` 無 account/user FK；`api/signals.py` 不提供account歷史API。`database/db.py` 提供service-owned commit模式而非authorization。

未來需測 account A不能查/改B；provider/account/environment mismatch拒絕；credentialredaction；PAPER不冒充LIVE；suspended禁止新intent但接受latefill；每個account fillIDnamespace獨立；restart/replay保持namespace；原有snapshot/terminal guards不變。這次只閱讀existingtests，不執行或新增testcode。
