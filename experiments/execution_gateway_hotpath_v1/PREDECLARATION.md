# Gateway hot-path measurement admission

Before any production edit: sequential F1 small (100 accounts/1000 pending orders/
10 closed history trades), then intermediate (500/5000/50). Identical frozen F1
shape, fixture clock, backlog, provider stub, pool3, costs and canonical commands
before/after. No strategy or frontend change. Each profile: existing cooperative
600s workload admission cap, 1800s worker admission cap checked between Gateway
calls, RSS768MiB checked at Gateway admission. These are cooperative boundaries,
not hard interrupt limits inside a transaction. No escalation beyond500.
Cap overrun inside a worker command must be reported explicitly, not concealed by
the legacy timed_out flag. Larger profile fails/caps: retain partial evidence.

Test-only wrappers retain inclusive and child-subtracted stage wall/CPU/SQL;
two cProfile sample admissions (first/last), one tracemalloc sample (middle).
An additional read-only observer connection samples lock waits/connections every
250ms. This perturbs measured work and is identical before/after; do not compare
raw durations to uninstrumented F3 as if equivalent instrumentation.

Candidate hypotheses (to be resolved by measurements, not assumed): per-candle
round trips and JSON writes; repeated order parsing/hashing; account/trade mirror
N+1/hydration; lock/connection contention; Decimal compute. Financial/canonical
validation, locking, idempotency, cursor sequencing and journal capture remain
authority. No Rust or distributed infrastructure; no D2-capacity claim.
