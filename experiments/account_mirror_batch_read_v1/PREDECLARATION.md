# ACCOUNT-MIRROR-BATCH-READ-V1 measurement admission

Before any production edit, measure canonical Gateway-generated accounts with
0/10/50/100/500 closed trades, progressively, on the owned isolated PostgreSQL
cluster. A single sequential account history may seed later shapes without
replaying from zero; a pending untouched LIMIT order is installed at each sample.
No strategy/provider network call, no financial seed bypass or account truncation.

Cooperative overall profile cap: 900 seconds, checked between complete canonical
open/close pairs and measurement actions. RSS admission cap: 768MiB. No hard
interrupt inside a financial transaction. Record cap overrun and achieved shapes;
do not escalate after a cap. After uses the same reached shapes, fixture prices,
clock, commands, instruments, and sample semantics. No D2 claim.

Each reached shape measures a fresh-session account read and first one-candle
observation. A separate instrumented account reread records schema/hash/document,
ORM row loads, SQL families, CPU/RSS and tracemalloc allocation evidence. Journal
reads are measured separately only through 50 trades (membership replay is not
part of this IO optimization). Samples are not production latency percentiles.

Approved seams: Gateway.get_account, Gateway.observe, existing repository parser
transaction seam, canonical Journal/Analytics, actual PostgreSQL SQL-count and
corruption injection. Cold-read query amplification must go red before the fix.
Every canonical reference still validates; existing unreferenced-extra and ORM
identity-map behavior must remain unchanged. No frontend/config/accounting/DB
schema/strategy changes. Rust/F4 are not authorized.
