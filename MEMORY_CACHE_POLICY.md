# Memory / Cache Policy

[PRODUCT_FOUNDATION_V1](PRODUCT_FOUNDATION_V1.md) 已批准operation-requiredmarket90dayshot/warm
target，非無限retention、非策略history上限。較長canonical15marchive需受驗證hydration支援
52weekly/200dailywarmup完整區間；目前尚無tiering/quotaimplementation。Capacitytargets不自動設定cachelimits。

Financial authority必須在完整cache loss後仍存在於PG；cache不能成為 fill、cash、
position、Journal facts的來源。hash檢查不是對cache寫入者的認證。

## 現有狀態與缺口

| Owner／容器 | 實作 bounds / lifetime | rebuild與風險 |
|---|---|---|
| ObservationWorker.status/_retry_at | configured instrument keys；poll5s；retry≤86400s | process restart重建；cooldown非cluster-shared；固定category log |
| worker targets/market range | targets未有account ceiling；range default100000，上限設定1000000；page≤1000 | 每cycle釋放，但完整range及multiple validating copies可同時存在 |
| execution Account projection | state含全部歷史trades，沒有totalhistory byte bound | PG重讀；不應稱為 bounded per-user cache |
| Journal/Analytics request | all fills/trades、membership與attachments materialized | request結束釋放，峰值隨歷史；page size不限制這些容器 |
| EvaluationJobs | active2、jobs4、retained bodies≤384MiB、timeout120s、terminal TTL300s | request時expire/evict oldest terminal；process death job消失；active/transient/child RSS不含在bytes ceiling |
| InFlightResponses | leases2；service-owned reserve/release | 完成/取消刪除flight；不是persistent/shared result cache |
| isolated evaluation runner | workers2；per-jobtimeout120s | process cleanup；各engine archive仍隨history，不能宣稱每evaluation O(1) memory |
| FileHistoricalCandleCache | 每symbol/timeframe一檔、atomic replace/hash；無TTL/總bytes/rows ceiling | provider rebootstrap；合併保留舊資料，整檔JSON load/save與hash |
| Settings lru_cache | 無參數singleSettings instance | process lifetime；不是tenantcache |

synthetic測量的 Python tracemalloc peak不是RSS，不含PG/child memory。
20 closed trades Journal peak845980bytes、Analytics802239bytes；不能外推為商用帳戶上限。

## 未來cache啟用的強制契約

任何新cache須同時聲明 finite max_entries/max_bytes、TTL、eviction、owner、
key scope、rebuild、metrics；未配置數字即不啟用。不得用「TTL有設定」代替byte bound。

| Cacheable候選 | key / limit / expiry契約 | loss / invalidation |
|---|---|---|
| instrument metadata | profile reference/version；entries≤server registry；finite byte budget | trusted registry重載；無profile不fallback |
| shared market hot observations | provider,symbol,timeframe,open,contenthash；finite perstreamcutoffs及bytebudget | PIT revalidation + DB archive/provider；conflict quarantine |
| account read DTO | subject,account,resource,cutoff,projection version；finite entries/bytes、短TTL | auth每次重驗，membership/version改變立即失效；financial admission不用cache |
| rate counters | route/IP可信來源/subject/account；finite keys/window+TTL，anti-cardinality policy | costly/mutation admission store失敗fail closed；不作accounttruth |
| historical files | server source identity；finite diskquota與完整approved warmup/research保留範圍 | atomic replace；可rebootstrap；不能剪掉strategyrequiredhistory改語義 |

部署budget需計算 parent RSS + runner children + thread/DB buffers + duplicated
range/models + result serialization + native allocations。LRU/TTL不是記憶體證明；
必須測 cold start、cancel/retry、busy responses、largest configuredcatchup、cachecorruption。
hot-state archive不可任意剪裁來調strategy或破prefix invariance；本階段不改它。
Redis只是未來共享cacheadapter選項，不是前提，也不持有金融權威。
