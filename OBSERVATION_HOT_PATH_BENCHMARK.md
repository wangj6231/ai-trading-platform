# Observation hot-path benchmark — F3

Predeclared before production changes: F1 owned-PG workload, small(100 accounts/1000 pending orders/10 closed
history trades), intermediate(500/5000/50), extended(1000/10000/100). History account is additional.
Sequential progression; stop escalation on cap/errors/RSS budget. Workload cap600s cooperative between
gateway commands; RSS budget768MiB checked at command seams (one-command overshoot possible). SQL30s,
pool1s; migration/cleanup excluded from workload cap. No hard process-watchdog claim.

Same fixtures, prices, clocks, F1 workload and F3 wrapper source before/after. Stage wrappers are test-only;
discovery/checkpoint/gateway/capture/delivery measured separately. No strategy calls/PnL interpretation.
No percentages required after observing data; no D2 capacity claim. Artifact directory experiments/product_foundation_f3/.
Baseline must be saved before any production optimization. Larger-profile cap is evidence, not completed load.

Baseline artifacts saved before production changes. small35.764s/21313queries; intermediate779.261s/354513queries
(see JSON for exact count). Intermediate exceeds600s; F1 timed_out=false is NOT evidence of meeting the cap:
the final worker command overran without a subsequent command-boundary check. Actual elapsed is authoritative.
Escalation stopped: extended1000/10000 NOT_ATTEMPTED due cap. Preserve both raw timing and inaccurate
underlying flag; do not relabel the run as within budget. Gateway728.631s versus discovery1.084s dominates.
First small diagnostic was rerun before production changes to save bounded artifacts after reducing verbose
telemetry output; only saved small is used for comparison. F1 financial fixture/profile source unchanged.


## Final comparable measurements — single retained pending index

All values newly measured; BEFORE files `baseline_*`, AFTER files `final_after_*`.
Earlier `after_*` two-index probes are SUPERSEDED, not mixed into this table.
One run per shape/build, not statistical capacity/SLO proof. Fixture hashes and F1/F3 harness source match.

| Metric | 100/1000 BEFORE | AFTER | DELTA | 500/5000 BEFORE | AFTER | DELTA |
|---|---:|---:|---:|---:|---:|---:|
| Workload wall s | 35.764 | 37.076 | 1.312 | 779.261 | 797.223 | 17.961 |
| Total SQL count | 21313 | 21105 | -208 | 354513 | 353469 | -1044 |
| Total SQL s | 12.526 | 13.663 | 1.138 | 328.788 | 350.760 | 21.972 |
| Process CPU s | 26.938 | 27.531 | 0.594 | 535.656 | 536.063 | 0.406 |
| Sampled RSS bytes | 118255616 | 116748288 | -1507328 | 123543552 | 121090048 | -2453504 |
| End DB connections (not peak) | 2 | 2 | 0 | 2 | 2 | 0 |
| Cluster WAL bytes | 78206672 | 87850984 | 9644312 | 2036261360 | 2166029600 | 129768240 |
| Retained max admission lag s | 27.213 | 28.931 | 1.718 | 731.928 | 751.229 | 19.301 |
| Fixture provider calls | 1 | 1 | 0 | 1 | 1 | 0 |
| Targets discovered | 100 | 100 | 0 | 500 | 500 | 0 |
| Gateway admissions (calls, not fills) | 100 | 100 | 0 | 500 | 500 | 0 |

| Scoped stage | 100/1000 BEFORE | AFTER | 500/5000 BEFORE | AFTER |
|---|---:|---:|---:|---:|
| Discovery SQL | 113 | 4 | 553 | 4 |
| Discovery wall s | 0.272 | 0.059 | 1.084 | 0.075 |
| Discovery SQL s | 0.053 | 0.019 | 0.203 | 0.035 |
| Gateway SQL | 12600 | 12600 | 303000 | 303000 |
| Gateway wall s | 26.765 | 28.487 | 728.631 | 748.106 |
| Gateway SQL s | 9.950 | 11.144 | 314.926 | 336.848 |

Old checkpoint reads100/500; new finite pages1/5 (page size100). Combined discovery/checkpoint SQL213→5
and1053→9, respectively97.65% and99.15% fewer in that scoped boundary. Discovery alone113→4 and553→4.
The unchanged wrapper measures old `checkpoint`, not new `checkpoints`; do not read an absent stage as
zero SQL/time. Bulk page query counts independently tested; separate plan diagnostic measured1page at
100targets. Total A/B SQL delta208/1044 exactly matches the replaced discovery/checkpoint amplification.

Total SQL drops only0.98%/0.29%; end-to-end wall increases3.67%/2.30%, and WAL increases12.33%/6.37%.
Do not claim overall acceleration. Canonical pending index references mutable state and adds maintenance;
WAL is a cluster-wide proxy, not isolated causal index attribution. No comparable index-free command write
microbenchmark is claimed. Final separate900canonical cancels:4500queries,2.000SQLs,6.137walls,
1415944clusterWALbytes. Index size409600bytes after churn; no forced planner hints or invented zero-cost write.

Final worker-cycle wall29.009s/751.337s; Gateway accounts for98.20%/99.57% of that measured cycle.
Capacity fixtures retain pending LIMIT work that is untouched by their shared observation; returned events0.
The100/500 admission figures count `Gateway.observe` calls, NOT successful fills. Financial fill/close/retry
parity is verified separately with the unchanged original Paper golden scenarios. These profiles measure
discovery and pending-work scanning, not fill throughput or execution profitability.

Actual PG16.11 EXPLAIN ANALYZE BUFFERS (plans_and_write_cost.json):1000active indexed rows/100targets,
6.337ms;100active after900cancelled/10targets,0.861ms. Pending index used; account join uses existing
account identity index. Valuation branch scans101canonical account rows, emits0 in this fixture; this is
not a proven indexed position path. Final removed experimental open-account index had no measured use.

Separate unchanged-Gateway residual probe:parse_account100calls/0.016s;lock_account100/0.103s;
parse_order82000/6.923s, matching2parses×10orders×41candles×100accounts. Production also loads all
account orders and history/mirrors, not just active work. Main A/B Gateway query counts12600/303000 do
not decrease. Source:per-candle mark lookup/insert and order cursor flush, plus repeated validation.
No canonical validator removed. Exact next narrow boundary:transaction-local validated immutable-order
origin reuse and measured mark/cursor query batching, with canonical hashes, closed-candle order, lock,
fill admission, retry and financial golden equivalence retained. Requires separate authorization.

Both intermediate final commands overrun600s; underlying timed_out=false preserved as a harness limitation.
Extended profile NOT_ATTEMPTED. No account/provider observations skipped to meet the cap. Every owned
fixture DB removed after completion. CPU is measured process CPU, not DB CPU; connections are end samples;
RSS is50ms sampled, not guaranteed native peak. PG network bytes/object growth/DB CPU UNKNOWN.
Provider is synthetic closed-candle fixture:external network0known, not production Binance quota evidence.
Lag uses bounded telemetry ring, possibly omitting early samples; no p95/p99 SLO claim. Runs sequential,
with no concurrent owned capacity/test run; background OS noise not controlled. No D2 capacity PASS.
