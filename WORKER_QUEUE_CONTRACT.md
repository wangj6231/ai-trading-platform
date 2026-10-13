# Worker / Durable Job Contract

[PRODUCT_FOUNDATION_V1](PRODUCT_FOUNDATION_V1.md) 已批准sharedproviderbudget與symbol-firstfanout。
100symbols/5kactiveaccounts/50kpendingorders為工程target，不改現有worker金融authority。
每userjob執行前serverresolve subject_id/account_id；create/read/result/cancel都需scope。
Internalobservation用servercapability，不把每marketstream變成一份per-userproviderfetch。

本文件包含已實作 ObservationWorker，不是重新設計一個假想替代品。
金融入口保持 `ExecutionGateway.observe(account, ValidatedMarketData)`。

## Actual observation path

`observation/worker.py::tick/_symbol` 按sorted configured symbols執行；同source/symbol
先拿PG session advisory lock，再查targets與checkpoint，抓一份closed1m range，
capture後按sorted account ID呼叫gateway，成功commit後才寫delivery。
一symbol多account共用batch，不以executionprovider選marketprovider。

| 行為 | 實作證據／擴展意義 |
|---|---|
| target lookup | repository.targets全帳戶掃描，每帳戶全部歷史orders；checkpoint額外逐target查詢 |
| catchup | earliest durable order cursor → current minute cutoff；page≤1000；defaultcap100000，不截斷/forwardfill |
| gateway工作 | current-cutoff batch；每candle掃該帳戶全部orders、寫/驗immutable mark；O(batch×history)候選來源 |
| checkpoint | append-only delivery PK(source,symbol,account,cutoff)；capture archive與financialcommit分開 |
| duplicate/restart | ordercursor + canonicalfilldedup + marks + checkpoint；crash afterfinancialcommit harmlessretry |
| Retry-After | process `_retry_at`，poll floor、≤86400s；429不改訂單，不補假資料 |
| backlog | overcap NOT_READY；必須營運處理，不能默默skip；一次catchup過慢跨minute會failclosed/retry |
| lifecycle | nonblockinglifespanstart；cancelnetwork，等ownedfiniteDBwork，釋放lock再dispose |
| multi-instance | 同stream同時只有一個lockowner；其他BUSY；不是persistentleaderelection或公平排程 |

advisorylock是session鎖，跨transaction存在並佔實體connection；process死亡釋放。
不可把目前lockconnection放進transaction-pooling PgBouncer而假設同一session。
如引入pooler，lock需保留direct/session connection與專用budget；migration/admin分離。
參考 [PostgreSQL advisory locks](https://www.postgresql.org/docs/16/explicit-locking.html#ADVISORY-LOCKS)。

## 實際放大因子

page network上界候選：`ceil(required_range/page_limit) * configured_provider_attempts`，
只是單cycle成功前重試上界；每次minute-rollover或失敗重播可能再抓同range。
一最慢LIMIT會使同symbol所有targets共用較長range；capture archive目前用於驗conflict，
不是省掉providerfetch的read-throughcache。readonlypendingorder也會寫peraccountmarks。
多副本 `_retry_at` 不共享：ownerA遇429放lock，B可立即重新抓，造成provider負載。
同一IP的chart、15m bootstrap、1mworker共用providerbudget卻尚無共同budgeter。
不宣稱「每分鐘一個request」，也不宣稱append-onlycheckpoint讓targetscan變bounded。

## 最小未來改進契約（未實作）

1. 從server-owned canonical orders/positions生成 active-work read projection，index
   source/symbol,nexteligibleopen,account,commandsequence。每頁固定上限，穩定order。
   漏項會skipfinancialopportunity，因此必須與現有targetscan雙讀parity及rebuild。
2. 仍把validated current-cutoff batch交gateway。改善worker查詢不解決gateway內
   historyscan；後者的實作改進需全eligibility/sequence/fee/retry等價tests，保留Interface。
3. 定義共享provider requestbudget/cooldown與成本backpressure後才增加副本。
4. 需要durablejob时先利用PG jobs/outbox可評估，不先選Kafka/RabbitMQ/SQS。

## Durable job semantics

| Job | required ordering / dedup / recovery |
|---|---|
| observation | source/symbol ordered opens；at-least-once delivery，exactly-once economic admission不是transport承諾 |
| analytics projection | account canonicalclose visibility + executionsequence；dedup trade/version；rebuild水位 |
| snapshot | attachment_id / typedorigin dedup；PENDING→READY/FAILED terminalreceipt immutable；renderer未實作 |
| reconciliation | account/order scope；UNKNOWN不能盲目重新submit；依原adapterreceipt契約 |
| future notification | committed canonicalevent→outbox；server-ownedentitlement，具體notification授權尚未定；不send-beforecommit |

future envelope必含jobtype/version、scope、dedupkey、known_at/cutoff、attempt、
lease owner/expiry、next_attempt_at、boundedredactederror；不存rawcredential。
ack aftercommit；retry指數backoff+限attempt/walltime/bytes；poisonjob隔離DLQ並告警，
不可把financialorder標成rejected以消除technicaljob。管理replay有audit、scope、dryrun。
Backpressure必有perstream/peraccount fairness及age監控；有限queue拒收不丟失已commitfacts。
目前 EvaluationJobs 是ephemeralcomputejobs，不是durableexecutionqueue；不混用其TTL。
