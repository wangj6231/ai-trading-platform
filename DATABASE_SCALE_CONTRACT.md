# Database Scale Contract

Approved targets/retention/recovery：[PRODUCT_FOUNDATION_V1](PRODUCT_FOUNDATION_V1.md)。
25kaccounts/10Mclosedtradesshape是隔離load工程目標，不是已證capacity；pool/timeout仍須測定。
金融active+24monthsretention不能繞過immutableguards；RPO5min/RTO60min需實際restore驗證。

範圍：PostgreSQL 仍為 execution/financial facts 唯一權威。以下未實作的部署要求
不等於目前已有保護；不分片、不改 migration、不改金融核心。

## 現況與連線預算

`app/database/db.py:16-24` 每 app 建一個 synchronous engine，pool_pre_ping=True，
沒有 authored pool_size/max_overflow/pool_timeout/statement_timeout/lock_timeout。
本次不連線的實際 PG dialect pool inspection：QueuePool，size5、overflow10、
checkout timeout30秒；不是 DB max_connections 或負載驗證。

未來部署必須明列每 process 的 P=pool_size、O=max_overflow、W=process數，
budget上界 `sum(W*(P+O)) + migration/admin/backup/lock-reserved connections`，
不得超過核准 DB budget。worker 的 advisory-lock connection 佔同一 pool，
持有期間又需要 transaction connection，不能配置成只夠鎖連線。
不以增加 overflow 掩蓋 saturation。每個 child process 自建 engine；不分享 fork前 connection。
連線上限及 recycle/checkout/query/lock/idle-transaction timeout 是 deployment參數，
須 load test與 failure contract，不能改 StrategyConfig hash。
參考 [SQLAlchemy pooling](https://docs.sqlalchemy.org/en/20/core/pooling.html)。

## 交易與 query policy

現有 Database.transaction 在成功 commit後回傳，失敗 rollback/close；read_session
不 commit，結束時 rollback。ExecutionRepository.read_account 使用 PG shared lock；
lock_account 為 exclusive lock。`observe` 的整個 contiguous batch 是一個帳戶交易。
金融 commit與 delivery checkpoint 是分開的；後者失敗由 idempotent replay恢復。
不得持有金融 row lock等待 provider network；現有 stream advisory lock是另外一回事。

針對同帳戶長 transaction與大量 immutable-history驗證，先量測 lock wait、
query count、account JSON bytes、batch length；不得移除 mirror validation來換速度。
昂貴 read projection需驗證一致性、cutoff與rebuild，才可取代 request-time replay。

| 查詢形狀 | 現有索引／缺口 | 候選索引，未新增 |
|---|---|---|
| active eligible orders by symbol | account/command uniques；symbol/status 在 JSON，不是 typed indexed columns | server-owned active-work projection；symbol,next_open,account,command_sequence |
| account order page | account+command_sequence unique可幫 account篩選，不等於 accepted_at排序索引 | account,accepted_at,order_id |
| fill replay | source/account/sequence unique，不等於 filled_at排序 | account,filled_at,execution_sequence；visibility另檢 received_at |
| closed-trade report | execution_trades.account_id FK無對應 report索引 | account,closed_at,trade_id及server-known visibility/version |
| attachments | auto-snapshot partial unique，不等於page索引 | trade_id,created_at,attachment_id |
| delivery checkpoint | PK(source,symbol,account,cutoff) | source指定時 prefix合理；無source查詢需 EXPLAIN，不假定有效 |
| captured candle | PK(source,symbol,open_at) | 已適合 exact identity/range；保留 hash conflict |

以新 Alembic revision、新/舊 query parity、realPG EXPLAIN(ANALYZE,BUFFERS) 和寫入成本
選索引；不為每 field 添加索引。不能將JSON狀態抽取當成未驗證金融權威。
migration runtime role分離，concurrent index如需要須獨立部署步驟；不在app請求跑DDL。

## 大表／partition readiness

orders、fills/events、account valuation marks、market_observations、deliveries、
future audit/job records會增長。Current history cache在文件，不是市場OHLC DB大表。
future read方法必帶 account/source、明確UTC範圍、穩定tie-breaker、bounded limit。
按月分區尚未選定：PG partitioned uniqueness要求與現有跨時間 fill身份/FK
可能衝突，必須維持globaldedup，不能把unique改為「同一月份unique」。
大表archive/partition detach目前會碰到append-only delete guards；不實作繞過trigger。

## Instrumentation／recovery

future pool checkout wait/usage/overflow、SQL normalized fingerprint latency、rows、
transaction/lock duration、deadlocks與WAL bytes。參數、account payload及secret不進slow log。
pg_stat_statements/slow-query設定尚未驗證。Query plan只能在隔離測試DB量測。
read replica僅允許標明as_of/lag的非金融投影；auth、balance、execution admission仍走primary。
備份/PITR及 restore驗證見 [BACKUP_DR_CONTRACT.md](BACKUP_DR_CONTRACT.md)。
